# 실행과 배포

## 관리자 웹: 로컬 검증 후 별도 검토·배포

`feat/admin-web`의 `0021`은 공용 DB에 적용하지 않은 초안이다. DB·결제 담당자 검토 전 develop에 병합·배포하지 않는다. Render는 서버 시작 시 자동 migration을 실행한다. 추천 측이 주문 시각을 먼저 추가하면 중복을 통합하고 다음 head로 번호·down_revision을 조정해 왕복 검사를 다시 한다.

화면 확인: `cd admin`, `npm ci`, `npm run dev`. 출력 URL에 `?demo=1`을 붙이면 개발 서버에서만 예시 주문·상품과 v2 실제 숫자 집계를 조회한다. 변경 요청은 보내지 않으며 운영 빌드에는 이 모드가 없다. 실제 로그인은 `admin/.env.example`을 `.env`로 복사해 공개값 세 개를 설정한다. Supabase 이메일 템플릿은 코드(Token) 방식이어야 한다. 신규 계정 자동 생성은 비활성이다.

API는 로컬 DB 주소를 명시하고 `ADMIN_ENABLED=true`, `SKINCARE_REFRESH_ENABLED=false`, `CORS_ORIGINS=["http://127.0.0.1:5173"]`를 설정한다. 기존 .env의 공용 DB 주소를 사용하지 않는다. 검증은 일회용 로컬 PostgreSQL만 사용한다. 운영자 grant 잡은 지정 환경에 쓰므로 DB 주소를 먼저 확인한다.

DB가 필요한 로컬 재현 예시(저장소 루트부터, Docker Desktop 실행 필요):

```powershell
# loopback에만 노출하는 폐기 가능한 개발 DB. 기존 DB 컨테이너를 재사용하지 않는다.
docker run -d --name vishue-admin-local -p 127.0.0.1:15439:5432 -e POSTGRES_USER=admin_local -e POSTGRES_PASSWORD=admin_local -e POSTGRES_DB=admin_local postgres:17-alpine
cd backend/api
$env:DATABASE_URL = 'postgresql+asyncpg://admin_local:admin_local@127.0.0.1:15439/admin_local'
$env:ADMIN_ENABLED = 'true'
$env:SKINCARE_REFRESH_ENABLED = 'false'
$env:CORS_ORIGINS = '["http://127.0.0.1:5173"]'
uv sync --frozen
uv run alembic upgrade head
uv run python -m app.jobs.seed_catalog fixtures/demo_catalog.json
# API에도 프런트엔드와 같은 SUPABASE_URL·SUPABASE_PUBLISHABLE_KEY 공개값을 설정한다.
# 실제 결제 시연 키는 서버 환경에만 설정한다.
uv run uvicorn app.main:app --host 127.0.0.1 --port 8000
```

앱을 이 로컬 API로 연결해 약관을 동의한 계정을 아래 grant 잡으로 등록한다. 다른 터미널에서 admin 웹을 실행한다. 재현을 끝내고 로컬 데이터를 폐기할 때만 `docker rm -f -v vishue-admin-local`로 자신이 만든 이 컨테이너를 정리한다. 이번 자동 검사에 사용한 review 컨테이너는 검사 종료 후 삭제한다.

운영 전환은 확장 migration → 전체 API 서버 코드 교체 → 이전 Pod가 없음을 확인 → ADMIN_ENABLED=true 순서다. 이전 서버는 확장 상태 값을 이해하지 못할 수 있으므로 혼재 중에는 켜지 않는다. 이 값은 관리자 API뿐 아니라 새 노출 필터·재고 경로도 제어하므로, 활성화 후 끄면 기존 카탈로그·결제 동작으로 돌아간다는 점을 고려한다.

```powershell
# backend/api에서, DB 검토·반영 후 대상 DB를 명시한 운영자만 실행
uv run python -m app.jobs.grant_staff_role --user-id <Supabase-user-id> --role admin
uv run python -m app.jobs.grant_staff_role --user-id <Supabase-user-id> --role viewer
uv run python -m app.jobs.grant_staff_role --user-id <Supabase-user-id> --revoke
```

회원은 먼저 앱에서 약관에 동의해 members에 존재해야 한다. 최초·후속 역할 지정은 이 잡만 사용한다. 자기 권한 부여 API는 없다.

Render: `vishue-admin` 정적 사이트(rootDir admin, build `npm ci && npm run build`, dist 게시, SPA rewrite)를 연결한다. `VITE_SUPABASE_URL`, `VITE_SUPABASE_PUBLISHABLE_KEY`, `VITE_API_BASE_URL`은 sync:false로 대시보드에 입력한다. API의 CORS_ORIGINS도 sync:false이며 기존 앱 origin과 관리자 origin을 JSON 배열에 함께 넣는다. DB 검토·반영 후 API의 ADMIN_ENABLED를 true로 켠다. DB·토스·Supabase secret 키는 admin에 전달하지 않는다.

Helm: `values-prod.yaml`에서 `admin.enabled=true`로 켠다. 동일 gateway의 `/`는 admin, 더 구체적인 `/api`·`/pay`는 기존 서버다. admin.apiBaseUrl이 비면 같은 origin이다. API ConfigMap에 `ADMIN_ENABLED=true`, 립 평가용 `ADMIN_LIP_EVAL_DIR=/data/lip-eval`과 PVC(`api.persistence.lipEval`)를 둔다(평가 기간 RWO → api replicas=1). nginx는 공개값만 runtime config.js로 받아 비루트·읽기 전용 파일시스템으로 실행한다. `docker build -t vishue-admin:dev admin` 후 kind 이미지 로드와 GitOps 흐름을 따른다. 소비자 웹은 `web/`(포트 5174)로 분리한다. 상세 체크리스트는 `docs/design/admin-ops-web-rollout.md`. 직접 kubectl apply·실제 Render/EKS 배포는 하지 않는다.

같은 백엔드 코드와 Dockerfile을 네 환경에서 씁니다. 환경 사이의 차이는 설정 값에만 있습니다. 왜 이렇게 나눴는지는 [ADR-0003](adr/0003-containers-helm-gitops.md), [ADR-0008](adr/0008-aws-environments.md), [ADR-0009](adr/0009-render-dev-environment.md)에 있습니다.

| 환경 | 용도 | 정의 | PostgreSQL | Neo4j | Redis | 배포 |
| --- | --- | --- | --- | --- | --- | --- |
| **dev (Render)** | **팀 공용 개발 서버** | `infra/render/render.yaml` | Supabase | AuraDB Free | 없음 | `develop`에 병합되고 CI 통과 시 자동 |
| Docker Compose | 개인 PC에서 백엔드 개발 | `infra/compose/` | 컨테이너 | 컨테이너 | 컨테이너 | `docker compose up` |
| kind | 쿠버네티스 동작 확인 | `infra/kind/`, `values-local.yaml` | 클러스터 안 | 클러스터 안 | 클러스터 안 | `helm upgrade` |
| 운영 (AWS EKS) | 배포·시연 | `infra/terraform/aws`, `values-prod.yaml` | RDS | AuraDB | ElastiCache | Argo CD (GitOps) |

```mermaid
flowchart LR
  Dev["개발자 PR"] --> CI["ci.yml<br/>변경 영역만 검사 → ci-ok"]
  CI -->|develop 병합| Render["Render<br/>api · chatbot 빌드 후 배포<br/>(시작 시 마이그레이션)"]
  CI -->|develop 병합<br/>시드 파일 변경| Data["dev-data.yml<br/>Supabase 시드 → AuraDB 동기화"]
  CI -->|main 병합| Img["images.yml<br/>GHCR 이미지 + SBOM"]
  Img --> Bump["자동 PR<br/>values-prod.yaml 태그 갱신"]
  Bump -->|병합 = 배포| Argo["Argo CD → EKS 롤링 배포"]
```

## 선택적 성분 매핑 파일

성분 조회에는 생성 재현·상품/호수/옵션 소유권·출처 버전·성분 검수가 확인된 `schemaVersion: 1` 매핑 JSON이 필요하다. `candidate`·`ambiguous`·미검수 자료를 `reproduced`/`verified`로 바꾸지 않는다. 로컬 `reports/ingredients/p0-2b-1-mapping.json`은 미검수 후보 자료이며 정상 조회의 증빙이 아니다.

Docker 없이 실행할 때는 `backend/api/.env`의 `INGREDIENT_MAPPING_PATH`에 해당 서버의 절대 파일 경로를 지정한다. 명시적으로 주입한 경로가 환경 설정보다 우선한다. 미설정·누락·형식 오류·지원하지 않는 버전은 명확한 503 코드, 일치하지 않거나 미검수인 근거는 UNKNOWN으로 처리한다.

Compose에서는 루트 `.env`의 `INGREDIENT_MAPPING_SOURCE`에 기존 호스트 파일의 절대 경로를 넣고 선택적 설정을 추가한다.

```bash
docker compose -f infra/compose/compose.yaml -f infra/compose/compose.ingredients.yaml --env-file .env config --quiet
docker compose -f infra/compose/compose.yaml -f infra/compose/compose.ingredients.yaml --env-file .env up --build
```

이 설정은 API 컨테이너의 `/app/runtime/ingredient-mapping.json`에 읽기 전용으로 연결한다. 파일이 없으면 디렉터리를 대신 만들지 않는다. 기존 기본 Compose 실행에는 파일 마운트가 없고 상품 등 다른 기능은 유지된다. 운영 배포의 파일 전달·검수 승인은 별도이며, 이 개발 설정을 운영 리소스에 수동 적용하지 않는다. 합성 근거는 운영 환경에서 검증된 성분 사실로 공개하지 않는다.

분리 동의어 승인 CSV를 받은 경우 루트 `.env`의 `INGREDIENT_ALIAS_APPROVALS_SOURCE`에 해당 호스트 파일의 절대 경로를 지정하고 다음 설정을 추가한다.

```bash
docker compose -f infra/compose/compose.yaml -f infra/compose/compose.ingredients.yaml -f infra/compose/compose.ingredient-approvals.yaml --env-file .env config --quiet
docker compose -f infra/compose/compose.yaml -f infra/compose/compose.ingredients.yaml -f infra/compose/compose.ingredient-approvals.yaml --env-file .env up -d --build
```

승인 CSV는 API 컨테이너에서 읽기 전용으로 연결되며 `INGREDIENT_ALIAS_APPROVALS_PATH`가 자동으로 지정된다. 승인 CSV를 교체한 후에는 같은 설정으로 `up -d --force-recreate api`를 실행한다. 이 설정을 추가하지 않으면 분리 동의어는 미승인으로 처리된다.

## 장바구니 추천 실험

API에 `CART_RECOMMENDATION_EXPERIMENT` 값을 지정하면 실험이 시작된다. Docker Compose는 루트 `.env`에서 값을 읽고, Docker 없이 실행할 때는 `backend/api/.env`에서 값을 읽는다. 실험 ID는 16자 이하의 영문 소문자, 숫자, 하이픈으로 지정한다. 빈 값이 기본값이다. 참여자는 AR 추천 대상 목록과 활동 수집 동의 목록에 모두 있고 최신 약관에 동의한 회원이다.

같은 실험에서 회원의 A/B 배정은 고정되며 AR 실험 배정과 독립적이다. A는 기존 장바구니를, B는 최대 5개의 추천 상품을 표시한다. AR 서버 순위 요청의 후순위 후보는 PostgreSQL에 저장되어 API 복제본끼리 공유한다. B는 같은 회원과 부위의 후보를 이어 쓰거나 현재 AR 점수 방식으로 새 순위를 매긴다. 추천 카드의 직접 담기에서 시작된 구매는 결제 승인 후에 귀속한다.

`backend/api`에서 아래처럼 실험 기간, 집계 기준 시각, 구매 관측 시간을 지정한다. 관측 시간이 지난 A/B 방문 전체가 분모다. 방문 당시 장바구니에 없던 상품을 결제한 방문의 비율이 주지표이고, 상품 종류에 관계없이 결제된 방문의 비율도 함께 집계한다. 카드가 노출된 방문과 추천에서 직접 담아 구매한 방문은 별도 수치로 확인할 수 있다.

```bash
uv run python -m app.jobs.cart_recommendation_report --id cart-v1 \
  --start 2026-11-01T00:00:00+09:00 --end 2026-11-08T00:00:00+09:00 \
  --as-of 2026-11-09T00:00:00+09:00 --purchase-window-hours 24
```

## 1. 팀 공용 dev 서버 (Render)

팀원은 Docker 없이 이 서버에 붙어서 개발합니다. 모두 무료 플랜입니다.

```
앱 (팀원 PC, Expo Go) ──→ Render: vishue-api ──→ Supabase (PostgreSQL)
                          Render: vishue-chatbot ──→ Neo4j AuraDB Free
GitHub Actions (dev-data) ── 시드 → Supabase, 동기화 → AuraDB, 12시간마다 깨우기
```

### 팀원이 쓰는 법

`.env`에 한 줄을 넣고 앱을 켭니다(`.env`를 바꾸면 `-c`로 캐시를 지워야 반영됩니다).

```
EXPO_PUBLIC_API_BASE_URL=https://vishue-api-xxxx.onrender.com
```

```bash
npx expo start -c
```

- 무료 서버는 15분 동안 요청이 없으면 잠듭니다. 잠든 뒤 첫 요청은 30초~1분 걸리고, 그다음부터는 빠릅니다.
- `develop`에 병합되고 CI(`ci-ok`)가 통과하면 Render가 새 코드로 다시 배포합니다(3~5분).
- 제품 데이터 바꾸는 방법은 [`DATA.md`](DATA.md)를 봅니다.

### 처음 한 번 설정 (관리자 1명)

이 설정 파일과 워크플로가 `develop` 브랜치에 들어간 뒤에 진행합니다. Render는 `develop`의 파일을 읽습니다.

**1. Supabase: DB 접속 주소 만들기**

1. 로그인에 쓰는 Supabase 프로젝트를 그대로 씁니다.
2. DB 비밀번호를 모르면 Project Settings → Database → **Reset database password**로 새로 만들고 적어 둡니다.
3. 화면 위쪽 **Connect** → **Session pooler** 주소를 복사합니다. 실습실 네트워크에서도 붙는 IPv4 주소입니다.
   ```
   postgresql://postgres.abcd1234:[YOUR-PASSWORD]@aws-0-ap-northeast-2.pooler.supabase.com:5432/postgres
   ```
4. 앞부분을 `postgresql+asyncpg://`로 바꾸고, `[YOUR-PASSWORD]`에 비밀번호를 넣고, 끝에 `?ssl=require`를 붙입니다. 이 값이 **`DATABASE_URL`**입니다.
   ```
   postgresql+asyncpg://postgres.abcd1234:비밀번호@aws-0-ap-northeast-2.pooler.supabase.com:5432/postgres?ssl=require
   ```
   비밀번호에 `@`, `:`, `/`, `#` 같은 특수문자가 있으면 주소가 깨지므로, 영문과 숫자로만 된 비밀번호를 쓰는 게 편합니다.
5. 같은 프로젝트의 Project Settings → API Keys에서 **Project URL**과 **publishable key**도 적어 둡니다(앱 `.env`의 `EXPO_PUBLIC_SUPABASE_*`와 같은 값).

**2. Neo4j AuraDB Free: 챗봇 DB 만들기**

1. [console.neo4j.io](https://console.neo4j.io)에 가입하고 **New instance → AuraDB Free**를 만듭니다.
2. 만들 때 나오는 **접속 정보 파일(.txt)을 꼭 내려받습니다.** 비밀번호는 이때 한 번만 보여 줍니다.
3. 파일 안의 `NEO4J_URI`(`neo4j+s://xxxx.databases.neo4j.io`), `NEO4J_USERNAME`, `NEO4J_PASSWORD`를 씁니다.

**3. Render: 서버 두 개 만들기**

1. [render.com](https://render.com)에 **GitHub 계정으로 가입**합니다.
2. GitHub 연결 화면에서 `gyuniverse-hq/SKN34-Final-Project` 저장소 접근을 허용합니다. 조직 저장소라 **조직 관리자의 승인**이 필요할 수 있습니다.
3. Dashboard → **New → Blueprint** → 저장소를 고르고, Branch는 `develop`, **Blueprint Path는 `infra/render/render.yaml`**로 입력합니다.
4. 서버 두 개(`vishue-api`, `vishue-chatbot`)의 빈 값을 채우고 **Apply**를 누릅니다.

   | 서버 | 키 | 값 |
   | --- | --- | --- |
   | vishue-api | `DATABASE_URL` | 1-4에서 만든 주소 |
   | vishue-api | `SUPABASE_URL`, `SUPABASE_PUBLISHABLE_KEY` | 1-5의 Project URL, publishable key |
   | vishue-api | `SUPABASE_SECRET_KEY` | 같은 화면의 secret key(`sb_secret_...`). 회원 탈퇴에만 씀 (비우면 탈퇴만 503) |
   | vishue-api | `NAVER_CLIENT_ID`, `NAVER_CLIENT_SECRET`, `YOUTUBE_API_KEY` | 팀 `.env`와 같은 값 (없으면 비워 둠) |
   | vishue-api | `TOSS_CLIENT_KEY`, `TOSS_SECRET_KEY` | Toss 개발자센터의 결제위젯 테스트 키 (비우면 결제만 503) |
   | vishue-api | `PAYMENT_WEB_BASE_URL` | 이 서버의 주소 (`https://vishue-api-xxxx.onrender.com`, 끝에 `/` 없이) |
   | vishue-chatbot | `NEO4J_URI`, `NEO4J_USER`, `NEO4J_PASSWORD` | 2-3의 AuraDB 접속 정보 |
   | vishue-chatbot | `SUPABASE_URL`, `SUPABASE_PUBLISHABLE_KEY` | 1-5와 같은 값 |
   | vishue-chatbot | `LLM_API_KEY`, `LLM_MODEL` | 챗봇을 켤 때 입력 (비우면 챗봇만 503) |

5. 첫 배포는 5~10분 걸립니다. 끝나면 서버 페이지 위쪽의 주소(`https://vishue-api-xxxx.onrender.com`)를 복사합니다.
6. 브라우저에서 `<주소>/api/health`가 `{"ok":true,...}`인지 확인합니다. `vishue-api`는 시작할 때 DB 표를 자동으로 만듭니다.

**4. GitHub: 데이터 동기화 설정**

저장소 Settings → Secrets and variables → **Actions**에서 다음을 추가합니다.

| 종류 | 이름 | 값 |
| --- | --- | --- |
| Variables | `DEV_API_URL` | 3-5의 `vishue-api` 주소 (끝에 `/` 없이) |
| Secrets | `DEV_DATABASE_URL` | 1-4의 `DATABASE_URL` |
| Secrets | `DEV_NEO4J_URI` | AuraDB `NEO4J_URI` |
| Secrets | `DEV_NEO4J_USER` | AuraDB `NEO4J_USERNAME` |
| Secrets | `DEV_NEO4J_PASSWORD` | AuraDB `NEO4J_PASSWORD` |

이후 `develop`에서 시드 파일, 마이그레이션, 이 워크플로 파일이 바뀌면 `dev-data`가 자동으로 돌아 카탈로그를 Supabase에 넣고 AuraDB로 복사합니다. Actions 탭에서 초록색이면 성공입니다.

- **Run workflow 버튼(수동 실행)과 12시간 예약 실행**은 GitHub 규칙상 이 워크플로가 `main`에 들어간 뒤부터 쓸 수 있습니다(`develop` → `main` 첫 병합 이후).
- 그 전에 다시 돌리고 싶으면 Actions에서 지난 `dev-data` 실행을 열고 **Re-run all jobs**를 누릅니다.

**5. 팀에 공유**

- 팀원에게 `EXPO_PUBLIC_API_BASE_URL=<vishue-api 주소>`를 알려 줍니다.
- 데이터 담당자를 Supabase 팀에 **Developer** 역할로 초대합니다(Organization → Team → Invite).

### 무료 플랜에서 알아둘 점

| 항목 | 내용 | 대응 |
| --- | --- | --- |
| Render 잠들기 | 15분 동안 요청이 없으면 잠들고, 첫 요청이 느림 | 불편하면 `vishue-api`만 Starter 플랜으로 올림 |
| Render 사용 시간 | 무료는 워크스페이스 전체가 월 750시간 | 서버 두 개가 하루 종일 깨어 있으면 월말에 모자랄 수 있음 |
| Supabase·AuraDB 일시 정지 | 며칠 쓰지 않으면 일시 정지 | `dev-data`가 12시간마다 깨움(이 워크플로가 `main`에도 있어야 예약 실행이 됨) |
| Redis 없음 | 캐시 없이 동작하고 레이트 리밋은 서버 메모리 | 개발 서버에는 충분함 |
| 챗봇 주소 | 쇼핑 서버와 주소가 따로임 | 앱에 챗봇 화면을 붙일 때 챗봇 주소를 따로 쓰거나 입구 서버를 추가 |

## 2. Docker Compose (로컬 전체)

Docker Desktop이 필요합니다. 저장소 루트에서 실행합니다.

```bash
docker compose -f infra/compose/compose.yaml --env-file .env up --build
```

- 루트 `.env`를 그대로 읽습니다. `EXPO_PUBLIC_SUPABASE_*`는 토큰 검증에, `NAVER_*`와 `YOUTUBE_API_KEY`는 판매처·제품 이미지·튜토리얼 검색에, `LLM_API_KEY`와 `LLM_MODEL`은 챗봇에 씁니다. 키가 없으면 해당 기능만 꺼집니다(챗봇은 503).
- 시작 순서는 자동입니다. PostgreSQL → `migrate`(Alembic) → `api` → 게이트웨이 순서로 뜨고, `chatbot`과 `sync-graph`는 Neo4j가 준비되면 뜹니다. 게이트웨이는 챗봇을 기다리지 않아서, 챗봇이 꺼져 있어도 쇼핑 API는 동작하고 `/api/chat`만 503을 돌려줍니다.
- 처음 실행은 이미지를 받고 만드느라 몇 분 걸립니다. `-d`를 붙이면 터미널을 닫아도 계속 돌고, 상태는 `docker compose -f infra/compose/compose.yaml ps`로 봅니다.
- 확인: `curl http://localhost:8080/api/products`, API 문서는 `http://localhost:8080/api/docs`
- 앱(`npx expo start`)은 개발 중에 Metro를 띄운 PC의 `:8080`으로 자동 연결됩니다. 휴대폰 Expo Go도 같은 Wi-Fi라면 따로 설정할 필요가 없습니다(PC 방화벽에서 8080 허용 필요). 터널 모드(`--tunnel`)처럼 PC 주소로 닿지 않을 때는 `.env`의 `EXPO_PUBLIC_API_BASE_URL`에 백엔드 주소를 넣습니다.
- LAN에 열리는 포트는 게이트웨이(8080) 하나뿐입니다. DB 관리 도구용 포트는 `127.0.0.1`에만, PC에 이미 설치된 PostgreSQL·Redis와 겹치지 않는 번호로 열립니다(PostgreSQL 15432, Redis 16379, Neo4j 17474·17687). 겹치면 `.env`에서 `GATEWAY_PORT`, `POSTGRES_HOST_PORT` 등으로 바꿉니다.
- Expo 웹(`localhost:8081`)에서 부르는 경우를 위해 CORS가 기본으로 열려 있습니다(`CORS_ORIGINS`).
- 카탈로그 넣기: `backend/api/seed/catalog.json`을 채운 뒤 다음을 실행합니다.

  ```bash
  docker compose -f infra/compose/compose.yaml run --rm seed
  docker compose -f infra/compose/compose.yaml run --rm sync-graph
  ```

- 데이터까지 지우기: `docker compose -f infra/compose/compose.yaml down -v`

### 서비스 하나만 직접 실행 (uv)

```bash
cd backend/api
cp .env.example .env
uv sync
uv run alembic upgrade head
uv run uvicorn app.main:app --reload
uv run pytest              # 단위 테스트 (DB 없이)
uv run ruff check . && uv run lint-imports
```

## 3. kind (로컬 쿠버네티스)

kind, kubectl, Helm이 필요합니다. 운영과 같은 차트를 노드 2대(zone 2개)에 올립니다.

```bash
# 클러스터와 게이트웨이 (처음 한 번)
kind create cluster --name vishue --config infra/kind/cluster.yaml
helm install eg oci://docker.io/envoyproxy/gateway-helm -n envoy-gateway-system --create-namespace
kubectl apply -f infra/platform/gatewayclass.yaml

# 이미지를 만들어 kind 노드에 넣기
docker build -t vishue-api:dev backend/api
docker build -t vishue-chatbot:dev backend/chatbot
kind load docker-image vishue-api:dev vishue-chatbot:dev --name vishue

# 배포 (DB 접속 정보는 차트가 릴리스 이름에 맞춰 자동으로 연결합니다)
helm upgrade --install vishue infra/helm/vishue -n vishue --create-namespace \
  -f infra/helm/vishue/values-local.yaml

# 게이트웨이를 localhost:8080으로 열기
kubectl -n envoy-gateway-system port-forward \
  "svc/$(kubectl -n envoy-gateway-system get svc \
    -l gateway.envoyproxy.io/owning-gateway-name=vishue -o jsonpath='{.items[0].metadata.name}')" 8080:80
```

- 코드를 고친 뒤에는 바뀐 서비스만 다시 빌드하고 `kind load` → `kubectl -n vishue rollout restart deploy/vishue-api` 순서로 반영합니다.
- 상태 확인: `kubectl -n vishue get pods -o wide`를 실행하면 `api`와 `chatbot` Pod가 zone별로 나뉘어 배치된 것을 볼 수 있습니다.
- GitOps까지 시연하려면 Argo CD를 설치하고 `kubectl apply -f infra/argocd/project.yaml -f infra/argocd/application-local.yaml`을 실행합니다(`develop` 브랜치를 따라갑니다).

## 4. AWS 운영 (배포 단계)

운영은 AWS EKS에 올립니다. AWS 자원은 모두 [`infra/terraform/aws`](../infra/terraform/aws)에 코드로 정의되어 있습니다([ADR-0008](adr/0008-aws-environments.md), [ADR-0011](adr/0011-production-cutover.md)).

| 항목 | 구성 |
| --- | --- |
| 네트워크 | VPC 2개 AZ, 노드·DB·캐시는 프라이빗 서브넷, NAT 1개 |
| 클러스터 | EKS, 노드 `t3.large` 2대 (AZ마다 1대) |
| 데이터 | RDS PostgreSQL 17(공용 원본), ElastiCache Redis(TLS), Neo4j AuraDB, S3(백업·덤프·에셋) |
| 시크릿 | Secrets Manager `vishue/production/*` → External Secrets |
| 배포 | `main` 병합 → 태그 갱신 PR 병합 → Argo CD |
| 1차 부가 | pause/resume 런북, gitleaks CI, 배포 경로 검증 |

### 컷오버 순서 (확정)

1. Terraform으로 VPC · EKS · RDS · Redis · Secrets Manager · S3를 만든다.  
2. 플랫폼(metrics-server, Envoy Gateway, External Secrets, Argo CD)을 설치한다.  
3. 시크릿과 `values-prod.yaml`을 채운 뒤 첫 이미지를 GitOps로 올린다.  
4. **데이터:** 기존 PostgreSQL 덤프를 RDS에 복원 → Alembic → 카탈로그만 시드로 보정 → `sync-graph`.  
5. 앱의 `EXPO_PUBLIC_API_BASE_URL`을 운영 Gateway로 바꾼다(팀은 API로 공용 DB를 본다).  
6. pause/resume 런북·gitleaks·배포 검증 스크립트를 같은 단계에서 갖춘다.  
7. Prometheus · Grafana · Langfuse는 클러스터가 안정된 뒤 2차로 둔다.

### 처음 한 번 (관리자 1명)

필요한 도구: AWS CLI(캠프 계정으로 `aws configure`), Terraform, kubectl, Helm.

**1. AWS 자원 만들기 (Terraform)**

```bash
cd infra/terraform/aws
terraform init
terraform plan        # 만들어질 자원 확인
terraform apply       # 15~20분
terraform output
```

- 비용은 대략 월 $250 안팎입니다(EKS·노드·NAT·RDS·ElastiCache·로드 밸런서). 캠프 크레딧 한도를 확인하세요. 프로젝트가 끝나면 `terraform destroy`로 지웁니다(운영 DB는 삭제 보호가 켜져 있어 `db_deletion_protection = false`로 먼저 바꿔야 함).
- 팀이 같이 쓰려면 Terraform 상태 파일을 S3에 둡니다(`versions.tf`의 주석 참고).

**2. 클러스터 공용 구성 요소 설치**

```powershell
aws eks update-kubeconfig --name vishue --region ap-northeast-2
pwsh -File infra/scripts/bootstrap-platform.ps1
```

수동으로 나누어 설치하려면 스크립트 내용을 그대로 따라도 됩니다(metrics-server · Envoy Gateway · External Secrets · Argo CD · `infra/platform/*` · Argo Application).

**3. 시크릿 값 채우기 (AWS 콘솔 → Secrets Manager)**

| 시크릿 | 채울 값 |
| --- | --- |
| `vishue/production/api` | `DATABASE_URL`, `REDIS_URL`은 Terraform이 채워 둠. `NAVER_*`, `YOUTUBE_API_KEY`만 입력 |
| `vishue/production/chatbot` | `NEO4J_PASSWORD`(운영용 AuraDB), `LLM_API_KEY` |

**4. values와 GitHub 설정**

- `values-prod.yaml`에서 "set before first deploy" 표시가 붙은 값을 채워 PR로 올립니다. 대상은 Supabase 공개 값, `NEO4J_URI`, `LLM_MODEL`, `gateway.hostname`입니다.
- GitHub Secrets에 `DEPLOY_PR_TOKEN`을 추가합니다. 이 저장소에 contents·pull requests 쓰기 권한만 준 fine-grained PAT입니다. 없으면 태그 갱신 PR에서 CI가 돌지 않아 `ci-ok`가 끝나지 않습니다.
- GHCR 패키지 `vishue-api`, `vishue-chatbot`을 공개로 두거나, pull secret을 만들고 `image.pullSecrets`에 지정합니다.
- 도메인이 생기면 `api.<도메인>`을 게이트웨이 NLB(`kubectl get svc -n envoy-gateway-system`)로 연결하고, cert-manager로 인증서를 만든 뒤 `gateway.tls`를 켭니다.

**5. 운영 데이터 넣기**

운영 DB(RDS)에는 시드가 자동으로 돌지 않습니다. 컷오버 때는 아래 순서를 씁니다([ADR-0011](adr/0011-production-cutover.md)).

1. Argo/Helm이 ExternalSecret으로 `vishue-api` Secret(`DATABASE_URL`)을 만든 뒤, 덤프를 gzip SQL로 ops 버킷에 올린다.
   ```powershell
   aws s3 cp .\vishue.dump.sql.gz "s3://$(terraform -chdir=infra/terraform/aws output -raw ops_bucket)/dumps/"
   kubectl apply -f infra/platform/restore-serviceaccount.yaml
   pwsh -File infra/scripts/restore-rds-dump.ps1 -Bucket (terraform -chdir=infra/terraform/aws output -raw ops_bucket) -Key dumps/vishue.dump.sql.gz -Yes
   ```
   RDS는 프라이빗이라 **클러스터 Job**으로만 복원한다. 전체 순서는 `pwsh -File infra/scripts/cutover-checklist.ps1`.  
2. `api` Pod가 뜨면 initContainer의 Alembic이 스키마를 맞춘다.  
3. Git `catalog.json`과 카탈로그만 어긋나면 `values-prod.yaml`에 `seedOnDeploy: true`를 잠깐 켠 PR로 한 번 배포하고(시드 → 그래프 동기화), 다음 PR에서 끈다.  
4. `pwsh -File infra/scripts/verify-prod.ps1 -GatewayUrl <Gateway URL>`로 확인한다.  
5. 덤프가 카탈로그만이고 나머지를 버려도 되면 시드만으로 단순화한다.

일정은 백엔드 담당자와 데이터 담당자가 함께 정합니다.

**6. 시연 외 기간 축소(pause) / 재개(resume)**

```powershell
# 미리보기(변경 없음) 후 -Yes 로 적용
pwsh -File infra/scripts/pause-prod.ps1 -ScaleNodes -StopRds          # 확인
pwsh -File infra/scripts/pause-prod.ps1 -ScaleNodes -StopRds -Yes
pwsh -File infra/scripts/resume-prod.ps1 -ScaleNodes -StartRds -Yes -GatewayUrl https://api.<도메인>
```

완전 삭제는 `terraform destroy`이며, 그 전에 `db_deletion_protection`과 최종 스냅샷을 확인한다.

**7. 1차 품질 가드**

- 시크릿 스캔: `.github/workflows/secrets.yml`(gitleaks).  
- 배포 후: `infra/scripts/verify-prod.ps1`.

### 배포와 롤백

1. `develop` → `main` PR이 병합되면 `images.yml`이 `sha-<커밋>` 태그로 이미지를 발행합니다.
2. 같은 워크플로가 `values-prod.yaml`의 `image.tag`를 바꾸는 PR(`chore: 운영 이미지 태그를 … 로 갱신`)을 엽니다.
3. 그 PR을 병합하면 Argo CD가 감지해서 롤링 배포합니다. 새 Pod가 `/readyz`를 통과해야 이전 Pod가 내려갑니다(`maxUnavailable: 0`).
4. 롤백은 태그 갱신 커밋을 revert하는 PR로 합니다. 클러스터에서 직접 `kubectl`로 고치면 Argo CD의 selfHeal이 Git 상태로 되돌립니다.

마이그레이션은 배포 중에 이전 버전 Pod와 함께 돌아도 깨지지 않게 작성합니다(확장 → 배포 → 정리). dev(Render)에서 먼저 확인된 변경만 `main`으로 올립니다. 자세한 원칙은 [`ARCHITECTURE.md`의 운영 원칙](ARCHITECTURE.md#운영-원칙)을 참고하세요.

## 5. 문제가 생겼을 때 (운영)

dev(Render)는 Render 대시보드의 서버별 **Logs** 탭에서 같은 JSON 로그를 봅니다.

```bash
kubectl -n vishue get pods                               # CrashLoopBackOff, Pending 확인
kubectl -n vishue describe pod <pod>                     # 이벤트 (프로브 실패, 이미지 pull 실패)
kubectl -n vishue logs deploy/vishue-api -c migrate      # 마이그레이션 실패
kubectl -n vishue logs deploy/vishue-api --since=10m     # JSON 로그, request_id로 검색
kubectl -n vishue create job --from=cronjob/vishue-sync-graph sync-now   # 그래프 즉시 동기화
```

| 증상 | 먼저 볼 것 |
| --- | --- |
| `api` Pod가 Ready가 안 됨 | `/readyz` 응답의 `database`, `redis` 값, `DATABASE_URL` Secret |
| `/api/chat`이 503 | `LLM_API_KEY`(Secret), `LLM_MODEL`(ConfigMap)이 비어 있는지 |
| 챗봇이 제품을 못 찾음 | `sync-graph` Job 로그, `api`의 `/api/products` 응답이 비어 있는지 |
| 401만 나옴 | `SUPABASE_URL`이 앱의 Supabase 프로젝트와 같은지, 토큰 만료 |

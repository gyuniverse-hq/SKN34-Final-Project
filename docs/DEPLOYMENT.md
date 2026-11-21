# 실행과 배포

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

## G5 지식 상담의 공유·배포 준비

G1은 Render·Compose·Helm에서 ON으로 설정한다. G5는 새 환경에서 명시적 OFF로
시작하고, 아래 DB 준비와 데이터 검증을 마친 뒤 API와 챗봇에서 함께 ON으로 바꾼다.
이미 준비된 D: 통합 환경의 G5 ON 설정은 이 기본 템플릿과 별개다. 설정 파일 수정이나
`/healthz`의 200 응답만으로 G5 상담 품질이 검증됐다고 판정하지 않는다.

### 서비스별 설정

| 설정 | API | 챗봇 |
| --- | --- | --- |
| `G1_SUPERVISOR_ENABLED` | 사용하지 않음 | `true` 유지 |
| `G5_ENABLED` | 준비 전 `false`, 검증 후 `true` | API와 같은 시점에 전환 |
| `G5_ALLOW_LOCAL_SOURCES` | `false` 유지 | 사용하지 않음 |
| `G5_OPENAI_API_KEY` | 질문 임베딩용 서버 비밀값 | Terra 선택·생성·검증용 서버 비밀값 |
| `G5_INTERNAL_TOKEN` | 내부 요청 인증 | API와 동일한 비밀값 |
| `CATALOG_API_URL` | 사용하지 않음 | API의 전체 기본 URL, `/internal/knowledge` 접미사 제외 |

G5 키·토큰·DB 암호는 Git이나 `EXPO_PUBLIC_*`에 넣지 않는다. API에 필요한 G5
임베딩 키와 G1의 챗봇 전용 `LLM_API_KEY`를 구분한다. Render에서는 두 서비스에
`sync: false`로 선언된 비밀값을 채우고, 챗봇의 `CATALOG_API_URL`에 실제 API 서버의
HTTPS 기본 주소를 지정한다. Blueprint를 다시 동기화할 때 `G5_ENABLED` 값도 확인한다.
Helm에서는 `secrets.api`·`secrets.chatbot` 또는 대응하는 External Secrets로 주입한다.
Helm의 기본 API 주소는 `http://<release>-api:8000`이며, 다른 주소가 필요한 경우
`chatbot.env.CATALOG_API_URL`로 지정한다. 챗봇→API 통신은 같은 release의 Pod만 허용한다.

### DB를 먼저 준비한다

1. 승인된 **별도 대상 DB**를 준비하고 접속 대상·백업·디스크 여유를 확인한다.
   D: DB의 파일 경로는 팀원의 접속 주소가 아니다. DB 전체를 덮어쓰지 않고 필요한
   G5 데이터만 전달한다. 기존 DB·Docker 볼륨을 재사용하거나 이미지 변경으로 전환하지 않는다.
2. PostgreSQL 17과 `halfvec(3072)`를 지원하는 pgvector를 준비한다. 현재 D: 검증
   기준은 pgvector 0.8.2다. 기본 `postgres:17-alpine` 이미지에는 확장 설치를 보장하는
   구성이 없다. 새 Compose 프로젝트에는 `POSTGRES_IMAGE=pgvector/pgvector:0.8.2-pg17-bookworm`을
   명시할 수 있다. `infra/compose/compose.g5.yaml`은 기존의 **DB 전용** 실행 파일이며
   전체 스택의 추가 설정 파일로 합쳐 쓰지 않는다.
   이미지의 버전·PostgreSQL 기반은 [pgvector v0.8.2 Dockerfile](https://github.com/pgvector/pgvector/blob/v0.8.2/Dockerfile)을 참고한다.
3. 새 kind 저장소를 준비한다면 PostgreSQL 이미지와 저장 용량을 별도 values로 지정한다.
   예: `dataStores.postgres.image=pgvector/pgvector:0.8.2-pg17-bookworm`,
   `dataStores.postgres.storage=8Gi`. 기본 2Gi는 전량 적재·WAL·인덱스 작업의 여유를
   보장하지 않는다. 기존 PVC의 이미지 교체나 크기 변경은 별도 작업이다.
4. Render/Supabase와 운영 RDS에서도 pgvector 가용 버전, 확장 생성 권한, 저장 용량을
   대상 DB에서 확인한다. 로컬 설치 성공으로 원격 DB 준비까지 완료 처리하지 않는다.
5. `backend/api`에서 **표준 마이그레이션 → G5 마이그레이션** 순서로 적용한다.
   아래는 이후 대상 DB 적용 승인을 받은 운영자가 실행할 절차이며, 모델 API는 호출하지 않는다.

```bash
# private-target.env: Git 밖의 대상 DB 전용 설정. DATABASE_URL은 SQLAlchemy URL이다.
uv run --env-file /private/private-target.env alembic upgrade head
uv run --env-file /private/private-target.env alembic -c alembic-g5.ini upgrade head
```

2026-11-21 검증 기준은 표준 `0030`, 별도 `alembic_version_g5`의 `g5_0001`이다.
공유·병합 직전에는 최신 develop의 표준 head를 다시 확인한다. Render 기동 명령,
Compose `migrate`, Helm initContainer는 현재 **표준 Alembic만** 실행한다. 따라서
G5의 별도 적용을 마친 후에 활성화한다. 표준 `alembic upgrade head`를 실행했다는
이유만으로 G5 테이블도 있다고 판단하지 않는다.

### 기존 원문·벡터를 재사용한다

대상 테이블이 비어 있는지 먼저 확인하고, 원본의 ID·버전·승인 상태를 보존한다.
현재 기본 검색·상담에 필요한 복사 순서는 다음과 같다.

1. `aihub_knowledge_document` → `aihub_knowledge_document_file`
2. `aihub_document_extraction` → `aihub_document_block`
3. `aihub_rag_embedding` → `aihub_rag_chunk`

대상에 같은 ID가 있으면 내용을 대조하고 충돌을 해결한 뒤 진행한다. 제약 조건을
끄거나 기존 데이터를 삭제해서 통과시키지 않는다. QA·발췌 연결까지 전달할 때는
`aihub_quote_alignment`가 참조하는 QA·출처 부모 데이터도 별도 manifest에 포함한다.
기본 원문·벡터 검색만을 위해 QA나 발췌 연결을 새로 생성할 필요는 없다.

전달물은 Git 밖에 두는 데이터 전용 덤프와 manifest다. PostgreSQL 17 도구를 사용하고,
libpq의 비공개 `g5-source`·`g5-target` service 설정으로 접속한다. SQLAlchemy의
`postgresql+asyncpg://` URL을 `pg_dump`에 그대로 넣지 않는다.

```bash
# 원본 읽기. 아래 파일 경로는 승인된 로컬 보관 위치로 지정한다.
pg_dump --dbname='service=g5-source' --format=custom --data-only --no-owner --no-privileges \
  --table=public.aihub_knowledge_document --table=public.aihub_knowledge_document_file \
  --table=public.aihub_document_extraction --table=public.aihub_document_block \
  --table=public.aihub_rag_embedding --table=public.aihub_rag_chunk --file="$G5_ARCHIVE"
# 대상 테이블이 비어 있고 ID 충돌이 없음을 확인한 후에만 실행한다.
pg_restore --dbname='service=g5-target' --data-only --no-owner --no-privileges \
  --single-transaction --exit-on-error "$G5_ARCHIVE"
```

manifest에는 테이블별 건수·ID 목록 해시, 문서 버전·원문 블록 해시, 청크 본문·원문
좌표·임베딩 키, 입력 해시·모델·차원·벡터 내용 해시, 덤프 파일 SHA-256을 포함한다.
일관된 스냅샷에서 추출하거나 원본 쓰기를 멈춘 상태에서 덤프와 manifest를 만든다.
서로 다른 시점의 건수와 해시를 혼합하지 않는다. 시퀀스와 외래키·인덱스도 확인한다.
단순 건수 일치는 전체 내용 일치의 증거가 아니다.

2026-11-21 D: 통합 DB의 기준은 다음과 같다. 다른 DB의 완료 결과가 아니다.

| 항목 | 기준 |
| --- | --- |
| 검증 성공 원문 / 원문 블록 | 3,105 / 447,122 |
| 청크 / 고유 벡터 | 36,167 / 36,040 |
| 서비스 승인 문서 | 3,105 |
| 임베딩 | `text-embedding-3-large`, 3,072차원 |
| 청크 / 입력 버전 | `large-3200-overlap-1000-v1` / `openai-3072-title-body-v1` |

복사 후에는 읽기 전용으로 manifest와 대조하고, HNSW·GIN 등 인덱스의 정의·유효성을
확인한다. HNSW가 존재한다고 기본 검색이 HNSW를 사용한다는 뜻은 아니다. 현재
기준선은 정확 코사인 벡터 상위 20개다. 해시 불일치·외래키 오류·건수 부족이면
활성화를 중단하고 실패한 복사 트랜잭션과 대상 DB를 조사한다. 전체 재임베딩이나
`index_knowledge --all`로 덮어쓰지 않는다.

### 활성화와 확인

- DB 검증과 비밀값 주입을 마친 후 Render 두 서비스의 `G5_ENABLED` 또는 Helm의
  `api.env.G5_ENABLED`·`chatbot.env.G5_ENABLED`를 함께 `true`로 바꾼다.
  Compose도 준비된 별도 프로젝트의 `.env`에서 `G5_ENABLED=true`로 전환한다.
- `G5_ALLOW_LOCAL_SOURCES=false`를 유지하고 문서의 서비스 승인 상태로 조회한다.
  D:에서 승인한 상태가 새 DB에 자동으로 생긴다고 가정하지 않는다.
- 내부 `/context`의 문서·버전·블록·UTF-16 범위를 확인한다. `/search`는 질문 임베딩
  API를 호출하므로 실제 모델 호출 승인을 받은 뒤에만 검색·상담을 시험한다.
- 최소 실제 앱 상담·후속 대화·공개 인용을 확인하고 모델별 토큰·비용·지연시간을 남긴다.
  저장 판정 재생·모의 테스트 통과와 실제 모델 상담 성공은 구분한다.
- 문제 시 API·챗봇의 G5만 OFF로 되돌리고 G1 ON과 기존 상품·성분·스타일 경로를
  유지한다. 검증을 이유로 원문·벡터를 삭제하거나 기존 DB를 롤백하지 않는다.

Render API 이미지가 참조하는 `model` 빌드 컨텍스트는 현재 Blueprint 선언에 전달
경로가 없다. 실제 Render 이미지 빌드 검증은 별도 선행 항목이며, 이 절차는 그 성공을
보장하지 않는다. Helm/Render의 실제 비밀값과 DB 준비 완료 여부도 배포 전 확인한다.
J11의 연구 지표 혼동은 잔여 품질 결함이며, 이 설정 보완으로 해결 처리하지 않는다.

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
docker buildx build --build-context model=./ml/runs/recommend-cat-v4/bundle -t vishue-api:dev backend/api
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

운영은 AWS EKS에 올립니다. AWS 자원은 모두 [`infra/terraform/aws`](../infra/terraform/aws)에 코드로 정의되어 있습니다([ADR-0008](adr/0008-aws-environments.md)).

| 항목 | 구성 |
| --- | --- |
| 네트워크 | VPC 2개 AZ, 노드·DB·캐시는 프라이빗 서브넷, NAT 1개 |
| 클러스터 | EKS, 노드 `t3.large` 2대 (AZ마다 1대) |
| 데이터 | RDS PostgreSQL 17, ElastiCache Redis(TLS), Neo4j AuraDB |
| 시크릿 | Secrets Manager `vishue/production/*` → External Secrets |
| 배포 | `main` 병합 → 태그 갱신 PR 병합 → Argo CD |

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

```bash
aws eks update-kubeconfig --name vishue --region ap-northeast-2
helm repo add metrics-server https://kubernetes-sigs.github.io/metrics-server/
helm repo add external-secrets https://charts.external-secrets.io
helm repo add argo https://argoproj.github.io/argo-helm
helm upgrade --install metrics-server metrics-server/metrics-server -n kube-system
helm upgrade --install eg oci://docker.io/envoyproxy/gateway-helm -n envoy-gateway-system --create-namespace
helm upgrade --install external-secrets external-secrets/external-secrets -n external-secrets --create-namespace
helm upgrade --install argocd argo/argo-cd -n argocd --create-namespace

kubectl apply -f infra/platform/gatewayclass.yaml
kubectl apply -f infra/platform/cluster-secret-store.yaml
kubectl apply -f infra/argocd/project.yaml -f infra/argocd/application-prod.yaml
```

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

운영 DB(RDS)에는 시드가 자동으로 돌지 않습니다. 넣을 때는 `values-prod.yaml`에 `seedOnDeploy: true`를 추가한 PR로 한 번 배포하고(배포 직후 시드 → 그래프 동기화가 순서대로 돎), 다음 PR에서 다시 지웁니다. 일정은 백엔드 담당자와 데이터 담당자가 함께 정합니다.

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

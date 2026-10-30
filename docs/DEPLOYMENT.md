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

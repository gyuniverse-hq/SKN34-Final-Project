# 아키텍처

## 전체 구성

전체는 앱(기기), 단일 진입점(Gateway), 백엔드 두 서비스, 데이터 저장소, 외부 서비스로 나뉩니다. 얼굴 영상은 기기 밖으로 나가지 않고, 백엔드에는 피부톤 추정 수치(ITA°, MST 단계, 언더톤)만 전달합니다.

```mermaid
flowchart LR
  subgraph Device["사용자 기기 · Expo 앱"]
    direction TB
    UI["화면 app/"]
    Data["서버 데이터<br/>hooks · lib/queries"]
    Local["기기 저장 store<br/>장바구니·리스트·설정"]
    AR["AR 렌더러 · 피부톤 추정<br/>MediaPipe · ITA° · MST"]
    Http["lib/api<br/>Supabase 토큰 첨부"]
    UI --> Data --> Http
    UI --> Local
    UI --> AR
  end

  Supa["Supabase Auth<br/>로그인·토큰 발급"]

  subgraph Cluster["Kubernetes · namespace vishue"]
    direction TB
    GW["Gateway · Envoy<br/>/api/chat → chatbot<br/>/api/* → api"]
    API["api · FastAPI<br/>카탈로그·셰이드 추천·회원"]
    BOT["chatbot · FastAPI<br/>GraphRAG 챗봇"]
    SYNC["sync-graph · CronJob<br/>+ 배포 후 1회"]
    GW --> API
    GW --> BOT
    SYNC -- "GET /api/products·looks" --> API
  end

  PG[("PostgreSQL · 원본<br/>제품·셰이드·룩·매장")]
  RD[("Redis<br/>캐시·레이트 리밋")]
  NEO[("Neo4j · 챗봇 전용 사본<br/>제품·성분·태그·룩 관계")]
  LLM["LLM API<br/>OpenAI 호환"]

  Http -- "HTTPS · JSON · Bearer<br/>얼굴 영상 없음" --> GW
  Http -. 로그인 .-> Supa
  API --> PG
  API --> RD
  BOT --> NEO
  BOT --> RD
  BOT --> LLM
  SYNC -- "한 방향 복사" --> NEO
```

- 앱은 진입점 하나(`https://api.<도메인>`)만 압니다. 서비스가 늘거나 나뉘어도 앱 코드는 바뀌지 않습니다.
- 데이터 소유권은 서비스별로 나뉩니다. PostgreSQL은 `api`만, Neo4j는 `chatbot`만 접근합니다. 챗봇은 카탈로그를 PostgreSQL에서 직접 읽지 않고 `api`의 HTTP 계약으로 받아 갑니다.
- 같은 컨테이너 이미지가 로컬(Docker Compose), 로컬 쿠버네티스(kind), 운영(EKS)에서 그대로 돌아갑니다. 실행 방법과 배포 흐름은 [`DEPLOYMENT.md`](DEPLOYMENT.md), 결정 이유는 [`adr/`](adr/README.md)에 있습니다.

지금 앱은 아직 저장소 안의 Expo API 라우트(`app/api/`, `server/`)를 호출합니다. 백엔드로 넘어가는 순서는 [옮기는 순서](#옮기는-순서) 절을 참고하세요.

## 앱 저장소의 두 런타임 (현재)

이 저장소에는 두 런타임이 함께 있습니다.

- **클라이언트**: Expo Go·웹에서 도는 앱 (`app/`의 화면, `components/`, `hooks/`, `lib/`, `store/`)
- **서버**: Expo Router API 라우트 (`app/api/**/*+api.ts`)와 서버 전용 로직 (`server/`)

두 쪽은 HTTP(`/api/*`)로만 통신하고, 주고받는 데이터 형태는 `types/`에 정의합니다. 각 쪽은 레이어로 나뉘며 **위 레이어는 아래 레이어만 import합니다.** 아래에서 위로, 또는 클라이언트에서 서버로 import하지 않습니다.

## 클라이언트 레이어

### Android 피부 분석 실험

피부 정보 등록은 마이페이지 → `app/skin-analysis.tsx` → 전용 훅 →
`lib/skinAnalysis.ts`의 실행 환경 선택 → `modules/skin-analysis/` 순서로 호출합니다.
모듈은 상위 앱 레이어를 import하지 않으며 TypeScript 레이어 경계를 린트로 검사합니다.
실험 기능은 `EXPO_PUBLIC_ENABLE_SKIN_ANALYSIS=1`에서 활성화합니다.
모바일 Expo Go에서는 `components/skin/SkinCamera.tsx`의 WebView를 통해
`modules/skin-analysis/web/`의 카메라·자동 촬영·ONNX Runtime Web CPU 추론을 실행합니다.
브라우저 런타임은 상위 앱 코드를 import하지 않고 상태·숫자 결과만 메시지로 전달합니다.
`scripts/skin-web-middleware.cjs`는 Metro 개발 서버에서 검증 자산과 웹 실행 코드의
명시된 파일만 GET/HEAD로 제공합니다. 사진 업로드나 서버 추론을 수행하지 않습니다.
웹 JPEG 코덱은 원본과 픽셀 단위로 일치하지 않아 별도 실험 전처리 버전으로 기록합니다.
WebView에서는 PSS를 측정할 수 없어 null을 저장하며 모델 전송 시간과 추론 시간을 구분합니다.
앱의 다른 화면과 기존 AR 렌더러는 기존 구조를 유지합니다.

Android 전용 빌드에서는 네이티브 CameraX·ML Kit로 자동 촬영하고 ONNX Runtime CPU로 4개 모델을 순차 실행합니다.
촬영 JPEG는 네이티브 메모리에서만 유지하며 분석·취소 후 참조를 해제합니다.
Expo Go에서는 카메라 프레임·ROI·텐서를 WebView 내부 메모리에서만 처리하며,
얼굴 사진·ROI·텐서를 서버나 React Native 메시지 경계로 보내지 않습니다.
숫자 결과와 설문은 `skinProfileStore`를 통해 저장하며, AsyncStorage 쓰기의 성공을
확인한 뒤 완료를 표시합니다. 측정 기록도 기기에만 저장하고 숫자 메타데이터만 공유합니다.
네이티브 모듈은 Expo 자동 연결로 포함되며 루트 `android/`·`ios/`를 직접 수정하지 않습니다.
실행·측정 절차와 제한은 [모바일 피부 분석](../reports/skin-analysis/mobile-analysis.md)을 참고합니다.

피부 모델 연구 환경은 운영 흐름과 별도로 관리합니다. `ml/src/`에는 학습·평가 코드,
`ml/configs/`에는 설정, `ml/tests/`에는 자동 테스트를 두고, 실행 방법과 결과 요약은
[`reports/skin-analysis/`](../reports/skin-analysis/README.md)에 모읍니다. 가중치·원본 데이터·
개별 표본 결과는 Git에서 제외합니다. 향후 LLM 외부 호출과 서비스 조합은 기존
`server/clients/`·`server/services/` 레이어를 따릅니다.

로컬 NIA 연구 도구의 화면은 `app/dev/nia.tsx`, 사진 분석·결과 요청 훅은 `hooks/useNia*.ts`,
표현 컴포넌트는 `components/nia/`에 둡니다. 컴포넌트는 화면에서 결과와 동작을 props로
받으며 `lib/nia`를 직접 호출하지 않습니다. 이 경계를 린트로 검사합니다. 개발 API는
`server/services/niaEvaluationService.ts`를 통해 로컬 Python 평가 프로세스에 연결하며,
production/test/미지정 환경에서는 차단합니다. Python 코드는 `server/nia/`·`server/acne/`에
있습니다. 이 도구는 운영 앱의 얼굴 영상 비전송 정책을 변경하지 않습니다.

```
app/ (화면, app/api 제외)     화면 조립, 네비게이션, 훅 호출
  ↓
hooks/                        여러 데이터 소스를 화면용으로 조합하는 훅 (예: 장바구니 + 제품 조회)
components/                   UI 컴포넌트
  ↓
lib/ · store/                 서버 상태(lib/queries), HTTP(lib/api), i18n, 포맷, 기기 저장, 클라이언트 상태(Zustand)
  ↓
constants/ · types/           테마, 정적 상수, 공용 타입
```

| 폴더 | import 가능 | 금지 |
| --- | --- | --- |
| `app/` 화면 | `hooks`, `components`, `lib`, `store`, `constants`, `types` | `server`, `data` |
| `hooks/` | `lib`, `store`, `types` | `app`, `components` |
| `components/` | `components/ui`, 같은 폴더 내부, `lib`, `store`, `constants`, `types` | `app`, `hooks`, `lib/queries`, `server`, `data` |
| `components/ui/` | 같은 폴더 내부, `lib/i18n`, `lib/format`, `lib/api`(에러 타입), `constants`, `types` | 위 금지 항목 + `store`, 다른 `components/` 폴더 |
| `lib/`, `store/` | 서로, `types` | `app`, `hooks`, `components`, `server`, `data` |
| `constants/`, `types/` | 외부 패키지만 | 프로젝트 내부 전부 |

- **데이터 조회는 화면이나 `hooks/`에서만** 합니다. 컴포넌트는 props로 데이터를 받습니다.
- 서버에서 오는 데이터는 react-query(`lib/queries.ts`), 기기에만 있는 상태는 Zustand(`store/`)가 맡습니다. 같은 데이터를 두 곳에 두지 않습니다.
- `components/ui/`는 어느 화면에서나 쓸 수 있는 범용 컴포넌트입니다. 특정 기능의 상태를 읽어야 하면 `components/<기능>/`에 둡니다.

## 서버 레이어

```
app/api/**/*+api.ts           라우트: 파라미터 파싱·검증, 상태 코드, 응답 형태
  ↓
server/services/              비즈니스 로직: 검색·필터, 룩과 제품 조합, 이미지 보강 정책
  ↓
server/repositories/          데이터 접근: 지금은 data/catalog 정적 데이터, 나중에 DB로 교체
server/clients/               외부 API 호출: 네이버, YouTube
  ↓
server/lib/                   공통: HTTP 응답·fetch, 캐시, 레이트 리밋, 환경 변수
```

| 폴더 | import 가능 | 금지 |
| --- | --- | --- |
| `app/api/` | `server/services`, `server/lib`, `types` | `server/repositories`, `server/clients`, `data` |
| `server/services/` | `server/repositories`, `server/clients`, `server/lib`, `types` | `app` |
| `server/repositories/` | `data`, `server/lib`, `types` | `server/services`, `server/clients` |
| `server/clients/` | `server/lib`, `types` | `server/services`, `server/repositories`, 다른 client |
| `server/lib/` | `types` | `server` 내 다른 레이어 |
| `data/` | `types` | 프로젝트 내부 전부 |

- **API 키는 `server/clients/`에서만 사용**하고 `server/lib/env.ts`로만 읽습니다. 클라이언트 코드가 `server/`를 import하면 키를 읽는 코드가 앱 번들에 들어갈 수 있습니다.
- 라우트에는 비즈니스 로직을 두지 않습니다. 같은 로직이 두 라우트에 필요해지면 서비스로 옮깁니다.
- 외부 API를 바꾸거나 데이터를 DB로 옮겨도 서비스와 라우트는 바뀌지 않아야 합니다.

- 리포지토리 함수는 지금 정적 데이터를 돌려주더라도 **항상 `async`** 로 둡니다. DB로 바꿀 때 호출하는 쪽을 고치지 않기 위해서입니다.
- 리포지토리는 저장된 데이터를 그대로 돌려주고, 조건 필터(예: 픽업 가능 매장만)는 서비스가 합니다.
- 파일 이름은 `<대상><레이어>.ts` 형식입니다 (`catalogService.ts`, `catalogRepository.ts`, `naverClient.ts`).

### 현재 파일

| 레이어 | 파일 |
| --- | --- |
| `server/services/` | `catalogService` (검색·필터·룩 조합·이미지 보강), `offerService` (온라인 판매처), `tutorialService` (튜토리얼 검색어 구성), `integrationService` (외부 API 설정 상태) |
| `server/repositories/` | `catalogRepository` (`data/catalog`의 제품·룩·매장) |
| `server/clients/` | `naverClient` (쇼핑·이미지 검색), `youtubeClient` (영상 검색) |
| `server/lib/` | `http`, `cache`, `env`, `text`, `concurrency`, `auth` (Supabase 액세스 토큰 검증) |

로그인은 Supabase Auth를 씁니다. 앱은 `lib/auth`에서 로그인하고 세션을 기기에 저장하며, `lib/api.ts`가 요청마다 액세스 토큰(JWT)을 붙입니다. 사용자 확인이 필요한 라우트는 `server/lib/auth.ts`의 `getAuthUser()`로 토큰을 검증합니다 (예: `app/api/me+api.ts`). Supabase의 Project URL과 publishable 키는 공개용이라 `EXPO_PUBLIC_`로 앱에 넣지만, secret 키는 넣지 않습니다.

## 린트로 강제하기

위 규칙은 `eslint.config.js`의 `no-restricted-imports`로 검사하므로, 위반하면 `npm run lint`가 실패합니다.

- 다른 폴더를 import할 때는 `@/` 별칭을 씁니다 (`@/server/lib/http`). `../`로 시작하는 상대 경로는 금지입니다. 상대 경로를 쓰면 린트 패턴이 어느 레이어인지 알 수 없기 때문입니다.
- 같은 폴더 안에서는 `./`를 써도 됩니다. 단 `server/clients/` 안에서는 금지입니다 (client끼리 의존하지 않도록).
- 규칙을 바꿀 때는 이 문서와 `eslint.config.js`를 함께 고칩니다.
- 백엔드는 같은 규칙을 import-linter로 검사합니다(`backend/*/pyproject.toml`의 `[tool.importlinter]`, `uv run lint-imports`). CI에서 위반하면 실패합니다.

## 새 기능을 넣을 때

예를 들어 로그인을 구현한다면 다음 순서로 위치를 정합니다.

1. 주고받는 형태를 `types/index.ts`에 정의합니다. 백엔드가 생기면 백엔드의 OpenAPI 스펙에서 생성합니다.
2. 서버: 새 기능은 백엔드에 만듭니다. `backend/api`(또는 챗봇 기능이면 `backend/chatbot`)의 `schemas/` → `routers/` → `services/` → `repositories/` 또는 `clients/` 순서입니다. 백엔드 응답 형태는 `types/index.ts`와 같은 camelCase JSON입니다.
3. 클라이언트: HTTP 호출과 훅은 `lib/`, 로그인 상태처럼 기기에 남길 값은 `store/`, 화면은 `app/login.tsx`
4. UI 문구는 `lib/i18n`의 네 사전(`en`, `ko`, `ja`, `zh`)에 모두 추가합니다.

## 백엔드

`backend/`에는 서비스 두 개가 있습니다. 각각 독립된 uv 프로젝트이고, Docker 이미지와 배포 단위도 따로입니다.

| 서비스 | 맡는 것 | 데이터 | 외부 호출 |
| --- | --- | --- | --- |
| `backend/api` | 카탈로그(제품·셰이드·룩·매장), 셰이드 추천(CIEDE2000 ΔE), 회원(`/api/me`) | PostgreSQL(원본), Redis(캐시) | Supabase Auth(토큰 검증) |
| `backend/chatbot` | 챗봇(`/api/chat`), PostgreSQL → Neo4j 동기화 잡 | Neo4j(사본), Redis(레이트 리밋) | LLM API, `api` 서비스 |

서비스를 둘로 나눈 이유는 [ADR-0001](adr/0001-two-backend-services.md)에 있습니다. LLM 호출은 느리고 비용이 들어서 따로 확장하고 따로 제한해야 합니다. 챗봇 장애가 쇼핑 기능으로 번지지 않아야 하고, LLM 키는 챗봇 Pod에만 있어야 합니다.

### 기술 스택

| 영역 | 선택 |
| --- | --- |
| 언어 | Python 3.12 (`.python-version`으로 고정) |
| 패키지·환경 관리 | uv (`pyproject.toml` + `uv.lock`, 둘 다 커밋) |
| 프레임워크 | FastAPI + Pydantic |
| 원본 DB | PostgreSQL 17, 접근은 SQLAlchemy 2(async, asyncpg), 스키마 변경은 Alembic |
| 검색 | PostgreSQL `pg_trgm` GIN 인덱스 (`products.search_text`) |
| 캐시·레이트 리밋 | Redis (없으면 캐시 없이 동작, 레이트 리밋은 프로세스 메모리) |
| 챗봇용 그래프 DB | Neo4j 5, 공식 `neo4j` Python 드라이버 |
| 인증 | Supabase Auth 토큰을 JWKS로 로컬 검증 ([ADR-0005](adr/0005-supabase-auth-jwks.md)) |
| 테스트 | pytest (단위 테스트는 가짜 저장소, PostgreSQL 통합 테스트는 CI) |
| 린트·레이어 강제 | ruff, import-linter |
| 배포 | Docker 이미지(비루트, 읽기 전용 파일시스템) → Helm → Argo CD |

- 패키지는 `uv add <패키지>`로만 추가합니다. `pip install`로 따로 설치하면 `uv.lock`과 실제 환경이 어긋납니다.
- 실행은 `uv run`을 붙입니다 (`uv run uvicorn app.main:app --reload`, `uv run alembic upgrade head`, `uv run pytest`).

### 레이어

두 서비스 모두 앱의 `server/`와 같은 구조이고, import-linter 계약으로 강제합니다.

```text
backend/<service>/
  pyproject.toml · uv.lock · .python-version · Dockerfile · .env.example
  alembic/                 마이그레이션 (api만)
  seed/catalog.json        카탈로그 시드, data/catalog/*.ts와 같은 형태 (api만)
  app/
    main.py                앱 조립: 미들웨어, 에러 핸들러, 라우터
    jobs/                  일회성 실행 진입점 (seed_catalog, sync_graph)
    routers/               요청 검증·상태 코드·응답        (← 앱의 app/api/)
    services/              비즈니스 로직                   (← server/services/)
    repositories/          DB 접근                         (← server/repositories/)
    clients/               외부 API 호출, 키는 여기서만     (← server/clients/)
    models/                PostgreSQL 테이블 (api만)
    schemas/               Pydantic 요청·응답 형태
    core/                  설정, DB·Redis 연결, 인증, 에러, 로깅  (← server/lib/)
  tests/
```

| 레이어 | import 가능 | 금지 |
| --- | --- | --- |
| `main`, `jobs/` | `routers`, `services`, `schemas`, `core` | `repositories`, `clients`, `models` |
| `routers/` | `services`, `schemas`, `core` | `repositories`, `clients`, `models` |
| `services/` | `repositories`, `clients`, `schemas`, `core` | 위 레이어 |
| `repositories/`, `clients/` | `models`, `schemas`, `core` | 서로, 위 레이어 |
| `models/` | `core` | 위 레이어 |
| `schemas/` | `core` | 위 레이어 |
| `core/` | 외부 패키지만 | 프로젝트 내부 전부 |

- 서비스는 FastAPI 의존성 함수(`get_catalog_service` 등)로 만들어집니다. 테스트는 이 함수를 가짜 저장소를 쓰는 서비스로 바꿔 끼웁니다.
- 리포지토리는 ORM 객체가 아니라 `schemas`의 Pydantic 모델을 돌려줍니다. 비동기 세션의 지연 로딩 문제가 서비스까지 번지지 않게 하기 위해서입니다.
- 챗봇의 `clients/` 모듈끼리는 서로 import할 수 없습니다(independence 계약).

### API 계약

`api`는 Expo API 라우트와 **같은 경로, 같은 JSON**을 돌려줍니다. 그래서 앱 전환은 기준 주소만 바꾸면 됩니다.

| 경로 | 서비스 | 비고 |
| --- | --- | --- |
| `GET /api/products?q=&category=&ids=` | api | `{ products }`, 5분 캐시 |
| `GET /api/products/{id}` | api | `{ product }` |
| `GET /api/looks`, `GET /api/looks/{id}` | api | `{ looks }`, `{ look, products }` |
| `GET /api/stores` | api | 픽업 가능 매장만 |
| `GET /api/me` | api | 로그인 필요 |
| `POST /api/shades/recommend` | api | `{ skin: { ita?, mst, undertone }, limit }` → ΔE 순위 |
| `POST /api/chat` | chatbot | 로그인 필요, 사용자당 분당 10회 |
| `GET /healthz`, `GET /readyz` | 둘 다 | Gateway로 노출하지 않음 (쿠버네티스 프로브용) |

- JSON 키는 camelCase이고(`priceKRW`, `nameKo`), TS의 선택 필드(`shadeId?`, `phone?`)는 값이 없으면 키를 빼고 보냅니다.
- 에러는 항상 `{ error, code }`(`ApiErrorBody`) 형태입니다. 잘못된 요청은 `400 invalid_request`입니다.
- 개발 환경에서는 `/api/docs`에서 OpenAPI 문서를 볼 수 있습니다. 운영에서는 꺼져 있습니다.

### PostgreSQL과 Neo4j

| DB | 담는 것 | 접근 |
| --- | --- | --- |
| PostgreSQL (원본) | 제품, 셰이드, 룩, 룩 구성, 매장 | `api`의 `catalog_repository`만 |
| Neo4j (사본) | `(:Product)-[:HAS_SHADE\|CONTAINS\|TAGGED]->`, `(:Look)-[:USES]->(:Product)` | `chatbot`의 `graph_repository`만 |

1. 데이터 추가와 수정은 **PostgreSQL에서만** 합니다(`seed_catalog` 잡 또는 이후 관리 API). Neo4j에 직접 쓰지 않습니다.
2. Neo4j는 `sync_graph` 잡이 `api`의 `GET /api/products`, `GET /api/looks`를 읽어 **한 방향으로만** 채웁니다. 쓰기는 트랜잭션 하나로 이뤄져서, 읽는 쪽은 이전 그래프나 새 그래프 중 하나만 봅니다.
3. 잡은 30분마다(CronJob) 돌고, 배포 직후에도 한 번 돕니다. 챗봇 서비스는 PostgreSQL 접속 정보를 갖지 않습니다 ([ADR-0002](adr/0002-postgres-source-neo4j-copy.md)).

### 운영 원칙

- **마이그레이션**: `api` Pod의 initContainer가 `alembic upgrade head`를 실행하고, PostgreSQL advisory lock으로 한 번에 한 Pod만 적용합니다. 롤링 배포 중에는 이전 버전 Pod도 함께 돌기 때문에, 스키마 변경은 확장 → 코드 배포 → 정리 순서로 나눕니다(컬럼 삭제와 이름 변경은 별도 PR). CI는 `alembic check`로 모델과 마이그레이션이 어긋나지 않았는지 확인합니다.
- **헬스 체크**: `/healthz`(liveness)는 의존성을 보지 않습니다. DB 장애로 Pod가 재시작되는 연쇄 장애를 막기 위해서입니다. `/readyz`(readiness)는 DB와 Redis에 연결되는지 보고, 실패하면 Gateway가 그 Pod로 트래픽을 보내지 않습니다.
- **로그**: 한 줄에 JSON 하나이고, 요청마다 `X-Request-ID`를 받거나 만들어 응답과 로그에 남깁니다. 챗봇은 질문 내용을 로그에 남기지 않습니다.
- **장애 격리**: Redis 장애는 캐시 미스로 처리하고(api), 레이트 리밋은 통과시킵니다(chatbot). LLM 장애는 `502 upstream_error`, 키나 모델이 설정되지 않았으면 `503 chatbot_unavailable`입니다.
- **개인정보**: 얼굴 영상과 이미지는 어떤 서비스에도 보내지 않습니다. 셰이드 추천과 챗봇은 기기에서 추정한 수치만 받습니다.

### 옮기는 순서

1. **1단계 (완료)**: 백엔드 두 서비스, PostgreSQL 스키마, 셰이드 추천, Compose·Helm·CI를 갖췄습니다.
2. **2단계**: 네이버·YouTube 연동(`offers`, `youtube/search`, 이미지 보강)을 `backend/api/app/clients/`로 옮깁니다. 그 뒤 앱의 `lib/api.ts`가 `EXPO_PUBLIC_API_BASE_URL`(공개 값)을 기준 주소로 쓰게 바꾸고, 앱의 `app/api/`와 `server/`를 삭제합니다. 챗봇과 셰이드 추천 화면은 이 시점에 연결합니다.
3. **3단계**: 앱 타입을 백엔드 OpenAPI 스펙에서 생성하고(`openapi-typescript` → `types/`), Langfuse로 LLM 호출을 추적하고 평가합니다 ([ADR-0007](adr/0007-observability.md)).

### 남은 결정

| 항목 | 현재 결정 | 바꿀 조건 |
| --- | --- | --- |
| 운영 배포처 | AWS EKS (서울 리전) + Argo CD | 캠프에서 AWS를 지원하지 않으면, 같은 이미지를 Render나 Cloud Run에 올립니다 ([ADR-0003](adr/0003-containers-helm-gitops.md)) |
| 운영 데이터 저장소 | RDS PostgreSQL, ElastiCache Redis, Neo4j AuraDB | 비용 문제가 있으면 PostgreSQL은 Supabase Postgres로 바꿉니다 |
| 챗봇 LLM | OpenAI 호환 API, 모델은 `LLM_MODEL`로 지정 | 모델 선정은 평가 세트를 만든 뒤에 합니다 |
| 챗봇 대화 기록 | 저장하지 않음 | 저장하려면 보관 기간과 동의 절차를 먼저 정합니다 |

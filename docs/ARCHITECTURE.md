# 아키텍처

이 저장소에는 두 런타임이 함께 있습니다.

- **클라이언트**: Expo Go·웹에서 도는 앱 (`app/`의 화면, `components/`, `hooks/`, `lib/`, `store/`)
- **서버**: Expo Router API 라우트 (`app/api/**/*+api.ts`)와 서버 전용 로직 (`server/`)

두 쪽은 HTTP(`/api/*`)로만 통신하고, 주고받는 데이터 형태는 `types/`에 정의합니다. 각 쪽은 레이어로 나뉘며 **위 레이어는 아래 레이어만 import합니다.** 아래에서 위로, 또는 클라이언트에서 서버로 import하지 않습니다.

## 클라이언트 레이어

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
| `server/lib/` | `http`, `cache`, `env`, `text`, `concurrency` |

## 새 기능을 넣을 때

예를 들어 로그인을 구현한다면 다음 순서로 위치를 정합니다.

1. 주고받는 형태를 `types/index.ts`에 정의합니다.
2. 서버: 라우트 `app/api/auth/...+api.ts` → 서비스 `server/services/` → 저장소 `server/repositories/` 또는 외부 인증 `server/clients/`
3. 클라이언트: HTTP 호출과 훅은 `lib/`, 로그인 상태처럼 기기에 남길 값은 `store/`, 화면은 `app/login.tsx`
4. UI 문구는 `lib/i18n`의 네 사전(`en`, `ko`, `ja`, `zh`)에 모두 추가합니다.

# VISHUE

> SKN34 Final Project · SK NETWORKS FAMILY AI CAMP 34기 최종 프로젝트 저장소입니다.

외국인 대상 K-뷰티 쇼핑 앱. **룩 발견 → AR 가상 메이크업 → 세트로 장바구니 → 매장 쇼핑 리스트 / 온라인 구매**.

- 협업 규칙(브랜치·커밋·PR): [`CONTRIBUTING.md`](CONTRIBUTING.md) · AI 도구용 요약: [`AGENTS.md`](AGENTS.md)
- 레이어 구조와 import 규칙: [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) · 결정 기록: [`docs/adr/`](docs/adr/README.md)
- 백엔드 실행과 배포(Compose · kind · AWS dev/운영): [`docs/DEPLOYMENT.md`](docs/DEPLOYMENT.md)
- 제품·룩·매장 데이터 넣기(데이터 담당자): [`docs/DATA.md`](docs/DATA.md)
- 출시 전 직접 해야 할 일: [`docs/LAUNCH_CHECKLIST.md`](docs/LAUNCH_CHECKLIST.md)
- 학습·평가 보고서와 재현·모델 인계 절차: [`reports/README.md`](reports/README.md)

## 기능

| 기획 요구사항 | 구현 |
| --- | --- |
| FR-01 제품 검색·상세 | 카테고리·검색(영문/한글), 컬러 선택, 주요 성분, 온라인 판매처 가격(네이버) |
| FR-02 장바구니 | 컬러별 라인, 수량, 기기 저장(앱 재시작 후 유지) |
| FR-03 AR Try-on | MediaPipe 얼굴 랜드마크로 립·블러셔·섀도 실시간 렌더링, 농도 조절, 누르고 비교 |
| FR-04 셀럽 룩 → AR | 룩 선택 시 AR에 일괄 적용, YouTube 튜토리얼 실시간 검색 |
| FR-05 Look-to-Cart | 룩 제품 세트를 컬러까지 한 번에 담기 |
| FR-06 매장 안내 | 직원에게 보여주는 한국어 쇼핑 리스트, 매장 선택·지도 |
| NFR-01 얼굴 비저장 | AR 영상은 기기 내 처리. 피부 분석은 명시적 촬영 JPEG 한 장만 인증된 GPU API로 전송하며 사진은 저장하지 않음 |
| NFR-02 다국어 | English(기본)·한국어·日本語·简体中文, 기기 언어 자동 감지 |

결제(PG)는 기획서상 범위 밖이라, 구매는 **매장 쇼핑 리스트**와 **외부 온라인 판매처 링크**로 연결합니다.

## 구조

```
app/                    Expo Router 화면
  (tabs)/               쇼핑 · 룩 · 가상 메이크업 · 장바구니 · 마이
  product/ look/        상세 화면
  checkout.tsx lists/   쇼핑 리스트 생성 · 보기
  legal/                개인정보처리방침 · 이용약관
  login, membership, rewards, saved, ingredients
                        새 기획 화면 (UI만 있음, 동작은 미구현)
  dev/ api/dev/         피부 분석 연구 도구 (개발 환경 전용)
server/                 피부 분석 연구 도구의 개발용 프록시 · Python 평가 코드 (nia/ acne/)
components/             UI 컴포넌트 (ui/ 범용 · shop/ celeb/ ar/ 기능별)
  ar/                   얼굴 추적 렌더러 (WebView / 웹 iframe 공용 HTML)
hooks/                  화면용 조합 훅 (장바구니 + 제품 조회 등)
lib/                    API 클라이언트, react-query 훅, 로그인(auth/), i18n, 포맷
store/                  Zustand (장바구니·쇼핑리스트·설정은 기기에 저장)
constants/              테마, 약관 등 정적 상수
__tests__/              장바구니 · i18n · 로그인 · AR · API 주소 테스트
ml/                     독립 Python 학습 프로젝트 (src · configs · tests · uv.lock)
reports/                학습·평가 문서와 공유 가능한 결과 요약
backend/                FastAPI 백엔드 (서비스별 uv 프로젝트)
  api/                  카탈로그 · 판매처(네이버) · 튜토리얼(YouTube) · 셰이드 추천(ΔE2000) · 회원
                        — PostgreSQL · Redis, 카탈로그 시드는 seed/catalog.json
  chatbot/              챗봇(GraphRAG) · PostgreSQL→Neo4j 동기화 잡 — Neo4j · LLM
infra/
  compose/              로컬 전체 구성 (게이트웨이 · 두 서비스 · DB 3종)
  render/               팀 공용 dev 서버 (Render Blueprint: api · chatbot, 무료)
  helm/vishue/          쿠버네티스 차트 (values-local: kind, values-prod: 운영)
  terraform/aws/        AWS 인프라 코드 (VPC · EKS · RDS · ElastiCache · Secrets Manager · 배포 권한)
  argocd/ platform/     GitOps 애플리케이션 · 클러스터 공용 리소스
.github/workflows/      ci (변경 영역별 검사 → ci-ok) · images (GHCR 발행 → 운영 태그 PR)
```

API 키는 백엔드(`backend/`)에서만 읽고 앱 번들에는 포함되지 않습니다.

## 실행

**Expo SDK 58** (Expo Go 58.x와 호환). 앱은 백엔드에서 데이터를 받습니다. 보통은 팀 공용 dev 서버(Render)를 쓰고, Docker는 필요 없습니다.

```bash
npm install
cp .env.example .env      # EXPO_PUBLIC_API_BASE_URL에 dev 서버 주소 입력 (팀에서 공유)
npx expo start -c
```

- 폰: PC와 같은 Wi-Fi에서 QR 스캔 (iOS Expo Go는 PC와 같은 Expo 계정으로 로그인 필요)
- 웹: 터미널에서 `w`
- dev 서버는 15분 동안 요청이 없으면 잠들어서, 첫 요청이 30초~1분 걸릴 수 있습니다.
- AR은 첫 진입 시 카메라 동의 → 권한 요청. 얼굴 추적 모델은 처음 한 번 인터넷에서 내려받습니다.
- 제품 데이터 바꾸기: [`docs/DATA.md`](docs/DATA.md)

백엔드를 직접 고치며 확인하려면 내 PC에서 띄웁니다(Docker Desktop 필요). `EXPO_PUBLIC_API_BASE_URL`을 비워 두면 앱이 내 PC의 `:8080`으로 연결됩니다.

```bash
docker compose -f infra/compose/compose.yaml --env-file .env up -d --build   # → http://localhost:8080
```

### 환경 변수 (`.env`)

| 변수 | 읽는 곳 | 용도 |
| --- | --- | --- |
| `YOUTUBE_API_KEY` | 백엔드 | 튜토리얼 검색 (YouTube Data API v3) |
| `NAVER_CLIENT_ID` / `NAVER_CLIENT_SECRET` | 백엔드 | 실제 제품 이미지·온라인 최저가 (네이버 쇼핑 검색 API) |
| `LLM_API_KEY` / `LLM_MODEL` | 백엔드 | 챗봇 |
| `EXPO_PUBLIC_SUPABASE_URL` / `EXPO_PUBLIC_SUPABASE_PUBLISHABLE_KEY` | 앱·백엔드 | 로그인 (Supabase Auth). 공개용 값이라 앱에 포함됨 |
| `EXPO_PUBLIC_API_BASE_URL` | 앱 | 백엔드 주소 (공개 값). 개발 중에는 비워 둠 |

백엔드 키에는 `EXPO_PUBLIC_` 접두어를 붙이지 마세요. 붙이면 앱 번들에 노출됩니다. 예외는 Supabase의 Project URL과 publishable 키, 백엔드 주소뿐이고, Supabase secret(`service_role`) 키는 절대 넣지 않습니다.

## 스크립트

DL 개발 테스트는 최종 가중치 묶음을 받은 뒤 `npm run nia:test`로 실행합니다.
[가중치 배치와 최초 실행 안내](reports/skin-analysis/model-handoff.md)를 참고하세요.

모바일 Expo Go에서는 WebView 카메라·자동 촬영·기기 내 WASM 피부 분석 실험을 실행할 수 있습니다.
Android 네이티브 경로를 시험할 때는 별도 Expo 개발/내부 빌드를 사용합니다.
`npm run skin:prepare`로 모바일 모델을 준비한 뒤
[모바일 피부 분석 실행·측정 안내](reports/skin-analysis/mobile-analysis.md)를 따릅니다.

```bash
npm run check      # 타입체크 + 린트 + 테스트
npm test
npx expo-doctor

# 백엔드 API 문서 (Compose 실행 중) → http://localhost:8080/api/docs
```

## 배포

- 백엔드(`backend/`): 컨테이너 이미지로 GHCR에 발행되고, Helm 차트와 Argo CD로 EKS에 배포됩니다. 흐름은 [`docs/DEPLOYMENT.md`](docs/DEPLOYMENT.md)를 참고하세요.
- 앱: EAS Build/Submit — `npx eas-cli@latest build --profile production --platform all`. 빌드 전에 EAS 환경 변수 `EXPO_PUBLIC_API_BASE_URL`에 백엔드 주소를 넣습니다.

자세한 순서는 [`docs/LAUNCH_CHECKLIST.md`](docs/LAUNCH_CHECKLIST.md) 참고.


## 피부 분석: 같은 저장소, 서로 다른 실행 환경

- 사용자 개발 PC: `npm ci` → `.env.example`을 `.env.local`로 복사하고 공개 API/Supabase 설정 입력 → `npm run client` → Expo Go 접속.
- 기본 모드는 서버 분석이다. 사용자 PC에는 Python/CUDA/모델 파일이 필요하지 않다. 기존 일반 백엔드 주소 `EXPO_PUBLIC_API_BASE_URL`과 GPU 주소 `EXPO_PUBLIC_SKIN_API_URL`은 구분한다.
- GPU 서버(Windows): Python 3.12·uv·NVIDIA 드라이버 준비 → 가중치 별도 배치 → `.env.skin-server.example`을 `.env.skin-server.local`로 복사 → `uv sync --project ml --locked --no-dev --group inference-server` → `scripts/start-skin-server.ps1 -HostAddress 127.0.0.1`. 이미 실행 중인 서버와 Tunnel은 그대로 사용한다.
- 기기 내 분석은 `EXPO_PUBLIC_SKIN_ANALYSIS_MODE=on-device`로 명시하고 기존 모델 준비 절차를 수행하는 별도 실험이다. 서버 분석 실패 시 자동으로 전환하지 않는다.
- 현재 사용자 승인 전송 대상은 `https://send-lots-advanced-amended.trycloudflare.com` 하나만 허용한다. 다른 origin·redirect·자동 전환은 거절한다. Tunnel 생성·재시작은 수행하지 않는다.
- 로그인 없는 임시 시험은 `.env.local`에 `EXPO_PUBLIC_SKIN_AUTH_MODE=test-token`을 명시하고 Metro를 실행한다. 마이페이지 → 피부 정보 등록의 개발용 입력란에 서버 시험 토큰을 매 촬영마다 직접 입력한다. 토큰은 메모리에서만 사용하며 환경변수·번들·로그·저장 기록에 넣지 않는다. 기본값은 `supabase`이며 시험 모드는 `__DEV__`에서만 작동한다. 자세한 설정과 실기기 검증 절차는 [GPU 서버 문서](reports/skin-analysis/desktop-gpu-server.md)를 참고한다.
- [설치·인증·전송 형식·검증 방법](reports/skin-analysis/desktop-gpu-server.md)

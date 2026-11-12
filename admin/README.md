# VISHUE 관리자 웹

Node 24와 npm을 사용한다. `npm ci`, `npm run dev` 후 출력된 주소를 연다. 로컬 화면 미리보기는 `http://127.0.0.1:5173/?demo=1`이며 개발 서버에서만 동작하는 조회 전용 모드다. 주문·상품은 예시이고 AR 평가는 v2 연구 보고서 숫자 집계다. 실제 DB나 로그인에 접속하지 않는다.

실제 API 사용 시 `.env.example`을 `.env`로 복사하고 Supabase 공개 URL·publishable 키와 API origin을 입력한다. 회원은 약관 동의 후 운영자가 역할을 지정해야 한다. secret/service_role·토스 키·DB 주소는 프런트엔드에 넣지 않는다. API는 `ADMIN_ENABLED=true`와 DB 스키마가 필요하다. 공용 적용 전 [검토안](../docs/design/admin-web-erd.md)을 확인한다.

검사: `npm run lint`, `npm run typecheck`, `npm test`, `npm run build`. root Expo와 의존성·검사를 분리한다. HTTP API 토큰 첨부는 src/api/client.ts 한 곳에서 한다. 화면/pages가 API를 호출하고 타입·계산은 아래 계층을 사용한다. 모바일·백엔드·연구 코드를 import하지 않는다.

Docker는 공개값 SUPABASE_URL·SUPABASE_PUBLISHABLE_KEY·API_BASE_URL을 runtime config.js에 넣는다. Render는 VITE_ 공개값을 빌드할 때 사용한다. SPA 경로 새로고침을 위한 nginx/Render rewrite를 포함한다.

인증 계약: [Supabase 이메일 코드](https://supabase.com/docs/reference/javascript/auth-signinwithotp), [코드 검증](https://supabase.com/docs/reference/javascript/auth-verifyotp). 로그인 설정이 없으면 설정 안내를 표시하며 임의 권한을 부여하지 않는다.

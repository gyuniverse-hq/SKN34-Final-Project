# ADR-0005 인증은 Supabase Auth를 유지하고, 백엔드는 JWKS로 토큰을 검증한다

- 상태: 채택 (2026-10-23)

## 배경

앱은 이미 Supabase Auth(이메일 코드, Google)로 로그인하고, `lib/api.ts`가 액세스 토큰을 붙입니다. 백엔드에서 자체 JWT를 새로 만들면 회원 관리와 비밀번호 처리, 소셜 로그인을 다시 구현해야 합니다.

## 결정

- 로그인과 토큰 발급은 Supabase Auth가 맡습니다. 백엔드에는 회원 비밀번호가 없습니다.
- 백엔드는 `Authorization: Bearer` 토큰을 프로젝트의 JWKS(`/auth/v1/.well-known/jwks.json`, RS256/ES256)로 **로컬에서 검증**합니다. 키는 10분 동안 캐시합니다. `aud=authenticated`, `iss`, `role=authenticated`를 확인합니다.
- 예전 방식인 공유 비밀(HS256)로 서명하는 프로젝트라면 Supabase Auth의 `/auth/v1/user`에 물어봅니다. Expo API 라우트의 `getClaims()`와 같은 전략입니다.
- 백엔드에는 공개용 Project URL과 publishable 키만 둡니다. Supabase secret(`service_role`) 키는 어디에도 두지 않습니다.

## 결과

- 대부분의 요청에서 인증 때문에 외부 호출이 생기지 않습니다(JWKS 캐시).
- Supabase 프로젝트를 비대칭 서명 키로 바꾸는 것을 권장합니다. 바꾸지 않으면 요청마다 Supabase 호출이 생깁니다.
- 회원 정보를 백엔드 DB에 둬야 해지면, 토큰의 `sub`(Supabase 사용자 ID)를 외래 키로 씁니다.

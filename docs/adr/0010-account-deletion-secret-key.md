# ADR-0010 회원 탈퇴를 위해 `api`만 Supabase secret 키를 가진다

- 상태: 채택 (2026-10-30)
- [ADR-0005](0005-supabase-auth-jwks.md)의 "Supabase secret 키는 어디에도 두지 않는다"를 이 결정으로 바꿉니다. 토큰 검증 방식은 그대로입니다.

## 배경

앱에서 계정을 만들 수 있으면 앱 안에서 계정을 삭제할 수도 있어야 합니다(App Store 심사 기준). Supabase 계정은 Auth 관리자 API(`DELETE /auth/v1/admin/users/{id}`)로만 지울 수 있고, 이 API는 secret 키(`sb_secret_...`, 예전 `service_role`)가 있어야 합니다.

대안으로 Supabase DB에 본인 계정만 지우는 SQL 함수(security definer)를 두고 앱이 직접 부르는 방법도 있었습니다. 하지만 운영 DB는 RDS라서 그 함수가 저장소 마이그레이션 밖에 따로 있어야 하고, 백엔드 회원 데이터 삭제와 계정 삭제가 두 번의 요청으로 나뉩니다.

## 결정

- `backend/api`만 `SUPABASE_SECRET_KEY`를 가집니다. 이 키는 `app/clients/supabase_admin_client.py`에서만 읽고, 계정 삭제에만 씁니다. 챗봇과 앱에는 두지 않습니다.
- `DELETE /api/me`는 Supabase 계정을 먼저 지우고, 그다음 `members` 표의 기록을 지웁니다. 계정 삭제가 실패하면 아무것도 지우지 않으므로 다시 시도할 수 있고, 이미 없는 계정(404)은 지운 것으로 봅니다.
- 주문(`orders`)은 지우지 않습니다. 거래 기록은 법정 보관 기간이 있고, 계정 정보(이메일 등)를 담고 있지 않습니다.
- 키가 없으면 탈퇴만 `503 account_deletion_unavailable`로 꺼지고, 나머지 기능은 그대로 동작합니다.
- 새 형식의 secret 키는 JWT가 아니므로 `apikey` 헤더로만 보냅니다. 예전 `service_role` 키(JWT)일 때만 `Authorization: Bearer`도 붙입니다.

## 결과

- 탈퇴가 요청 한 번으로 끝나고, 삭제 순서와 실패 처리가 백엔드 테스트로 검증됩니다.
- `api` Pod가 탈취되면 secret 키도 노출됩니다. 이 키는 RLS를 우회하므로 시크릿 저장소(Render 환경 변수, AWS Secrets Manager)에만 두고, 노출되면 Supabase 대시보드에서 바로 교체합니다.
- 탈퇴 후에도 이미 발급된 액세스 토큰은 만료(기본 1시간) 전까지 JWKS 검증을 통과합니다. 앱은 탈퇴 직후 로그아웃해서 토큰을 버립니다.

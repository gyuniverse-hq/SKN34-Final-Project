# VISHUE 웹 (쇼핑 + 관리자)

앱과 분리된 웹입니다. **포트 5174 하나**로 쇼핑과 관리자를 같이 씁니다.

- 로그인 전: 공통 로그인 화면
- 일반 회원: 쇼핑 홈·장바구니
- 직원(`staff_roles`): `/admin` 운영 화면 (admin 패키지 UI 임베드)
- AR 가상 메이크업은 구현하지 않고 앱으로 유도합니다

## 로컬

```bash
cd web
cp .env.example .env   # Supabase 공개값 + VITE_API_BASE_URL=http://127.0.0.1:8000
npm ci
npm run dev            # http://127.0.0.1:5174
```

API는 `ADMIN_ENABLED=true`와 CORS에 `http://127.0.0.1:5174`가 필요합니다.  
직원 권한은 약관 동의 회원에 `grant_staff_role`로 부여합니다.

별도 `admin` Vite(5173)는 쓰지 않습니다. admin 소스는 `@admin` 별칭으로 이 앱에 포함됩니다.  
`admin` 패키지의 `?demo=1` 미리보기만 예외적으로 `cd admin && npm run dev`로 볼 수 있습니다.

## 스크립트

- `npm run typecheck`
- `npm run build`

## 배포 메모

Render static 또는 별도 Helm 서비스로 배포할 수 있습니다. 운영 API와 같은 카탈로그·결제 계약을 씁니다.
자세한 롤아웃은 `docs/design/admin-ops-web-rollout.md`를 보세요.

# VISHUE 소비자 웹

앱과 분리된 쇼핑 웹입니다. AR 가상 메이크업은 구현하지 않고 앱으로 유도합니다.

## 로컬

```bash
cd web
cp .env.example .env   # Supabase 공개값 + VITE_API_BASE_URL
npm ci
npm run dev            # http://127.0.0.1:5174
```

API CORS에 `http://127.0.0.1:5174`를 넣으세요. 결제는 로그인 세션이 필요합니다.

## 스크립트

- `npm run typecheck`
- `npm run build`

## 배포 메모

Render static 또는 별도 Helm 서비스로 배포할 수 있습니다. 운영 API와 같은 카탈로그·결제 계약을 씁니다.
자세한 롤아웃은 `docs/design/admin-ops-web-rollout.md`를 보세요.

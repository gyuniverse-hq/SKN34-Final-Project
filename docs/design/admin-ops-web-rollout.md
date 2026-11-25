# Admin AWS 연동 · Ops · 소비자 웹 롤아웃

날짜: 2026-11-24  
브랜치: `feat/admin-aws-ops-web`  
전제: PR #285(립 제품 패널) develop 머지 완료.

## 현재 갭 (시작 시점)

| 항목 | 이전 | 목표 |
|------|------|------|
| Helm `admin.enabled` | prod false | true |
| API `ADMIN_ENABLED` | prod 미설정(기본 false) | true |
| 립 평가 이미지 | 로컬 `runtime/lip-eval` | PVC(또는 RWX) `/data/lip-eval` |
| Ops 화면 | 없음 | 추천·챗봇·시스템 |
| 소비자 웹 | 없음 | `web/` 쇼핑 + AR→앱 CTA |

## Phase 계획

1. **A** — prod admin on, ADMIN_ENABLED, lip-eval PVC, CORS/staff 런북  
2. **B** — admin Ops API·화면  
3. **C** — `web/` 소비자 쇼핑  

## 평가 이미지 정책

- 시연·평가 기간 AWS(PVC)에 보관. Git 커밋 금지.
- 점수·CSV는 DB/내보내기로 유지.
- 인프라 철거(`terraform destroy` 등) 시 PVC·스냅샷과 함께 이미지 삭제.

## 수동 체크리스트

(에이전트가 코드로 못 하는 아침 작업 — 아래「수동」절을 매 Phase 후 갱신)

### A 수동

1. AWS Secrets Manager `vishue/production/api` JSON에 평가 채점용 키 추가(없으면 자연스러움 채점 503):
   - `LLM_API_KEY`, `LLM_MODEL`(또는 `ASTRA_MODEL`), 필요 시 `LLM_BASE_URL`
2. Argo CD sync (values-prod 변경 반영). admin 이미지 태그가 레지스트리에 있는지 확인.
3. `CORS_ORIGINS`에 admin 공개 origin 포함(시크릿/컨픽 — 환경에 맞게).
4. staff grant: `uv run python -m app.jobs.grant_staff_role --user-id <id> --role admin` (약관 동의 회원).
5. 스모크: `/api/admin/me`, `/products`, `/orders`, `/lip-eval/products`.
6. 로컬에 있던 bare/real/ar는 **admin UI로 재업로드**(또는 PVC에 일회 복사).

### B 수동

1. chatbot 내부 URL이 클러스터 DNS와 다르면 `CHATBOT_BASE_URL` 조정.
2. Ops 화면 empty 상태면 데이터·권한 확인.

### C 수동

1. `web` env: Supabase 공개값, `VITE_API_BASE_URL`, AR 앱 스토어/딥링크 URL.
2. CORS에 소비자 웹 origin 추가.
3. Toss `PAYMENT_WEB_BASE_URL` / return URL을 웹 결제 완료 경로에 맞춤.

## 구현 요약

### A
- `values-prod.yaml`: `admin.enabled=true`, `ADMIN_ENABLED`, lip-eval PVC, api replicas=1
- `_backend.tpl`: api 전용 PVC 마운트
- `CHATBOT_BASE_URL` / `ADMIN_LIP_EVAL_DIR` 설정 키

### B
- `GET /api/admin/ops/{recommendations,chatbot,system}`
- admin 메뉴: 추천 Ops · 챗봇 Ops · 시스템

### C
- `web/` Vite 앱: 립 목록·상세·장바구니·주문 생성, AR→앱 CTA

## 화면·API (B 이후)

| 화면 | 경로 | API |
|------|------|-----|
| 추천 Ops | `/ops/recommendations` | `GET /api/admin/ops/recommendations` |
| 챗봇 Ops | `/ops/chatbot` | `GET /api/admin/ops/chatbot` |
| 시스템 | `/ops/system` | `GET /api/admin/ops/system` |
| 소비자 웹 | `web/` `:5174` | `/api/products`, `/api/payments/orders` |

## 철거 시

1. CSV로 점수 export.  
2. PVC/`ADMIN_LIP_EVAL_DIR` 삭제.  
3. `ADMIN_ENABLED` 끄기(선택).  
4. 클러스터·RDS 정책에 따라 destroy.

## 로컬 검증 명령

```bash
# admin
cd admin && npm ci && npm run typecheck && npm test && npm run build

# api
cd backend/api && uv run ruff check app/services/admin_ops_service.py app/routers/admin.py
uv run lint-imports
uv run pytest tests/test_admin_ops_service.py -q

# web
cd web && npm ci && npm run typecheck && npm run build

# helm
helm lint infra/helm/vishue -f infra/helm/vishue/values-prod.yaml
```

## 아침에 할 일 (번호)

1. Argo sync로 `values-prod` 반영 확인 (admin Deployment·api PVC).  
2. Secrets Manager api 시크릿에 `LLM_API_KEY` / `LLM_MODEL` 추가(채점용).  
3. `CORS_ORIGINS`에 admin·`web` origin 추가.  
4. staff grant.  
5. `/api/admin/me`·상품·주문·lip-eval·ops/* 스모크.  
6. 로컬 평가 사진 admin에 재업로드.  
7. `web/.env` 채우고 `npm run dev`로 쇼핑 확인.

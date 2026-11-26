# 관리자 웹 로컬 구현 검토 전달서

기준일: 2026-11-13. `feat/admin-web`, 최신 develop `fbf41c8`에서 분기. 공용 DB 접속·적용, 실제 평가 게시, 외부 결제 취소, Render/EKS 배포는 하지 않았다.

## DB 담당자 리뷰 필요

로컬 초안: `backend/api/alembic/versions/0034_admin_web.py`, revision **0034**, down_revision **0033**, 파일 하나. 신규 테이블은 staff_roles·admin_audit_log·product_admin_state·eval_runs다. 모든 신규 표에 RLS를 켜며 클라이언트 직접 접근 정책은 없다. 상세 컬럼·FK·인덱스·기존 검토안 차이는 [ERD](design/admin-web-erd.md)를 확인한다. 전체 서버 교체가 끝난 후에만 ADMIN_ENABLED를 켜서 이전 버전 서버가 확장 주문 상태를 읽지 않게 한다.

orders.created_at·paid_at은 기존 행 NULL을 유지하는 확장 변경이며, 추천 ERD와 **같은 migration에서 한 번만 추가**해야 한다. 지금은 이 로컬 초안에만 있다. 추천 측이 먼저 추가하면 이 초안에서 제거·통합한다. order_lines.option_id는 추가하지 않았다. 추가 stock_debited는 실제 차감량만 복원하기 위한 nullable 컬럼이다. 두 시각의 최종 소유 migration·번호·순서, 역할/감사/평가 보관 기간과 탈퇴 처리를 확정해야 한다.

product_admin_state는 CASCADE FK다. 시드가 상품을 모두 삭제하므로 같은 transaction advisory lock에서 유지되는 상품의 관리자 상태를 복구하도록 바꿨다. 제거 상품 상태만 삭제한다. 이 정책, 제품 단위 재고, ID 재등장 정책을 검토해야 한다. 감사 actor 및 평가 uploaded_by는 회원 삭제 시 SET NULL, 직원 역할은 CASCADE, created_by·updated_by는 문자열이다.

**Render는 시작 시 migration을 자동 실행한다. 이 브랜치는 DB 검토 전에 develop으로 병합하면 안 된다.** 최종 PR 직전 develop을 다시 받아 새 head와 migration 번호를 대조하고 로컬 왕복 검사를 반복한다.

## 결제 담당자 리뷰 필요

ADMIN_ENABLED=true일 때 생성 시 합산 수량을 검사하고 확정 시 잠금 아래 재검사한다. 토스 승인 → 재고 차감 → paid/paid_at → purchase_confirmed → 한 DB commit 순서다. 중복 확정은 다시 차감하지 않는다. 토스 호출에 안정된 Idempotency-Key를 사용한다. 관리자 취소는 토스 성공 후 상태 변경·실제 차감량 복원·감사를 commit한다. 취소 실패/결과 불명은 502 payment_cancel_failed와 rollback이다.

모바일 `app/checkout.tsx`는 paid만 성공으로 판단하므로 결제 상태 조회에서는 paid·preparing·shipped·delivered를 paid로 정규화한다. 관리자 조회는 실제 배송 상태를 유지한다. 모바일 코드는 읽기만 했으며 배송 상태별 호환성 테스트 4개를 추가했다.

외부 결제와 DB commit은 원자적이지 않다. 외부 성공 뒤 DB가 지속적으로 실패하거나 멱등 보존 기간이 지나면 토스 대조·환불/운영자 조정이 필요하다. 배송 연동·부분 취소·쿠폰·정산·회원 관리·실제 VLM 자동 판정은 범위 밖이다.

토스 공식 계약 확인: [결제 취소 API](https://docs.tosspayments.com/reference#결제-취소), [인증·멱등 키](https://docs.tosspayments.com/reference/using-api/authorization). `POST https://api.tosspayments.com/v1/payments/{paymentKey}/cancel`, Basic 인증, body `{cancelReason}`로 전액 취소한다. 테스트는 모의 HTTP이며 URL 인코딩과 실패 응답·동일 멱등 키를 확인한다. 실제 토스 테스트 결제 취소는 사람 확인이 필요하다.

## 로컬 사용

`admin/`에서 `npm ci`, `npm run dev`. `http://127.0.0.1:5173/?demo=1`은 개발 전용 조회 미리보기다. 상품·주문은 예시, AR 숫자는 2026-11-12 v2 5명 집계다. 별도의 DB나 Supabase 연결 없이 볼 수 있다. 실제 연결은 [배포 안내](DEPLOYMENT.md)를 따른다. 개발 서버에서 로컬 API에 연결한 경우에만 권한 없음 화면에서 본인이 약관을 확인하고 동의하여 로컬 회원 기록을 만들 수 있다. 관리자 권한은 별도로 운영자 잡이 부여하며 이 보조 화면은 운영 빌드에 들어가지 않는다.

실제 로그인은 기존 Supabase 이메일+코드, 서버 직원 역할 검사다. 프런트엔드는 공개 URL·publishable 키만 갖는다. viewer는 변경 버튼·감사 메뉴가 없고 서버도 변경을 거부한다. API는 [명세](design/api-spec.md)에 11개 경로와 권한·응답·오류를 기록했다. 입력·출력 모델은 `backend/api/app/schemas/admin.py`, 프런트 타입은 `admin/src/api/types.ts`다.

AR 집계는 `publish_eval.py --dry-run`으로 생성했다. HTTP 게시 도구는 원본 경로·개별 ID·이미지 해시를 전송하지 않는다. 집계 스키마로 생성 시·전송 전에 검증하고 HTTP redirects를 거부한다. 원본 보고서의 실제 VLM 평가는 미실행이며 대시보드도 판정 불가·미측정으로 표시한다. 같은 얼굴의 짝 차이 CI가 없으면 버전의 개선을 확정하지 않는다. MDC95는 사진 한 장의 참고값이다.

## 검증 환경과 결과

- 일회용 Docker PostgreSQL 17, `vishue-admin-review-pg`, loopback **127.0.0.1:15439**, 별도 admin_review DB. DATABASE_URL을 명시했고 기존 .env 값을 사용하지 않았다. API 통합 테스트는 추가 격리 스키마에서 실행했다.
- 빈 DB upgrade head, downgrade -1 → upgrade head 왕복, alembic check, 단일 0021 head: 통과.
- backend/api Ruff·import-linter: 통과. 전체 pytest 486 passed·9 skipped. 관리자 테스트는 49개(36개 상태 조합 포함)이며 동시 결제 경합도 검증했다. 기존 테스트 임시 폴더의 Windows 권한/부모 폴더 문제는 checkout의 tmp 아래 basetemp를 명시해 해결했다.
- admin lint·typecheck·Vitest 13개·build: 통과. 로그인 요청 오류는 안전한 오류 코드에 따라 안내하며 계정을 자동 생성하지 않는다. 최대 JS chunk 약 517KB(압축 약 150KB)의 빌드 권고가 남아 있다. root npm run check의 타입·린트는 통과했다. 병렬 Jest는 기존 테스트 2개가 시간 초과했으나 npm test -- --runInBand에서 76 suites·1,001 tests가 모두 통과했다. 테스트 제한·코드는 완화하지 않았다.
- Helm local·prod lint: 통과(icon 권고만). 관리자 Docker build와 읽기 전용·비루트 실행, `/orders/any` SPA 새로고침·`/config.js` HTTP 200 확인. 실제 클러스터 배포·브라우저 시각 검사는 미실행.
- 원래 연구 작업 공간의 기존 pytest 15개, 새 게시 도구 테스트 2개가 통과했다. v2 dry-run payload는 엄격한 스키마를 통과했다. 실제 API 업로드는 하지 않았다.

## 추가 의존성·라이선스

루트 package.json·uv.lock은 바꾸지 않았다. admin의 package-lock.json으로 고정했다. React 그래프는 SVG라 차트 라이브러리는 없다. 새 백엔드 런타임 패키지도 없다.

| 패키지 | 버전 | 라이선스 |
| --- | --- | --- |
| react / react-dom | 19.3.1 | MIT |
| @supabase/supabase-js | 2.119.0 | MIT |
| react-router | 8.5.1 | MIT |
| @tanstack/react-query | 5.107.1 | MIT |
| vite | 8.3.8 | MIT |
| @vitejs/plugin-react | 6.3.0 | MIT |
| typescript | 6.0.3 | Apache-2.0 |
| eslint | 10.14.0 | MIT |
| typescript-eslint | 8.72.2 | MIT |
| vitest | 5.1.0 | MIT |
| @testing-library/react | 16.3.3 | MIT |
| @testing-library/jest-dom | 7.0.1 | MIT |
| jsdom | 31.0.0 | MIT |
| @types/react / @types/react-dom | 19.3.0 | MIT |

TypeScript는 typescript-eslint의 지원 범위(<6.1)에 맞춰 6.0.3을 선택했다. 개발 도구의 minimatch 취약점(GHSA-g3hv-75wg-m249)은 11.0.8 override로 패치하고 lint·검사를 다시 실행했다. npm install 감사 결과 0 vulnerabilities. Prettier 3.10.1(MIT)은 일회성 포맷 도구로만 사용했다.

## 변경 파일 범위

- backend/api: 신규 admin 모델·스키마·라우터·인증/업무/재고 서비스·관리자/재고 repository·grant 잡, 단일 migration, 통합/계약 테스트·숫자 픽스처. 기존 결제·토스 client·카탈로그 시드 repository·CORS·주문 모델·응답을 보완했다.
- admin/: 독립 앱·로그인·권한별 화면·주문·상품·평가·감사 페이지·API·타입·테스트·개발 전용 미리보기·Docker/nginx·환경 변수 예시.
- research/lip_rubric/: publish_eval.py·모의 HTTP 테스트·README만 추가. 원래 실험 코드나 얼굴 데이터는 복사하지 않았다.
- infra/: Render 정적 사이트·CORS 입력, Helm admin deployment/service/route·NetworkPolicy·local 값. .github/workflows/: admin 검사와 ci-ok 집계, 이미지 publish 설정.
- docs/: ADR-0011·색인, 아키텍처·API·배포·데이터 안내·ERD·이 전달서. 루트 tsconfig와 ESLint에서 admin을 제외했다. 모바일 화면·컴포넌트·hook·lib·store는 수정하지 않았다.

## 사람이 할 일

DB·결제 담당자가 위 변경을 검토하고 추천 측 주문 시각 migration과 통합한다. 병합·배포로 스키마가 반영된 뒤 운영자가 grant_staff_role로 최초 관리자를 지정한다. Render 사이트·공개 환경 변수·CORS를 설정하고 ADMIN_ENABLED를 활성화한다. 마지막으로 실제 이메일 로그인·토스 테스트 취소·배포 화면을 확인하고, 검토한 v2 요약을 publish_eval.py로 게시한다.

## PR 본문 초안

### 변경 사항

팀 내부 관리자 웹과 권한·감사·주문·상품 상태·숫자 평가 API를 추가하고 로컬 DB에서 검증했습니다. 공용 DB와 실제 결제·배포에는 적용하지 않았습니다.

### 영향 범위

- `backend/api/` — **새 테이블 4개**, **orders 상태 값 확장**, **paid 재고 차감·canceled 복원으로 결제 흐름 변경**. migration **0021**, down_revision **0020**의 로컬 초안. **DB 담당자 리뷰 필요**, **결제 담당자 리뷰 필요**.
- `admin/`, `research/lip_rubric/` — 관리자 웹과 숫자 집계 게시 도구.
- `infra/`, `.github/workflows/` — 비활성 기본값의 운영 차트와 정적 사이트·검사 설정.
- `docs/`, `tsconfig.json`, `eslint.config.js` — 설계·운영 계약 및 Expo 검사 분리.

DB 검토가 끝난 뒤 필요하면 백엔드와 관리자 웹/평가 PR로 나눕니다. 최종 PR 직전 develop 동기화, migration 번호·단일 head·로컬 왕복 검사를 다시 확인합니다.

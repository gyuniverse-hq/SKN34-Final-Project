# 관리자 웹 DB 설계 · 로컬 구현 검토안

기준일: 2026-11-13

**로컬 임시 DB에만 구현·검증하며 공용 DB에는 미적용. DB·결제 담당자 검토 전 병합·배포 금지.**

사용자의 후속 지시에 따라 문서 합의 → 구현 순서를 로컬 구현 → 변경안 검토로 바꿨다. 이전 검토안(`docs/admin-web-erd`, `9bae038`)과 달라진 컬럼·기본값·FK를 아래에 명시한다. 기준 develop은 `fbf41c8`, head는 `0033`. `0034_admin_web.py`(revision 0034, down_revision 0033)는 로컬 초안이며 최종 번호가 아니다.

## 1. 변경 범위 요약

| 구분 | 대상 | 변경 |
| --- | --- | --- |
| 신규 | staff_roles, admin_audit_log, product_admin_state, eval_runs | 직원 권한·감사·재고/노출·숫자 평가 집계 |
| 기존 보완 | orders | nullable created_at·paid_at, 생성시각+ID 인덱스. String 상태 값 확장 |
| 기존 보완 | order_lines | nullable stock_debited: 실제 차감량 스냅샷. 제한 없음·유한 재고 전환 후 취소 오복원 방지 |
| 기존 재사용 | members, products, shades, user_behavior_events | 회원·카탈로그 원본·paid 확정 구매 이벤트 |
| 다른 제안과 공동 협의 | orders.created_at·paid_at, order_lines.option_id | 시각은 추천 측과 **같은 마이그레이션에서 한 번만 추가**. 현재 초안에 시각을 모았으며 추천 측 선반영 시 이곳에서 제거·통합. option_id는 추가하지 않음 |

추천 ERD `recommendation-v2-feedback-erd.md`는 기준 develop 및 기존 로컬 docs에서 찾지 못했다. `0020`은 추천/노출/행동 이력만 만들며 orders의 두 시각·order_lines.option_id를 추가하지 않는다. 원본 ERD와 옵션·구매 귀속 계약은 담당자가 확인해야 한다.

## 2. 핵심 ERD

실선은 물리 FK이며 신규는 제안 구현이다. 기존 orders.user_id와 order_lines.product_id·shade_id에는 카탈로그/회원 FK가 없으므로 선을 그리지 않았다. created_by·updated_by는 문자열이며 FK가 아니다.

```mermaid
erDiagram
  MEMBERS["members 기존"] ||--o| STAFF["staff_roles 신규"] : CASCADE
  MEMBERS ||--o{ AUDIT["admin_audit_log 신규"] : "actor SET NULL"
  MEMBERS ||--o{ EVAL["eval_runs 신규"] : "uploader SET NULL"
  PRODUCTS["products 기존"] ||--o| STATE["product_admin_state 신규"] : CASCADE
  PRODUCTS ||--o{ SHADES["shades 기존"] : CASCADE
  ORDERS["orders 기존 보완"] ||--o{ LINES["order_lines 기존 보완"] : CASCADE
  LINES ||--o{ EVENTS["user_behavior_events 기존"] : "nullable FK"
```

## 3. 신규 테이블 상세

N은 NOT NULL, Y는 nullable. 시간은 timestamptz, ID UUID는 API에서 문자열이다.

### staff_roles

| 컬럼 | 타입 | NULL | 의미 |
| --- | --- | --- | --- |
| user_id | varchar(64) | N | PK·members FK CASCADE |
| role | varchar(16) | N | admin 또는 viewer |
| created_at | timestamptz | N | 기본 now() |
| created_by | varchar(64) | Y | 운영자 작업은 NULL, API 부여 없음 |

최초 관리자 포함 모든 지정·회수는 운영자 grant_staff_role 잡으로만 한다. 이전 granted_at 제안 대신 구현 명세의 created_at·created_by를 사용했다. 직원 서비스에서 require_user와 DB 역할을 함께 확인한다.

### admin_audit_log

| 컬럼 | 타입 | NULL | 의미 |
| --- | --- | --- | --- |
| id | uuid | N | PK |
| actor_user_id | varchar(64) | Y | members FK SET NULL, 운영자 잡 NULL |
| action / target_type / target_id | varchar(80) / (40) / (128) | N | 허용된 작업과 대상 ID |
| before_json / after_json | jsonb | Y | 작업별 허용된 상태 필드만 |
| request_id | varchar(128) | N | 서버 요청 ID, 유일값 아님 |
| created_at | timestamptz | N | 기본 now() |

이전 occurred_at·before_value·after_value 명칭을 이번 명세에 맞췄다. 변경과 같은 트랜잭션에 저장한다. 토큰·결제키·얼굴 자료·자유 입력 취소 사유를 감사 JSON에 넣지 않는다. 감사 API는 admin만 조회한다.

### product_admin_state

| 컬럼 | 타입 | NULL | 의미 |
| --- | --- | --- | --- |
| product_id | varchar(64) | N | PK·products FK ON DELETE CASCADE |
| is_visible | boolean | N | 기본 true |
| stock | integer | Y | NULL=제한 없음, 0 이상 |
| updated_by | varchar(64) | Y | 마지막 관리자 ID |
| updated_at | timestamptz | N | 기본 now(), 관리자 변경 시 서버 갱신 |

이전 필수 stock_quantity·기본 비노출 제안을 대체한다. 상태 행이 없어도 기존처럼 노출·재고 무제한이다. 원본 가격·이름·색은 편집하지 않는다. 시드는 제품을 삭제·재생성하므로 별도 테이블만으로 보존되지 않는다. 구현은 시드·결제·관리자 재고 변경이 같은 transaction advisory lock을 잡고, 시드가 상태를 스냅샷한 후 같은 ID로 재등장한 상품만 복구한다. 실제 제거된 상품은 CASCADE로 상태도 사라진다. 제품 ID를 다른 상품에 재사용하면 안 된다.

### eval_runs

| 컬럼 | 타입 | NULL | 의미 |
| --- | --- | --- | --- |
| id / kind | uuid / varchar(16) | N | PK, human·bench·judge |
| created_at | timestamptz | N | 저장 시각, 평가 날짜 자체와 구분 |
| renderer_commit / renderer_dirty | varchar(40) / boolean | N | 렌더러 커밋·미커밋 여부 |
| rubric_version / metric_version | varchar(64) | N | 척도·지표 버전 |
| benchmark_sha256 | varchar(64) | N | 고정 manifest 집계 digest, 개별 이미지 해시 아님 |
| summary_json | jsonb | N | 엄격한 집계 스키마 |
| summary_hash | varchar(64) | N | rendererCommit·kind·benchmarkSha256·정규화된 summaryJson의 결합 digest, UNIQUE 멱등 키 |
| uploaded_by | varchar(64) | Y | members FK SET NULL |

이전 evaluated_on·schema_version·metrics의 최소 제안을 확장했다. `schemas/admin.py`가 계약 원본이다. summary 허용 키: factors(total·texture·shading·gloss·boundary·adhesion의 estimate·low·high·n), reliability(raterCount·icc21·icc2k·normalizedIcc·alpha), mdc95, finishes·mouths·itaBins(허용 구간 label·total), correlations(허용 metric·spearman), codeMetrics(metric·value), pairedComparison(이전 렌더러 커밋·face-paired-bootstrap·totalDelta), vlmVerdict, unmeasured. 모든 객체는 extra=forbid다. 경로·URL·이미지 ID/해시 필드·1KB 초과 문자열·비유한 수를 거부한다. 얼굴·평가자 개별 기록과 자유 텍스트는 저장하지 않는다.

## 4. 기존 테이블 보완

- orders.status는 String(20)을 유지한다. 관리자 전이는 paid→preparing→shipped→delivered, paid|preparing→canceled만 허용한다. pending·동일 상태 재요청·완료 후 취소 등은 409 invalid_transition이다. 결제 확정의 pending→paid는 별도 기존 경로다.
- created_at·paid_at은 기존 행 NULL을 유지한다. 새 주문 생성과 paid 확정에 서버 시각을 넣는다. 미상 시각을 추정해 채우지 않는다. 관리자 목록은 NULL을 마지막으로 두고 ID를 보조 정렬한다.
- stock_debited는 제한 있는 재고에서 실제 차감한 라인 수량이다. 기존 주문·무제한은 NULL/0이며 취소 시 임의 수량을 더하지 않는다. CHECK는 0≤차감량≤quantity 또는 NULL이다.
- ADMIN_ENABLED=true일 때 주문 생성에서 합산 수량을 검사하고 paid 직전에 잠금 아래 재검사한다. 토스 승인 후 재고 차감·paid·paid_at·purchase_confirmed 기록을 같은 DB 트랜잭션으로 commit한다. 외부 호출과 DB는 원자적이지 않다. 같은 키 재시도는 멱등 처리하며 승인 후 DB 실패가 지속되면 토스 대조·환불/운영자 조정이 필요하다.
- 취소는 토스 취소가 먼저다. 실패·결과 불명이면 상태·재고·감사를 rollback하고 502 payment_cancel_failed다. 성공한 취소만 실제 차감량을 한 번 복원한다. DB 실패 뒤 재시도도 동일 토스 멱등 키를 사용한다. 취소된 주문의 purchase_confirmed는 과거 승인 사건으로 남으며 현재 매출 지표는 주문 상태를 함께 봐야 한다.

## 5. 제약·인덱스·서버 검증

역할·평가 kind CHECK, 재고 비음수 CHECK, 평가 JSON 객체 CHECK, summary_hash UNIQUE, 감사 created_at 및 (target_type,target_id,created_at), 평가 created_at, 주문 (created_at,id) 인덱스가 있다. 네 신규 테이블에 RLS를 켜고 클라이언트 정책을 만들지 않는다.

FK만으로 인가·허용 상태 전이·소속·노출·재고 경합·구매 중복은 보장되지 않는다. 서버가 검증한다. 기존 구매 이벤트 order_line 유일 인덱스와 직렬화 잠금이 중복 기록을 막는다. 옵션 ID가 없으면 shade_id를 option_id로 추측하지 않는다. 카탈로그 목록·상세의 숨김 필터와 캐시 무효화를 함께 적용한다. 모든 변경과 감사 저장은 함께 성공하거나 rollback한다.

## 6. 담당자와 확정할 사항

1. DB 담당자: `0021` 초안의 최종 번호·down_revision, 추천 ERD와 어느 쪽이 먼저인지, 주문 시각의 단일 추가 위치. 새 head에 맞춰 최종 PR 직전 재검사한다.
2. FK CASCADE+유지 상품 상태 복구, 제거/재등장 상품의 정책, 제품 단위 재고의 충분성. 이전 무FK·고아 보존안과의 차이 검토.
3. actor_user_id SET NULL 및 created_by·updated_by 문자열의 탈퇴 처리, 감사·평가 보관 기간과 집계 공개 최소 기준. 운영자 권한 회수·마지막 관리자 보호 절차.
4. 결제 담당자: paid 시 재고 차감·purchase_confirmed 순서, 외부 성공 뒤 DB 실패 복구, 토스 취소 실패/결과 불명 처리, 취소 이벤트의 분석상 해석.
5. 집계 schema 확장과 benchmark manifest digest 허용. 보고서의 팀원 소표본·낮은 렌더 원점수 일치도·미실행 VLM 한계를 표시한다.

## 7. 구현 확인 기준

권한별 401/403, 자기 부여 API 부재, 전체 36개 상태 조합, 취소 실패 rollback, 감사 실패 rollback, 재고 부족, 중복·동시 결제, paid 차감·취소 복원, 숨김 필터, 시드 상태 보존, 평가 거부 사례·멱등을 로컬 테스트한다. 빈 DB upgrade head→downgrade -1→upgrade head, alembic check와 단일 head를 확인한다. 실제 토스 결제·배포는 별도 사람 확인이다.

### 확인 근거

`AGENTS.md`, `CONTRIBUTING.md`, `docs/ARCHITECTURE.md`, `docs/DATA.md`, `docs/cosing-data-setup.md`, `docs/adr/README.md`, `backend/api/app/models/{order,catalog,member,admin,recommendation_feedback}.py`, `app/services/{payment_service,catalog_service,admin_service,inventory_service}.py`, `app/repositories/{catalog_repository,admin_repository,inventory_repository}.py`, `app/jobs/seed_catalog.py`, `alembic/versions/0004_orders.py`·`0020_recommendation_feedback_history.py`·`0034_admin_web.py`(backend/api 기준). 평가 출처는 원래 로컬 `feat/lip-rubric-eval`의 `research/reports/lip_rubric_eval.md`와 읽기 전용 eval.db·집계 JSON이다. 픽스처에는 숫자 집계만 복사했다.

DB 검증은 별도 Docker `vishue-admin-review-pg`, loopback 포트 15439의 일회용 PostgreSQL과 테스트별 격리 스키마만 사용한다. 공용 Supabase·Render DB는 조회·접속·변경하지 않았다.

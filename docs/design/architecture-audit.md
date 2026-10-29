# 아키텍처 감사

## 0. 감사 범위와 방법

2026-10-28 저장소 작업 트리의 코드·마이그레이션·설정·기존 문서를 정적으로 비교했다. 런타임, 실제 카메라, 운영 DB, 외부 제공자, 배포 상태는 확인하지 않았다. **PARTIAL**은 코드가 있지만 기능의 완결성 또는 작동이 검증되지 않았다는 뜻, **PROPOSED**는 조치 제안, **UNKNOWN**은 증거 부족을 뜻한다. 추정 위험은 실제 장애나 침해로 단정하지 않는다. 문서 작성 시 이미 존재한 결제 관련 미커밋 사용자 변경은 분석 대상에 포함하되 수정하지 않았다.

## 1. 유지할 설계

| 영역 | 관찰과 근거 | 판정 |
|---|---|---|
| 데이터 소유 | api가 PostgreSQL을 소유하고 chatbot은 `clients/catalog_client.py`를 통한 HTTP 수집으로 Neo4j 사본을 갱신한다. `backend/chatbot/app/services/graph_sync_service.py` | PARTIAL: 경계 코드 존재, 실제 동기화 미검증 |
| 그래프 갱신 | Neo4j 사본 삭제와 재생성을 단일 write transaction에 넣는다. `backend/chatbot/app/repositories/graph_repository.py` | PARTIAL: 장애·규모 시험 미검증 |
| 모바일 레이어 | `docs/ARCHITECTURE.md`, `eslint.config.js`에 화면·훅·컴포넌트·데이터 계층 규칙이 있다. | PARTIAL: 전 저장소 준수 여부는 린트 실행 결과에 따름 |
| 시드 검증 | 카탈로그 구조·제품 및 룩 참조를 확인하는 로직과 테스트가 있다. `backend/api/app/jobs/seed_catalog.py`, `backend/api/tests/test_seed_catalog.py` | PARTIAL: 실제 데이터·실행 결과 미확인 |
| 장애 격리 | chatbot 별도 프로세스·키·레이트 제한; Redis 미설정 시 대체 경로; health/readiness 분리. `backend/*/app/core/`, `backend/*/app/routers/health.py` | PARTIAL: 부하·복구 측정 전 |
| 데이터 출처 | YouTube 후보 정규화는 DB에 직접 쓰지 않고 검토 상태를 남긴다. `backend/api/app/jobs/normalize_youtube_candidates.py` | PARTIAL: 자동 전체 매칭 파이프라인이나 정확도는 확인되지 않음 |

## 2. 우선 해결할 차이

| 우선 | 발견 및 영향 | 근거 | 제안 · 수용 기준 |
|---|---|---|---|
| P0 | 명시된 사용자 정책은 얼굴 이미지·영상의 서버 전송을 금지한다. 기존 GPU 피부 분석 문서는 JPEG 한 장 업로드 예외를 기술한다. 코드에서도 명시적인 on-device 설정이 아니면 server 모드를 선택하고, 해당 모드에서 캡처 JPEG를 POST하는 경로가 있다. 실제 전송·배포 여부는 확인하지 않았다. | `docs/ARCHITECTURE.md` 데스크톱 GPU 피부 분석 절, `lib/skinAnalysis.ts`, `hooks/useSkinAnalysis.ts`, `lib/skinServer.ts` | **PROPOSED:** 실행 경로·기본값·테스트를 감사하고 정책에 맞게 기기 내 처리만 허용. 운영·개발 모두 사진/프레임/ROI의 서버 송신이 없다는 네트워크 관측 및 자동 테스트로 입증한다. 모델 자산 다운로드와 얼굴 데이터 전송은 구분한다. |
| P0 | LLM 프롬프트는 후보에만 추천하라고 요구하지만 응답 텍스트는 후보와 사후 비교하지 않는다. 반환 제품은 검색된 후보 전체이므로 답변 속 존재하지 않는 이름이나 가격이 그대로 전달될 가능성이 있다. | `backend/chatbot/app/services/chat_service.py`, `backend/chatbot/app/clients/llm_client.py` | **PROPOSED:** 구조화된 제품 ID 응답을 검증하고 미존재 ID·임의 가격을 거부/재생성 또는 안전한 대체 답변으로 처리한다. 악의적 입력과 빈 후보 평가를 통과한다. |
| P0 | 현재 미커밋 결제 흐름에서 외부 승인과 DB 커밋은 별도 단계다. 승인 성공 후 커밋 실패나 동시 승인 요청에서 상태 불일치 가능성은 코드만으로 배제할 수 없다. 실제 오류 발생은 UNKNOWN. | `backend/api/app/services/payment_service.py`, `repositories/order_repository.py`, `clients/toss_client.py` | **PROPOSED:** 제공자 멱등 계약·주문 잠금·불확실 결과 재조회/재조정 및 동시성 테스트를 추가하고 외부 승인 완료 후 저장 실패를 복구 가능하게 한다. |
| P1 | 작업 트리의 `payment_service.py`는 `app.models.order.OrderRow`를 직접 import하므로 문서의 services → models 금지와 불일치한다. 현재 계층 계약은 하위 계층 직접 접근 자체를 막는 별도 금지 규칙이 보이지 않아 이 위반을 검출한다고 가정할 수 없다. 실제 검사 결과는 미확인이다. | `backend/api/app/services/payment_service.py`, `docs/ARCHITECTURE.md`, `backend/api/pyproject.toml` | **PROPOSED:** 리포지토리 입력 DTO/팩토리로 경계를 복원하고 해당 금지 계약을 보강하거나 합의된 경계 변경을 문서·import-linter에 함께 반영한다. |
| P1 | `look_items.shade_id`, `look_products.shade_id`는 색상 복합 FK가 아니다. `order_lines`의 제품·셰이드도 스냅샷 문자열이다. 참조 검증이 빠진 입력 경로에서는 불일치 위험이 있다. | `backend/api/app/models/catalog.py`, `idol_look.py`, `order.py`; Alembic 0001–0004 | **PROPOSED:** 기존 데이터 검사 후 제품별 shade 검증을 모든 쓰기 경로에 적용하고, 이력 스냅샷 요구를 고려해 FK 도입 여부를 결정한다. 잘못된 참조 거부 테스트를 만든다. |
| P1 | 영상 제품 정규화는 휴리스틱과 검토 파일을 포함하나 제품명 정규화→판매처 실상품 매칭→정확 일치/유사 후보 신뢰도 검증까지 완성되었다는 증거는 없다. | `backend/api/app/jobs/normalize_youtube_candidates.py`, `backend/api/app/models/idol_look.py` | **PROPOSED:** 원문·출처·검토자 판단·버전을 보존하고 검증 전 후보를 실제 사용 제품으로 표시하지 않는다. 라벨링된 표본의 precision/recall을 측정한다. |
| P1 | 기본 운영 values의 hostname, image tag, Neo4j/LLM 등이 비어 있고 TLS는 false다. 템플릿은 배포 준비물을 설명할 뿐 실제 운영 보호 상태는 확인하지 못한다. | `infra/helm/vishue/values-prod.yaml`, `infra/helm/vishue/templates/gateway.yaml`, `docs/DEPLOYMENT.md` | **PROPOSED:** GitOps 배포 전 실제 값·인증서·secret 연동과 HTTPS redirect를 검증하고 readiness, 롤백 및 복구 리허설을 기록한다. |

개발 전용 NIA 프록시도 이미지가 포함될 수 있는 JSON을 로컬 Python 서비스로 전달한다 (`server/services/niaEvaluationService.ts`). localhost 여부와 관계없이 사용자의 서버 전송 금지 지시가 적용되므로 해당 연구 흐름의 허용 범위와 차단도 P0 감사에 포함한다. 이 문서 작업은 동작을 변경하지 않았다.

## 3. 성능·안정성 및 중복 검토

1. **AR — PARTIAL:** 실기기 프레임 시간, 모델 초기화, 발열·회전·메모리·조명 변화에 대한 측정 결과는 이 감사에서 확인하지 못했다. 카메라 프레임은 기기 내 처리로 유지하고 플랫폼·기기별 p50/p95와 프레임 드롭을 측정한 후 목표를 정한다. 근거 `components/ar/faceTrackerHtml.ts`, `components/ar/`.
2. **셰이드 — PARTIAL:** `shade_service.py`는 base 제품의 전체 셰이드에 대해 CIEDE2000을 계산하고 정렬한다. 카탈로그 증가 시 CPU·DB 부하가 우려되나 현재 병목이라는 증거는 없다. 규모별 부하 시험 이후 인덱싱·캐시를 결정한다.
3. **그래프 — PARTIAL:** 전체 교체는 단순하지만 카탈로그 증가 시 write transaction 크기와 동기화 시간이 커질 수 있다. 실패율과 마지막 성공 시각을 관측한 뒤 증분 동기화 여부를 판단한다. 근거 `backend/chatbot/app/repositories/graph_repository.py`, `infra/helm/vishue/templates/sync-graph.yaml`.
4. **인증·오류 공통 코드 — PARTIAL:** 양 서비스에 `core/auth.py`, `core/errors.py`, `core/ratelimit.py`가 각각 존재한다. 중복은 독립 배포에 유리하나 계약 차이 가능성이 있다. 공통 패키지 도입 전 계약 테스트와 변경 동기화 비용을 비교한다.
5. **카탈로그 표현 — PARTIAL:** 기본 `looks`/`look_items`와 YouTube 기반 `makeup_looks`/`look_products`가 나뉜다. 각각 출처·목적이 다르므로 같은 엔터티라고 단정하지 않는다. 데이터 소유권 및 변환 규칙을 명시하고 공통 기능의 의도치 않은 중복을 점검한다.

## 4. 시험과 운영 공백

저장소에는 `backend/api/tests/`, `backend/chatbot/tests/`, `server/nia/tests/`와 앱 테스트가 있다. 테스트 파일의 존재는 통과나 실기기/실서비스 검증을 의미하지 않는다. 외부 서비스 장애, 카탈로그 매칭 정확도, 얼굴 데이터 유출 방지, 조명·피부톤별 AR 품질, 결제 동시성·재조정, 데이터 복원 및 삭제 절차를 명시적으로 평가해야 한다. 배포 상태, 백업, 모델 품질·공정성, 실제 지연·비용은 **UNKNOWN**이다.

## 5. 후순위 개선

**PROPOSED:** 기능별 모듈 경계와 API 계약을 먼저 안정화하고 이후 영상 수집, 오프라인 평가, 접근성, 비용 지표를 순차적으로 보완한다. 별도 브로커나 추가 마이크로서비스는 실제 비동기 작업량과 장애 격리 필요성이 계측되기 전 도입하지 않는다. 기존 저장소 이동이나 대규모 리팩터링은 이 감사의 범위가 아니다.

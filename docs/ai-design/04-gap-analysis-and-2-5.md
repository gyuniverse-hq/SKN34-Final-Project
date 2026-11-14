# VISHUE AI — 기존 설계 대조·충돌 기록 및 2-5 인계

> 기준: `develop d1cf4868f74d2ff6db188bf2c7646146f3ec72ad` (2026-11-14 KST)  
> 상태: **읽기 기반 정적 분석**. 브랜치 작업은 문서 작성만. 운영 상태·실제 데이터 최신성·실기기 E2E 결과를 새로 검증하지 않았다.
> 관련: [상위 목차](README.md), [1단계 승인](01-user-experience.md), [2단계 구조](02-architecture.md), [2-4 실행 계약](03-execution-contracts.md).

## 1. 검토한 기존 문서

| 기존 문서 | 현재의 역할 | 이번 새 문서와의 관계 |
| --- | --- | --- |
| [`docs/ARCHITECTURE.md`](../ARCHITECTURE.md) | 앱·Gateway·API/Chatbot·DB 소유권 및 운영 구조 | 기존 런타임 사실의 기준. 이번 문서는 목표 AI 내부 구조를 보완 |
| [`docs/deliverables/vishue-system-architecture-spec.md`](../deliverables/vishue-system-architecture-spec.md) | 10/28 기준 제출용 시스템 명세 | **과거 시점 스냅샷**, LangGraph 미도입 표기를 최신 목표 미승인으로 혼동 금지 |
| [`docs/adr/0001-two-backend-services.md`](../adr/0001-two-backend-services.md) | API/Chatbot 서비스 분리 | 유지 |
| [`docs/adr/0002-postgres-source-neo4j-copy.md`](../adr/0002-postgres-source-neo4j-copy.md) | Catalog PostgreSQL 원본·Neo4j 사본, 서비스 소유권 | 유지. 새 챗봇 영속 데이터의 소유권은 별도 ADR 필요 |
| [`docs/adr/0007-observability.md`](../adr/0007-observability.md) | JSON 로그·요청 ID·Langfuse 관측 결정 | 기존 결정 존중; Agent trace 및 사용자 미디어/개인정보 제한 추가 검토 |
| [`docs/adr/0008-aws-environments.md`](../adr/0008-aws-environments.md), [`0009`](../adr/0009-render-dev-environment.md) | 초기 dev/운영 인프라 결정 및 dev 대체 | 최신 로컬·운영 배포 사실과 구분 |
| [`docs/ai-alignment/README_FIRST.md`](../ai-alignment/README_FIRST.md) | 10/31 AI 평가·Codex 인계 자료 | 기존 평가 원본/Gold 검수 상태 보존. 새 12개 과업 화이트리스트 아님 |
| [`docs/INGREDIENT_CONSULTATION.md`](../INGREDIENT_CONSULTATION.md) | 성분 검증·오류·회귀 계약 | Tool/근거 검증에 재사용. 모든 자연 대화 정책을 대표하지는 않음 |
| [`docs/AIHUB_DATA_RIGHTS.md`](../AIHUB_DATA_RIGHTS.md) | AIHub 원문·발췌 보관 및 이용권한 | 서비스 RAG·외부 모델 제공 승인 전 제한 유지 |
| [`docs/AIHUB_REVIEW_CONTRACT.md`](../AIHUB_REVIEW_CONTRACT.md) | QA/문서/주장 검수·권한·발행 계약 | 승인 자료 0건 기준 기록; 현재 DB 실측 아님 |
| [`docs/LOOK_FLOW_SPEC.md`](../LOOK_FLOW_SPEC.md), [`docs/AR_SPEC.md`](../AR_SPEC.md) | 기존 룩·AR 실행·카메라 개인정보·시연 범위 | 기존 AR 내부 소유권 유지. 대화 통합·업로드/음성 정책만 별도 설계 |
| [`docs/LAUNCH_CHECKLIST.md`](../LAUNCH_CHECKLIST.md) | 출시 전 개인정보·실기기 등 수동 확인 | 기존 '마이크 권한 없음/이미지 수집 없음' 가정은 새 목표와 재검토 필요 |

## 2. 목표 설계와 기존 명세·구현의 차이

| ID | 현재 근거 | 이번 목표 설계 | 차이 유형 및 처리 |
| --- | --- | --- | --- |
| G-01 | 기존 `ChatService.route_intent/build_plan`; `compound_request_unsupported` | 복합 자유 질문·다단계 계획·재판단 | **설계 변경 필요**: 단일 intent/정규식 분기는 전문 Tool 내부에만 남기고 Supervisor가 목표 조정 |
| G-02 | `schemas/supervisor.py` `TaskPlan.tasks` 최대 2개, 단일 ToolResult | 작업 DAG·병렬/Handoff/부분성공 | **새 계약 제안**, 실제 API·Graph 스키마 미확정 |
| G-03 | `backend/chatbot/pyproject.toml`에 LangGraph 의존성 없음 | LangGraph·Checkpointer | **미구현** |
| G-04 | Redis `ChatSessionRepository` 600초 이하 TTL, WATCH 버전 검증 | 장기 이력+동의 기억+장애 재개 | **범위 차이**: 현재 Redis 세션 검증 재사용하되 영속 대화 별도 |
| G-05 | `docs/ARCHITECTURE.md`와 ADR-0002는 'PostgreSQL은 API만 접근' | 챗봇 영속 Checkpointer/기억을 위한 PG 후보 | **잠재적 ADR 충돌**: Catalog DB와 챗봇 전용 데이터/자격증명 분리, 서비스 소유권 명시 |
| G-06 | 기존 AR_SPEC 및 `docs/ARCHITECTURE.md`에서 실시간 얼굴 프레임 기기 내 | 사용자 제공 이미지·영상은 명시적 동의 후 서버 분석 가능 | **동의·입력 범위 차이**: 실시간 AR 프레임 비전송 유지, 별도 업로드·외부 LLM 제공 정책 새로 설계 |
| G-07 | 피부 분석 코드에 별도 `lib/skinServer.ts` 서버 전송 경로 존재 | 피부 분석 결과 활용·선별 동의 | **문서 정합성 점검**: '얼굴 영상은 항상 기기 밖으로 안 나감'의 예외 범위·해당 모드 고지 확인 필요 |
| G-08 | `lib/arCommandAck.ts`의 ACK outbox는 개발용/JS 프로세스 메모리; 일부 AR 복원 코드 | 영속 Action Ledger/Outbox, ACK 장애 복구 | **미구현·설계 제안**; 같은 명령 중복 적용 금지, AR 담당 계약 합의 |
| G-09 | `ChatService` 운영 AR 요청 저장소 미구성 시 503 차단 | 사용자 요청 후 실제 AR 상태 변경·ACK | **운영 통합 미검증**; 코드의 직접 변경 금지, 2-6 인계 |
| G-10 | `ChatRequest`는 텍스트 문자열·맥락 중심, `LlmClient.complete`는 텍스트 응답 | 미디어·STT·TTS·구조화 Tool Calling | **미구현**; 미디어 참조·원문 최소화·접근 통제 계약 필요 |
| G-11 | `backend/api/app/schemas/style_look.py`는 스타일 룩·연결 상품 정보 제공, 검수 레시피 응답 없음 | S05/S12의 검수 레시피·단계별 코칭 | **데이터/API 공백**; 실제 승인 레시피 수량·발행 경로 3단계 실사 |
| G-12 | `AIHUB_DATA_RIGHTS.md`는 외부 LLM·서비스 RAG 보류, `AIHUB_REVIEW_CONTRACT.md` 검수/발행 0건 기록 | 검증된 지식 RAG | **차단**: 이용권한·문서별 재사용·근거 승인 확인 전 색인·원문 제공 금지 |
| G-13 | Neo4j는 API 동기화 기반 관계 사본 | Neo4j+Vector Search 하이브리드 검색 | **검색 설계 미확정**: 승인된 데이터의 색인, 원본 검증, 갱신/철회 규칙 필요 |
| G-14 | ADR-0007은 Langfuse를 관측 도구로 채택(도입 자체는 별개) | Agent 실행·비용·품질 추적 | **기존 결정과 도구 재선택 주의**: LangSmith로 무단 교체하지 않음, 민감 데이터 기록 최소화 |
| G-15 | 10/31 평가 패키지: 359건, Gold 승인 0 기록 | 14개 능력·12개 과업의 자유 대화·복합 평가 | **평가 목적 차이**: 기존 평가 보존, 새 사용자 목표 평가 기준은 4단계 합의 |
| G-16 | 이전 PR #227~#232 모두 Closed·미병합, PR #229·#231 누적 의존 | 데이터 검증·평가 자산 재사용 | **코드 재통합 선결**: 최신 develop과 독립 diff·마이그레이션 번호 충돌 검증 필요 |
| G-17 | `docs/LAUNCH_CHECKLIST.md`의 '마이크 권한 요청 없음/이미지 수집 없음' 기존 출시 가정 | STT/TTS·동의된 업로드·사진/영상 기반 상담 | **출시/개인정보 명세 충돌**: 개인정보 처리방침·권한·보존·동의·스토어 라벨·시연 안내 갱신 필요 |

위의 G-07과 G-17은 새 설계가 기존 내용을 무효화했다는 주장보다 **기능별 처리 경계를 분명히 해야 하는 충돌·점검 지점**으로 기록한다.

## 3. 기존 PR #227~#232 재사용 원칙

| 기존 PR | 유용한 내용 | 이번 변경에 적용할 때 |
| --- | --- | --- |
| #227 | AIHub 원본·검수·주장 이력 | 권리 확인과 공개 발행 상태 분리, 기존 `0019` 마이그레이션 번호 그대로 재사용 금지 |
| #228 | 옵션 검색·수집가/현재가·성분 판정 | Catalog Tool 계약을 최신 API 기준으로 재작성 |
| #229 | 승인 근거 발행·철회·Redis 재검증 | 데이터/근거 코드는 보존 후보, 단일 기능 오케스트레이션은 새 계획 계약에 맞춰 재평가 |
| #230 | 36개 후보·47턴·379 assertion 및 채점기 | 기존 구조에 종속된 예상값은 재평가, Gold 승인으로 표시 금지 |
| #231 | 옵션 원문·관측·sourceVersion | 원본 귀속/완전성/검수·버전 재검증 보존 |
| #232 | 격리 실행·관측 | 새 Tool/Agent trace와 연결, mock PASS와 실제 LLM PASS 구분 |

현재 `develop` Alembic은 기존 `0019`를 넘어 후속 마이그레이션이 존재한다. 기존 PR 마이그레이션을 cherry-pick 하는 대신 최신 기준으로 선형 재구성하고 격리 DB 마이그레이션/복구를 검증한다. **이 문서 작업은 코드 이식·PR 재개·통합 완료를 수행하지 않았다.**

## 4. 상태 증거 규칙

- **EXISTING-CODE**: GitHub 파일과 해당 커밋에서 코드가 보인다는 의미.
- **TESTED**: 실제 실행한 명령/환경/데이터/결과를 기록한 경우에만.
- **VERIFIED-E2E**: 실제 LLM, DB, API, 앱, AR 실기기 등의 각각 명시된 범위가 확인된 경우에만.
- **PROPOSED**: 문서상의 권장 설계. 기술 담당/팀 합의 필요.
- **ACCEPTED-USER**: 제품 목표·정책에 대한 사용자 승인. 운영 배포 완료가 아님.
- **BLOCKED**: 권한·데이터/원본 미비 등 전제조건이 충족되지 않은 상태.

## 5. 2-5 Tool·근거·데이터 접근 설계 인계

2-5에서는 아직 최종 결정하지 않은 다음 기술 계약을 구체화해야 한다.

| 설계 대상 | 필요한 결정과 증거 | 현재 상태 |
| --- | --- | --- |
| Tool Registry | 등록·입력 출력 스키마·인증·권한·타임아웃·멱등성·실패 정책 | PROPOSED |
| Catalog Tool | 상품·판매 옵션/`shadeId`·가격 유형·기준시각·재고·조회 범위·현재값 vs 수집값 | 현재 일부 코드, 상세 계약 필요 |
| Ingredient Tool | 정확한 옵션 귀속·원문 완전성·MFDS 매핑·MATCH/NOT_MATCH/UNKNOWN/ERROR·철회·sourceVersion | 기존 성분 검증 재사용 후보, 실제 승인 근거 확보 별개 |
| Style Tool | 룩 ID, 검수 단계, 영상 구간·관찰 범위, 상품·호수·AR 지원 | 실제 검수 레시피 수량/서빙 경로 미확인 |
| Knowledge/RAG | 자료 권리 사전 검사, 검색/재순위화/출처 검증, 최신 발행·철회, 원문과 파생 색인 권리 | AIHub 권한 BLOCKED, 대체 허용 자료 후보 검토 |
| Neo4j·VectorDB | 승인된 원본 → 색인 동기화, 버전 일치, 정본 재조회, 검색 결합·성능 측정 | 벡터 기술·인덱스 미결정 |
| Media/Skin Tool | 사용자 동의·외부 업로드·보관·삭제, 관찰과 추정 구분, 피부 분석 버전·불확실성 | 2-5/3단계 상세 필요 |
| AR Action | 실제 상품·호수 확인, Action Ledger/ACK/Undo/복원 및 동일 ID 멱등성 | AR 담당과 2-6 계약 예정 |
| 오류·감사 | 권한 차단, 미확인, 조회 실패, 부분 성공, 분산 Trace·비용·실제 E2E | 2-7/4단계 상세 필요 |

**다음 진행 위치: 2-5.** 1단계의 제품 범위와 2-4 실행 정책을 유지하고 Tool/근거 경계를 정식 상세 설계한다. 신규 기술 결정은 필요한 경우 ADR을 작성하며, 현재 `develop`의 기존 아키텍처·운영 코드·ADR을 이번 브랜치에서 직접 수정하지 않는다.

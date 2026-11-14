# VISHUE — 실행·기억·Agent 협력 계약 (2-2~2-4)

> 상태: **PROPOSED 기술 상세안**. 2026-11-15. 사용자 확정 정책은 [DECISIONS](DECISIONS.md), 목표 경험은 [01](01-user-experience.md). 예시 스키마·상태값은 **API 반영 전 제안**이다. 구현·실행 테스트가 아니다.
> 기준: `develop d1cf4868`. [현재와의 차이](04-gap-analysis-and-2-5.md).

## 1. 논리적 상태의 소유권

| 상태 영역 | 소유·저장 후보 | 허용된 활용·갱신 |
| --- | --- | --- |
| Conversation | 대화방·현재 메시지·현재 목표, 영속 대화 이력과 LangGraph thread | 현재 스레드 맥락 기본 사용 |
| Execution | plan, tasks, Handoff, 중단·재개 위치, ToolResult | Checkpointer + 필요시 영속 실행 이력 |
| Session references | 순서가 확정된 상품 후보(resultSetId), 일시 필터, 캐시 | Redis TTL; 만료되면 원본 재조회 |
| Long-term memory | 동의한 취향·프로필·보유 제품 | 사용자 전용 영속 저장소, 명시적 저장·수정·삭제 |
| Catalog / Evidence | 상품·옵션·성분·룩·승인 근거·출처 버전 | 원본 소유 서비스가 기준. 대화의 과거 답변은 정본 아님 |
| Media | 업로드 식별자·검수/동의 상태·분석 관찰·만료 | 원본은 접근 통제된 별도 미디어 저장소, Checkpoint에 원본 미보관 |
| Device / AR | 실제 렌더러 상태·명령 결과·적용 ACK | 앱 권한 + 상태 버전 검증; LLM 스냅샷은 실행 근거가 아님 |

**Checkpoint는 대화와 실행 재개 도구이며 외부 시스템의 실제 행동에 대한 단독 정본이 아니다.** 대화 기록·체크포인트·동의 장기 기억의 동시 삭제 정책이 필요하다. 영속 데이터 저장 위치와 테이블·리전은 2-7/팀 ADR에서 확정한다.

## 2. 식별자·버전 계약 (권장)

| 키 | 범위·수명 | 재전송·변경 규칙 |
| --- | --- | --- |
| `ownerId/userId` | 사용자/익명 세션 권한 주체 | 토큰/세션 소유 확인, 타인의 thread·media 접근 거부 |
| `threadId` | 하나의 대화방 또는 실행 스레드 | 체크포인터 스레드 키, 소유자와 결합 |
| `turnId` | 하나의 논리적 사용자 발화 | 새 발화마다 발급. 같은 입력 재시도는 같은 turn 유지 |
| `requestId` | HTTP 처리의 멱등성 키 | **같은 논리 요청 재시도는 동일 ID·payload fingerprint**. 다른 payload 동일 ID면 409 |
| `planId` | 특정 사용자 목표의 작업 계획 | 한 턴에 여러 목표/계획 있을 수 있음 |
| `planVersion` | 계획 개정 번호 | 수정·정정 시 증가, 늦은 구버전 결과가 최신 선택을 덮지 못함 |
| `taskId` | 계획 내 하나의 작업 | 입력·의존성·실행 결과·실패 사유 연결 |
| `actionId` / `commandId` | 실제 변경 행동(AR, 저장·삭제) | 동일 행동은 장애 후에도 같은 ID로 조회·재시도. 재생성 금지 |
| `stateVersion` | 대화의 애플리케이션 버전 | 갱신 시 기대 버전 비교. 충돌 시 재조회·재계획 |
| `arStateVersion` | 기기의 실제 AR 상태 버전 | 렌더 적용 전 앱 최신 상태와 비교. 대화 버전과 별개 |
| `checkpointId` | LangGraph 저장 시점 식별 | 복원·감사 참조. `stateVersion`과 동일시하지 않음 |
| `schemaVersion` | 메시지·Tool·Agent 입출력 버전 | 호환·마이그레이션·구형 앱 처리 명시 |
| `sourceVersion` / `indexVersion` | 상품·근거 원본 및 검색 사본 버전 | 검색·상담 시 현재 유효성 재검증, 철회·변경 판정 무효화 |

**동시성 원칙:** 단일 thread에서 동시에 제출된 실행은 기대 `stateVersion`과 요청 소유자를 검사한다. 두 요청이 같은 버전을 읽으면 먼저 커밋한 것만 확정되고 나머지는 새 상태를 확인해 조정한다. LangGraph node 병렬 실행 중 `task_results[taskId]`는 각자의 키로 병합하고, `selected_product` 같은 단일값을 서로 덮어쓰게 하지 않는다.

## 3. LangGraph State 목표 구조

```python
# 의사 설계 — 코드 구현/확정 필드명이 아님
class VishueState(TypedDict):
    messages: Annotated[list, add_messages]
    thread_id: str
    current_goal: dict
    session_preferences: dict
    long_term_memory_refs: list[str]
    conversation_search_grant: dict | None
    media_refs: list[dict]
    selected_refs: dict
    plan: dict
    task_results: dict[str, dict]
    evidence_refs: list[dict]
    pending_action: dict | None
    error_events: list[dict]
    response: dict | None
    state_version: int
```

설계 구현 시 다음을 분리한다.

- **요청 입력/출력 TypedDict/Pydantic 계약** vs **LangGraph 내부 State** vs **Checkpointer 저장 직렬화**.
- **공통 State**: 사용자 목표·공유 결과 참조. **전문 Subgraph State**: 검색 루프·사고 과정이 아닌 검증 가능한 중간 결과·허용 도구.
- **비밀정보**: access token, 원본 얼굴 사진/영상, 개인 동의 상세를 메시지·LLM prompt·일반 실행 추적에 무분별하게 복제 금지.
- **병합 규칙**: 메시지 reducer, taskId 기준 결과 병합, 단일 선택/동의 변경은 버전 조건부 확정.
- **감사·삭제**: 체크포인트 속 개인 정보의 삭제·만료·보존, 장기 기억 수정·삭제와 연동.

## 4. 과거 대화 참조: 확정 B, C 확장성

현재 기본 `ContextProvider` = **현재 thread 이력 + 동의된 장기 기억**. `ConversationRetriever`는 인터페이스로 분리하지만 **사용자가 이전 대화 요청을 명시하지 않으면 호출 금지**. 호출 시 소유자·삭제·접근 권한·검색 범위 검사 후 반환한다.

향후 C 자동 관련 대화 검색은 Retriever 교체가 아니라 **검색 트리거 정책과 사용자 권한/동의 계약의 확장**으로 설계한다. 저장된 과거 추천 가격·성분은 현재 Catalog에서 재확인. 과거 기록·검색 인덱스 삭제는 연동하여 처리한다.

## 5. TaskPlan 및 하위 작업 데이터 계약

```json
{
  "planId": "example-plan",
  "planVersion": 2,
  "threadId": "example-thread",
  "turnId": "example-turn",
  "goal": "선호 스타일과 검증된 상품으로 AR 체험",
  "tasks": [
    {
      "taskId": "visual",
      "type": "visual_understanding",
      "mode": "subgraph_or_tool",
      "dependsOn": [],
      "status": "PENDING",
      "inputRefs": ["media-ref"],
      "requiredPermissions": ["media-analysis"]
    },
    {
      "taskId": "skin",
      "type": "profile_lookup",
      "mode": "tool",
      "dependsOn": [],
      "status": "PENDING"
    },
    {
      "taskId": "style",
      "type": "style_coaching",
      "mode": "subgraph",
      "dependsOn": ["visual", "skin"],
      "status": "PENDING"
    },
    {
      "taskId": "product",
      "type": "product_consultation",
      "mode": "subgraph_or_tool",
      "dependsOn": ["style"],
      "status": "PENDING"
    },
    {
      "taskId": "ar",
      "type": "ar_action",
      "mode": "controlled_workflow",
      "dependsOn": ["product"],
      "status": "PENDING",
      "requiresValidDeviceState": true
    }
  ]
}
```

값은 테스트 예시이며 실제 진행 결과나 특정 Agent 개수의 확정이 아니다. 작업 상태는 `PENDING → RUNNING → COMPLETED/PARTIAL/WAITING_USER/FAILED/BLOCKED/CANCELLED/SUPERSEDED`를 지원하고, 외부 행동 결과 불명확은 `UNKNOWN`으로 별도 기록한다. `dependsOn` 그래프에서 순환을 검출하고 실행을 차단한다. 업무 목표가 바뀌면 planVersion을 올리고 구버전 작업을 `SUPERSEDED` 처리한다.

전문 Agent 요청: `taskId`, `goal`, `contextRefs`, `allowedTools`, `dependencies`, `planVersion`, `ownerScope`, `timeBudget`, `schemaVersion`.  
전문 Agent 결과: `taskId`, `status`, `resultRefs`, `evidenceRefs`, `missingInputs`, `proposedNextTasks`, `errors`, `version`.  
Agent가 제시한 후보는 검증·정합성 검사 전까지 사용자 대상 확정 사실이 아님.

## 6. Supervisor·전문 Agent·Tool·Handoff의 권한

| 역할 | 소유 책임 | 재위임·실행의 경계 |
| --- | --- | --- |
| Supervisor | 사용자 최신 목표·전체 계획·작업 생명주기·결과 구성 | 계획 변경·다른 전문 영역 이동은 여기서 조정 |
| 전문 Agent/Subgraph | 위임된 전문 목표의 세부 계획·Tool 조합·반복 | 허용된 도구만 실행; 다른 업무 필요 시 결과/Handoff 요청 |
| Tool Executor | 실제 API·모델 호출과 구조화된 결과 | 입력 검증, 인증/권한/마감시각/멱등성 적용 |
| Evidence Validator | 권리·출처·발행·버전·실제 상품/옵션 검증 | 미확인·실패를 확정 판정으로 승격 금지 |
| Action Controller | 실제 변경 행동 승인·중복 방지·결과 추적 | 명확한 사용자 의사·기기 현재 상태·부작용 확인 |
| 앱·AR 실행 계층 | 실제 렌더 상태·ACK | LLM/서버 제안만으로 적용 성공 선언 금지 |

Handoff 시 반드시 `fromAgent`, `toAgent`, `taskId`, `reason`, `contextRefs`, `planVersion`, `returnTo`, `executionGrant`를 남긴다. Supervisor가 승인한 계획의 고정 전이는 코드로 수행할 수 있으며, 매 호출마다 Supervisor LLM 재판단을 강제하지 않는다.

## 7. 순차·병렬 실행의 조정

- 선행 의존성이 없는 읽기 작업은 병렬 허용: 예) Visual 분석과 동의된 프로필 조회.
- 의존성 있는 작업은 선행 결과/근거 상태를 받아 실행: 스타일 → 상품·호수 → 필요한 성분 → AR.
- 병렬 결과는 각각의 taskId·inputHash·planVersion과 함께 수집한다. 최신 계획의 입력과 다른 오래된 결과는 사용자 선택·상태에 커밋하지 않는다.
- Agent가 여러 Tool을 쓰더라도 개인 정보와 원본을 무제한 공유하지 않는다. 입력 범위·권한·목표를 좁힌 참조만 전달한다.
- 성분 조건의 부재 확인 등 직접적인 사실 판단은 Tool/근거 검증이 책임진다.
- 부분 작업 실패는 사용자 목표 실패로 자동 승격하지 않는다. 유효한 일부 결과·대안·추가 질문이 가능하다.

## 8. 동시 요청 정책: 확정 C

**사용자의 최신 명시적 목표는 지체 없이 반영. 취소 가능한 조회·분석은 취소/재계획하며, 외부 상태 변경은 실행 상태를 조사한 후 후속 행동을 결정**한다.

| 상황 | 계약 |
| --- | --- |
| 취소 가능한 검색·LLM 분석 | 취소 신호 전달, 취소가 늦게 적용돼도 구버전 결과 무효화 |
| 이미 전달된 AR 명령 | 무조건 재전송·중복 실행하지 않음; 기존 actionId의 실제 렌더/ACK 상태 먼저 확인 |
| 명령 실행 전 사용자 취소 | 아직 적용되지 않았으면 취소, 실행 기록 남김 |
| 적용 후 되돌리기 | 별도 Undo 행동과 이전 성공 상태 참조, 현재 arStateVersion 확인 |
| 실패 후 복원 | Restore 독립 상태/결과/ACK 관리. 취소·Undo와 동일시하지 않음 |
| 신규 발화 중 기존 결과 도착 | 일치하는 planVersion/inputRef만 반영; 오래된 답변은 최신 사용자 목표에 끼어들지 않음 |

**ACK 유실 ≠ 실행 실패**. 기기 상태와 영속 Action Ledger 확인 없이 사용자에게 적용 완료 또는 미적용을 단정하지 않는다.

## 9. 영속 기록·재시작·멱등성

| 구성요소 | 데이터 소유권 | 복구 기준 |
| --- | --- | --- |
| LangGraph Checkpointer | thread·그래프 노드·작업 결과·사용자 입력 대기 | 마지막 영속 checkpoint에서 재개, 재개 전 부작용 확인 |
| 챗봇 기록 DB (제안) | 대화·동의·Action Ledger/Outbox·작업 이벤트 | 사용자별 권한, 조건부 상태 갱신·복구·감사 |
| Redis | 10분 내 상품 후보/일시 세션/캐시 및 보조 중복 정보 | 만료 후 정본 조회; Redis만 믿고 외부 행동을 재실행하지 않음 |
| Catalog API + PostgreSQL | 상품·옵션·성분·룩의 기준 정보 | 항상 원본 API 검증 |
| AR 기기 | 실제 실행·렌더 상태 | actionId, arStateVersion, 앱 renderer 결과, ack 영속화 계약 필요 |

권장 실행 기록 상태: `PREPARED → DISPATCHED → APPLIED/NO_CHANGE/FAILED/REJECTED/UNKNOWN`, ACK 전송 상태 별도. 실제 명령 의도·actionId를 **실행 전에 영속 기록**하고, ACK를 재전송할 때는 같은 actionId와 결과를 재사용하며 명령 자체를 재적용하지 않는다. 영속 Outbox의 전송·중복 규칙은 AR 담당과 2-6에서 합의해야 한다.

실패 시 재계획: 네트워크 오류는 제한 재시도, 입력 부족은 질문, 근거 부족은 UNKNOWN, 권한 미확정 자료는 검색 단계부터 차단, 상태 충돌은 최신 조회, 앱 ACK 불명확은 Action Ledger/기기 재조회 후 결정. 사용자 목표의 `COMPLETED/PARTIAL/WAITING_USER/FAILED` 최종 상태는 Supervisor가 검증 계층 결과를 종합해 작성한다.

## 10. 실제 구현과 구분해야 할 차이

- 현행 `ChatService.build_plan`은 복합 요청을 중단하며 `TaskPlan.tasks` 최대 2개. 위 DAG 계획은 **목표 계약**.
- 현행 Redis 세션은 600초 최대, `WATCH` 기반 충돌 검사 존재. 새 영속 Checkpointer·장기 대화 DB가 구현됐다는 뜻이 아님.
- 현재 JS ACK Outbox는 프로세스 메모리에만 존재. 영속 Outbox·서버 Action Ledger 및 운영 AR 안정성이 확인되지 않음.
- 실기기 렌더 결과와 서버 ACK는 다른 사실. 실제 AR 명령의 중복·취소·복원은 통합 시 E2E로 검증해야 함.

## 11. 열린 기술 검토 항목 (미확정)

1. 영속 체크포인터와 챗봇 전용 DB의 물리 배치·소유 권한·암호화·유지 기간.
2. 프로필·대화·영상·Checkpoint 연결 삭제 및 동의 철회 시 중단·폐기 정책.
3. 장기 대화 검색의 대상·색인 방식과 향후 C 자동 검색 동의 UI.
4. 이벤트·Outbox 스키마, 모바일 프로세스 재시작 후 ACK 결과 회수 방식, 장기 실행 작업 마감.
5. LangGraph 세부 node/subgraph·동적 Send, 결과 reducer, 최대 반복·비용·지연 기준.
6. 사용자 표시용 진행 이벤트와 모바일 메시지 표시의 정확한 API.
7. 각 Agent의 분리가 실제 상담 품질을 개선하는지 검증할 평가 설계.

다음 [2-5 인계와 충돌 목록](04-gap-analysis-and-2-5.md)에서 Tool·권한·출처 계약을 상세화한다.

# VISHUE 공통 대화 문맥 계약 보완안

> 상태: PARTIALLY ACCEPTED — 사용자 확정 방향 4건과 pending 전이·오류 계약, 초기 입력 제한을 반영. G3 최소 구현 방향은 승인됐지만 현재 요청은 문서 반영·격리 준비안 정리까지이며 코드 수정·환경 기동은 아직 하지 않는다.
> 작성 기준: 2026-11-16. G1 `f2e25eaaf48064ab940d632683f9be225c049608`, G2 PR #248 `f2373a5994ce6d48ed15bb4ab838c0fffb77efee`.
> 작성 위치의 체크아웃은 G1 `feat/vishue-supervisor`다. 아래 G2 구현 설명은 별도 G2 체크아웃 검토 결과이며, 이 폴더에 G2 코드가 반영됐다는 뜻이 아니다.

## 1. 목적과 적용 경계

G2의 핵심 개발 종료를 유지하면서, G3가 기존 상품·성분 문맥을 재사용하는 방법과 G6·G7 인계 경계를 정한다. 공통 계약은 하나의 거대한 저장 객체가 아니다. 기존 정본을 참조하고 현재 요청에 필요한 값만 전달한다. 모든 필드를 VishueState·Redis·Zustand에 동시에 복제하지 않는다.

이번 결과물은 문서뿐이다. G1·G2 PR, 기능 코드, DB, 기본 OFF 플래그, 기존 평가 원본·결과를 변경하지 않는다. G4 옵션 검색과 G8 복합 Agent 실행을 선행 구현하지 않는다. 아래 변경 후보는 이후 승인과 담당자 협의를 위한 범위이며 수정 지시가 아니다.

### 기존 문서와의 관계

| 기준 자료 | 그대로 유지할 계약 | 이 문서의 보완 |
| --- | --- | --- |
| [01 사용자 경험](01-user-experience.md) | 현재 방 중심, 동의 장기 기억, 명시적 과거 방 요청 정책 B | 문맥 선택·다른 방 조회의 경계 |
| [03 실행·기억 계약](03-execution-contracts.md) 1~4절, 13~14절 | 상태 소유권, ID/버전, Handoff, 실제 상태와 checkpoint 구분 | 현재 코드 필드와 연결하고 구현 단계를 표시 |
| [04 차이 분석](04-gap-analysis-and-2-5.md) | 목표 설계와 구현을 구분 | G2 이후 문맥 관련 차이를 한정해 추가 |
| [05 근거·데이터](05-tool-evidence-data-contract.md), [06 Tool 구현](06-tool-implementation-contracts.md) | 원본·도구 근거와 실행 검증 | evidenceRefs를 정본 대신 쓰지 않는 규칙 |
| [07 언어·평가](07-ko-first-language-and-evaluation.md), [08 옵션 근거](08-option-search-evidence-and-sync.md) | 한국어 우선 검증, 옵션 귀속·근거 상태 | G3 검증 기준과 G4 경계 |
| [G1 종료 문서](../ai-alignment/04_llm_stage4_evaluation/g1_open_issues.md) | 개발 종료와 후속 평가·통합 분리 | G1 평가를 재개하지 않음 |
| G2 `docs/ai-alignment/04_llm_stage4_evaluation/g2_implementation.md` @ `f2373a5` | 단기 세션·CAS·일반 설명 보존, G7 어댑터 | G3의 최근 문답·확인 질문 연결 |
| 멘토링 숙제 05 조사 보고서 | DST + 최근 대화 + 필요한 기록 선택을 우선 검토 | 기술 후보를 단계별 계약으로 정리 |

숙제 05 입력은 `C:/Users/playdata2/Downloads/VISHUE_멀티턴_대화_효율화_조사_보고서.md`다. 보고서의 PoC 16/16은 기존 기록상 구조화 명령의 상태 전이 결과이며 실제 LLM 이해·토큰 절감 증거가 아니다. 원본 실행 자료를 이번 문서에서 재검증하지 않았다. 실제 모델 효율 비교와 STT·AR 통합은 보고서에서도 미실시다. 보고서의 기술 후보나 참고 링크를 구현 의무로 취급하지 않는다.

## 2. 현재 코드와 재사용 범위

경로는 저장소 상대 경로이며 아래 평가는 G2 기준 커밋을 사용한다.

| 현재 구조 / 코드 | 실제 책임 | 목표 계약과의 연결 |
| --- | --- | --- |
| `backend/chatbot/app/schemas/vishue_state.py` / VishueState | turn/request/thread/result ID, 세션 버전, decision/plan/response를 담는 턴 실행 상태 | 요청별 문맥 투영의 실행 컨테이너. 영속 대화·장기 기억 저장소 아님 |
| `backend/chatbot/app/schemas/chat.py` / BeautyContext | 후보 순서, 선택 상품·호수, 필터, 발급 시각, 세션 참조 | productContext의 기존 기반 |
| 같은 파일 / ChatSessionState | 서버 소유 snapshot, 근거 참조, 마지막 요청·응답과 만료 | 단기 상품 정본. 전체 transcript나 장기 멱등 로그 아님 |
| `backend/chatbot/app/repositories/chat_session_repository.py` | 소유자·토큰·만료 검증, Redis CAS, 최대 600초 TTL | 기존 수명·권한·동시성 유지. 대화 전체 TTL로 확대하지 않음 |
| `backend/chatbot/app/schemas/catalog.py` / CatalogIngredients, IngredientDecision | product/shade/option 귀속, 성분 조건·판정, 검수·coverage·원본 버전·근거 | ingredientContext의 대상과 근거 참조. 과거 답변을 재검증 근거로 쓰지 않음 |
| `backend/chatbot/app/services/beauty_consultation_service.py` | 상품 참조·필터 병합과 Catalog/성분 조회 | 기존 조회·조건 의미를 재사용. 성분 문맥을 별도 상품 DB로 만들지 않음 |
| `backend/chatbot/app/schemas/style_recipe.py` / StyleContext | kind/lookId, recipeId/version, currentStep | styleContext 재사용. 클라이언트 단계는 힌트 |
| `backend/chatbot/app/services/style_recipe_service.py` | 레시피 조회, 버전 변경 시 단계 재설정·범위 검증 | G6 재개·단계 검증 기반 |
| `store/chatConversationStore.ts`, `types/chatConversation.ts` | 방 ID, ownerKey, 메시지, 선택 revision, generation, 요청 snapshot, 룩 단계 | 앱 UI 정본. 서버 인증이나 영속 conversation 권한의 증거는 아님 |
| `app/chat.tsx`, `hooks/useChat.ts` | 현재 요청·화면·상품·룩 문맥 전송; G2 generalMakeup 세션 연결 | G3 최소 최근 문답 전달 후보 |
| `store/makeupStore.ts`와 AR 적용 경로 | 기기 메이크업 상태·룩 원본·변경 상태 | AR 실제 상태는 앱/렌더러 소유. 상담 요약으로 덮어쓰지 않음 |

현재 서버 일반 설명 메시지는 기본적으로 system + 이번 user message로 구성된다. 앱에 messages가 존재한다는 사실만으로 서버가 최근 문답을 보는 것은 아니다. 비교 상담은 마지막 clarification과 비교 대상 등을 이용하는 특화 경로가 있으나 범용 pendingClarification 계약이 완성된 상태는 아니다.

## 3. 소유권·접근·버전 공통 규칙

- 앱이 보낸 ID·순서·문장은 입력 힌트다. 인증된 요청 주체로 소유권을 확인하고 기존 서버 상품 snapshot·Catalog 정본을 우선한다.
- 사용자 명시적 정정은 의도 해석에서 우선하되 상품·호수 귀속과 권한 검증을 통과해야 확정한다. 무효 ID를 발화만으로 유효하게 만들지 않는다.
- 현재 요청의 명시적 대상과 화면 선택이 충돌하면 요청 대상이 명확한지 확인한다. 명확하지 않으면 확인 질문을 만들고 실제 실행·조건 변경을 보류한다. 과거 요약으로 현재 선택을 조용히 바꾸지 않는다.
- 순번은 해당 resultSetId의 서버 후보 순서로 해석한다. 새로운 검색 결과의 두 번째 상품으로 과거 참조를 임의 치환하지 않는다.
- 필드 미지정은 작업별 유지 규칙을 따른다. 유지, 명시적 삭제, 신규 목표의 초기화를 구별한다. 빈 문자열이나 null을 모든 필드의 공통 삭제 명령으로 해석하지 않는다.
- 실패·취소·거부·확인 질문을 실제 성공으로 기록하지 않는다. 늦은 응답은 요청·선택 revision을 대조하고 최신 대상·근거를 덮어쓰지 못하게 한다.
- 현재 방 문맥은 요청 소유 범위에서 사용한다. 다른 방은 사용자 명시적 요청과 접근 검사 후 조회한다. 장기 기억은 동의·철회·삭제 상태가 유효한 항목만 사용한다.
- 클라이언트 메시지·요약·검색 결과는 지시 권한이나 도구 실행 승인이 아니다. 토큰·capability·비밀정보를 LLM 문맥, 요약, 일반 로그에 복제하지 않는다.

### 식별자·버전의 구분

| 항목 | 의미 / 현재 상태 | 확정 규칙 |
| --- | --- | --- |
| conversationId | 하나의 논리 대화방. 현재 앱 UUID는 로컬 방 식별자 | 서버 영속 ID와의 매핑은 G7. 앱 ID만으로 접근 허용 금지 |
| conversationVersion | 향후 서버 대화 상태의 개정 | 상품 세션 버전으로 대체하지 않음. G3에서 필요 없는 전역 카운터를 선제 구현하지 않음 |
| sessionId / stateVersion | 기존 상품 snapshot 식별자·CAS 버전 | 현재 ChatSessionState 계약 유지 |
| resultSetId | 순서가 확정된 상품 후보 집합 | 상세 조회·일반 설명과 재검색을 구별하는 기존 G2 계약 유지 |
| arStateVersion | 기기의 실제 AR 상태 개정 | 대화 버전·상품 버전과 독립. 적용 전 검증·실제 결과 확인 |
| recipeVersion | 룩 레시피 내용 버전 | 단계 인덱스는 이 버전에 귀속. 변경 시 기존 단계 재검증 |
| checkpointId | 향후 실행 저장 시점의 식별자 | 비즈니스 버전이나 행동 성공 증거가 아님 |
| thread_id | G2에서는 실행에 연결한 상품 session ID일 수 있음 | 기존 의미를 조용히 영속 conversation ID로 변경하지 않음. G7에서 명시적 어댑터 |
| schemaVersion / sourceVersion | 계약 형식 / Catalog·근거 원본 개정 | 호환성과 원본 무효화를 각각 관리 |

## 4. 공통 문맥 필드 계약

모든 이름은 논리적 제안이다. 실제 공개 API 이름·저장 타입은 해당 단계에서 확정한다. '수명'은 의미적 유효기간이며 모두 Redis TTL을 공유한다는 뜻이 아니다.

| 필드 | 의미와 정본 소유자 | 갱신·무효화 / 수명·버전 | 접근·재사용·구현 단계 |
| --- | --- | --- | --- |
| conversationId | 현재 방 식별; 앱 방과 향후 서버 방을 구별 | 새 방 생성, 사용자 전환 시 격리; G7 보관 정책 | 현재 앱 ID 재사용, 서버 매핑·소유 검증은 G7 |
| currentGoal | 현재 이어지는 과업. 서버가 검증한 의도 상태 | 명시적 목표 변경·완료·취소 시 교체; 방/과업 수명 | 현 decision/plan에서 투영. G3 성분 과업만 최소 사용 |
| activeFocus | 이번 요청의 상품·호수·룩 등 대상 참조와 선택 출처 | 명시적 선택·정정 시 갱신, 대상 충돌 시 미확정; 대상 revision에 귀속 | 현재 화면은 힌트, 서버 대상 검증. G3 상품/성분부터 |
| productContext | 후보 순서·결과 집합·선택·검색 조건 | 검색·상세·삭제는 기존 규칙; 세션 만료 시 재조회 | BeautyContext/ChatSessionState 재사용, 토큰은 prompt 제외 |
| ingredientContext | 대상 product/shade/option, 질문 조건·operator, 근거 참조·검수 상태 | 호수·상품·조건·원본 버전 변경 시 관련 판정 무효화 | Catalog 원본이 정본. G3에서 참조 연결; 전체 원문 복제 금지 |
| styleContext | 룩·레시피·단계 | 룩 전환·레시피 변경·단계 선택 시 갱신; recipeVersion에 귀속 | 기존 StyleContext 재사용, G6 확장 |
| recentMessages | 이번 해석에 필요한 최근 문답의 선택된 투영 | 새 문답·정정·삭제·소유 전환 반영; 요청 단위 선택 | G3 최소 연결. 사용자 입력/과거 답변은 사실·권한 정본 아님 |
| pendingClarification | 현재 과업의 미확정 항목과 질문·답변 연결 | 해소·취소·대상/목표 변경·기준 버전 무효화 시 종료 | G3 최소 상태. 원래 방·대상 밖에서 재사용 금지 |
| contextSummary | 오래된 문답의 파생 요약 | 원본 범위·생성 버전·정정·삭제와 연결, 낡으면 재생성/폐기 | G7. 재검증 가능한 ID/근거를 대체하지 않음 |
| evidenceRefs | 근거 ID·원본 버전·귀속·검수 상태에 대한 참조 | 대상·원본·검수/철회 변경 시 재검증 | 현 Catalog/session 참조 재사용; 조회 권한·원문 사용권 검사 |
| actionRefs | 실제 행동 요청·결과의 참조 | 요청/적용/실패/취소를 구분, 결과 이벤트로 확정 | 해당 실행 시스템 소유. AR 실제 적용은 앱 결과로 확인; G3 새 실행 로그 금지 |
| memoryRefs | 동의한 장기 기억의 참조 | 저장·수정·동의 철회·삭제에 따라 유효성 변경 | G7. 현재 세션 선호를 자동 장기 저장하지 않음 |

ingredientContext는 '질문에 답할 조건'과 '지속 검색에 적용할 조건'을 구분한다. '이 제품에 향료 있어?'를 지속 제외 조건으로 자동 승격하지 않는다. excludes + MATCH는 제외 조건 충족이라는 기존 의미를 유지한다. 전성분 미완전 UNKNOWN과 조회 실패 ERROR를 대화 요약 과정에서 확정 판정으로 바꾸지 않는다.

### pendingClarification 최소 계약

- 질문 식별자, 발생한 턴/논리 요청, goal·대상 참조, 부족한 항목, 답변 후보가 있다면 후보 참조, 생성 시 기준 버전, 상태를 연결한다.
- 상태는 최소 대기·해소·취소·무효화를 구별한다. 생성/만료 시각의 구체 정책은 대상 수명과 사용성 측정에 따라 정한다.
- 질문 중 대상·호수·목표가 바뀌면 새 문맥과의 호환성을 검증한다. 호환되지 않으면 기존 질문을 무효화하고 필요한 질문만 다시 한다.
- '03호' 같은 짧은 답은 유효한 대기 질문이 있을 때만 그 질문의 슬롯으로 해석한다. 없으면 임의 상품에 결합하지 않는다.
- pendingClarification은 사용자 승인, pending_action, HTTP 요청 중 상태, AR Undo 이력과 별개다.

## 5. 문맥 선택과 효율화

### 요청별 처리 순서

1. 요청 주체·현재 방·전달 참조의 접근 가능 여부를 확인한다.
2. 기존 상품 세션과 필요한 대상·근거를 검증한다. 순번·정확한 ID는 결정적 조회를 우선한다.
3. 현재 목표·대상·유효한 확인 질문과 관련 최근 문답을 선택한다.
4. 필요한 경우에만 허용 범위의 기록을 조회한다. 다른 방은 명시적 요청 정책 B를 적용한다.
5. 선택된 문맥으로 의도를 해석하고 출력 계획·도구 인자·근거를 검증한다.
6. 확정한 결과만 각 정본 소유자 규칙에 따라 갱신한다. prompt를 만들었다는 이유로 새 snapshot을 저장하지 않는다.

| 방법 | 역할 | 제한과 단계 |
| --- | --- | --- |
| DST | 현재 의도·대상·조건·확인 질문 추적 | 문자열 요약 대신 구조화 상태 우선. G3 기존 상태에서 필요한 부분만 |
| Sliding Window | 최근 문답의 제한된 전달 | 질문-답변 쌍과 진행 중 확인 질문을 끊지 않음. 임의 고정 N/토큰 임계치 미확정 |
| Context Selection | 현재 대상·질문에 필요한 문맥 투영 | 다른 상품·룩·방의 무관한 기록 배제. 선택 출처와 누락을 관측 가능하게 함 |
| Summarization / Compaction | 긴 문답의 오래된 부분 압축 | G7. 원본 범위·버전·ID·정정 이력 추적, 비용·정확도 실측 후 적용 조건 결정 |
| 정확한 ID 조회 | 상품·옵션·순번·명확한 기록 참조 해결 | 상품 사실은 Catalog에서 재확인. vector 검색으로 ID 귀속을 대신하지 않음 |
| 기억 검색 | 현재 상태만으로 해소되지 않는 허용 과거 기록 조회 | G7. 현재 방·명시적 이전 방·동의 기억의 검색 권한을 구별 |
| Prompt Caching | 공통 지침·도구 정의 등 반복 입력의 처리 최적화 후보 | 기억·권한·최신성 보장 아님. 공급자/모델별 조건을 적용 시 확인하고 hit·비용·지연 실측 |

Snapshot은 특정 시점의 확정 상태이고 Event Log는 무엇이 요청·실행·확정됐는지 추적하는 기록이다. 요청 snapshot만으로 실행 성공을 판정하지 않는다. G2의 last_response는 TTL 내 재전송용이며 전체 이벤트 로그가 아니다. AR '아까대로'는 실제 변경 이력을 사용하는 AR 책임으로 남기고, G3 성분 문맥 설계에 Undo 엔진을 추가하지 않는다.

## 6. 현재와 목표의 차이 및 G3 최소 변경 후보

| 차이 | G3 최소 대응 | 이번에 하지 않을 일 |
| --- | --- | --- |
| 서버에 최근 문답 목록 없음 | 현재 방의 필요한 문답만 선택·전달·검증하고 성분 해석에 연결 | 전체 transcript 영속화·다른 방 자동 검색 |
| 확인 질문이 비교 상담 등 개별 경로에 분산 | 기존 비교 후속 동작을 보존하며 성분 대상/호수 질문에 최소 pending 계약 적용 | 범용 모든 과업 오케스트레이터 |
| 상품·성분 참조는 있으나 문맥 연결 규칙이 분산 | 대상·호수·원본 버전 변경 시 재조회/무효화를 명시 | Catalog 원본·옵션 검색 API 재설계 |
| 로컬 방 ID와 서버 상품 session ID가 다름 | 관계를 명시하고 권한 주체를 혼동하지 않기 | 영속 conversation DB·Checkpointer 구축 |

### 승인 전 검토할 파일 범위

- `backend/chatbot/app/schemas/chat.py`: 최소 최근 문답·확인 질문 입출력이 필요한지 정의. 기존 상품 문맥 재사용 우선.
- `backend/chatbot/app/schemas/supervisor.py`, `backend/chatbot/app/services/chat_service.py`: 성분 목표·대상·문맥 선택 연결, 일반 상담 및 G1 OFF 호환.
- `backend/chatbot/app/services/beauty_consultation_service.py`: 기존 성분 참조·후속 질문·재검증 경로 연결.
- `app/chat.tsx`, `hooks/useChat.ts`, `types/index.ts`, `types/chatConversation.ts`, `store/chatConversationStore.ts`: 현재 방의 필요한 문답 전달, 질문 연결, 선택 revision과 늦은 응답 처리.
- 관련 chatbot·앱 테스트: 대상 변경·후속 질문·권한·기존 상담 경로를 검증.

위 목록은 전부 수정해야 한다는 뜻이 아니다. API 전달과 실제 저장 필요성을 먼저 판단한다. `vishue_state.py` 확장과 새 저장소는 선행 요구가 아니다. 기존 ChatSessionState의 선택적 pending 필드 추가는 9절에서 확정한 방향이며 구체 저장 스키마는 후속 세부 설계 대상이다. 9절에서 유효한 기존 상품 세션에 pending을 추가하는 방향은 확정했다. 수명·전이·버전의 세부 계약과 실제 코드 변경 범위는 착수 전 별도 승인받는다. 클라이언트의 대기 질문만으로 서버 권한을 인정하지 않는다.

## 7. G6·G7 인계

### G6 스타일

기존 StyleContext의 룩 종류·lookId·recipeId/version·currentStep을 재사용한다. 레시피 변경 시 이전 단계가 여전히 유효한지 서버가 판단한다. 성분 질문으로 잠시 전환했다가 돌아올 때 룩·단계를 보존할지 초기화할지 명시한다. 영상 메타데이터·일반 팁·검수된 레시피는 동일한 근거 수준으로 취급하지 않는다. 레시피에서 제안한 상품과 실제 AR 적용 완료를 구분한다.

### G7 영속화·기억

- 서버 소유 conversation과 기존 로컬 방·단기 상품 session의 매핑을 정의한다. 현재 G2 thread_id/state_version 의미를 무단 변경하지 않는다.
- 체크포인트는 실행 재개용이다. Catalog 정본과 기기 AR 상태는 복원 시 재확인한다. 만료된 세션 capability를 되살리지 않는다.
- summary는 파생물로 원본 메시지 범위와 버전을 연결한다. 정정·삭제·동의 철회 시 summary·검색 인덱스·checkpoint와의 정합성을 설계한다.
- memoryRefs는 동의한 취향·프로필·보유 제품 범위에서만 사용한다. 단기 필터나 성분 질문을 사용자 장기 특성으로 자동 저장하지 않는다.
- 세션 토큰을 포함한 last_response 전체를 영속 snapshot에 복사하지 않는다. 허용 필드를 명시하고 비밀정보를 제외한다.
- 기존 과거 방 명시적 요청 B 정책을 유지한다. 자동 관련 방 검색은 별도 정책 승인 사항이다.
- 저장 위치·보관 기간·삭제·복구·동시성 ADR과 측정 후 임계치를 확정한다. 이 문서에서 DB나 vector index 도입을 결정하지 않는다.

## 8. 핵심 시나리오와 최소 검증 기준

| 시나리오 | 기대 결과 / 확인할 증거 |
| --- | --- |
| 추천 → 두 번째 상품 → 향료 질문 | 서버 resultSet 순서의 동일 productId, 선택된 shade/option 귀속, 실제 Catalog 호출·근거 |
| 성분 답변 후 호수 변경 → 같은 질문 | 변경한 호수 재조회, 이전 옵션의 MATCH 재사용 금지, sourceVersion 연결 |
| 확인 질문 → '03호' | 유효한 질문 대상과 결합; 대상 밖 호수는 거부/재확인 |
| 확인 질문 도중 다른 상품 선택 | 기존 질문 무효화, 늦은 답변이 새 상품에 적용되지 않음 |
| 일반 설명 → '그 제품 성분은?' | 일반 설명이 상품 결과를 교체하지 않고 유효 대상에 복귀 |
| 명시적 정정·조건 삭제 | 유지와 삭제 구분, 이전 조건을 요약이나 recentMessages가 재주입하지 않음 |
| 동일 요청 재시도·늦은 응답 | 기존 멱등성 유지, 새 선택/질문 상태를 구응답이 덮지 않음 |
| 만료·타 사용자·로그아웃/전환 | 기존 403/410/409 의미 보존, 무단 조회·방 간 누출 금지 |
| 근거 부재·전성분 미완전·도구 오류 | UNKNOWN/ERROR 분리, 오래된 답변·요약으로 MATCH 생성 금지 |
| 룩 단계 중 성분 질문 후 복귀 | G6에서 룩·recipeVersion·단계 확인; AR 적용으로 오인하지 않음 |
| 이전 방 요청 없음/있음 | 없음: 다른 방 조회 없음. 있음: G7 권한·삭제·검색 범위 검사 |
| 기억 삭제·동의 철회 | G7 summary·검색 사본·복원 경로에서 삭제 항목 재등장 방지 |

G3 최소 검증은 관련 계약·서비스 테스트와 앱의 실제 요청 payload 연결을 포함한다. fixture 테스트, 실제 모델/Catalog, 실제 Redis/auth, 앱/실기기 검증을 구분해 기록한다. 테스트 이름·실행 HEAD·입력·예상 및 실제 대상 ID·필터·근거·상태 변경을 남기며 미실행을 통과로 처리하지 않는다. 기존 G1 113건 평가를 이번 계약 작성의 선행 조건으로 재개하지 않는다.

### 효율 비교 계획 — 실행 결과 아님

동일 시나리오·모델·설정·데이터 기준으로 Full History, Window, DST+Window, 필요 시 Retrieval+DST를 비교한다. 참조 해결 정확도, 잘못된 실행률, 필요한 확인 질문의 누락/과잉, 입력·출력·캐시 토큰, 실제 API 비용, 응답시간 평균·p95를 수집한다. 원본 조회·요약·검색의 비용과 지연도 포함한다. 각 방식의 정보 접근 범위, cold/warm cache, 실패·재시도·부분 결과를 분리한다. 정보 누락으로 답을 못한 결과를 토큰 절감 성공으로 계산하지 않는다.

효율 최적화용 최근 턴 수·토큰 예산·요약 임계치·장기 보관 기간과 성능 합격 수치는 미확정이다. 입력 폭증 방지용 초기 API 상한은 별도 사용자 승인으로 12절에 확정했으며 최적 window 크기를 의미하지 않는다. G3 진행에 G7 방식까지 모두 구현·실험할 것을 요구하지 않는다.

## 9. G3 착수 전 계약 결정표

2026-11-16 사용자 결정으로 다음 **네 가지 방향을 확정**했다. 이는 설계 선택의 승인으로, G3 코드·DB 변경이나 구현 착수 승인이 아니다.

1. **세션 생성 전 제한 수용:** 서버 pending 저장·복원을 보장하지 않는다. 상품 선택/구체 식별을 요청하고 후속 입력은 새 대상 해석의 힌트로 재검증한다. 가짜 후보/resultSet을 만들지 않는다.
2. **기존 세션에 pending 추가:** 유효한 상품 세션의 `ChatSessionState`에 선택적 `pendingClarification`을 두는 방향으로 진행한다. 기존 소유권·토큰·Redis·CAS 구조를 재사용하며 별도 pending 저장소를 만들지 않는다.
3. **단일 진행 요청 유지:** G3는 현재 앱의 한 번에 한 요청 제약을 유지한다. 정책 C 전체 구현으로 주장하지 않으며 선택 변경·늦은 응답 방어는 보존한다.
4. **한국어 G1 ON 재사용:** 기존 한국어 + G1 ON 경로를 사용한다. 별도 G3 플래그는 이번 범위에서 추가하지 않고, G1 기본 OFF와 OFF·비한국어 기존 동작을 유지한다.

아래 표에서 **확정**은 위 사용자 결정 및 이미 합의한 경계이고, **권장**은 그 방향을 구현하기 위한 미확정 세부안이다. 세부 권장안을 사용자 확정으로 확대하지 않는다.

| ID / 항목 | 확정 사항 및 유지할 권장안 | 남은 세부 결정 항목 |
| --- | --- | --- |
| C01 확인 질문의 정본 | **확정:** 기존 상품 세션에 선택적 서버 pending 추가, 앱은 참조/표시. 세션 생성 전 저장·복원 미보장, 별도 저장소·가짜 후보 발급 없음 | 공개 필드·질문 ID 형식, 대상·부족 슬롯·생성 요청 연결, 선택적 필드의 구형 snapshot 호환 |
| C02 pending 수명·전이 | **확정:** 기존 소유권·CAS, 세션 TTL 이내 수명, pending만으로 TTL 연장 없음. 결과 집합 유지 시 resultSetId 유지, 실제 상태 커밋 시 버전 증가. 11절 전이·오류 계약 채택 | 필드·직렬화·구형 snapshot 호환, 실제 함수별 구현·테스트 설계 |
| C03 최근 문답 입력 | **권장:** 현재 방의 필요한 user/assistant 문답만 비신뢰 입력으로 전달. 현재 발화·실패/미완료 응답 제외, 정정 우선. 서버 영속 대화 저장은 G7 | 필드명·schemaVersion, ID·순서·상태 형식, 자동 문답 포함 예외, 정정/삭제 표현, 누락·중복·역순 처리 |
| C04 재시도 문맥 | **권장:** 최초 선택 문맥을 기존 ChatRequestSnapshot.args에 고정. 같은 requestId 재시도는 동일 payload, 새 대상/답변은 새 논리 요청 | snapshot 필드·fingerprint 직렬화 호환, pending 해소 응답 유실 후 재전송, 충돌 시 재조회/재질문 UI |
| C05 입력 제한 | **확정:** 초기 API 제한은 현재 발화 1,000자, 이력 최대 8개, user 1,000자/assistant 2,000자, 이력 합계 8,000자. 스키마 초과 400 invalid_request, 전송 크기 초과 413. 64KiB 로컬 본문 제한 유지 | 64KiB의 직접 접속·운영 적용 및 413 본문 통일 범위, 앱/서버 문자 수 일치 검증. 효율 최적값은 미확정 |
| C06 동시 요청 | **확정:** 기존 단일 진행 요청 제약 유지. 제한적 취소/새 목표 동시 접수도 G3에 추가하지 않음. 최신 선택에 대한 구응답 방어 유지 | 선택 변경·pending 해소 경쟁의 결과 반영 규칙과 테스트. 정책 C 전체 취소·재계획은 별도 후속 범위 |
| C07 적용 언어·플래그 | **확정:** 한국어 + 기존 G1 ON 재사용, 별도 G3 플래그 없음, 기본 OFF 보존. OFF·비한국어 기존 동작 유지 | 비활성 경로 신규 필드 무시/검증 순서, 구형 payload 호환, 활성/비활성 평가 사례 |
| C08 성분·근거 검증 | **권장:** 기존 Catalog 귀속·검수·coverage·정규화·사용 권리 계약 재사용. 직접 관측과 부재 증명 구분. G4 옵션 교집합 선행 구현 없음 | 실제 상품/호수/자료 묶음, 허용 동의어·정규화 기준, 원문 외부 제공 권리, 버전 변경·철회·오류 응답과 필수 검증 환경 |

### 9-1. 확인 질문의 정본과 세션 생성 전 경로

현재 G2는 일반 설명 후 기존 문맥을 unchanged로 반환하는 경로에서 새 snapshot을 커밋하지 않는다. 따라서 response나 VishueState에 pending 필드만 추가해도 저장된다고 가정하면 안 된다. 저장이 필요하다면 명시적인 상태 전이와 재전송·CAS 계약이 필요하다.

**사용자 확정 방향:** 유효한 상품 세션에 성분 질문용 선택적 pending을 추가한다. **세부 권장안:** 질문 ID에 소유자, 대상 product/shade/option 또는 미확정 슬롯, 발생 요청, 기준 상태를 연결한다. 유효한 서버 pending이 없으면 짧은 답변을 이전 질문의 답으로 임의 소비하지 않는다. 다만 현재 상품에 대한 명확한 독립 선택 요청까지 'pending이 없다'는 이유로 일괄 거부하지는 않는다.

**사용자 확정 제한:** 상품 세션 생성 전에는 서버 pending 저장·재시작 복원을 보장하지 않는다. 상품 선택 또는 구체적인 식별을 요청한다. 후속 발화와 최근 문답은 새 대상을 해석하는 입력 힌트로만 사용하고 상품·호수 귀속을 다시 검증한다. 서버 pending 없이 들어온 '03호'를 이전 질문의 인증된 답변처럼 소비하지 않으며, 대상이 불명확하면 재질문한다. 확인 질문을 위한 가짜 후보/resultSet 또는 별도 pending 저장소를 만들지 않는다. **남은 세부 결정:** 선택 필드·직렬화·구형 snapshot 호환과 오류/UI 연결. TTL·버전·상태 전이·오류 의미는 11절에서 확정했다. 기존 세션 저장소 수정 필요 범위는 G3 착수 전 별도 승인한다.

### 9-2. 최근 문답의 입력·신뢰 계약

**권장안:** 일반 사용자/상담 답변 문답만 제한적으로 받으며 클라이언트가 system/developer/tool 역할을 선언해 권한을 높일 수 없게 한다. assistant 문장 역시 클라이언트 제공 이력이며 신뢰된 서버 실행 기록이나 검증된 상품 사실로 취급하지 않는다. 도구 결과가 필요하면 서버의 근거 참조로 재조회한다.

최근 문답은 현재 요청 이전의 기록이다. 이번 발화를 history와 현재 message에 중복 전달하지 않는다. 실패·미완료·취소된 응답을 성공한 상담 답변처럼 포함하지 않는다. 재시도용 UI 메시지·상태 안내와 자동 질문은 기본 제외하되, 실제 상담 연결에 필요한 자동 문답을 포함하려면 출처와 포함 규칙을 명시한다. 정정·삭제·목표 변경이 이전 문답보다 우선한다.

**결정 필요:** 메시지 ID·순서·role·내용·상태·참조의 최소 구조, 질문-답변 연결 방식, 현재 방 일치 확인 방법. G3의 앱 conversationId는 서버 영속 권한 증명이 아니므로 다른 방 조회 키로 사용하지 않는다. 메시지 순서·중복·관련성을 서버에서 검증하고, 해석 불가능한 이력은 조용히 확정 상태로 승격하지 않는다.

### 9-3. 재시도와 fingerprint 호환

G2 `_answer_session`은 요청 모델 전체를 직렬화한 fingerprint를 사용하고 같은 requestId의 다른 payload를 충돌로 처리한다. recentMessages·pending 참조가 추가되면 이 값들도 동일 요청 판정에 영향을 줄 수 있다.

**권장안:** 첫 전송 시 문맥 선택을 완료하고 `ChatRequestSnapshot.args`에 고정한다. 같은 요청 재시도 때 현재 메시지 목록을 다시 수집하지 않는다. 사용자가 상품·호수·질문 답을 변경했거나 만료 후 새 문맥으로 처리하려면 기존 요청을 새 payload로 덮어쓰지 말고 새 논리 요청·requestId를 사용한다. 비결정적 시각·매번 새로 만든 요약을 동일 요청 payload에 추가하지 않는다.

**결정 필요:** 신규 선택 필드가 생략된 기존 요청의 직렬화·fingerprint 호환, 처리 완료했으나 응답이 유실된 pending 해소 요청의 재전송 방식, 충돌 시 앱 재조회·재질문 흐름. 기존 상품 응답의 마지막 요청 캐시를 모든 확인 질문에도 이미 적용된 보장처럼 기술하지 않는다.

### 9-4. 입력 제한과 동시 요청 제약

8절의 '실측 전 임계치 미확정'은 효율 최적화 목표에 해당한다. 실제 API를 구현할 때 메시지 수·개별 길이·전체 요청 크기를 무제한으로 받는다는 뜻은 아니다. **권장안:** 서비스 제한과 기존 API 정책을 근거로 유한한 입력 상한을 정하고 초과 처리를 명시한다. 창 크기·토큰 예산의 최적값은 별도 실험으로 조정한다. 문답을 조용히 잘라 대상/부정/정정을 잃은 채 실행하지 않는다.

기존 01·03의 동시 요청 정책 C는 최신 사용자 의사를 즉시 반영하는 목표다. 현재 `app/chat.tsx`는 진행 요청이 있으면 새 전송을 막고, Zustand는 요청·generation·선택 revision으로 늦은 결과를 방어한다. 이는 정책 C 전체 구현과 같지 않다.

**사용자 확정:** G3는 현재 단일 요청 제약을 유지하고 변경된 선택에 대한 구응답 방어를 보존한다. 제한적 취소/새 목표 동시 접수를 추가하지 않는다. **남은 세부 결정:** 선택 변경과 pending 해소가 겹칠 때 최신 상태 반영·거부 규칙 및 검증 사례. 제약 유지 결정은 기존 목표 정책 C 자체의 변경이 아니다. 범용 취소·재계획과 AR 실행 복구는 이번 구현 범위가 아니다.

## 10. 보완된 G3 최소 구현·검증 범위

### 최소 구현 권장안

1. **대상·성분 연결:** 기존 BeautyContext, 서버 snapshot, Catalog 계약으로 현재 상품·호수·질문 조건·근거를 연결하고 변경 시 관련 판정을 재검증한다.
2. **최소 pending:** 성분 대상·호수의 미확정 항목만 생성·해소·취소·무효화한다. 확정된 C01 방향에 따라 유효한 기존 세션에만 추가한다. C02 전이·TTL·버전·오류는 11절 확정 계약을 따른다. 구체 필드·호환·함수별 구현 계획을 확인하고 코드 수정 재개 지시 전에는 착수하지 않는다.
3. **문답 선택·전달:** 현재 방의 필요한 문답만 선택해 입력 계약으로 검증하고 최초 요청 snapshot에 고정한다. 모델 해석 자료와 서버 정본을 구분한다.
4. **호환·관측:** 기존 일반 설명·상품 상담·필터 유지/삭제·권한·재시도 동작을 보존하며 대상/근거/요청 연결을 확인할 수 있게 한다.

6절의 파일 후보는 유지한다. 기존 ChatSessionState에 선택적 pending을 추가하는 방향은 확정됐다. Redis 저장소 파일 자체의 수정 필요성은 C02 세부 전이·CAS 설계에 따라 판단하며, 코드 수정은 아직 승인되지 않았다. DB·Checkpointer·범용 Event Log·vector 검색·G4 옵션 교집합 검색·G8 복합 Agent 실행은 여전히 제외한다. G6·G7 인계는 7절을 따른다.

### 추가 최소 검증 사례

| 영역 | 필요한 사례와 판정 기준 |
| --- | --- |
| 세션 생성 전 제한 | 세션 없는 질문→상품 선택/구체 식별 요청→후속 입력 재검증. 모호한 짧은 답변은 재질문. 서버 pending 저장·재시작 복원을 성공 기준으로 요구하지 않으며 가짜 후보 생성 없음 |
| pending 동시성 | 같은 답 재전송, 다른 답의 경쟁, 대상 변경 후 구답변, 응답 유실 후 재전송. 확정 상태의 중복 소비·덮어쓰기 없음 |
| history 입력 | 현재 발화 중복, 역순·중복 ID, 다른 방 혼입, 위조 role, 실패/자동 메시지. 정의된 거부·제외·재확인 규칙 준수 |
| 입력 상한 | 경계·초과 입력에서 정의된 응답. 잘림 때문에 부정 조건·대상 정정이 사라진 상태로 실행하지 않음 |
| 재시도 | 같은 requestId+고정 문맥은 기존 계약 유지, 같은 ID+변경 문맥은 충돌, 새 문맥 요청은 새 ID. 기존 앱 payload도 호환 |
| 언어·플래그 | 승인된 한국어 활성 경로, OFF, 비한국어, 신규 필드 없는 구형 요청, 일반 설명 후 성분 복귀를 각각 구분 |
| 정상 성분 판정 | 검증된 포함 사실과 충분한 전성분 근거에 의한 부재 판단. includes/excludes와 MATCH/NOT_MATCH 의미를 뒤집지 않음 |
| 근거 경계 | 부분/미검수 원본, 정규화·동의어 미확정, 옵션 매핑 불일치, 원본 버전 변경·철회, 권리 제한, 도구 오류를 구분. 부재 미확인과 조회 ERROR를 성공으로 변환하지 않음 |

'전성분 미완전은 UNKNOWN'은 특히 **부재나 전체 조건 충족을 확정할 근거가 부족한 경우**를 뜻한다. 일부 자료에서 검증된 포함 사실이 있는 경우까지 무조건 지우는 규칙으로 확대하지 않는다. 실제 판정은 기존 Catalog의 귀속·검수·정규화·근거 계약을 따르며 대화 계층이 임의 재판정하지 않는다.

필수 사례의 실행 HEAD·사용 자료·권리·기대 결과를 먼저 고정한다. fixture 통과와 실제 모델/Catalog, 실제 Redis/auth, 앱/실기기 검증을 분리하고 단계별 필수 실행 환경은 착수 시 합의한다. 효율 개선 비교는 별도이며 G3 기능 통과를 토큰 절감으로 대체하지 않는다. G1 평가나 전체 회귀를 계약 보완 작업의 조건으로 다시 실행하지 않는다.

## 11. 확정 pending 전이·오류 계약

사용자가 권장안을 채택했다. 한 상품 세션에는 활성 pending 하나만 둔다. 완료 질문 목록이나 범용 Event Log를 추가하지 않으며, 기존 마지막 요청 응답 캐시를 재사용한다. 상품 세션 생성 전 서버 pending 저장·복원 미보장 제한은 유지한다.

| 상황 | 확정 동작 |
| --- | --- |
| 질문 생성 | 기존 세션에 pending 저장, 세션 버전 +1. 기존 후보·필터·resultSetId·만료 유지 |
| 모호한 답변 | 같은 pending 유지, 200 clarification. 저장 상태가 같으면 버전 증가 없음 |
| 추가 슬롯 필요 | 새 질문 ID로 교체, 버전 +1. 이전 질문 ID 재사용 금지 |
| 유효 답변 | Catalog 귀속 재검증 및 원래 성분 조회 후 결과와 pending 해소를 한 CAS 커밋으로 확정 |
| 명시적 취소·다른 목표 | pending 제거를 커밋. 새 상품 검색의 후보·resultSetId·TTL은 기존 검색 규칙 적용 |
| 일반 설명 | 대상이 유지되면 pending·버전·TTL 유지 |
| 조회 오류 | 성공적으로 해소한 것으로 기록하지 않고 pending 유지. 기존 오류·재시도 경로 사용 |
| 세션 만료 | pending도 만료, 복원 금지 |

pending만의 변경은 TTL을 연장하지 않는다. 후보 집합이 같으면 resultSetId를 유지하며 실제 저장 상태 변경 때만 세션 버전을 올린다. 원래 질문의 성분 조건·목적을 구조화해 보존하여 '03호' 답변 뒤 성분 질문을 잃지 않게 한다. 전체 프롬프트나 전체 SearchPlan의 저장은 요구하지 않는다.

검사 순서: **소유권·만료 → 동일 요청의 마지막 응답 캐시 → 세션 버전/결과 집합 → 질문 ID → 답변 검증·실행 → CAS 커밋**. 응답 유실 후 같은 요청을 보냈을 때 이미 해소된 pending이라는 이유로 성공 응답 재전송을 막지 않는다. 기존 TTL 내 마지막 요청 재전송 범위를 넘어선 장기 멱등성은 보장하지 않는다.

| 조건 | 확정 응답 |
| --- | --- |
| 권한·토큰 불일치 | 기존 403 계약 유지 |
| 세션 만료 | 기존 410 계약 유지 |
| 세션 버전·결과 집합 불일치 | 기존 409 계약 유지 |
| 동일 requestId + 다른 payload | 409 `chat_request_conflict` |
| 전달한 질문 ID가 현재 pending과 불일치 | 409 `chat_clarification_conflict` |
| 질문 ID 형식·신규 필드 입력 검증 실패 | 400 `invalid_request` |
| 모호한 답·추가 확인 필요 | 200 clarification |
| 서버 저장 불가 | 기존 503 계열. 저장 완료로 표시하지 않음 |

질문 ID 없는 구형 요청은 pending 답으로 강제 소비하지 않고 독립 요청으로 처리한다. 명확한 현재 상품 선택·질문까지 일괄 거부하지 않는다. 같은 requestId 재시도는 최초 문맥 payload를 유지하고 새 대상·새 답변은 새 논리 요청으로 처리한다. 신규 선택 필드의 기본값 직렬화와 기존 fingerprint 호환은 구현 테스트로 확인해야 한다.

## 12. 확정 초기 입력 제한과 기존 표본 점검

아래 제한은 **초기 API 입력 상한**으로 사용자 승인됐다. 실제 LLM의 최적 window·토큰 예산·비용 절감 효과를 입증하거나 확정한 것이 아니다.

| 항목 | 초기 제한 |
| --- | --- |
| 현재 사용자 발화 | 기존 1,000자 유지 |
| recentMessages | 최대 8개 메시지 |
| 이력 user 텍스트 | 메시지당 1,000자 |
| 이력 assistant 텍스트 | 메시지당 2,000자 |
| 이력 텍스트 합계 | 8,000자 |
| role·ID | user/assistant만 허용, 비어 있지 않은 ID, 중복 금지, 배열 순서 사용 |
| 전송 본문 | 기존 로컬 Nginx 64KiB 제한 유지. 아래 적용 한계 참조 |

스키마·길이·개수·합계 위반은 기존 validation handler의 **400 invalid_request**, 전송 본문 크기 초과는 **413**으로 구분한다. 서버는 초과 이력을 조용히 잘라 실행하지 않는다. 앱은 관련 문답을 선택하되 문자열 중간을 자르지 않는다. 필수 질문·답변을 선택 범위에 넣을 수 없으면 누락 문맥을 추측해 실행하지 않고 재확인한다. 앱과 서버는 문자 수 계산을 일치시켜야 하며 Unicode·한글·이모지 경계 테스트를 포함한다.

### 응답 표본 근거와 한계

기존 G1 `b08ac90` 평가 원본의 JSONL을 읽기 전용 집계했다. 평가를 재실행하거나 기존 판정을 수정하지 않았다.

원본 위치: `C:/Users/playdata2/.codex/visualizations/2026/11/15/01a1dedd-94a8-72e0-ac7a-8466d24bb1e9/g1-final-b08ac90/observations.jsonl`, 판정 대조 `evaluation.jsonl`. 이 경로는 로컬 증빙 위치이며 저장소 공유 자료나 현재 G3 HEAD의 실행 결과가 아니다.

| 표본 | 건수 | answer 중앙값 | p95 | 최대 |
| --- | ---: | ---: | ---: | ---: |
| isMock=false, isSynthetic=false, HTTP 200 | 64 | 92자 | 322자 | 449자 |
| 위 표본 중 기존 평가 PASS | 42 | 92자 | 140자 | 228자 |

assistant 2,000자 초과는 0건이다. HTTP 200 전체를 의미적 성공으로 취급하지 않는다. 저장된 비어 있지 않은 실제 요청 31건은 compact JSON UTF-8 최대 238바이트였으나 세션 참조가 없어 G3 전체 payload 크기 검증을 대신하지 못한다. 긴 멀티턴 표본이 부족하므로 8개·8,000자가 최적이라는 결론을 내리지 않는다.

`infra/compose/nginx.conf`의 `client_max_body_size 64k`는 확인했다. 챗봇 직접 포트와 운영 Gateway의 동일 제한, 413의 JSON 본문 통일은 미확인이다. 이를 코드·인프라에서 추가 강제하려면 기존 최소 수정 범위 밖 요청 처리 변경 여부를 별도로 보고한다. 단순한 모델 스키마 검증을 전송 전 본문 제한으로 표현하지 않는다.

## 13. 성분 자료·환경 준비 점검 결과

점검은 로컬 파일 조회, 컨테이너/포트 상태 조회, Catalog GET, Redis PING만 수행했다. 모델 호출·평가 실행·DB 쓰기·서비스 재시작은 하지 않았다. 아래는 점검 시점 상태다.

### 실제 자료

Catalog `http://127.0.0.1:8080/api/products?category=lip`은 HTTP 200, 상품 908개를 반환했다. 그중 아래 3개 상품·5개 호수에 향료 includes 조회를 수행했다.

| productId | shadeId |
| --- | --- |
| oy-a000000162092 | a000000162092-001 |
| oy-a000000246445 | a000000246445-044, a000000246445-040 |
| oy-a000001002067 | 01, 02 |

5건 모두 `synthetic=false`, `UNKNOWN`, `mapping_not_verified`, `mappingStatus=candidate`, `reviewStatus=unreviewed`, `normalizationStatus=unverified`, `ingredientCoverage=unknown`, `optionId/evidenceId/sourceVersion=null`이었다. 미확인 안내·호수 변경 후 재조회 사례로는 활용할 수 있지만 포함·부재 성공 근거는 아니다. 전체 Catalog에 검수 자료가 없다는 결론으로 확대하지 않는다. 다시 사용할 때 현재 응답을 재확인한다.

미추적 `reports/ingredients/p0-2b-1-mapping.json`은 `ingredientReviewApproved=0`, `exactSnapshotAvailable=false`, `snapshotProvided=false`이며 과거 입력 해시·실행 기록 가용성도 false다. 파일을 변경하거나 PR에 포함하지 않았고 검수 완료 자료로 승격하지 않았다. 기존 ingredient 테스트 fixture 역시 합성 자료로 표시돼 있어 실제 자료 검증의 대체물이 아니다.

| 검증 항목 | 상태 | 해제 조건 |
| --- | --- | --- |
| 실제 검수된 포함 판정 | **BLOCKED_DATA** | 검증된 상품/호수/옵션 귀속, 검수·정규화, evidenceId/sourceVersion을 갖춘 사례 지정 |
| 실제 검수된 부재 판정 | **BLOCKED_DATA** | 위 조건과 함께 부재를 판단할 충분한 전성분 coverage 및 정규화 근거 확보 |
| 옵션 변경에 따른 실제 성분 차이 판정 | **BLOCKED_DATA** | 변경 전후 호수 각각의 승인 근거 확보. 단순 UNKNOWN 재조회와 구별 |
| 승인 원문의 외부 모델 제공 | **BLOCKED_RIGHTS** | 자료별 사용 목적·외부 제공 권리 확인. 검수 완료와 권리 승인은 별개 |
| 실제 UNKNOWN 처리·대상 재조회 | 자료 후보 확보 / 검증 NOT_RUN | 위 표본의 최신성 확인 후 G3 코드로 실행 |

BLOCKED_DATA/RIGHTS를 합성 PASS로 대체하지 않는다. 자료 부족 자체가 pending·문맥 코드의 구현 불가를 의미하지는 않지만 실제 성분 성공 검증 완료 선언은 막는다. G3 최종 상태에는 기능 테스트 결과와 이 차단 항목을 분리해 남긴다.

### 환경

| 환경 | 관측 | 판단 |
| --- | --- | --- |
| 개발 의존성 | D:의 node_modules, API·챗봇 가상환경 존재 | 설치 존재 확인. 실행 검증 아님 |
| Redis | vishue-redis-1, 127.0.0.1:16379, PING=PONG | 연결 가능. 공유 인스턴스에 G3 테스트 쓰기 금지 |
| Catalog | 로컬 8080 HTTP 조회 정상 | 읽기 전용 참조 가능, G3 검수 자료는 별도 |
| LLM | 외부 설정에 키·모델 존재 | 인증·quota·실제 호출 가능성 미확인. 키를 문서/로그에 기록하지 않음 |
| Metro | 8081에서 packager-status:running | 프로젝트 경로·G3 앱 연결·실기기 준비 미확인 |
| 현재 챗봇 | vishue-chatbot:dev 이미지, VISHUE-chat-ui-test 경로 읽기 전용 마운트 | **G3 소스 아님. 현재 서버 결과를 G3 검증으로 사용 금지** |
| 인증·Expo Go | 실제 계정/게스트·기기 흐름 미점검 | G3 연동 검증 NOT_RUN |

현재 챗봇 마운트 원본은 `D:/dev/02_TeamProjects/VISHUE-chat-ui-test/backend/chatbot/app`이다. 실행 중이라는 사실만으로 `feat/vishue-ingredient-context` 코드가 서빙된다고 판단하지 않는다.

## 14. G3 전용 격리 환경 준비안 — 미실행

기존 서비스·공유 데이터·현재 Metro를 변경하지 않는다. 아래 포트는 예약·확정값이 아닌 후보이며 준비 시 점유를 확인해 빈 포트를 선택한다. 프로세스 기동·새 설정 파일 생성은 이번 문서 작업에 포함하지 않는다.

| 구성 | 준비안 | 확인할 증거 |
| --- | --- | --- |
| G3 챗봇 | D: G3 브랜치의 backend/chatbot과 기존 uv 환경으로 별도 프로세스. 예: 127.0.0.1:18003 | 실행 cwd·소스 HEAD·PID·포트·기동 설정 출처 |
| G3 Redis | 기존 서비스와 다른 전용 임시 인스턴스, 예: 127.0.0.1:16380. 고유 이름·격리 데이터 | 기존 Redis와 주소/프로세스 분리, CAS·TTL 테스트 대상 확인 |
| G3 Catalog | 우선 기존 8080 Catalog GET만 사용. 오류·버전 변경은 합성 HTTP fixture로 분리 | 실제 응답의 출처·버전·귀속, 합성 여부 |
| G3 앱/Metro | D: 프로젝트에서 별도 빈 포트, 예: 18081. 챗봇 URL만 G3 전용 주소로 프로세스별 주입 | 앱 요청이 G3 챗봇에 도달하는 trace, 기존 8081 유지 |
| G3 프록시 | 본문 64KiB·413 검증이 필요하면 별도 프록시 후보 포트/구성. 기존 nginx.conf·Gateway 수정 금지 | 대상이 G3 서버인지, 64KiB 경계 응답, 직접 접속 차이 |
| 실기기 | Expo Go에서 접근 가능한 개발 PC 주소·전용 포트 사용. 필요 시 G3 프로세스만 LAN 바인딩 | 디바이스→G3 서버 요청 연결, 사용자/게스트 인증과 소유권 |

실기기에서 127.0.0.1은 PC를 뜻하지 않는다. LAN 접근·방화벽 설정 변경이 필요하면 별도 범위로 보고한다. 기존 서비스 URL·앱 설정 파일을 덮어써서 연결하지 않는다. 권리 미확인 원문은 외부 모델에 전송하지 않으며, 실제 모델 smoke에는 허용 입력과 자료만 사용한다.

환경 변수는 G3 프로세스에만 주입한다. 코드의 G1 기본 OFF는 유지하고 해당 검증 프로세스에서만 ON으로 실행한다. OFF·비한국어 호환 검증은 별도 설정으로 수행한다. 비밀 설정을 복사·커밋하지 않는다. Redis 실행기는 기존 `tests/run_redis_sessions.py`의 격리 패턴을 우선 검토하되 G3 사례가 이미 포함돼 있다고 보지 않는다.

준비 순서: 포트·기존 컨테이너 목록 기록 → 전용 Redis → G3 챗봇 → 합성/실제 자료 구분 확인 → 별도 앱 연결 → 실제 인증·Expo Go 최소 흐름. 테스트 상태는 결정적 단위/계약, 실제 Redis HTTP, 실제 모델+Catalog, 앱 payload, Expo Go를 분리한다. G1 전체 평가나 G4~G8 구현은 포함하지 않는다.

종료 시 이번에 만든 프로세스·컨테이너만 식별해 정리한다. 공유 Redis FLUSH, 기존 컨테이너 재시작/교체, 공용 DB 데이터 수정은 하지 않는다. 준비 후 실행 HEAD·주소·환경 구분·실행 결과를 기록하고 자료 차단 항목은 유지한다.

## 15. 남은 세부사항과 착수 경계

확정: 기본 선택 4건, G3 최소 구현 방향, pending 전이·오류·TTL·버전 규칙, 초기 입력 제한. 이를 다시 미정으로 되돌리지 않는다.

남은 항목: 공개 필드/질문 ID·schemaVersion, Unicode 길이 계산·직렬화·구형 snapshot/fingerprint 호환, 64KiB 적용 경로·413 표시, 실제 자료/권리 차단 해제, 격리 환경 포트·실행 연결·필수 검증 환경 증빙. 코드 수정이나 새 환경 기동은 현재 요청에서 수행하지 않는다.

G1·G2 개발 종료와 Draft/Stacked PR, 기본 OFF, 기존 평가 원본·결과는 유지한다. G2를 재개하거나 G3 완료를 선언하지 않는다. G6 스타일·G7 영속화/요약/기억, G4 교집합 검색·G8 복합 실행의 경계는 기존 절을 따른다.



## 16. G3 최소 구현 및 격리 검증 기록 (2026-11-16)

본 절은 사용자 구현 승인 후의 기록이다. 13~15절의 미실행/착수 전 표현은 당시 점검 기록이며 현재 구현 상태는 본 절을 따른다. C01~C08의 단계 경계는 유지한다. G2 종료 상태를 재개하거나 G6~G8 구현을 포함하지 않는다.

### 구현 계약과 파일 매핑

- `backend/chatbot/app/schemas/chat.py`: 선택적 recentMessages / clarificationId / pendingClarification. 기존 ChatSessionState.schemaVersion과 BeautyContext.version을 유지하는 선택적 확장이다. absent/empty 신규 필드는 직렬화에서 생략해 기존 요청 fingerprint를 유지한다. 한국어 G1 ON의 chat/beauty_consultation만 신규 입력을 해석한다.
- `backend/chatbot/app/services/chat_service.py`: 기존 Redis 소유권·만료 → 동일 requestId/fingerprint replay → 세션·결과 버전 → 질문 ID → 해석/검증 → CAS 순서를 재사용한다. pending 생성·교체·해소·취소만 버전을 올리고, pending만 바뀔 때 TTL/resultSetId는 보존한다. 모호한 답은 200 clarification으로 유지한다. 실제 상품/호수는 기존 Catalog 경로에서 재검증한다. 이전 선택 상품과 질문 대상이 다르면 유효한 질문 대상이 원래 조건을 복원하되 새로운 사용자 선택은 이를 무효화한다.
- `backend/chatbot/app/services/beauty_consultation_service.py`: 최근 문답과 질문의 최소 성분 조건을 비신뢰 해석 힌트로 전달한다. 세션 capability 토큰은 프롬프트에 넣지 않는다. 이력을 사실·권한·상품/호수 귀속의 근거로 사용하지 않는다.
- `types/index.ts`, `types/chatConversation.ts`, `store/chatConversationStore.ts`, `app/chat.tsx`, `hooks/useChat.ts`: 현재 방·소유자·generation의 완료된 문답 쌍만 선택하고 실패/자동 안내를 제외한다. 최초 snapshot의 이력과 질문 ID를 재시도에 재사용한다. 늦은 응답 및 선택 revision 방어를 재사용한다. 질문 ID 409는 상품 세션을 초기화하지 않고 해당 pending과 실패 snapshot만 해제하며 자동 재시도하지 않는다.
- `backend/chatbot/tests/test_g3_ingredient_context.py`, `__tests__/chatConversationStore.test.ts`, `__tests__/chatScreen.test.ts`: G3 계약과 입력/재시도/앱 연결 테스트. Catalog·LLM 대역과 실제 Redis/프록시 opt-in 테스트를 구분한다.

pending 공개 필드: `id`, `missingSlot`, `productId`, `resultSetId`, `createdRequestId`, `createdStateVersion`, `expiresAt`, `ingredientConditions`. 질문 자체의 독립 TTL이나 영속 conversation ID는 만들지 않는다. 한 상품 세션에 활성 질문 하나만 유지한다. 세션 이전에는 저장·복원이 없으며, 이미 특정 상품을 가진 기존 상세 요청 경로는 유지한다. 이력이나 pending을 별도 DB·장기 기억으로 복제하지 않는다.

### 입력 경계

현재 발화 1,000 / 이력 최대 8개 / user 1,000 / assistant 2,000 / 합계 8,000은 Unicode code point 수다. Python len과 앱 Array.from으로 맞춘다. 결합 문자·ZWJ 이모지의 보이는 글자 수와 같다고 가정하지 않는다. 입력창은 최대 1,000 code point로 제한하고, HTTP의 초과·중복 ID·잘못된 역할·질문 ID는 기존 400 invalid_request로 거부한다. 최근 이력은 문답 쌍을 잘라 보내지 않고 상한 내 완료 쌍만 선택한다.

64KiB는 G3 임시 nginx에서만 검증했다. 65,536 bytes의 잘못된 메시지 본문은 앱 검증의 400까지 도달하고, 65,537 bytes는 nginx 413이다. FastAPI 직접 접속이나 운영 Gateway에 같은 제한이 있다는 주장은 하지 않는다. 413은 기존 앱 요청 실패 UI를 사용한다.

### 격리 환경 및 실행 결과

- 소스: D:/dev/02_TeamProjects/SKN34-Final-Project, feat/vishue-ingredient-context, 부모 f2373a5994ce6d48ed15bb4ab838c0fffb77efee.
- 전용 Redis: `vishue-g3-redis-f2373a5`, 127.0.0.1:16380, 영속 볼륨 없음. 공유 16379에는 테스트 쓰기/FLUSH를 하지 않았다.
- 별도 챗봇: 18003. G1 ON과 Catalog 8080 GET, 전용 Redis를 프로세스 환경에만 설정. 기존 VISHUE-chat-ui-test 서버는 사용하지 않았다.
- 별도 nginx: `vishue-g3-proxy-f2373a5`, 18080, 64k 본문 제한. 임시 설정/로그는 저장소 밖 TEMP/vishue-g3-f2373a5에 둔다.
- 별도 Metro: D: 소스로 18081에서 packager-status:running 확인. 채팅 주소를 전용 18080으로 주입. 기존 8081/서비스는 종료하거나 변경하지 않았다. 이 사실만으로 실기기 앱 E2E를 PASS 처리하지 않는다.
- 관련 핵심 백엔드 200 passed / 1 skipped. G3·G2·세션·성분 경로, 실제 Redis CAS/동시 재전송/TTL, 실제 413 경계를 포함한다. skip은 G2의 별도 live opt-in이다.
- beauty/style/AR 관련 확장 확인: 346 passed / 1 skipped / 1 failed. 실패는 기존 test_style_recipe.py의 test_real_catalog_and_chat_http_with_bundled_unreviewed_content가 임시 서버 기동 12초 제한을 넘은 것이다. 해당 테스트만 재실행해도 동일했다. 원인은 확정하지 않았으며 통합 검증 실패를 감추거나 기존 테스트를 수정하지 않는다.
- Ruff 및 import-linter 계약 3개 통과. 앱 typecheck/변경 파일 ESLint 통과, 두 관련 Jest suite 82건 통과(입력창 이모지·결합 문자 경계 포함). 전체 G1 평가/전체 프로젝트 테스트는 실행하지 않았다.
- 실제 guest HTTP + LLM + Catalog: 추천→호수 확인 pending→일반 설명 후 같은 세션 버전 유지 확인. 호수가 없는 추천 상품은 실제 해소 사례로 쓰지 않았다. 별도 상품 oy-a000000246445를 지정한 상세→향료 질문→Catalog 호수 이름 답변에서 같은 상품으로 조회·pending 해소 및 MATCH/ingredient_present 응답을 관측했다. 이는 연결 smoke이며 아래 자료 승인 판정을 대체하지 않는다.
- 첫 smoke는 locale 대신 language를 보낸 실행 실수로 비한국어 기본 경로가 Neo4j 연결 오류 500을 반환했다. locale=ko로 바로잡은 G3 경로는 200이었다. 이 실패를 G3 PASS로 포함하지 않는다.

### 자료/환경 차단과 후속 인계

검증 도중 기존 Catalog 데이터가 변경되었다. oy-a000000246445 / a000000246445-044의 현재 응답은 directly_reviewed/verified, partial coverage, normalizationStatus=unverified, synthetic=false이며 evidenceId/sourceVersion 및 reports/ingredients/pr233-review-record.md 참조가 생겼다. 이전 13절의 UNKNOWN 표본을 현재 전체 데이터 상태로 단정하지 않는다. 이번 G3 범위에서는 검수 원본·귀속·권리 승인 기록을 감사하지 않았으므로 실제 포함 판정 승인도 **BLOCKED_DATA**, 부재/옵션 차이는 **BLOCKED_DATA**, 원문 외부 제공 권리는 **BLOCKED_RIGHTS**로 유지한다. 반환된 MATCH를 검수 완료 PASS로 승격하지 않는다. 성분 원문을 새로 외부 LLM에 제공하지 않았다.

실기기 Expo Go와 실제 회원 인증의 앱→서버 E2E는 **BLOCKED_ENV**(연결된 검증 기기/계정 미확인). 앱 요청 snapshot·질문 ID·최근 문답은 Jest 대역으로 확인했으며 Metro 기동과 구분한다. 스타일 실HTTP 통합 실패는 별도 미해결 검증 항목이다.

G6: StyleContext/recipeVersion/단계 진행 책임과 독립 버전 유지. G7: 승인된 pending/상품 세션 계약을 영속화 설계에 매핑하고 동의 기억·요약·검색·checkpoint를 별도로 구현한다. G4 복합 옵션 검색과 G8 복합 실행은 이 PR 범위 밖이다. G3 핵심 구현은 Draft 검토 대상으로 제출하며 실제 자료·실기기·미해결 통합 검증까지 완료됐다고 선언하지 않는다.

작업 중 별도 변경으로 등장한 infra/compose/nginx.conf와 scripts/data/oliveyoung/build_reviewed_ingredient_mapping.py는 G3 변경/스테이징 대상에서 제외한다. 기존 G1 검토 문서와 성분 매핑 JSON의 SHA256은 작업 전후 동일함을 확인했다. G1/G2 기본 OFF·Draft·부모 base·평가 원본은 유지한다.


## 17. PR #249 핵심 결함 수정 계약 및 재검증 (2026-11-16)

기준은 G3 1d02c7182a7b5d71ae703c89296f157e73ad021b / G2 f2373a5994ce6d48ed15bb4ab838c0fffb77efee다. 16절의 초기 구현 기록은 보존하며, 최종 리뷰에서 발견된 P1 1건·P2 3건의 보완은 본 절을 따른다.

### pending과 선택의 우선순위

1. 소유권·만료 → 재전송 캐시 → 세션 버전 → clarificationId 검증 순서는 유지한다.
2. 유효한 질문 ID와 이전과 동일한 상품 선택을 보낸 짧은 답변은 pending 상품을 사용한다. A 화면에서 B 성분 질문을 시작한 뒤 남은 A screenContext는 새로운 선택이 아니며 B를 덮지 않는다.
3. 앱의 명시적 카드/호수 선택은 질문 ID를 해제하고 현재 선택을 보낸다. 질문 ID가 없고 pending과 다른 상품 또는 변경된 호수 힌트가 오면 이전 질문을 무효화한다. 선택 힌트는 반드시 Catalog 검증을 통과해야 하며 서버 후보 순서·권한을 대체하지 않는다.
4. 현재 발화의 명시적 다른 순번/상품명은 기존 SearchPlan과 Catalog 후보 조회로 해결한다. 유일하게 확인된 새 대상이 있으면 이전 pending 조건을 이어 붙이지 않는다. 모호하거나 존재하지 않는 대상을 추측하지 않는다.
5. 일반 설명 중 명시적 새 선택이 있으면 그 선택을 검증하고 질문 무효화를 커밋한다. 선택 변경이 없는 설명은 기존 pending·버전·TTL을 유지한다.
6. 앱은 최신 selection revision 방어를 유지하고, 해제한 질문 ID 하나를 메모리에 기록해 늦은 응답 또는 일반 설명 응답으로 같은 질문이 되살아나는 것을 막는다. 방/세션 초기화 때 이 기록을 비우며 새로운 영속 저장소·이벤트 로그를 만들지 않는다.

### 목표 변경·취소·신규 검색

- “성분 말고 색상만 보여줘”, “성분 말고 이제 가격만 알려줘”는 기존 pending을 종료하고 동일 상품의 새 detail/price 요청을 처리한다. 성분이라는 단어가 남아 있어도 이를 새 성분 조회로 강제하지 않는다. 일반 화장법 설명은 성분 목표를 포기한 것으로 보지 않는다.
- “질문 취소해줘”와 “취소하지 말고 03호로 확인해줘”를 구분한다. 단어 언급만으로 취소하지 않고 명시적인 명령·부정·마지막 정정을 구분한다. 임의의 자연어 표현 전체를 해결한 범용 의도 엔진이라고 주장하지 않는다.
- pending 종료만 발생하면 resultSetId·TTL을 유지하고 상태 변경을 기존 CAS로 한 번 커밋한다. 오류를 성공 해소로 저장하지 않으며 동일 requestId 재전송은 원래 성공 응답을 재사용한다.
- 세션 없이 최근 문답이 있으면 기존 상담 해석으로 현재 과업을 분류하되, 새로운 독립 상품 검색이면 G1 Tool 선택과 Catalog 실행을 다시 거친다. 최근 문답이 없는 동일 검색과 반환 카드·서버 후보·세션 생성의 일관성을 검사한다. 이력 유무가 G1 Tool Calling 생략 사유가 되지 않는다.
- 기존 세션 참조/조건 변경/확인 질문은 기존 G2/G3 경로를 유지한다. G2의 명시적 제형 필터 전용 경로를 일반 G1 검색으로 되돌리지 않는다. 이력은 비신뢰 해석 힌트이며 Tool 인자·Catalog 사실·권한 검증을 대체하지 않는다.

### 수정 전후 검증

변경 파일은 chat_service.py, beauty_consultation_service.py, chatConversationStore.ts, G3 backend 테스트, store 테스트 및 이 문서의 6개다. API·스타일 서비스·Compose·DB·기본 OFF·기존 평가를 수정하지 않는다.

- 수정 전 신규 백엔드 재현 13건 중 9건 실패 / 4건 통과. 앱 재등장 경계 2건 실패. 취소 단순 언급에 대한 추가 재현도 수정 전 실패를 확인했다.
- 수정 후 G3/G2·기존 세션·G1 모델/Tool·성분 관련 테스트: 265 passed / 3 skipped. skipped는 전용 Redis·프록시 및 G2 live opt-in이며 이번 통합 PASS에 포함하지 않는다.
- 앱 store/screen 관련 두 suite: 84 passed. 기존 질문 ID 충돌 시 세션 보존, snapshot 재시도와 늦은 선택 응답 방어를 포함한다.
- 신규 검색의 Tool/해석 호출, 실제 서비스 실행기 및 Catalog 대역의 호출·반환 카드·세션 결과를 비교했다. 이것은 실제 LLM 성능 평가가 아니다.
- 기본 경로 외에도 실제 새 카드 선택, 명시적 새 순번/상품명, 새 선택 후 일반 설명, 취소 부정 및 정정을 확인했다.
- 전체 G1 113건·전체 프로젝트 평가·무관한 AR/스타일 재평가는 실행하지 않는다.

### 실제 연결 관측과 BLOCKED

현재 vishue-api-1이 연결한 호스트는 vishue-pr233-postgres이며, 읽기 전용 SELECT로 alembic revision 0022를 확인했다. 기존 8080 Catalog GET에서 아래 응답을 재확인했다. DB 수정·서비스 재시작·설정 변경은 하지 않았다.

| product / shade | 향료 includes 관측 | 자료 상태 |
| --- | --- | --- |
| oy-a000000246445 / a000000246445-044 | MATCH / ingredient_present | verified, partial, normalizationStatus=unverified, synthetic=false, optionId/evidenceId/sourceVersion 존재 |
| oy-a000000162092 / a000000162092-001 | UNKNOWN / absence_not_verifiable | verified, partial, normalizationStatus=unverified, synthetic=false, optionId/evidenceId/sourceVersion 존재 |

이는 0022 연결 상태와 반환 계약의 재확인이다. 원본별 상품/호수/옵션 귀속·완전성·정규화 및 검수 기록의 독립 감사까지 완료한 것은 아니므로 실제 검수 승인 BLOCKED_DATA, 외부 원문 사용 권리 BLOCKED_RIGHTS를 유지한다. 특히 partial 자료의 미관측을 성분 부재로 승격하지 않는다.

이전 전용 G3 Redis/서버/프록시는 중지 상태이며 공유 Redis를 검증 대상으로 대체하지 않았다. 이번 수정의 실제 Redis CAS·LLM·Catalog를 잇는 G3 통합 흐름은 미실행이다. 실제 회원 인증·Expo Go는 BLOCKED_ENV다. 이전 16절 smoke를 이번 수정 HEAD의 실제 통합 PASS로 재사용하지 않는다.

### 스타일 실패 및 종료 판단

최종 읽기 전용 리뷰에서 동일 Python/의존성·정적 자료·12초 제한으로 G2/G3를 비교했다. 양쪽 프로세스는 정상 기동했지만 style-looks API가 VerifiedVideoProductRepository를 통해 DB를 조회하면서 테스트의 127.0.0.1:1 주소에 연결하지 못해 500을 반환했다. 정적 자료만 조회한다는 테스트 전제와 실제 의존성의 충돌이며 G3 신규 회귀가 아니다. 별도 담당 후속 작업으로 격리 DB 또는 명시적 정적 테스트 의존성을 정리해야 한다. 테스트 제한시간을 늘려 성공으로 맞추거나 이번 G3에 API/스타일/Compose 변경을 포함하지 않는다.

핵심 결함 재현과 관련 자동 회귀는 해소했다. 종료 판정은 **조건부 종료 가능**이다. G3 핵심 코드 수정은 종료할 수 있으나 실제 수정 HEAD의 통합·실기기 검증과 자료/권리 감사는 남는다. G6 스타일 상태와 G7 영속화/요약/동의 기억, G4 옵션 복합 검색 및 G8 전체 실행은 기존 후속 범위를 유지한다. Draft·G2 base를 보존하고 자동 병합·배포하지 않는다.


## G4 최소 구현 보충 (2026-11-17, 로컬 작업본)

G3 계약을 교체하지 않고 옵션 검색 결과를 확장했다. 본문의 과거 실제 통합 미실행 기록은 당시 상태이며 PR #249의 이후 G3 실제 LLM·Catalog·Redis 검증과 구분한다. 이번 G4에는 실제 통합 검증을 전용하지 않는다.

- G1 ON·한국어의 `optionSearch` 검색/조건 변경만 새 Catalog HTTP 경로를 사용한다. 일반 G2 상품 수준 검색·G3 단일 상품 성분 질문/pending·G1 OFF·비한국어·AR·스타일 경로는 기존 경계를 유지한다.
- `BeautyFilters`에 선택적 `optionSearch`, `priceBasis`, `unsupportedConditions`; `BeautyContext`에 선택적 `optionScope[{productId,shadeId,optionId}]`; `ChatResponse`에 선택적 `optionSearch` 결과를 추가했다. 기존 메시지는 이 필드 없이 유효하다.
- 후보 순번은 기존 product ID 순서이며 옵션 순번으로 바꾸지 않는다. 같은 상품의 옵션들은 별도로 보존한다. 이전 후보 안에서 좁힐 때 서버가 저장한 옵션 범위를 재검증하며 클라이언트가 변조한 optionScope는 채택하지 않는다. 명시적으로 새 화면 상품을 선택하면 이전 옵션 범위를 제거한다.
- 세션 owner/token/expected version/request ID/질문 ID/TTL/CAS 저장소는 변경하지 않았다. 검색·조건 변경은 기존 결과 집합 갱신 규칙, 상세·pending은 기존 TTL 규칙을 따른다. 최초 요청을 세션 없이 재전송하면 기존 409 규칙을 유지한다. 세션 있는 동일 요청 재전송은 저장 응답을 반환한다.
- 부분 결과라도 검증된 귀속의 참고 옵션이 있으면 조건 상태와 함께 저장할 수 있다. 전체 오류 또는 불완전한 빈 검색으로 이전의 유효한 결과 집합을 덮지 않는다. G4 검색으로 상담을 바꾸면 기존 pending 해소 규칙을 재사용한다.
- 앱은 해당 메시지에 옵션 판정을 보존한다. 기존 owner/generation/revision 방어를 통과한 응답만 반영하며, 새 원문 저장·요약·장기 기억을 추가하지 않는다.

### 최소 구현 당시 실행 검증 (종료 감사 보완 전)

- API: `test_option_search`, `test_ingredient_api`, `test_ingredient_service`, `test_ingredient_mapping`, `test_ingredient_identity`, `test_ingredient_canonical_identity`, `test_catalog_api`, `test_catalog_optional_texture` — 157 passed.
- 챗봇: `test_g4_option_search`, `test_g3_ingredient_context`, `test_g1_model_service`, `test_g2_multiturn`, `test_chat_sessions`, `test_g1_catalog_tool`, `test_g1_supervisor`, `test_partial_ingredient_sessions` — 230 passed / 3 skipped (opt-in 실제 연동).
- 앱: `chatProducts`, `chatScreen`, `chatConversationStore` — 111 passed.
- typecheck·Expo lint·변경 Python 파일 Ruff·양쪽 백엔드 import-linter(각 3 kept / 0 broken)·git diff --check 통과.
- G4 후속 가격/상세는 옵션 범위·기존 상세 TTL을 보존하고 참고가로 현재가 조건을 재판정하지 않는다. 최저가 옵션 정렬은 미지원 재질문으로 처리한다.
- Windows sandbox의 asyncio 내부 socketpair 정지로 대역 테스트를 sandbox 밖에서 실행했다. API 기존 pytest 공용 임시 폴더 ACL 오류는 새 OS 임시 경로로 해결했다. 실서비스는 기동하지 않았다.
- 실제 G4 LLM·Catalog·Redis·실회원·Expo Go는 미실행. 전체 G1 113건 평가와 전체 프로젝트 테스트는 재개하지 않았다. 기존 스타일 HTTP/실DB 전제 충돌은 별도 후속 과제로 유지한다.


### 종료 감사 보완 및 검증 (2026-11-17)

- 이름 있는 성분 하나 삭제는 기존 `clearFilters=[ingredientConditions]` 후 유지할 조건을 재설정하는 계약을 사용한다. 추가는 병합, 같은 이름의 includes/excludes 변경은 교체한다. 프롬프트의 향료 조건 삭제와 포괄적 fragranceFree 삭제를 구분했다. 가격 기준만 변경해도 유효한 refine으로 인정한다.
- 기존 세션·CAS·TTL 저장소는 수정하지 않는다. 응답의 effectiveRequest/checkedAt과 조건별 근거는 기존 lastResponse 및 앱 메시지 경로에 보존한다. 불완전한 빈 결과에서도 검사한 요청은 결과에 남고 기존 유효 문맥은 보존한다. 옛 저장 응답에는 새 필드가 없을 수 있다.
- 대역 테스트로 복합 조건 설정 → 특정 성분 삭제 → 성분 추가 → 연산자 교체 → 가격 상한/기준 변경과 저장된 유효 요청을 확인했다. 자연어 해석 자체의 실제 LLM 성공으로 계산하지 않는다.
- 실제 LLM·Catalog HTTP·PostgreSQL 동시 변경·전용 Redis·실회원·Expo Go는 이번에 실행하지 않는다. G4-N01/B01/B02/E01 정식 평가 완료로 간주하지 않으며 특히 B01 사람 의미 검수가 남는다. 자료 완전성·권리·환경 BLOCKED는 유지한다.


이번 보완의 실행 결과 (이전 최소 구현 결과와 별도):

- API 관련 회귀: `test_option_search`, `test_ingredient_service`, `test_ingredient_mapping`, `test_ingredient_api`, `test_ingredient_identity`, `test_ingredient_canonical_identity`, `test_oy_catalog` — **147 passed**. 마지막 근거 필드/스냅샷 오류 처리 변경 뒤 `test_option_search` **23 passed** 재확인. 두 숫자는 중복이 있으므로 합산하지 않는다.
- 챗봇 관련 회귀: `test_g4_option_search`, `test_g1_model_service`, `test_g1_catalog_tool`, `test_g2_multiturn`, `test_g3_ingredient_context`, `test_chat_sessions`, `test_ingredient_consultation` (`-k 'not live'`) — **289 passed / 2 skipped / 1 deselected**. 마지막 근거 검증 보강 뒤 G4/G1 model 집중 테스트 **56 passed** 재확인. 합산하지 않는다.
- 앱 `chatProducts`, `chatScreen`, `chatConversationStore` — **111 passed**. 옵션 제형 미확인 표시 assertion을 추가하고 기존 순번·선택·늦은 응답 회귀를 실행했다.
- 최종 typecheck, Expo lint, 변경 영역 Ruff, 양쪽 import-linter 각 3 kept/0 broken, diff whitespace 검사 통과. API TestClient의 기존 httpx 사용 중단 예정 경고 1건은 남는다.
- Windows sandbox에서 asyncio 내부 socketpair 생성이 멈춰 해당 테스트 프로세스만 중단하고 대역 테스트를 sandbox 밖에서 실행했다. 공용 pytest 임시 폴더 ACL 오류는 고유 OS 임시 경로로 회피했다. 실제 서비스 기동·실데이터 조회는 하지 않았다.
- 이번 보완은 제시한 후보 중 **23개 기존 작업 파일**을 수정했다. `chatScreen.test.ts`는 기존 회귀로 충분해 수정하지 않았다. 새 프로젝트 파일·의존성·DB 구조는 추가하지 않았다. Compose·G1 검토 문서·성분 보고서·매핑 스크립트는 시작 시점과 파일 해시가 같음을 확인했다.
- 종료 판정: 이번 코드 보완과 집중 자동 검증은 완료. 실제 PostgreSQL 동시 갱신, LLM의 날짜·선택 삭제 해석, Catalog/Redis/회원/Expo Go, G4 정식 평가와 사람 검수는 미완료다. 옵션별 제형 근거 및 권리 증빙이 없어 **G4 전체 종료는 보류**한다.


### 기존 데이터 활용 보완 검증 (2026-11-17)

사용자가 승인한 21개 파일 범위에서 수정했다. 일반 옵션 가격 요청의 기본 기준을 collected_snapshot으로 정하고 유효 기준을 기존 세션 필터에 보존한다. 명시적 current_offer/catalog_reference는 유지한다. 시간대 없는 기록, 옵션 가격이 없어 상품 참고가만 표시한 경우, 상품 제형 분류의 근거, 성분 신원 연결 개수를 앱에 구분해 표시한다. 부분 목록의 포함 확인은 활용하고 부재 확정 조건은 유지한다. 이전 권리 미확인 일괄 차단은 사용자 지시에 따라 제거하고 limitations로 보존했다. 상세 계약은 08의 기존 데이터 활용 보완 절을 따른다.

- API: `test_option_search`, `test_ingredient_service`, `test_ingredient_mapping`, `test_ingredient_api`, `test_ingredient_identity`, `test_ingredient_canonical_identity`, `test_oy_catalog` — **153 passed**. 시간대 없는 수집가 비교/현재가 구분, 옵션 가격 누락 시 참고가 fallback, 제형 출처별 참고 후보, 상품번호 대소문자 귀속, 성분 연결 집계 포함.
- 챗봇: `test_g4_option_search`, `test_g1_model_service`, `test_g1_catalog_tool`, `test_g2_multiturn`, `test_g3_ingredient_context`, `test_chat_sessions`, `test_ingredient_consultation` (`-k 'not live'`) — **296 passed / 2 skipped / 1 deselected**. 새 수집가 계약과 기본/명시적 가격 기준 보존, 기존 G1/G2/G3 대역 회귀 포함.
- 앱: `chatProducts`, `chatScreen`, `chatConversationStore` — **112 passed**. 성분 연결 집계·리뷰 제형 출처·시간대 미확인 시각 표시 및 기존 선택/늦은 응답 회귀 포함.
- typecheck·Expo lint·양쪽 Ruff·import-linter 각 3 kept/0 broken·git diff --check 통과. API의 기존 TestClient/httpx 사용 중단 예정 경고 1건은 유지한다.
- 모든 테스트는 대역/합성 자료 검증이다. Windows asyncio sandbox 제약이 이미 확인되어 Python 테스트는 sandbox 밖에서 실행했다. 실제 DB·LLM·Redis·실회원·Expo Go 연동, G4 정식 평가·사람 검수는 실행하지 않았다. 직전 읽기 전용 DB 조사 수치와 이번 테스트 결과를 혼합하지 않는다.
- 새 프로젝트 파일·의존성·DB 변경은 없다. 서비스 기동·커밋·푸시·PR 생성은 하지 않았다. 원 검수 JSON/매핑/보고서, Compose 및 승인 범위 밖 작업은 보존했다. 성분 부재·옵션 제형의 근거 한계와 실제 연동 검증은 여전히 남는다.


### G4 조건 해석·검색 범위 실연동 재검증 (2026-11-17)

사용자 승인 6개 파일 안에서 두 챗봇 서비스 파일·두 테스트·08/09 문서를 보완했다. 초기 8개 방향 원문을 재구성하지 않는다. G1 한국어 프롬프트 식별자는 g1-ko-v5이며 G4 실행 직전 보정은 한국어·G1 ON·옵션 search/refine에 한정한다. G2/G3 상태 소유권·TTL·CAS 계약은 그대로다.

자동 검증:
- 챗봇 G4/G1 model/G1 catalog/G2 multiturn/G3 context/chat sessions/ingredient consultation 집중 회귀: **306 passed / 2 skipped / 2 deselected** (`-k 'not live'`). 이전 회차 숫자와 합산하지 않는다.
- 새 회귀는 잘못된 모델 인자의 향료/무향료·가격 경계, 충돌 재확인, 명시적 교체, 부분 결과 뒤 Catalog 재검색, 명시적 이전 옵션 범위, 저장 effectiveRequest를 검사한다. 대역 테스트를 실제 모델 성능으로 계산하지 않는다.
- 변경 Python Ruff 통과, import-linter 3 kept / 0 broken. 프로젝트 typecheck와 Expo lint(--no-cache) 통과. API 구현은 수정하지 않았다.
- 최종 부정 표현/조건 삭제 방어 회귀 3건을 포함한다. 포함하지 마/제외하지 말아줘/포함 조건 빼줘를 원문 보정기가 반대 조건으로 바꾸지 않는다.

실제 환경 및 관측:
- 기존 DB를 읽기 전용으로 사용하는 별도 G4 API(18082), 챗봇(18083), 전용 Redis(18379)를 사용했다. 수정 반영을 위해 별도 G4 챗봇만 재시작했다. 실제 모델은 gpt-6-luna이며 챗봇은 Catalog HTTP로만 조회했다. 기존 서비스·DB 원본·Compose·평가 원본은 변경하지 않았다.
- 원래 매트 복합 요청: 3만원 이하를 30000, 향료 제외를 개별 excludes, 판테놀을 includes로 보존했다. 검사한 7개 옵션 모두 향료 발견으로 EXCLUDED였다. TIMEOUT 부분 결과에서 상품 세션이 만들어지지 않아 다음 요청은 409 chat_session_required였다. 이 흐름을 다단계 성공 또는 매트 성공 사례로 계산하지 않는다.
- 토리든 립으로 동일 조건 흐름을 검증: 최초 30000 상한·향료 제외·판테놀 포함 → 판테놀만 삭제 → 나이아신아마이드 추가 → 향료 includes 교체 → 20000 상한 → current_offer 전환까지 HTTP 응답과 유효 요청에서 확인했다. fragranceFree는 false이며 다른 조건은 보존됐다. 1~6단계는 productIds/optionScope 제한 없이 Catalog를 재조회했다.
- 7단계 `그중 가격 기준만 수집가로`: 이전 상품 2개·옵션 6개만 검사하고 6/6 완료. 응답은 앞서 표시한 후보 범위이며 전체 Catalog 완료가 아니라고 명시했다. 참고 후보이며 조건 충족 확정 성공이 아니다.
- 5단계에서 TIMEOUT·조건 조회 오류 3건이 발생했다. PARTIAL과 일부 조회 실패 안내를 보존했다. 그 외 단계도 WORK_LIMIT 등이 있어 전체 검색 성공으로 표시하지 않는다. 정식 G4-E01 일부 페이지 실패 평가를 대체하지 않는다.
- 실제 모델의 `3만원 미만`은 상한 29999. 실제 퓌 옵션 수집가 12900은 상한12900에서 가격 MATCH, 상한12899에서 NOT_MATCH였다.
- 마지막 응답 재전송은 200/동일 응답, 타인 접근403, 오래된 버전409를 재확인했다. 실제 Redis TTL 관측값558초. 만료·CAS 동시 쓰기는 이전 실연동 검증 결과와 구분하며 이번 자동 회귀에 포함한다.

미완료: 실제 회원·Expo Go·앱 실기기, 정식 G4-N01/B01/B02/E01 전체와 사람 검수, 성분 부재/옵션 제형의 확정 근거. 이 보완과 재검증은 G4 전체 종료·출시 승인이 아니다. 커밋·푸시·PR 생성은 하지 않았다.

최종 코드 재확인: 부정 표현 방어를 반영하고 별도 G4 챗봇만 다시 시작한 뒤 토리든 7단계를 새 세션으로 재실행했다. 1~6단계의 조건·가격·범위가 위 기대값과 일치했고 모두 errors=0이었다(검색은 WORK_LIMIT 부분 결과). 7단계는 이전 상품 2개/옵션6개만 6/6 검사하고 범위 안내를 반환했다. 앞선 실행의 TIMEOUT/오류 관측 기록은 삭제하지 않는다. 최종 파일 해시 대조에서 승인한 6개 외 기존 미커밋·미추적 파일 변경/삭제는 없었다. 기존 API·챗봇·PostgreSQL 컨테이너 ID/시작 시각이 유지됐고 G4 API의 읽기 전용 연결 bootstrap도 유지됐다.

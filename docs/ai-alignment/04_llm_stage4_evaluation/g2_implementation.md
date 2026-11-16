# G2 멀티턴 핵심 구현

기준: 2026-11-16. 부모 PR #244 / `feat/vishue-supervisor` /
`f2e25eaaf48064ab940d632683f9be225c049608`. 시작 및 PR 준비 시 GitHub에서 같은 HEAD,
Draft, develop 미병합을 확인했다. G2 브랜치는 `feat/vishue-multiturn`이며 부모 브랜치를
base로 하는 Draft Stacked PR이다. 부모가 통합되기 전 develop 대상 PR로 바꾸지 않는다.

## 추가 검토 및 보완 (PR #248)

PR #241의 병합 커밋 `ecd0c9a56833aa36d3f0c9d104afe16030277744`에 포함된
`docs/ai-design/03-execution-contracts.md`, `07-ko-first-language-and-evaluation.md`를
기준으로 검토했다. 해당 문서는 현재 브랜치와 동일하다. 정식 G2-N02는 가격 변경 시
촉촉함 유지 사례이며, 최초 구현 검증만으로 매트 변경까지 지원했다고 해석하지 않는다.

| 항목 | 분류 | 이번 보완 / 후속 경계 |
| --- | --- | --- |
| 매트 조건을 표현하지 못하고 조건 변경 결과를 반환 | 실제 결함 | SearchPlan·BeautyFilters에 `texture: matte`를 추가하고 Catalog 상품의 texture가 정확히 일치할 때만 후보로 사용 |
| 미지원 또는 빈 refine, 지원·미지원 조건 혼합 | 실제 결함 | `unsupportedConditions`와 누락 방어 검사로 clarification 응답; 필터·결과·버전·TTL을 변경하지 않음 |
| generalMakeup이 요청에서 기존 세션을 생략 | 실제 결함 | 앱이 서버 세션과 generalMakeup 힌트를 함께 전송; 일반 설명은 검색 없이 이전 문맥 보존 |
| 상품 수준의 매트만 지원 | 의도된 최소 범위 | 다른 제형, 상대적인 “더 매트”, 지속력·워터프루프·옵션별 보장은 지원하지 않음 |
| 옵션별 제형·성분·가격의 교차 검증 | G4 의존성 | 상품 메타데이터 일치를 옵션 검증 완료로 승격하지 않음; 3개 후보 그룹 전체 구현도 이관 |
| ChatSessionState와 VishueState의 공존 | 설계상 허용, G7 계약 필요 | 아래 수명·권한·버전 구분을 유지하며 새 저장소나 State 재설계 없음 |

매트는 설명 문자열의 키워드로 판정하지 않는다. 메타데이터가 없거나 glossy인 상품은
제외한다. 기존 가격·카테고리·촉촉함 선호를 유지하며 `clearFilters: [texture]`로 삭제할
수 있다. 조건 변경은 Catalog 전체를 다시 검색하고 “그중”처럼 명시한 경우에만 이전 후보로
제한한다. 촉촉함은 기존의 선호 순위이며 검증된 성능 보장이 아니다.
응답에 상품 수준 메타데이터와 옵션별 제형·실제 발림 미확인을 구분한다.
앱에는 기존 4개 언어 번역을 재사용한 매트 조건 칩을 표시한다. 카드의 전체 조건 검증은
기존 보수적인 미확인 표시를 유지하며 옵션 검증 완료 UI를 추가하지 않는다.

모델에는 표현할 수 없는 조건을 `unsupportedConditions`로 반환하도록 요구한다.
주요 미지원 제형·성능 표현과 아무 변화가 없는 refine에는 결정적 방어 검사도 적용한다.
이는 임의 자연어의 모든 조건을 완벽하게 감지하는 온톨로지 구현은 아니다.
미지원이 포함된 요청은 지원하는 가격만 부분 적용하지 않고 전체 변경을 보류한다.

generalMakeup은 G1 ON 한국어에서만 일반 설명을 강제한다. 기존 서버 세션의 소유권·만료·
버전 검증은 그대로 수행한다. 화면/룩 정보로 상품 검색을 유도하지 않으며, 설명 뒤 상품
참조에는 같은 세션을 사용한다. OFF/비한국어에서는 기존처럼 해당 요청의 context를
무시하므로 기존 자유 상담·상품 상담 라우팅을 유지한다.

### 승인된 추가 영향 범위

- `backend/chatbot/app/schemas/{chat,supervisor}.py`: 매트 필터, 미지원 조건, 일반 설명 힌트.
- `backend/chatbot/app/services/{chat_service,beauty_consultation_service}.py`: 조건 적용·거부,
  Catalog 범위 및 일반 설명 처리.
- `app/chat.tsx`, `hooks/useChat.ts`, `types/chatConversation.ts`: 일반 설명의 세션 전달.
- `types/index.ts`, `lib/chatConditions.ts`: 클라이언트 필터 계약과 조건 칩.
- `backend/chatbot/tests/test_g2_multiturn.py`, `__tests__/chatScreen.test.ts`,
  `__tests__/chatConditions.test.ts`: 변경 관련 검증. 이 문서에 계약·검증 기록 추가.
- Catalog API·데이터, 저장소, G1 기본값, G1 평가, 다른 담당자의 기능은 변경하지 않는다.

### G7에 넘길 상태 계약

| 상태 | 현재 권한과 수명 | G7 연결 계약 |
| --- | --- | --- |
| ChatSessionState | 서버 소유 상품 결과 snapshot, 소유자·토큰 검증, 최대 600초 TTL, CAS | 짧은 상품 조회 capability로 유지; 장기 대화 원본으로 사용하지 않음 |
| VishueState + Runtime | 한 턴의 실행 상태와 해당 턴에 주입한 canonical context | 현재 그래프는 checkpointer 없이 compile; 향후 영속화 시 허용 필드만 투영 |
| thread_id | 현재 상품 세션을 연결하는 실행 상관 ID; 첫 생성 전에는 없을 수 있음 | 앱 대화방 ID나 영속 conversation ID로 간주하지 않음 |
| state_version / resultSetId | 상품 snapshot 커밋 버전 / 후보 집합 식별자 | 대화 checkpoint 버전·AR 버전과 독립적으로 관리 |
| requestId / last_response | TTL 내 마지막 상품 응답 재전송·동시 요청 제어 | 장기 idempotency나 전체 대화 이력 보장으로 확대하지 않음 |

G7은 소유자가 확인된 영속 conversation과 단기 상품 세션을 어댑터로 연결한다.
복원 시 세션 만료·권한과 Catalog 상품/옵션을 다시 확인하고, 만료된 capability를
checkpoint에서 되살리지 않는다. 선택·조건·근거의 필요한 필드만 저장하며 session token이나
capability가 포함된 last_response 전체를 영속 checkpoint에 복사하지 않는다.
동의·보관·삭제 정책 및 장기 저장소 선택은 G7 ADR에서 결정한다. G2의 기존 Redis 상태를
별도 원본으로 중복 저장하거나 VishueState에 영속 대화 필드를 선제 추가하지 않는다.

### 이번 변경 검증

- Ruff PASS, import-linter **3개 계약 PASS**.
- 관련 chatbot 6개 파일: **199 PASS / opt-in 실모델 1 SKIP**.
  G2, chat, beauty consultation, session, G1 model/supervisor의 변경 경로만 실행했다.
- 앱 typecheck 및 변경 TS/TSX 파일 ESLint PASS.
- chatScreen·chatConditions·chatConversationStore: **3개 스위트 / 103 PASS**.
  추천 → 일반 설명 → 이전 상품 참조의 앱 전달 인자를 검증했다.
- 2026-11-16 18:42 KST, G1 ON + 실제 `gpt-6-luna` + 로컬 Catalog HTTP:
  확장 smoke **1 PASS**, 추천 → 순번 → 가격 → 매트 → 혼합 미지원 → 일반 설명.
  매트 후보의 Catalog texture, 가격·촉촉함 유지, 미지원/설명 시 세션 보존,
  버전 **1 → 2 → 3 → 4**를 assertion으로 확인했다.
- 확장 smoke 첫 실행은 모델이 매트 변경을 이전 후보로 제한해 빈 결과가 되어 실패했다.
  조건 변경의 검색 범위를 보완한 후 통과했다. 추가 이전 후보 테스트의 최초 실패는
  fixture 기본 상품이 모두 matte였기 때문이며 glossy/미확인 데이터를 명시한 후 통과했다.
- 실제 Redis/auth/UI/실기기 E2E·사람 의미 평가의 통과를 뜻하지 않는다.
  G1 평가 및 전체 회귀는 재실행하지 않았다. 아래 전체 테스트 수치는 최초 구현 이력이다.

## 최초 구현 변경 사항

- 기존 일반 `chat`은 요청의 `chatContext`와 `requestId`를 제거해 첫 추천 이후 서버
  결과를 이어갈 수 없었다. G1 ON + 한국어 일반 대화를 기존 상품 상담 세션 경로에 연결했다.
  OFF 및 다른 언어의 일반 chat은 기존 파싱·라우팅을 유지한다. AR context는 계속 무시한다.
- 새 세션 저장소나 모델·의존성을 추가하지 않는다. 기존 서버 snapshot, 순번 해석,
  필터 병합/명시적 삭제, Catalog 재조회, Redis WATCH/MULTI를 재사용한다.
- 클라이언트가 바꾼 후보 순서·필터 대신 서버 상태를 사용한다. 상세 조회는 결과 순서와
  resultSetId/만료 시각을 유지하고 stateVersion을 증가시킨다. 조건 변경은 새 결과 ID를 발급한다.
- 한국어 G1 ON 경로에서 전달한 세션이 잘못되면 모델/Catalog 호출 전에 차단한다.
  타 사용자·위조 토큰 403, 만료 410, 오래된 버전·결과 409를 구분한다.
- 중간 일반 설명은 상품/Neo4j 조회 없이 응답하고 이전 세션을 `unchanged`로 유지한다.
  이 일반 설명은 새 snapshot으로 커밋하지 않으므로 동일 요청의 설명문 캐시는 보장하지 않는다.
- 상품 조회의 동일 요청 재전송은 기존 마지막 응답 캐시를 사용한다. 동일 ID의 내용 변경은
  409이며, 동시 요청은 한 번만 커밋한다. 과거 모든 턴의 응답을 보관하는 장기 대화 이력은 아니다.

## 최초 구현 영향 범위

- `backend/chatbot/app/schemas/chat.py`: 플래그 ON 한국어 chat의 요청 ID·세션 파싱.
- `backend/chatbot/app/services/chat_service.py`: 기존 세션 경로 연결과 일반 설명의 문맥 보존.
- `backend/chatbot/tests/test_chat.py`: OFF 한국어 chat의 잘못된 legacy 필드 무시 회귀.
- `backend/chatbot/tests/test_g2_multiturn.py`: G2 최소 계약 및 명시적으로 실행하는 실모델 smoke.
- 이 문서. 최초 구현에서는 프론트·API 서비스·Redis 저장소·배포 설정·기능 플래그 기본값을 변경하지 않았다.

## 최초 구현 검증 이력

- Ruff 및 import-linter: 통과(3개 계층 계약 유지).
- G2 최소 계약: **10 PASS / 실모델 opt-in 1 SKIP**. 서버 순번, 필터 유지/삭제,
  외부 상품의 shade 거부, HTTP 403/410/409, 재전송, 동일/다른 요청 동시성, 일반 설명 문맥 보존.
  LLM/Catalog/Redis는 명시적인 테스트 대역이며 HTTP 인증 검증기도 fixture이다.
- 챗봇 전체 pytest: **878 PASS / 5 SKIP**. 이후 테스트만 보강해 추가한 동일 요청 동시성
  사례를 포함한 위 G2 10건이 통과했다. 전체 최초 실행의 17건 임시 폴더 권한 오류는
  전용 `--basetemp`로 재실행하여 해소했다. G1 전체 평가 실행기를 실행한 것은 아니다.
- `npm run check -- -- --runInBand --testTimeout=30000`: 타입·린트 및
  **95개 Jest 스위트 / 1,118개 테스트 PASS**.

### 실제 모델 + Catalog HTTP smoke

2026-11-16 18:08 KST, G1 ON, `gpt-6-luna`, 로컬 Catalog HTTP에서 **1 PASS**.
추천 6개 → 두 번째 상품 상세 → 2만원 이하로 조건 변경을 연속 실행했다.
순번 상품 일치, 기존 후보 정렬·결과 ID 보존, 가격 조건 교체 및 촉촉함·카테고리 유지,
새 결과 ID 발급, stateVersion **1 → 2 → 3**, 참고 가격 안내를 assertion으로 검증했다.
Catalog 검색 및 상세 요청은 HTTP 200이었다.

Redis는 결정적 대역, 소유 신원은 서비스 호출 fixture다. 실제 Redis/auth/UI/실기기 E2E나
사람 의미 평가의 PASS로 확대하지 않는다. 최초 시도는 다른 서비스의 8000 포트 404,
두 번째는 기존 원격 Catalog의 timeout으로 실패했다. 로컬 8080의 실제 Catalog를 확인한 후
통과했으며 실패 이력을 성공 결과로 바꾸지 않는다.

재실행: 외부 설정 파일 경로를 `G2_LIVE_ENV_FILE`, 실제 Catalog base URL을
`G2_LIVE_CATALOG_URL`에 지정하고 chatbot에서
`uv run pytest tests/test_g2_multiturn.py -k live_model -q -s`를 실행한다.
비밀 설정 파일은 복사·커밋하지 않는다. 테스트 프로세스에서만 G1을 ON으로 한다.

## #245·#246 공통 코드 분석

- #245 HEAD `d231d51fc9dc0dbfbc6dd7c0a8ef0b29c087be56`, 미병합.
  AR 렌더·룩 프리셋·관련 테스트/문서 변경으로, 이번 G2 5개 파일과 직접 겹치지 않는다.
- #246 HEAD `dccfa4f7895326f6dff013e1795d3585b05f416b`, 미병합.
  `schemas/chat.py`, `services/chat_service.py`, `tests/test_chat.py`가 직접 겹친다.
  실제 patch에서 #246은 AR 선택/제안 스키마, 별도 AR LLM 주입, AR 제어 분기와 비동기 ACK를
  추가한다. G2는 일반 chat 파싱과 상품 세션 연결을 바꾼다. 같은 파일이라는 이유로 통째로
  한쪽을 선택하면 안 되며, 합칠 때 AR 라우팅·ACK·생성자 주입과 G2의 OFF/ON 검증을 함께 확인한다.
- #246의 `repositories/chat_session_repository.py`는 AR adjustment 저장/조회 메서드를
  추가한다. 이번 G2는 이 파일을 수정하지 않고 기존 상품 세션 CAS 계약을 재사용한다.
  향후 통합 시 AR snapshot과 상품 결과 버전/키를 혼용하지 않아야 한다.
- 위 분석은 변경 파일·patch 비교이며 merge 실행이나 충돌 해결 완료 선언이 아니다.
  #245/#246의 기능·커밋은 G2에 가져오지 않았다.

## 보존 및 후속 범위

G1 기본 OFF, `g1_open_issues.md`, 기존 평가 원본/결과를 그대로 보존했다.
G1 113건 전체 평가, 사람 평가 18건, REG-02·REG-07·GEN-11 계약, 실기기·팀 E2E를
재개하거나 완료 처리하지 않는다. G2 대표 사례의 전체 환경 평가도 이번 최소 검증과 구분한다.
앱 전송의 변경 경로는 위 관련 테스트로 검증했다. 실제 Redis, 실기기 앱 카드/상세 연결,
Expo Go, 비한국어 확대, 장기 이력 및 통합 리뷰는 후속이다.

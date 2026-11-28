# G8 마감 1단계 실제 조사 — 2026-11-28

기준: feat/compound-consultation / 200010e1a6bad86ad0364f981f47a6ab1ba721fc. 제품 코드·공용 설정·기존 실행 증거를 변경하지 않았다. 이번 산출물은 같은 디렉터리의 stage6-investigation-* 진단 파일뿐이다. develop 병합, commit, push, PR, 배포 없음. 원격 최신 develop을 이번에 fetch하지 않았다.

## 세 종류의 진행표

전체 G8: ① 설계 → ② 기준·계약 → ③ 실행 구조 → ④ 첫 복합 상담 → **⑤ 협력 완성의 종료 조건 보완** → ⑥ 통합 검증 → ⑦ PR 인계. 기존 ⑥ 표적 실행 증거는 있지만 ⑤ 종료 및 ⑥ 전체 통과를 선언하지 않는다.

| 마감 실행 6단계 | 이번 상태 |
|---|---|
| 1 복원·플래그 조사 | 실행 완료. 플래그 결함 재현. 현재 복원 양성 확보. 과거 복원 실패의 단일 원인은 미확정 |
| 2 확인된 결함 수정 | 미착수. 아래 범위를 판단하기 위한 증거만 생성 |
| 3 최신 develop 통합 | 미실행 |
| 4 대표 시나리오 실제 검증 | 과거 증거 보존. 이번에는 복원 표적만 실행. 새 N01/N02/E01/B01 전체 실행 아님 |
| 5 최종 회귀·종료 판정 | 미실행. 이번 표적 테스트를 전체 완료로 승격하지 않음 |
| 6 PR 인계·병합 | 미실행 |

| 기존 ⑤ 완료 기준 6묶음 | 이번 조사로 갱신할 판단 |
|---|---|
| 1 공통 계획 진입 | 기존 구현 유지. G8 최초·저장 맥락 후속의 G5 OFF 방어 보완 필요 |
| 2 결과 기반 협력 | 기존 연결 유지. 비활성 기능을 실행하지 않고 가능한 결과를 보존하는 경계 보완 필요 |
| 3 후속 변경·질문 | 기존 구현 유지. G8 OFF + 중단된 저장 부모가 일반 상담을 가로채는 호환 동작 확인 |
| 4 실행 중단·교체 | 기존 실제 실행 증거 유지. 이번에 전체 종단 재실행하지 않음 |
| 5 판정·응답·복원 | 현재 두 저장 상담의 실제 복원 성공. 옵션 미실행을 정상 검색 완료로 판정하는 결함 확인. 과거 무한 로딩 원인 미확정 |
| 6 종료 증거·문서 정합성 | 과거 기록은 보존하고 이번 진단으로 해석을 보완. 최종 통합 결과 대조는 남음 |

## 1. 실제 재현 결과

### 로그인 웹과 실제 저장 상담

Aside 연결 프로필을 명시해 실제 로그인 브라우저를 사용했다. API 19834, Chat 19833, Expo 웹 19836은 현재 소스를 실행했다. 실제 Supabase 세션, PostgreSQL vishue_g8_browser, Catalog를 사용했다. 새 상담 POST를 보내지 않았으며 모델 호출은 런처에서 차단했다. 새 유료 모델 호출 0회, 차단 시도 역시 0회다. 기존 합성 상담의 저장 결과를 조회한 것이며 새 모델 답변 생성 또는 모의 답변 재생으로 표시하지 않는다.

| 실행 | 실제 관측 | 범위 |
|---|---|---|
| 메모리 계측 번들, 최근 립펜슬 상담 선택 | detail GET 200 → store 복원 성공 → recover 종료 → detailLoading 해제. open 183ms | 현재 코드의 메모리 계측, 제품 파일 불변 |
| 메모리 계측 번들, N02 룩 상담 선택 | 같은 경로 성공. 일반 7단계·보유 후속·팔레트 카드 표시. open 274ms | 실제 저장 상담/PG |
| 복원한 N02 카드 상세 | /product/oy-a000000162667?optionId=A000000162667-012&requireShade=1. [단품]07웜베이지, 앱 등록 가격 17,000원, 가격 시점 2026-10-28T10:06:07 표시 | 실제 Catalog 상세. AR·결제 실행 없음 |
| 원본 번들, N02 Enter 선택 | 02:43:06Z에 버튼 click 확인, detail GET 200(서버 110ms), 저장 내용·카드 복원 | 메서드 래핑 없는 원본 번들. DOM 관찰 리스너만 사용 |
| 원본 번들, 최근 립펜슬 Enter 선택 | 02:44:04Z에 버튼 click 확인, detail GET 200, 옵션 카드 복원 | plain-restore.txt에 화면 원문 |
| 원본 번들, 최근 립펜슬 마우스 선택 | 02:43:47Z 실제 click target이 상담 버튼이 아닌 HTML. 해당 선택의 detail GET 없음 | 이 시도의 입력 대상 오류 확인. 앱 open/auth 대기로 분류하지 않음 |

계측 구간은 브라우저 메모리에만 phase/span/route/method/status/로딩 상태를 기록했다. 토큰·쿠키·계정 ID·상담 ID·발화 본문은 기록하지 않았다. hooks/useChatConversations.ts, lib/api.ts, app/chat.tsx의 변환 전 바이트 해시는 transformations.jsonl에 있다. 원본 번들로 재시작한 뒤에는 변환기를 주입하지 않았다. 중간에 SDK 공개 메서드의 시작/종료를 메모리에서 관찰한 성공 실행도 있으며, 이는 별도 runtime.* 이벤트다. 그 메서드 래핑은 최종 원본 번들 대조 전에 전체 페이지 이동으로 제거했다.

**과거 복원 무한 로딩의 단일 원인은 확정하지 못했다.** 이번 원본 번들의 선택 미도착 1건은 실제 target=HTML로 설명되지만 과거 실행에도 같은 원인이었다고 소급하지 않는다. 계측 없는 화면에서 관측한 일부 로딩은 상담 선택 전 목록 조회 중이었다. 이를 복원 실패 재현이라고 표현한 중간 보고는 정정한다. 기존 HTTP 로그의 path segment 수만으로 detail GET 부재를 단정할 수 없다.

### 기능 플래그 계약 재현

| 조건/경로 | 실제 관측 | 실행 종류 |
|---|---|---|
| G8 ON, Chatbot G5 OFF, 최초 지식 작업 | 실제 consult_knowledge 래퍼를 통과해 KnowledgeService.consult 모의 함수 1회 | 실제 서비스/그래프 + 모의 모델·내부 지식. HTTP 0 |
| 위 결과 직렬화·서버 prepare_request 후 지식 후속 | 같은 OFF 우회 1회 | 저장 맥락 어댑터 실제. 이 사례의 PG 저장은 모의가 아니라 **미실행** |
| Catalog G5 OFF / 잘못된 토큰 / 정상 토큰 | API authorized 의존성은 각각 g5_disabled / g5_forbidden / 허용 | 실제 의존성, 합성 설정. HTTP·DB 0 |
| G1 OFF + G8 ON, 기본 상품 검색 | 기본 Catalog 검색·예산 필터 지원 | 실제 부모/상품 서비스 + 모의 모델·Catalog |
| G1 OFF + G8 ON, 특정 상품 성분 조회 | 정확한 옵션을 연결한 성분 Tool 1회 | 같은 모의 계약 검증. 반환 문구는 실제 상품 사실이 아님 |
| G1 OFF + G8 ON, 현재가·옵션 검색 | 옵션 Tool **0회**, optionSearch 결과 없음, 답변은 후보 없음, consultation.status=**completed** | 결함 재현 |
| 같은 옵션 요청, G1 ON | 옵션 Tool 1회, optionSearch 결과 있음, current_offer 미확인으로 partial | 대조군. 모의 가격 자료 |
| G8 OFF, 신규 일반 상담 | 부모 계획 모델 0회, 기존 일반 답변 | 모의 모델, 실제 ChatService |
| G8 OFF, 활성 저장 부모 맥락 | G8/지식 실행 없이 기존 일반 답변 | 서버 맥락 직렬화/복원 실제, PG 미실행 |
| G8 OFF, 중단된 저장 부모 맥락 + '안녕' | '중단한 상담을 다시 이어갈까요?'가 일반 답변을 가로챔 | 기존 호환 동작 확인. OFF 시 정책 명시 필요 |
| G7 저장 OFF | 일반 상담 200, 저장 상담 GET 503 persistence_disabled | 실제 PG + 모의 인증·모델 |
| G7 기억 OFF | 기억 미적용, 기억 REST 읽기/쓰기 503 | 실제 PG + 모의 인증·모델 |
| 구조화 기억 OFF | 보유 기억 미전달, 구조화 제안 생성 없음 | 실제 PG + 모의 인증·모델 |
| 실행 중 기억 OFF 전환 | 409 request_interrupted, 늦은 메시지 저장 없음 | 실제 PG, 통제된 모의 전문 실행 |
| 동의 철회·기억 수정·후보 무효화 | 기존 PG 사례 통과, Redis 후보 삭제 실제 확인 | 실제 PG/Redis DB15 + 모의 인증·모델 |

G1은 모든 상품 상담 또는 모든 LLM을 끄는 전역 스위치가 아니다. 현재 G8은 별도 계획기를 사용할 수 있고, G1에 묶인 G4 옵션 검색만 비활성화된다. 기존 의존성 자체를 전면 재설계하는 것이 이번 수정의 목표가 아니다.

## 2. 확인된 원인과 코드 근거

### 확정 F1: G5 OFF의 직접 호출 우회

- chat_service.py:697 이후 부모 실행은 G8 경로로 연결된다. :762/:770의 _dispatch_parent_read 지식 호출에는 G5 조건이 없다.
- consultation_parent_graph.py:1078의 기존 전문 협력 지식 호출 역시 직접 래퍼를 부른다.
- knowledge_service.py:697의 공통 consult_knowledge는 키와 내부 토큰 존재만 확인한다. g5_enabled는 확인하지 않는다.
- 기존 chat_service.py:2190의 legacy 지식 실행에는 G5 검사가 있어 진입 경로 간 차이가 난다.
- Catalog API rag.py:17은 별도의 G5 OFF를 막는다. API 측 방어가 존재한다고 Chatbot 측 비활성 조건 준수로 간주하지 않는다. 실제 유료 호출 여부는 재현하지 않았으며 합성 키와 모의 내부 함수로 진입만 증명했다.

### 확정 F2: 미실행 옵션 조회를 정상 무검색 결과로 처리

- beauty_consultation_service.py:1161은 g4_enabled를 locale==ko && g1_supervisor_enabled로 결정한다.
- :1284의 옵션 조회는 g4_search일 때만 실행된다.
- G8가 확정한 옵션/current_offer 요구가 G1 OFF에서 일반 상품 경로로 흘러, 실제 옵션 조회가 없는데 completed + 후보 없음으로 반환된다.
- '조회 기능 비활성/요구 미확인'과 '정상 조회 결과 없음'을 구별해야 한다. 옵션 가격이나 판매 상태를 추정해 해결하지 않는다.

### 확인 B1: G8 OFF의 중단 부모 호환 경계

- consultation_intent_service.py:500은 G8 OFF에서 부모 해석을 생략한다.
- 그러나 chat_service.py:708의 cancelled 부모 응답 분기는 G8 조건 밖에 있다.
- 중단된 저장 부모가 남아 있으면 일반 발화도 재개 질문으로 반환된다. 실제 G8 실행이나 권한 확대는 없었지만 OFF 상태에서 기존 일반 상담을 계속할 수 있는지의 호환 계약은 정리해야 한다.

### 복원 경로에서 확인한 사실

- app/chat.tsx:375 onSelect → hooks/useChatConversations.ts:194 open → lib/api.ts:277 apiChatUserRequest → 사전 인증 → 실제 GET → body → 사후 인증 → restoreServerRoom → 요청 복구 → finally다.
- 훅의 loading은 listLoading || detailLoading이다(:303). 목록 로딩만으로 상세 복원 대기라고 단정할 수 없다.
- app/chat.tsx:288~300의 AppState active는 목록/활성 상담 refresh를 실행한다. Aside 호출 사이 브라우저 전환과 함께 새 list GET이 기록됐다. 이 정상 재조회가 스냅샷의 로딩 관측에 영향을 주었다.
- 성공 계측에서 인증·body·restore·recover·finally가 모두 종료됐다. SDK @supabase/auth-js 2.118.0의 기본은 lockless이며 현재 client.ts는 별도 lock을 넘기지 않는다. 구버전 Supabase lock 교착을 확정 원인으로 쓰지 않는다.
- lib/api.ts:65~88의 타이머는 fetch 응답 헤더까지다. 사전/사후 인증과 body 읽기는 포함하지 않는다. 무기한 대기의 가능한 코드상 공백이지만 이번 실패 원인으로 입증되지 않았다.
- 복원 중 새 chat POST 및 자동 룩 안내 발송은 0회다. 과거 중복 실행과의 인과관계는 미확정이다.

## 3. 아직 확정하지 못한 사항

1. 과거 장시간 로딩이 인증, body, 선택 이벤트, 목록 재조회 중 어디에서 발생했는지. 옛 로그는 요청 식별이 부족하다.
2. 마우스 click이 HTML에 도달한 구체적인 Aside 좌표/포커스 원인. 이번 입력 오류는 확인했지만 제품 UI 결함 또는 모든 과거 실패 원인으로 확대하지 않는다.
3. G8 OFF에서 중단된 저장 상담의 계속 사용 정책. 재개 실행은 막되 읽기와 일반 상담을 허용하는 방향을 권장한다.
4. 새로운 소스와 최신 develop 통합 후의 동작. 이번에는 병합하지 않았다.
5. 원래 14능력·12시나리오 전체, 실기기 AR/카메라·음성, 운영 환경, G5 실제 새 답변. 모두 이번 범위 밖이다.

## 4. 수정 대상 파일과 최소 방향 — 아직 수정하지 않음

모든 경로는 저장소 루트 기준이다. 이 표는 다음 수정 승인을 위한 제안이며 이번에 해당 파일을 수정하지 않았다.

| 파일 | 수정 방향 | 영향/검증 |
|---|---|---|
| backend/chatbot/app/services/knowledge_service.py | 공통 지식 진입에서 G5 OFF를 외부 호출 전에 차단 | 기존 direct/legacy/N01/N02 경로 모두 준수. ON 정상 동작 유지 |
| backend/chatbot/app/services/consultation_parent_graph.py | 지식 기능 비활성 결과를 실패/미지원으로 보존하고 가능한 상품 결과 유지 | 의존성·부분 성공·완료 판정 |
| backend/chatbot/app/services/chat_service.py | 직접 위임의 비활성 처리 및 G8 OFF 중단 부모 일반 상담 경계 | 단일 상담/저장 부모 호환 |
| backend/chatbot/app/services/beauty_consultation_service.py | 옵션 기능 비활성 시 요구를 일반 검색 완료로 바꾸지 않음 | 기본 상품/성분 조회 유지. 새 기능 스위치 추가 없음 |
| backend/chatbot/tests/test_knowledge_service.py | OFF에서 지식/HTTP/모델 0회와 ON 대조 | 중앙 방어 |
| backend/chatbot/tests/test_g8_consultation_intent.py | 최초·후속·직렬화 복원과 G8 OFF active/cancelled | 부모 경계 |
| backend/chatbot/tests/test_g8_consultation_parent.py | 부분 결과와 최종 상태 보존 | 협력/판정 |
| backend/chatbot/tests/test_g4_option_search.py | G1 OFF 요구 미실행/ON 정상 조회/기본 검색 유지 | 옵션 정확성 |
| docs/ai-design/G8-IMPLEMENTATION-SPEC.md | 기존 플래그의 실제 지원 범위·OFF 호환 처리 명시 | 기존 기능 범위 유지 |
| docs/ai-design/G8-WORKLOG.md | 이번 조사와 옛 로그의 해석 보완 및 다음 수정 결과 연결 | 과거 증거는 삭제하지 않음 |

lib/api.ts, hooks/useChatConversations.ts, app/chat.tsx, lib/auth/client.ts는 조사한 파일이며 현재로서는 제품 수정 대상에 넣지 않는다. 기존 인증 소유권 검사를 줄이거나 추정 원인으로 재설계하지 않는다. 지식 계획기에 전달할 기능 목록 변경은 최소 수정 구현 중 필요성이 확인되는 경우에만 별도로 범위를 정한다.

## 5. 병합 전 반드시 해결할 항목

- F1: G5 OFF 시 외부 지식/모델 호출 진입 차단.
- F2: 옵션 조회 미실행을 정상 no_match/completed로 보고하지 않도록 수정.
- B1: G8 OFF + cancelled 저장 부모의 일반 상담 동작을 정하고 코드·계약을 일치시킴. 권한 유출로 확인된 문제와는 구분한다.
- 복원: 실제로 상담 버튼에 선택이 전달된 로그와 상세 응답/로딩 종료/카드 복원 증거를 최종 통합 소스에서도 확보. 현재 양성으로 과거 실패 기록을 삭제하지 않음. 새로운 재현이 없다면 추정 인증 수정은 필수 작업으로 추가하지 않음.

## 6. 후속으로 넘길 사항

- 인증/body 대기의 종단 시간 제한·상세 사용자 복구 UX는 현재 원인으로 입증되지 않은 보강 후보다. 새 제한값을 조용히 추가하지 않는다.
- N02 일반 상담·영상 등록 상품 소개·보유 확인·정확한 판매 옵션 추천에 사람 검수 레시피를 다시 필수화하지 않는다. 영상 실제 기법·특정 대체 적합성·AR은 해당 근거/실행 계약을 계속 요구한다.
- 데이터 부족/대체 적합성 미확인, 신규 능력, 운영 배포 준비, 실기기 AR 등은 기존 구분대로 담당 범위와 후속 검증을 남긴다.
- G7 require_persistence는 env local/test만 허용한다. production persistence_unavailable은 현재 정책이며 이번 G8 기능 확장으로 해제하지 않는다.

## 7. 수정 후 완료 기준

1. G5 OFF + G8 ON의 최초/후속/저장 맥락에서 지식 검색·임베딩·생성 호출 0회. 제품 조회만 가능한 복합 요청은 유효한 결과를 보존하고 정직한 partial/unsupported 판정.
2. G1 OFF에서 기본 상품/직접 성분 조회 유지. 옵션 요구는 실행 불가/미확인으로 구분하고 no_match/completed로 허위 완료하지 않음. ON에서는 실제 옵션 입력과 판정이 유지됨.
3. G8 OFF에서 저장 active/cancelled 맥락을 읽어도 새 G8 실행/자동 재개 없음. 정한 일반 상담 동작 유지. 기존 저장 데이터 삭제/변형 없음.
4. G7 저장·기억·구조화 기억 OFF, 동의 철회와 실행 중 철회의 기존 저장 방어 회귀 0건.
5. 실제 로그인 웹에서 유효한 선택 → 사전 인증 → 상세 GET 200 → body → 사후 인증 → store 복원 → 요청 복구 → 로딩 종료. 복원 카드와 정확한 optionId 상세 연결, 자동 안내 중복 0회.
6. 위 표적 검증 후 최신 develop 통합과 원래 N01/N02/E01/B01 평가를 마감 3~5단계에서 수행. 이번 표적 PASS만으로 ⑤/G8 전체 완료를 선언하지 않음.

## 실행 증거와 한계

- flags.json, flags-v3.log: 실제 ChatService/부모/지식 래퍼 + 모의 모델·내부 지식, HTTP 0. 우회를 검출한 테스트이므로 실행 성공이 제품 결함 해결을 뜻하지 않는다.
- product-flags.json, product-flags-v2.log: 실제 부모/상품 서비스 + 모의 Catalog/모델. ingredientPayload=false는 배치 응답 필드 검사일 뿐이며 get_ingredients 1회와 옵션별 답변은 별도 기록돼 있다.
- api-flags.json: Catalog 의존성의 OFF/토큰 경계.
- unit.xml/log: 기존 G7 서비스 28 PASS.
- pg.xml/log: 기존 선택 PG 테스트 3 PASS, 1 SKIP(초기 Redis URL 미설정), 31 deselected.
- redis.xml/log: 위 SKIP을 실제 Redis DB15로 별도 실행 1 PASS. 초기 DB가 비었음을 확인했으며 flush하지 않았다.
- memory-flags.xml/log: 임시 진단 PG 테스트 4 PASS. 인증·모델은 모의. 알 수 없는 integration mark 경고 1건은 제품 실패가 아니다.
- typecheck.log/lint.log: npm run typecheck / npm run lint PASS. 앱 전체/백엔드 전체 회귀는 재실행하지 않았다.
- browser-events.jsonl, http.jsonl: 실제 브라우저·서버 시각/단계. plain-restore.txt, instrumented-detail.txt: 실제 화면 원문.
- baseline.json, source-integrity.json, record.json: 기준 소스·불변 검증·명령/원본/모드·증거 식별값. security.log: 신규 산출물만 검사. 전체 Git 검사를 새로 했다고 쓰지 않는다.

원본 초기 실패도 보존했다. flags.log는 진단 FakeGraph 누락으로 Neo4j 재시도 후 시간 초과한 설정 실패, flags-v2는 외부 래퍼만 대체한 중간 검증이다. product-flags-initial.json은 합성 옵션 ID 불일치로 성분 경로에 도달하지 못한 초기 fixture다. web.log의 초기 transformer 경로/CRLF anchor 오류와 cold Metro build 지연은 진단 설정 문제다. 이를 제품 결함·최종 통과 증거로 사용하지 않는다. 최신 유효 결과는 위에 명시한 v3/v2와 XML이다.

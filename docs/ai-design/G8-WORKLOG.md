# G8 진행 기록

① 설계 → ② 기준·계약 → ③ 실행 구조 → **④ 첫 복합 상담** → ⑤ 협력 완성 → ⑥ 통합 검증 → ⑦ PR 인계

2026-11-26 KST. [구현 정본](G8-IMPLEMENTATION-SPEC.md). ① 인계 완료. ② 두 정본 및 기준선 작성. ③ 실제 부모 그래프와 첫 세 전문 작업 연결. ④ 코드·계약·화면·저장 검증, 실제 데이터와 모델 결과는 아래 기록을 기준으로 판단한다.

## 기준과 변경 파일

- 원격 `develop` 및 격리 브랜치 `feat/compound-consultation` HEAD 모두 `c70240ae266930f357fb522e839b6dc544504836`. 사용자 작업 사본은 `feat/g7-conversation-persistence` / `d9c6a77c1467d11465a72c66b8f2579b8ab68609`, 조사 시 추적 파일 51개 변경과 다수 미추적 파일. 모든 G8 변경은 격리 브랜치의 미커밋 변경이다.
- 초기 자료는 2026-11-25 킥오프 MD v0.1, 「G8 설계 의견 정리」 5개 턴, PR #241 및 G7 PR #284와 해당 코드다. 지정 G8 정본과 후속 G8 브랜치를 확인한 범위에서 찾지 못했다. 개발 하위 에이전트가 도구, 앱, 저장을 분담했고 공통 계약·그래프·정상 진입·통합 검토는 메인이 맡았다.
- 챗봇 `app/` 아래 신규 `schemas/compound_consultation.py`, `services/compound_consultation_graph.py`, `services/compound_consultation_service.py`. 기존 `core/config.py`, `schemas/chat.py`, `schemas/conversation.py`, `services/chat_service.py`, `services/conversation_context.py`, `repositories/conversation_repository.py`에서 설정, 실제 진입, 영속 허용 목록과 복원을 연결했다.
- 앱 `types/index.ts`, `types/chatConversation.ts`, `store/chatConversationStore.ts`, `app/chat.tsx`, `components/chat/ChatProducts.tsx`, `lib/i18n/{en,ko,ja,zh}.ts`에서 즉시 응답·복원과 카드 표시를 연결했다. 기존 향료 결과 컴포넌트가 복합 답변/인용을 가리는 문제와 상품 대표가가 정확한 옵션 가격을 덮는 문제를 피했다.
- 테스트 `backend/chatbot/tests/test_g8_compound_consultation.py`, `backend/chatbot/tests/test_g7_conversation_api_pg.py`, `__tests__/chatScreen.test.ts`, `__tests__/chatProducts.test.ts`, `__tests__/chatConversationStore.test.ts`. 별도 PR, 커밋, 배포 없음.

## 실행 증거

[작업별 요청·결과와 실행 식별 JSONL](../../reports/g8/first-compound/trace.jsonl) · [Chrome의 첫 상담 화면](../../reports/g8/first-compound/chat.png)

| 실행 | 데이터·도구 | 관측 결과 |
|---|---|---|
| 부모·전문 작업 계약 | 실제 LangGraph, Python HTTP 클라이언트 + mock transport/모델 | 선행 9위 후보의 optionId를 바꿔 2번째 Catalog 요청 본문의 변화 확인. 첫 배치 503 후 2번째 배치의 적합 후보 보존. 그늘/옵션 미식별은 조회 생략, 불완전 성분은 UNKNOWN. |
| G7 실제 저장과 복원 | FastAPI TestClient, PostgreSQL 17.12 및 LangGraph checkpoint, 합성 로그인·도구/모델 | 첫 답변 10개 중 1개 적합, 8개 불일치, 1개 미확인. 같은 requestId 재전송 시 다음 도구 호출 0. 상담 재조회 및 15,000원 예산 변경으로 옵션 재검증, 이전 9위 제외. 일부 nullable 근거 필드가 복원할 때 빠지는 오류를 수정하고 즉시·복원 JSON이 같음을 확인했다. |
| 실제 앱 표시 | Expo Web SDK 58, Chrome, ko-KR. FastAPI/그래프 실제, 지식·플래너·Catalog/추천·게스트 단기 저장 대역 | 첫 입력에서 9위 `sale-9` 90ml의 18,500원 카드와 검색 범위 확인. 같은 게스트의 15,000원 후속 HTTP 200, 조건에 맞는 카드 0. 화면의 관리 문장·제품·가격은 합성 시험 자료다. |
| 현행 API와 실제 데이터 일부 | 기준 SHA의 API + 격리 PostgreSQL, 실제 카탈로그에서 만든 V4 스냅샷. G5 꺼짐 | dry/pores Top10과 6+4 옵션을 HTTP로 확인. 첫 cold 배치 제한 시간 후 나머지 조회 보존. warm 실행은 충족 0, 불일치 4, 미확인 6, 조회 실패 0. 실제 완료된 추천 카드 0. |
| 기존 로컬 배포 | 8082의 이전 API | `conversation` 출처를 보낸 V4 요청 400, 해당 서비스의 OpenAPI에 옵션 검색 경로 없음. 위 검증은 같은 SHA의 별도 HTTP 서버를 사용했다. |

### 실제 모델·HTTP·저장과 발견한 결함

대표 발화와 예산 변경 발화만 OpenAI `api.openai.com`의 `gpt-6-luna`에 보내는 범위를 별도로 승인받았다. 첫 호출 4,104ms·816토큰, 후속 3,165ms·826토큰. 첫 계획은 `dryness, pores`, 예산 20,000원, 제외 성분 향료를 반환했다. 관리 질문에 섞인 쇼핑 표현은 G8에서 일반 관리 질문으로 분리한다. 후속 모델은 같은 목표·제외 성분을 유지하고 예산을 15,000원으로 바꿨으며 추가 지식 조회를 생략했다. 청구 비용은 미측정이다.

최초 실제 모델 실행에서 최종 저장 응답이 `503 persistence_unavailable`였다. 당시 격리 DB를 별도로 확인한 결과 중첩 실행 네임스페이스에 체크포인트 15행과 G8 작업·결과 블롭이 남았다. 하위 그래프가 체크포인터를 상속하지 않도록 수정했다. 수정 후 실제 API/PG 실행은 **첫 턴 실제 모델의 기존 응답을 재생**하고 후속은 새 실제 모델 응답을 사용했다. 두 요청 모두 200, 재전송한 카드·답변이 동일하고 저장 메시지가 2개에서 4개로 늘었다. 15,000원에서는 불일치 7개, 미확인 3개였다. 별도 PG 회귀에서 두 턴의 체크포인트·블롭·대기 쓰기 전 네임스페이스를 조회해 루트만 존재하며 질문 원문·옵션·지식 단서가 없음을 확인했다. 최초 503을 일으킨 내부 예외는 회수되지 않았다.

실제 G5 모델의 관리법 작성은 **NOT_RUN**이다. 승인된 발화 외에 G5 원문·발췌문을 외부로 전송하지 않았다. 원본 저장소를 읽기 전용으로 확인한 범위는 승인·검수·원본 SHA가 일치하는 3,105문서, 해당 청크 36,167개, 인덱스 `large-3200-overlap-1000-v1`, 임베딩 `text-embedding-3-large` 3,072차원이다. 준비 상태와 실제 답변 품질은 별도 판정한다. 실자료 가격·성분 실행에서 G5를 끈 결과는 부분 성공이다.

실제 판매 옵션 `A000000238408-001`은 수집가 10,430원으로 예산을 충족했다. 전체 성분에서 향료 제외를 확정할 증거가 부족해 카드에서 제외했다. 수집가와 추천 기여 성분 코드로 빈 근거를 채우지 않았다. V4 스냅샷 `local-20261104-conservative-v1-20261125T155759212955Z`. 실데이터 추출 manifest SHA256 `2a5f3be32f99acec64134c904f4a92cd53b0578ebe7f197ec24970192defa143`.

## ④ 화면 문구와 근거 확인

첫 화면에 보였던 ‘검증된 관리 원칙’은 합성 지식 답변에 넣었던 문장이었다. ‘수집 가격’은 옵션 가격의 내부 출처 분류를 화면에 표시한 결과였다. 사용자가 고객에게 자연스럽게 안내하도록 수정을 요청했다. 관리법은 바로 안내하고 출처 번호를 붙인다. 카드는 상품과 용량, 금액을 먼저 보여주고 ‘가격 정보’를 열면 확인 시점을 볼 수 있다. 가격·전성분 근거와 소유권·저장 계약은 종전 기준을 적용한다.

최종 PG 회귀 실행 `g8-final-copy-pg-2026-11-25T16:17:23.714270+00:00`은 새 격리 PostgreSQL에서 대표 발화와 예산 변경을 처리했다. 본문의 `[1]`은 합성 관리 문장의 원문 인용 `K1.E1`에 연결됐다. 첫 턴은 18,500원인 90ml 옵션 1개, 후속은 15,000원 이하에서 적합 0개였다. 두 턴 모두 중복 요청의 추가 도구 호출 0회였다. 저장 버전 1·2, 루트 전용 체크포인트와 복원된 본문을 검사했다. 해당 실행은 모델과 상품 데이터를 대역으로 사용했다.

원본 JSONL 7·8행의 실제 가격·성분 결과에도 수정 문구를 오프라인으로 적용한 기록을 12·13행에 추가했다. 가격 확인일은 2026-11-02, 금액은 10,430원이고 향료 제외 여부는 미확인이다. 원격 모델 호출, API 재조회, 기존 저장 답변 변경은 없었다.

최종 캡처는 Chrome의 430×1040 한국어 화면이다. 가격·자료·검색 범위는 처음에 접혀 있다. 각 항목을 눌러 2026. 11. 25. 가격 확인일, 인용 1번의 원문, 추천 후보 9위를 확인하고 다시 접었다. PNG SHA256은 `945e79f9809f264ace46ede0b37fdf549a94223de60c2b7bc41b9c309850d9d3`이다. JSONL의 `final_source_manifest`에는 추적 파일의 diff SHA256과 신규 파일을 포함한 소스·테스트 23개의 개별 SHA256이 있다.

최종 챗봇 전체 회귀는 `pytest -q -p no:cacheprovider --basetemp <fresh-temp>`에서 **1,404 통과, 96 건너뜀**(63.56초)이었다. Ruff 전 파일 통과, import-linter 계층 계약 3개 통과. 이 결과와 별도로 전용 PG를 사용한 최종 저장 회귀 1개를 실행했다.

최종 앱 TypeScript 검사와 Expo lint가 통과했다. 관련 Jest 3개 스위트는 동시 검증 중 한 실행에서 7건 실패했다. 테스트 하나는 이전 상담방 답변 표시 기대값에서 실패했고 나머지 실패의 정확한 원인은 확인되지 않았다. 소스 변경 없이 `--runInBand --no-cache`로 재실행한 결과는 **3개 스위트, 159건 모두 통과**였다. 모바일 앱 실기기 확인은 ⑥에 남아 있다.

## 다음 작업

⑤ N01의 지식→상품 도구 입력, N02 보유품·룩과 부족품만 조회, E01 일부 서비스 실패, B01 기억 제안과 추천 동시 표시·AR/ACK 경계를 구현·검증한다. 실행 중 취소·교체·권한 철회·구버전 응답 폐기와 미완료 재개도 해당 단계에서 다룬다. ⑥ 필수 환경과 핵심 의미 사람 검토, Expo Go 실기기, 권한이 충족된 G5 실자료 응답까지 확인한다. ⑦ 팀 리뷰와 PR은 후속 지시에 따른다.

## 게시 후 상태 및 ④ 보완 → ⑤ N01

전체는 ① 설계 → ② 기준·계약 → ③ 실행 구조 → ④ 첫 복합 상담 → ⑤ 협력 완성 → ⑥ 통합 검증 → ⑦ PR 인계다. 현재 ④ 두 결함 보완과 ⑤ N01 성분 검색 연결의 코드·계약 검증을 수행했다.

2026-11-26 KST에 구현 0e3973f와 문서 5ed8ac1을 origin/feat/compound-consultation에 게시했다. 원격과 로컬 HEAD 5ed8ac159af50cbe459eaea445c285e0ff2c9529 일치 및 깨끗한 작업 트리를 확인했다. 기존 trace는 당시 기록 그대로 보존한다.

게시 전 검사 대상은 위 커밋의 소스다. npm run check -- --runInBand --silent는 npm 인자 전달 때문에 Jest 순차 옵션이 적용되지 않았고 상품 카드 테스트가 5초를 초과해 중단했다. 같은 소스로 npm run check -- -- --runInBand --silent를 실행해 타입·린트·105개 suite/1,320건 통과(125.955초)를 확인했다. 재실행 프로세스 시작은 2026-11-26 01:35:41 KST, Jest 시작은 01:36:12 KST였다. 정확한 명령 종료 시각은 별도 보존하지 않았다.

게시 전 챗봇은 uv run --frozen ruff check ., uv run --frozen lint-imports, uv run --frozen pytest -q --basetemp <fresh-temp>를 실행했다. UV_PROJECT_ENVIRONMENT로 잠금 파일과 일치하는 기존 G7 검토 가상환경을 사용했다. Ruff·계층 3개 통과, 1,404건 통과·96건 건너뜀(45.26초)이었다. 초 단위 실행 시각은 별도 보존하지 않았다.

이번 수정은 후보 생성 목표 보존·구버전 재조회, 설명 전용 목표 변경의 후보 무효화, 질문 맥락 보존, 근거 있는 지식 조건의 다음 옵션 요청 연결이다. 정상 ChatService 3턴과 G7 컨텍스트 직렬화·복원, 세럼·크림 사용 순서 질문, 글리세린→판테놀 제안 변화에 따른 HTTP 본문 변화, 사용자 향료 제외 우선, 잘못된 근거, 제안끼리 충돌, 지식·추출 실패를 검증했다.

신규 증빙은 reports/g8/n01/trace.jsonl이다. 1~15행은 초기 14건 실행이며 16행부터 최종 소스 manifest와 15건 실행이다. 최종 실행의 각 턴에 planner/knowledge/searchExtractor의 mock 또는 not_called를 명시했다. live/replay 호출은 없다. fixture-v1/fixture-rag/fixture-label 자료와 실제 HTTP 클라이언트·MockTransport를 사용했다. manifest UTC 시각과 파일별 SHA256이 검증 대상 미커밋 소스를 식별한다.

2026-11-26 02:07~02:08 KST에 uv run --frozen ruff check .와 uv run --frozen lint-imports가 통과했다. uv run --frozen pytest -q -p no:cacheprovider --basetemp <fresh-temp>는 1,413건 통과·96건 건너뜀(44.09초)이었다. 최종 집중 실행은 15건 통과했다. 증빙 수집 실행에는 이미 불러온 anyio/langsmith 모듈의 assertion-rewrite 경고 2개가 있었다. 앱 npm run typecheck와 npm run lint도 통과했다.

실제 G5/모델의 질문 보존·조건 추출은 NOT_RUN이다. 이번 실제 PostgreSQL 통합은 TEST_CHAT_DATABASE_URL 미설정으로 NOT_RUN이며, 확인한 저장 범위는 컨텍스트 직렬화·복원이다. 기존 PG 테스트의 모의 계획기는 새 추출 호출을 처리하도록 갱신했다. 앱 재촬영·Expo Go·사람 검토는 NOT_RUN이다.

다음은 N01 실환경·사람 검토와 제품 종류/제형 등 검색 표현, 후속 턴의 지식 조건 지속·해제 검증이다. N02, E01 전체 시나리오, B01, 실행 중 취소·재개는 ⑤ 후속 범위에 남아 있다. 이번 변경은 5ed8ac1 위의 로컬 미커밋 변경이다.

### N01 게시 전 최종 검사

2026-11-26 02:14 KST에 구현·테스트 여섯 파일을 9b1df1d로 커밋했다. 이번 게시 전 npm run check -- -- --runInBand --silent는 타입·린트·105개 suite/1,320건 모두 통과(101.307초)했다. 챗봇 uv run --frozen ruff check .와 uv run --frozen lint-imports 통과, uv run --frozen pytest -q -p no:cacheprovider --basetemp <fresh-temp>는 1,413건 통과·96건 건너뜀(46.94초)이었다. 이번 앱 검사에는 재실행이 필요하지 않았다. 미실행 실환경 항목은 앞 절의 판정을 따른다.

신규 trace 32개 레코드를 대상으로 인증 토큰·키·이메일·전화번호·사용자 경로와 식별 필드, URL의 인증정보·쿼리를 확인했다. 검토 범위에서 자격증명·실사용자 식별정보를 발견하지 않았다. 질문은 합성 사례이고 링크는 example.test다. trace SHA256은 5e4f13c31dd5cddfab0e5af34559b8a77295db83a7ed2e16d6e52178babd8fea다. 스테이징한 소스가 검증 대상과 같음을 확인했다. 원래 trace와 신규 trace의 실행 이력은 그대로 보존했다.


## 64188a2 검토 반영 — ⑤ 협력 완성 중 N01

전체 순서는 ① 설계 → ② 기준·계약 → ③ 실행 구조 → ④ 첫 복합 상담 → ⑤ 협력 완성 → ⑥ 통합 검증 → ⑦ PR 인계다. 현재 위치는 ⑤ N01 후속 조건 구현·검증이다. 작업 기준은 64188a2861a804b6ff1d4d89558fc11ce0995e00이며 아래 변경은 로컬 미커밋이다.

G5 resolve의 최종 claims와 초안 findings.index를 비교하던 결함을 제거했다. 첫 주장 탈락·두 번째 성분 권고 통과를 실제 resolve 함수로 만들어 N01에 전달한 회귀가 통과했다. 모델·원문 자료는 이 회귀에서 모의이며 resolve 함수는 실제 코드다. 최종 추출 입력에서도 초안 findings를 제외했다.

성분 한도와 실제 전송 목록이 동일한 중복 제거 함수를 사용한다. 향료/Fragrance가 포함된 사용자 제외 6개는 5개로 정리되고 지식 조건 1개가 추가되어 6개로 조회된다. Catalog 응답 대역의 새 성분 근거도 실제 클라이언트의 provenance 검증 계약에 맞췄고, 9위 옵션이 eligible까지 도달하는 것을 확인했다.

후속 상태는 사용자 조건과 지식 출처를 분리해 저장한다. 예산 변경 유지, 개별 해제, 목표 변경 재평가, 전체 해제의 5턴을 검증했다. 후보 재사용은 기존 V4 목표 기준이다. 구버전 저장 상태는 기본값으로 읽으며, 새 목표의 지식이 실패하면 이전 목표의 제안을 재사용하지 않는다.

### 로컬·실제 PostgreSQL 검증

집중 회귀 17건 통과. 실제 일회용 PostgreSQL에서는 기존 G8 저장 회귀와 신규 N01 5턴 회귀 2건이 통과했다. 매 턴 저장된 출처와 조건을 다시 읽고, 중복 재전송 시 추가 모델·도구 호출 0회를 검사했다. PostgreSQL은 실제, 로그인 검증과 모델·Catalog는 대역이다. 기존 서비스와 분리한 WSL 경로 /tmp/vishue-g8-followup-dcfe629a262a40deabb15789d9bc656f, 포트 56947을 사용했다.

새 DB를 UTF-8로 준비하고 Alembic 및 기존 init_chat_checkpoints 작업을 실행했다. 최초 PG 실패는 checkpoint_writes 테이블 미초기화였으며 초기화 후 복구했다. 그다음 실패는 재전송 응답에서 생략되는 chatContext까지 동일하다고 기대한 테스트였다. 기존 G7 계약에 따라 answer/compound/knowledge/conversation과 추가 호출 여부를 검증하도록 고쳤다. 실패 실행도 신규 trace에 남겼다.

챗봇 전체 uv run --frozen pytest -q -p no:cacheprovider --basetemp <fresh-temp>는 1,415건 통과·97건 건너뜀(63.20초)이었다. Ruff와 import-linter 계층 3개, 앱 npm run typecheck와 npm run lint도 통과했다. 이후 해제 목록 누적 처리와 추출 입력의 초안 findings 제외에 대해 최종 집중·PG 검증을 추가했다. 원문 증빙 수집 실행에는 이미 불러온 pytest 모듈의 assertion-rewrite 경고가 있다.

### 실제 G5·모델·Catalog·PostgreSQL 3턴

2026-11-26 02:51~02:52 KST에 사용자가 승인한 예시 3턴을 실제 연결로 실행했다. OpenAI에 예시와 관련 G5 발췌·답변을 전송하는 승인을 별도로 받았다. 이전 두 예시만 승인된 상태에서는 자동 승인 검토가 실행을 차단했으며, 추가 승인 후 실행했다.

기존 로컬 G5 배포판을 기동하고 기준 코드 API를 127.0.0.1:19828에서 실행했다. 기존 API 가상환경의 python-multipart 누락은 잠금 파일 기준의 임시 환경으로 해결했다. 원본 데이터의 자동 갱신은 비활성화했다. 실제 데이터 V4 요청은 HTTP 200, dataVersion=null, 후보 0개와 mapping_unavailable을 반환했다.

첫 턴은 계획 gpt-6-luna 1회, G5 gpt-6.1-terra 3회(select/answer/detect), 추출 gpt-6-luna 1회를 실제 호출했다. G5는 검색 20개, 원문 일치 발췌 8개, 최종 주장 1개와 partial을 반환했다. 추출 모델의 '약산성 세안제' 제안은 근거 검사에서 거부됐다. 예산 변경과 지식 조건 전체 해제 턴은 계획 모델만 각각 1회 호출했다. 세 턴 모두 HTTP 200이며 PostgreSQL에 저장·복원됐다. 각 재전송의 추가 HTTP 호출은 0회였다.

위 실제 원격 호출 7회는 챗봇 프로세스 HTTP 계측치다. 별도 API 프로세스의 임베딩 호출 횟수는 미계측이며 G5 trace의 임베딩 입력 토큰 33개·2,516ms만 관측했다. 설정 모드와 실제 호출 수를 구분해 기록했다. 실제 Catalog 옵션 조회는 후보가 없어 NOT_RUN이다. 따라서 실제 양성 지식 조건의 유지·해제를 실데이터로 통과했다고 판정하지 않는다.

신규 기록은 reports/g8/n01/trace.jsonl 뒤에 추가했다. live_followup_manifest/turn/replay, pg_followup_test/turn과 집중 실행 manifest를 구분한다. 실자료 quote/claim은 SHA256과 길이로 저장해 원문 발췌가 증빙 파일에 그대로 노출되지 않게 했다. sourceVersion 등 근거 식별자는 보존했다. 실제 3턴 실행 뒤 최종 코드에서 해제 누적 상한의 암묵적 전체 해제를 제거하고 추출 입력의 findings를 제외했으며, 해당 최종 코드의 외부 모델 재호출은 수행하지 않았다.

### 남은 범위

실제 양성 성분 권고와 V4 스냅샷이 있는 데이터로 N01 전체 연결을 검증해야 한다. 모델이 제품 종류를 성분으로 제안한 사례는 실패 기록으로 유지한다. 제품 종류·제형 검색 확장, N02, E01 전체 시나리오, B01, 실행 중 취소·재개, 앱 실기기와 사람 검토는 남아 있다. PR·추가 push는 이번 실행 범위에 포함하지 않았다.

최종 수정 후 집중·실제 PG 결합 실행은 20건 통과·20건 선택 제외(5.08초)였다. followup_final_validation 레코드에 최종 소스 6개와 diff SHA256을 기록했다. 기준 커밋의 기존 N01 trace 837,921바이트가 현재 파일의 prefix로 그대로 남아 있음을 검사했다. 임시 API와 이번 일회용 PostgreSQL은 종료했고 DB 자료·로그는 보존했다.


### 후속 조건 변경 게시 전 검사 — 2026-11-26 03:02 KST

사용자의 후속 지시로 이번 변경도 구현·테스트와 문서·증빙의 두 커밋으로 나눠 feat/compound-consultation에 게시한다. 위 절의 push 미포함은 당시 실행 범위이며 이번 게시 지시로 갱신된다. 전체 순서와 현재 위치 ⑤ 협력 완성 중 N01은 유지한다. PR은 생성하지 않는다.

구현·테스트 여섯 파일을 b0435a6으로 커밋했다. 스테이징 소스가 검증한 작업 파일과 같음을 확인했다. 게시 전 npm run check -- -- --runInBand --silent는 타입·린트·105개 suite/1,320건 모두 통과(88.938초)했다. 같은 소스의 챗봇 uv run --frozen ruff check .와 uv run --frozen lint-imports는 통과(계층 3개 KEPT), uv run --frozen pytest -q -p no:cacheprovider --basetemp <fresh-temp>는 1,415건 통과·97건 건너뜀(37.21초)이었다. UV_PROJECT_ENVIRONMENT는 잠금 파일과 일치하는 기존 G7 검토 가상환경을 사용했다. 이번 게시 검사에 재실행은 필요하지 않았다. 검사 완료 확인 시각은 03:02 KST이며 명령별 시작·종료 시각은 별도 보존하지 않았다.

trace 전체 92개 레코드와 기준 64188a2 이후 추가된 60개를 검사했다. 인증 키·토큰·JWT·비밀키·이메일·전화번호·주민번호·로컬 사용자 경로와 민감 필드, 실제 환경의 자격증명 값 대조에서 노출을 발견하지 않았다. URL 호스트는 example.test이며 질문은 합성 사례다. 실제 G5 주장 8개와 발췌 10개는 해시·길이 형태이고 원문 필드는 없다. 기존 trace의 바이트 prefix를 보존했다. 이번 trace SHA256은 fd407b8af6d06c74095cfc35a061c42d7eff0fdd01932fe9f9be848f2c1abfd4다.

게시 검사는 새 실제 모델 호출을 포함하지 않았다. 앞 절의 실제 연결 결과와 최종 코드 외부 모델 재호출 미실행, 실제 양성 조건·옵션 조회의 미검증 판정을 유지한다. 다음 작업은 유효한 V4 자료에서 N01 양성 연결 검증과 남은 ⑤ 범위다.

## f7b97e1 검토 반영 — 2026-11-26 03:34 KST

전체: ① 설계 → ② 기준·계약 → ③ 실행 구조 → ④ 첫 복합 상담 → ⑤ 협력 완성 → ⑥ 통합 검증 → ⑦ PR 인계. 현재는 **⑤ N01 진행 중**이다. 원격·로컬 기준 f7b97e1b3cd2ef0134804d12d7b14e89417e0cec, 확인한 develop c70240ae266930f357fb522e839b6dc544504836. 이번 변경은 미커밋이며 PR을 생성하지 않았다.

변경 파일은 chatbot의 compound_consultation_graph.py, chat_service.py, test_g8_compound_consultation.py, test_g7_conversation_api_pg.py와 G8-IMPLEMENTATION-SPEC.md, 이 문서, docs/AIHUB_DATA_RIGHTS.md, reports/g8/n01/trace.jsonl이다. 기존 구현·trace를 유지했다.

### 구현 및 확인 범위

- may_plan의 삭제해/적용해 차단과 route_intent의 추천+적용 분류에 같은 검색 조건 대상 판정을 적용했다. 기억·AR·별도 얼굴 적용이 섞인 요청은 기존 경계를 유지하며 G8 OFF의 기존 분류도 보존한다.
- 정상 ChatService에서 해제·삭제·재적용·다시 적용→실제 CatalogClient 요청 본문 변화를 대역 HTTP로 확인했다. 사용자 향료 제외는 유지한다. 새 PG 7턴은 조건 채택→예산 유지→개별 삭제→목표 변경→전체 해제→재적용→삭제를 저장·복원하고 재전송 추가 호출 0회를 확인한다.
- 원래 N01은 모의 계획기의 상황 질문→후속 답변→원래 발화·당김/각질 상황을 지식 입력에 전달→건조함 목표 상품 조회를 확인했다. 질문 전에는 상품·목표를 생성하지 않는다. 모델 계획에 clarify를 추가하고 기존 resultType=clarification을 사용했다. G7 실행·저장 경계와 기존 recentMessages 계약을 유지한다.
- 외부 전송 문서 §1-2에 기존 OpenAI 승인과 예시 3턴·G5 발췌·검증 답변의 G8 추출 승인을 연결했다. 수신처·API·항목·목적을 명시했다. 제공기관 승인 원본을 확인했다고 주장하지 않는다.

### 실제 실행과 증빙

최종 챗봇 전체 pytest -q -p no:cacheprovider --basetemp <fresh-temp>: **1,426 통과·97 건너뜀, 41.84초**. Ruff와 import-linter 계층 3개 통과. 앱 npm run typecheck, npm run lint 통과. 앱 전체 Jest와 실기기 재촬영은 이번에는 실행하지 않았다. 잠금 환경은 기존 G7 검토 venv이며 소스는 이 작업 트리다.

G8 집중·실제 PG 결합: **46 통과·4 건너뜀, 13.71초**. 그 뒤 G8 OFF 라우팅 보존을 추가했고 최종 소스로 PG 7턴 테스트를 재실행해 **1건 통과, 4.17초**를 확인했다. PostgreSQL은 실제 17.12, 합성 인증·계획기·G5·Catalog는 대역이다. 신규 entry_revision_test/entry_final_pg 레코드의 턴별 modelConfiguredMode=mock, actualRemoteModelCalls=0과 요청·저장 상태를 확인한다. 원래 N01 대역 대화는 original_n01 속성으로 별도 기록했다.

실제 V4 사전 점검: 로컬 vishue_g5_integration PostgreSQL 17.12의 SELECT count(*) FROM skincare_serving 결과 **0행**. 데이터 버전은 없고 실제 후보·정확한 옵션·성분 근거 조회는 NOT_RUN이다. **후보 생성용 스냅샷 부재(BLOCKED)**이며 조건 불일치나 근거 부족으로 판정하지 않는다. 실제 양성 연결이 진행될 자료가 없어 이번 새 외부 모델 호출은 0회다. 기존 실제 3턴 실행의 범위를 이번 성공으로 확대하지 않는다. 원본 데이터·스냅샷은 수정하지 않았다.

기존 일회용 PG 경로가 없어 새 /tmp/vishue-g8-entry-20261126-0325, 포트 56947, vishue_chat_test를 초기화했다. Alembic과 init_chat_checkpoints 후 실행했으며 종료했다. DB 자료와 로그는 로컬 보존한다. 첫 준비의 쉘 변수 전달 오류와 Windows ProactorEventLoop 오류는 명시 경로·SelectorEventLoop로 해결했다. 증빙 훅 인자 오타는 테스트 시작 전에 수정했다.

최초 집중 실행은 26 통과·1 실패였다. G1 OFF로 history가 제거되는 테스트 준비를 G1 ON 계약에 맞췄고 27건 통과했다. 최초 전체 실행은 기본 pytest 임시 폴더 접근 거부로 1,408 통과·97 건너뜀·17 준비 오류였다. 원인 확인 후 새 임시 경로로 재실행해 위 최종 결과를 얻었다. 실패·재실행을 성공으로 덮어쓰지 않는다.

trace의 entry_revision_manifest/entry_revision_final_full은 파일별 SHA256을 보존한다. 이 두 레코드의 diffSha256은 실행 디렉터리에 상대적인 pathspec 때문에 빈 diff를 해시했으므로 식별 근거로 사용하지 않는다. entry_final_source의 저장소 루트 기준 diffSha256과 파일별 SHA256을 최종 기준으로 사용한다. 기존 f7b97e1 trace는 바이트 prefix로 유지하며 비밀·인증정보·실사용자 식별정보를 검사한다.

### 별도 판정과 다음 작업

| 범위 | 현재 판정 | 남은 사용자 경험 |
|---|---|---|
| 성분 연결 하위 사례 | 코드·모의 조건 연결·실제 PG 후속 통과, 실제 양성 연결 BLOCKED | 유효한 V4 버전·후보·옵션 근거가 있는 환경에서 지식 채택→옵션 판정→예산 유지→해제 |
| 원래 N01 | 상황 확인과 후속 연결 모의 검증, 전체 미완료 | 실제 모델의 원인 설명·관련 상품 적합성, 유분·베이스 제형 등 다른 원인, 앱 표시·사람 검토 |
| N02·E01·B01 | 전체 시나리오 미완료 | 보유품 기반 룩과 부족품 추천, 서비스 부분 실패 경험, 기억·AR 권한 및 실행 경계의 통합 |

다음은 실제 V4 스냅샷이 있는 검증 환경 연결, 원래 N01의 실제 모델·앱·사람 평가, 이어서 N02·E01·B01 확장이다. 이번 데이터 부재를 해결하기 위해 합성 스냅샷을 실자료로 게시하거나 운영 데이터를 갱신하지 않는다. 신규 파일·공용 계약 변경이 필요한 확장은 구체화 후 기존 승인 규칙을 적용한다.

최종 trace 145개(신규 53개)의 토큰·JWT·비밀키·이메일·전화번호·로컬 사용자 경로 패턴과 기존 환경의 실제 자격증명 값을 대조했고 노출을 발견하지 않았다. f7b97e1의 기존 trace prefix 보존을 확인했다. trace SHA256: d24a13bf5fbc29c6c6a01714c38c3f70606a4d51ea986047115708da0a6fca63. git diff --check 통과. 이번 변경은 로컬에 남겼으며 commit·push·PR은 수행하지 않았다.

### 게시 전 검사 — 2026-11-26 03:39 KST

후속 사용자 지시로 구현·테스트와 문서·증빙을 두 커밋으로 나눠 feat/compound-consultation에 게시한다. 앞 절의 미커밋·push 미실행은 당시 상태다. 구현·테스트 네 파일은 3bb4798로 커밋했다. 원격 사전 확인은 f7b97e1이며 검증 소스와 스테이징 내용, entry_final_source의 파일별 SHA256 및 저장소 루트 기준 diff SHA256이 일치했다.

이번 게시 검사에서 npm run check -- -- --runInBand --silent는 타입·린트·105개 suite/1,320건 통과(92.614초)했다. 챗봇 uv run --frozen ruff check . 및 uv run --frozen lint-imports는 통과(계층 3개 KEPT), uv run --frozen pytest -q -p no:cacheprovider --basetemp <fresh-temp>는 1,426건 통과·97건 건너뜀(36.34초)이었다. 기존 G7 검토 venv를 UV_PROJECT_ENVIRONMENT로 지정했다. 이번 게시 검사에는 재실행이 필요하지 않았다. 완료 확인 시각은 위 절 제목과 같으며 명령별 시작·종료 시각은 별도 보존하지 않았다.

trace 145개와 신규 53개를 다시 검사해 검사 대상 민감정보 및 실제 환경 자격증명 값이 없음을 확인했다. trace와 기존 prefix를 변경하지 않았으며 위 SHA256을 유지한다. 실제 모델·API·PG를 이번 게시 검사에서 추가 호출하지 않았고, 앞 절의 실환경 판정과 남은 N01 범위를 그대로 유지한다. 현재 위치는 ⑤ N01이며 PR은 생성하지 않는다.

## 1dceb38 검토 반영 — 2026-11-26 04:10 KST

전체: ① 설계 → ② 기준·계약 → ③ 실행 구조 → ④ 첫 복합 상담 → **⑤ 협력 완성 중 N01** → ⑥ 통합 검증 → ⑦ PR 인계. 기준 HEAD는 1dceb38cf1eabf9f1aac9deccb7e2919fd8e4298, branch는 feat/compound-consultation이다. 이번 변경은 로컬 미커밋이며 PR·push는 수행하지 않았다.

### 변경과 검증

이전 검토의 세 문장(조건 변경 뒤 얼굴에 발라/강도를 조절해줘/립 색도 설정해줘)은 G8 ON에서 general로 분류되어 계획 진입이 가능한 결함이었다. 기존 route_intent의 실행 정규식을 EXECUTION_REQUEST로 공유하고, 조건 구절을 제거한 나머지에도 같은 실행 판정을 적용했다. 단어를 각각 별도 예외로 추가하지 않았다. 정상 ChatService에서 G8 ON/OFF 응답이 같고 G8 계획·Catalog·AR 호출이 없음을 검사했다. 순수 조건 삭제·재적용 회귀도 유지했다.

원래 N01의 영속 검증을 추가했다. 원래 발화→상황 질문 저장→재전송→클라이언트 recentMessages 없는 다음 발화→서버가 PG에서 복원한 원래 발화·질문을 계획기에 전달→G5 입력과 건조함 목표 상품 조회를 확인했다. G1 ON/OFF 두 설정 모두 통과했다. 두 턴 각각 재전송에서 추가 계획·지식·Catalog 호출은 0회다. 실제 PostgreSQL 17.12를 사용하고 모델·G5·Catalog·인증은 대역이다. 성분 추출은 빈 목록이므로 성분 양성 연결 검증을 대체하지 않는다.

집중 pytest 실행(`test_g8_compound_consultation.py`, `test_g7_conversation_api_pg.py`, `-k 'original_n01 or mixed_execution or condition_provenance'`)은 **7 통과·49 선택 제외, 6.48초**다. G8 파일 전체는 **31 통과, 0.78초**다. 신규 mixed_n01_test의 original_n01_pg 속성에 G1 설정, 턴별 대화·호출 수·서버 복원 history·도구 요청을 보존했다. 모델 설정은 mock, 실제 원격 모델 호출은 0이다.

최종 챗봇 전체 `pytest -q -p no:cacheprovider --basetemp <fresh-temp>`: **1,429 통과·99 건너뜀, 37.25초**. 새 PG 두 설정은 전체 실행에서는 환경 미설정으로 건너뛰며 위 별도 실제 PG 실행 결과와 구분한다. 기존 잠금 버전의 G7 검토 venv에서 수행했다. `uv run --frozen ruff check .`, `uv run --frozen lint-imports`(3 KEPT), 앱 `npm run typecheck`와 `npm run lint`가 통과했다. 앱 전체 Jest·실기기·실제 모델 검증은 이번에 실행하지 않았다.

이전 임시 PG 경로가 없어 /tmp/vishue-g8-mixed-20261126, 56947, vishue_chat_test를 새로 준비했다. 기존 Alembic과 init_chat_checkpoints를 실행하고 Windows SelectorEventLoop를 사용했다. 검증 후 이 인스턴스만 종료했고 로컬 데이터·로그를 보존했다.

### V4 환경 확인

| 확인 대상 | 실제 결과 | 판정 |
|---|---|---|
| 프로젝트 .env.local의 로컬 DB 15441 / vishue_g5_integration | skincare_serving 0행 재확인 | snapshot_absent로 BLOCKED |
| 로컬 API 8000 | V4 POST 404, OpenAPI는 별도 서비스이며 skincare 경로 없음 | VISHUE 검증 환경 아님 |
| 로컬 PostgreSQL 5432 | Docker backend / WSL relay가 포트 소유 | 데이터베이스·스냅샷 미확인 |
| Docker 목록 | 최초 조회 중단, 10초 제한 재확인도 timeout | 컨테이너 환경 식별 불가 |
| Ubuntu 배포판 | psql 경로 및 postgres 프로세스 없음 | 실행 중인 PG 확인 안 됨 |

준비된 V4 환경을 찾았다고 판단하지 않는다. 다른 환경의 데이터 부재도 주장하지 않는다. 설정된 로컬 DB와 서비스만 읽기 전용으로 확인했으며 원본 데이터·배포 설정을 변경하지 않았다. 실제 후보·정확한 옵션·성분 근거·지식 조건 채택은 여전히 NOT_RUN이며 조건 불일치·근거 부족 판정과 구분한다.

### 문서·남은 범위

실행 안내에 비영속 recentMessages는 G1 ON을 요구하지만 G7 영속 history는 서버가 복원한다는 차이를 명시했다. 원래 N01의 저장·복원 공백은 이번 실제 PG 검증으로 보완했다. 원래 N01의 실제 모델 원인–해결책–상품 관련성, 앱·사람 검토와 성분 하위 사례의 실제 양성 연결은 남아 있다. N02·E01·B01 전체 경험도 후속 범위다.

변경 파일은 chatbot 서비스 2개·테스트 2개, G8 구현 계약·이 작업 기록·기존 N01 trace다. mixed_n01_manifest와 mixed_final_validation에 기준 HEAD, 미커밋 소스 SHA256, 저장소 루트 기준 diff SHA256을 기록했다. 다음 작업에는 V4 데이터가 준비된 API/DB 연결 대상의 식별 또는 Docker 접근 복구가 필요하다. 실제 자료가 확보되면 버전→후보→정확한 옵션·성분 근거 순으로 점검한 뒤 양성 연결을 검증한다.

최종 trace는 156개(신규 11개)이며 1dceb38의 기존 145개 바이트 prefix를 보존했다. 토큰·JWT·비밀키·이메일·전화번호·개인 경로 패턴 및 실제 환경 자격증명 값 대조에서 노출을 발견하지 않았다. 소스·diff 해시 일치와 git diff --check 통과를 확인했다. trace SHA256은 d7859406df18397d7b37a111d1d11304f8cb49d32a2d4ece2d9eb5d22349c403이다.

### 게시 전 검사 — 2026-11-26 04:20 KST

후속 사용자 지시로 구현·테스트와 문서·증빙을 두 커밋으로 나눠 feat/compound-consultation에 게시한다. 위 미커밋·push 미실행은 당시 상태다. 구현·테스트 네 파일을 8cade25로 커밋했다. 원격 사전 확인은 1dceb38이며 검증한 소스·diff 해시와 스테이징 내용의 일치를 확인했다.

게시 전 앱 npm run check -- -- --runInBand --silent는 타입·린트·105개 suite/1,320건 통과(94.012초)했다. 챗봇 uv run --frozen ruff check . 및 uv run --frozen lint-imports는 통과(3 KEPT), uv run --frozen pytest -q -p no:cacheprovider --basetemp <fresh-temp>는 1,429건 통과·99건 건너뜀(41.49초)이었다. UV_PROJECT_ENVIRONMENT로 기존 잠금 버전의 G7 검토 venv를 사용했다. 이번 게시 검사에는 재실행이 필요하지 않았다. 완료 확인 시각은 위 제목과 같고 명령별 시작·종료 시각은 별도 보존하지 않았다.

신규 11개를 포함한 trace 156개에서 검사 대상 민감정보와 실제 환경 자격증명 값이 없음을 다시 확인했다. trace 원본·기존 prefix와 위 SHA256을 유지한다. 이번 게시 검사에서 실제 모델·API·PG를 추가 호출하지 않았다. 현재 단계는 ⑤ N01이며 실제 양성 연결의 V4 환경 차단과 남은 사용자 경험은 앞 절의 판정을 유지한다. PR은 생성하지 않는다.

## 4173f36 후속 구현·실제 검증 — 2026-11-26 05:21 KST

전체: ① 설계 → ② 기준·계약 → ③ 실행 구조 → ④ 첫 복합 상담 → **⑤ 협력 완성** → ⑥ 통합 검증 → ⑦ PR 인계. 현재는 **⑤-1 N01 실제 연결·품질 검증, ⑤-2 N02 첫 연결**이다. 시작 시 원격과 HEAD는 4173f36658fb96086388971ceb927a651deb147b, develop은 c70240ae266930f357fb522e839b6dc544504836이었다. branch는 feat/compound-consultation이며 기존 작업 트리는 깨끗했다. 이번 변경은 미커밋이고 commit·push·PR·배포하지 않았다.

### 변경과 담당

메인은 ChatService/compound graph/공통 결과 검증·표시와 관련 테스트, 문서·증빙을 수정했다. 실행 동사만으로 정상 상담을 차단하지 않고 모델의 scope로 설명·검색 조정과 실제 상태 변경·혼합을 구분한다. 의미 판단 결과를 기존 경로로 돌릴 때 버리지 않고 안전한 복합 요청 안내를 사용한다. 설명 전용 목표 변경은 기존 후보 무효화를 유지한다. 설명 전용 계획에 잘못 붙은 상품 목표·조회 플래그는 실행·저장하지 않으며 조건 변경은 refine을 요구한다.

실제 G5의 의역 주장 때문에 유효한 원문 인용이 탈락하는 문제를 수정했다. 최종 주장 인용 연결·원문 구절·주장과 구절의 성분명 확인은 유지하고, 의역 주장에 동일한 원문 문장이 있어야 한다는 중복 제약만 제거했다. 실제 포함 조건을 답변에서 '제외 여부'로 표시하던 결함도 수정했다.

개발 하위 에이전트 v4_recovery는 성공 이력·덤프 추적과 격리 복원을 담당했고, 메인이 실제 HTTP 후보·옵션을 확인했다. n02_contract_audit는 신규 schemas/owned_look_consultation.py, services/owned_look_consultation_service.py, tests/test_g8_owned_look.py 및 consultation_memory.py의 보유 주제 선택을 담당했다. 메인이 내용을 검토하고 ChatService에 통합해 정상 호출 경로를 추가 검증했다. 제품 Agent와 개발 하위 에이전트는 별개다.

N02는 O1 보유품→S1 검수 룩→N1 부위 판정→P1 필요한 상품→R1 정확한 호수 재검토의 실제 입력 연결을 구현했다. 동일 상품·호수로 충족한 부위는 추가 조회하지 않고, 명시적 미보유만 조회한다. 등록 목록 부재는 미확인이다. 조건 미지원·근거 부족·일부 실패를 보존한다. 가격·성분 조건, 일반 대체품 적합성, 지속적인 후속 협력은 아직 완료하지 않았다.

### 실제 V4 환경 회복

과거 성공 기록과 PR #282 자료를 따라 원본 vishue_db_0033_final_20261123.dump를 찾았다. 로컬 보존 위치는 D:/dev/02_TeamProjects/vishue-dump-inspection이며 크기 759,262,803 bytes, SHA256 fe83525204a1b1becd947624a9ceb409954bdb21eddbcb9655ddaf6d24b6bc05다. 원본·기존 개발 DB는 변경하지 않았다.

PostgreSQL 17.12의 별도 /tmp/vishue-g8-v4-restore-20261126, localhost:56949/vishue_g8_v4_validation에 복원했다. 계정·주문·행동 등 13개 TABLE DATA를 제외하고 members/orders 0행을 확인했다. 읽기 역할은 SELECT/CONNECT/USAGE 및 default_transaction_read_only=on이다. PG17의 미지원 exclude-table-data 옵션은 TOC 목록으로 바꿨다. HNSW 생성 중 대기 제한 이후 완료를 확인하고 이미 존재하는 인덱스를 제외한 post-data 재개가 exit 0으로 끝났다.

스냅샷 버전은 local-20261104-conservative-v1-20261123T111457291156Z, 옵션 1,002개·매핑 774개다. 현재 SkincareSnapshot 검증 통과, 원본 JSON과 복원 JSON 일치, 정규화 SHA256 1d45244f6cdf95822142eeae403d5d2587653855fbd6dfbb9aecc7e7f3597dbb를 확인했다. 실제 상품 9,035·호수 11,231·수집 옵션 21,951·옵션 성분 715,482행이다. 이는 11월 25일 G8 스냅샷을 복원했다는 뜻이 아니다.

API는 현재 소스를 사용했다. G5 검색 API 19828은 기존 G5 DB 15441에, Catalog/V4 API 19829는 격리 읽기 전용 DB에 연결했다. SKINCARE_REFRESH_ENABLED=false, 기존 pr233-reviewed-mapping.json 검수 매핑을 사용했고 추천 순위·CosIng 정책은 바꾸지 않았다. 사전 실제 조회는 건조함+모공/유분/민감함 각각 10개 후보와 6+4 옵션 배치를 확인했다. 2만 원·향료 제외 조건에서 각각 unknown/excluded=6/4, 5/5, 7/3이었다. 후보 없음이 아니라 후보의 조건 불일치·근거 부족이다.

### 실제 모델·API·PG 결과

원본 증빙은 reports/g8/n01/trace.jsonl의 recovered_v4_preflight, recovered_live_*, base_method_* 및 scope_live_model_release다. 모델은 계획·추출 gpt-6-luna, G5 gpt-6.1-terra; 실제 G5 promptVersion terra-b-claim-scope-v6, contextVersion same-source-b-1050-citations-v2다. 문서별 sourceVersion과 정확한 옵션 식별자·조회 본문은 trace에 보존했다. G5 검색 API의 임베딩은 text-embedding-3-large 실제 호출이지만 별도 API 프로세스여서 아래 호출 수에는 포함하지 않았고 trace에도 명시했다.

| 실행 | 실제 결과 | 모델 HTTP 요청 / 지연 |
|---|---|---|
| 최종 실행 범위 분류 8사례 | 사용 순서 knowledge, 조건+설명 refine, 목표 변경 refine, 혼합 4건 차단, 기억 혼합 기존 경계 모두 기대 일치 | 7회, 호출 턴 1.23~2.30초; 기억 혼합 0회 |
| 성분 하위 사례 1턴 | 히알루론산·판테놀 includes 채택, 실제 Catalog 요청 전달, 10옵션 중 제외4·미확인6 | 5회 / 33.44초 |
| 예산 15,000원 변경 | 위 지식 조건 유지, 사용자 향료 제외 유지, 제외7·미확인3 | 1회 / 5.87초 |
| 지식 조건 전체 해제 | 지식 조건 제거·cleared=true, 사용자 향료 제외만 유지 | 1회 / 6.82초 |
| 원래 N01 첫 질문 | 원인을 단정하지 않고 당김/각질·유분/뭉침·기초/베이스 확인 | 1회 / 3.24초 |
| 원래 N01 당김/각질 답변 | 실제 G5 partial, 목표 dryness로 조회, 제외6·미확인4; 현재 로션·쿠션과 들뜸의 인과·특정 상품 적합성은 미확인 | 5회 / 38.08초 |
| 원래 N01 예산 변경 | PG 복원 후 동일 목표 유지, 제외9·미확인1 | 1회 / 4.82초 |
| 이미 유분 상황을 제공한 N01 | 중복 질문 없이 실제 원인·관리 설명과 조회, 적합5·제외5; 지식 성분 조건은 없음 | 5회 / 33.82초 |
| 베이스 제형·사용 순서 최종 | 임의 피부 목표 없이 실제 G5 실행, insufficient_evidence·상품 조건 미지원 안내, 상품 조회 없음 | 4회 / 26.92초 |

위 성공 턴은 실제 격리 PG 56947/vishue_chat_test에 저장하고 같은 요청 재전송에서 추가 HTTP 0회·같은 답변을 확인했다. 인증은 합성 verifier, Redis는 double이며 실제 사용자 인증·실기기 E2E 성공으로 확대하지 않는다. 상품 카드는 compound.options 응답 데이터 기준이며 실제 앱 렌더링은 이번에 확인하지 않았다.

성분 하위 사례는 실제 지식 조건→옵션 입력→판정→후속 저장 연결을 확인했다. 그러나 이 조건에서 적합 상품은 0개이므로 성분 포함·향료 제외를 모두 충족하는 실제 추천 카드 성공을 주장하지 않는다. 유분 사례의 5개 적합 옵션을 그 증거로 대체하지 않는다. 원래 N01의 건조함 원인·베이스 제형 해결 설명은 여전히 근거와 품질 보완이 필요하다.

### 실패와 검증 범위

초기 실제 실행에서 예산 변경 502가 한 번 발생했다. 모델 HTTP는 200이었지만 당시 함수 인자를 기록하지 않아 원인 확정 불가다. 이전 live PG의 지식 응답을 재사용한 진단에서는 계획·추출 모델만 2회 실제 호출했다(recovered_live_diagnostic, G5 replay). 예산 계획은 재현되지 않았고, 원문/의역 중복 제약을 확인했다. 이후 새 실제 G5 3턴은 모두 성공했다. 초기 유분·베이스의 불필요한 반복 질문도 기록을 유지한다.

베이스 재검증은 모델이 knowledge와 임의 goal/빈 goals를 함께 반환하거나 최상위 조회 플래그를 추가해 502가 났다. explanation-only 어댑터가 상품 상태를 사용하지 않게 보완한 뒤 최종 200이었다. 이 성공은 충분한 상담 품질을 뜻하지 않는다. G5는 근거 부족을 반환했다.

집중 계약 66건 통과 후 실제 PG 포함 최종 계약 87 통과·4 건너뜀(16.56초)을 확인했다. 해당 명령은 Windows SelectorEventLoopPolicy를 설정한 pytest.main으로 test_g8_compound_consultation.py, test_g8_owned_look.py, test_g7_conversation_api_pg.py를 실행했다. scope_n02_final_contract_pg에 시작·종료 시각, 파일 해시, 각 테스트 결과와 N02 전문 작업 입력/결과를 기록했다. 이후 표시 결함의 테스트만 추가하여 1 통과·45 선택 제외(0.15초), 구현 소스는 동일하다.

전체 백엔드 pytest -q -p no:cacheprovider --basetemp <fresh-temp>는 1,464 통과·99 건너뜀(38.29초)이었다. 이 실행 뒤 explanation-only 플래그 무시를 추가했으므로 최종 전체 재실행으로 주장하지 않고 위 집중·PG 검증을 최종 근거로 쓴다. 최종 ruff check .와 lint-imports 3 KEPT, 앱 npm run typecheck와 npm run lint는 통과했다. 앱 전체 Jest, N02 실제 Catalog/PG/모델, 실기기, 사람 평가는 NOT_RUN이다.

환경 실패도 구분한다. 샌드박스 uv 캐시 접근 실패와 중단한 pytest는 통과로 세지 않는다. 기존 잠금 venv를 승인된 실행 환경에서 사용했다. 최초 PG 집중 실행은 Windows 기본 이벤트 루프로 3건이 persistence_unavailable(503)로 실패했고 SelectorEventLoopPolicy 재실행으로 해결했다. 중간 Ruff의 프롬프트 줄 길이 1건도 수정 후 최종 통과했다. 초기 scope_live_model은 실행 중 소스 수정으로 매 턴 파일 해시가 실행 모듈과 같다고 보장되지 않으므로 최종 근거에서 제외하며, 소스 고정·전후 해시 확인한 scope_live_model_release를 사용한다.

### 남은 범위와 다음 작업

- 데이터 환경 차단: V4 스냅샷 부재는 이번 격리 복원으로 해소. 원본·운영 데이터 변경 없음.
- 데이터·근거 한계: 향료 제외 및 지식 포함 조건을 모두 확인한 실제 추천 상품 확보, 건조함/베이스 상담 근거 보완.
- 구현: N02 일반 대체 적합성·검색 조건·후속 턴, 공통 부모의 전문 작업 제안 기반 재계획, 취소·미완료 실행 재개. 고정 작업 연결을 G8 전체 협력 완성으로 보지 않는다.
- 미실행·검토: N02 실제 연결·앱, N01 최종 앱 표시와 사람 검토, E01/B01 전체 통합, ⑥ 전체 G8 평가.
- 다음: N02의 현재 동일 상품·호수 계약을 기반으로 실제 G7 룩 선택·동의 기억 저장/복원부터 확인하고, 근거가 있는 대체 후보와 후속 조건 변경으로 확장한다. N01 부족한 근거와 상품 조건은 별도 추적한다.
- 사용자 판단 필요: 현재 없음. commit/push는 별도 후속 지시를 기다린다.

검증 후 이번 API 19828/19829와 격리 PG 56947/56949를 종료했다. 복원 데이터와 로그는 보존하고 기존 G5 DB는 유지했다. 기존 trace 156개 바이트 prefix를 보존했다. 최종 기록·민감정보 검사 식별값은 아래 추가 기록을 따른다.

최종 trace는 209개(신규 53개)다. 기존 156개 바이트 prefix 보존, API 키·JWT·비밀키·이메일·개인 경로·자격증명 URL 패턴과 실제 환경 비밀 값 대조에서 노출을 발견하지 않았다. 실제 G5 quote/claim은 해시·길이로 보존하고 실행 답변은 검토용으로 기록했다. trace SHA256: 589e25643a30961d5668eda68a2d969e0b157d6ce73d14c63b5cf1ec78812120. scope_n02_final_source에 최종 Python 9개 파일 해시(신규 3개 포함)와 tracked diff 해시를 기록했다. 마지막 포트 확인에서 이번 네 포트의 listener가 없음을 확인했다. git diff --check 통과.

## 신규 증빙 형식 전환 — 2026-11-26

전체: ① 설계 → ② 기준·계약 → ③ 실행 구조 → ④ 첫 복합 상담 → **⑤ 협력 완성** → ⑥ 통합 검증 → ⑦ PR 인계. 현재 N01/N02 구현·검증 상태는 유지하고, 보안 PR #296 이후 증빙 정리 2번을 수행했다.

보안 PR #296은 2026-11-26 11:48:51 KST에 699d9b067e7ef1ca327617e12adbdd55fafd3ffd로 develop에 병합되었다. 원격 gitleaks/app/ci-ok 성공을 확인했다. 이번 작업 HEAD는 feat/compound-consultation의 4173f36658fb96086388971ceb927a651deb147b 그대로이며 develop 병합·commit·push는 수행하지 않았다.

변경 파일은 reports/g8/n01/trace.jsonl, 신규 trace-format-migration.json, 이 WORKLOG다. Git HEAD에 게시된 156개 기록의 바이트 prefix를 그대로 유지하고 미커밋 53개만 sourceManifestVersion=2 형식으로 전환했다. 전체는 209개다. 파일 경로→해시 map을 path/sha256의 독립 필드 배열로 바꿨고, 작업 결과·입력·모델 모드·호출 수·성공/실패 판정·소스 해시 값은 유지했다. 53개를 구형 의미 구조로 역변환하여 원본 JSON과 모두 동일함을 확인했다.

원본 209개 전체는 Git 밖의 %USERPROFILE%/.codex/evidence-archives/vishue-g8/20261126/trace.original.jsonl에 바이트 그대로 보존했다. 임시 실행 복사본과 별개인 지속 보관 경로이며 증빙 보관 판단 전에는 삭제하지 않는다. 원본을 프로젝트에 다시 추가하거나 인코딩해서 보안 검사를 우회하지 않는다. trace-format-migration.json에는 백업 참조, 도구 commit·해시, 원본/전환본/게시 prefix 해시와 각 전환 행의 전후 해시를 기록했다.

도구는 병합 commit 699d9b의 scripts/g8_evidence.py를 Git에서 읽어 사용했으며 작업 branch에 별도로 복사하지 않았다. 실제 Gitleaks 8.30.1과 빈 ignore로 신규 53개를 검사해 전환 전 generic-api-key 2건(exit 1), 전환 후 0건(exit 0)을 확인했다. 검사 원문 값은 출력하지 않았고 redact 결과만 로컬 임시 검사 폴더에 보존했다. 구현·테스트 Python 9개 파일은 기존 실행 증빙의 해시와 모두 일치했다.

과거 이력 전체의 scanner 통과는 이번 판정에 포함하지 않는다. 게시된 trace와 이력은 유지했고, G8 branch에는 develop의 .gitleaksignore가 아직 들어오지 않았다. 다음은 현재 G8 변경 전체의 커밋 전 검증·커밋 후 develop 통합과 재검사다. 이번 형식 전환은 새로운 모델/API 실행이나 G8 기능 완료를 뜻하지 않는다.

전환 전 trace SHA256: 589e25643a30961d5668eda68a2d969e0b157d6ce73d14c63b5cf1ec78812120

전환 후 trace SHA256: 4c55043103227ca317a81c3e6c1cfbda5c59e32a7653b84456ac1c1a3869075e

최종 검증: 원본 지속 보관본·게시 prefix·53개 역변환 일치를 다시 확인했다. npm run typecheck와 npm run lint 통과. 기능 소스가 바뀌지 않아 모의/실제 상담 평가를 다시 실행하지 않았으며 기존 결과를 유지한다. 이번 신규 기록·변환 명세·WORKLOG의 별도 Gitleaks 검사와 git diff --check 결과는 최종 보고에 따른다.

## G8 변경 보존 및 develop 통합 착수 — 2026-11-26 13:10 KST

전체 ① 설계 → ② 기준·계약 → ③ 실행 구조 → ④ 첫 복합 상담 → **⑤ 협력 완성** → ⑥ 통합 검증 → ⑦ PR 인계. 현재 ⑤-1 N01의 실제 연결·품질 보완 및 ⑤-2 N02 첫 연결 상태를 유지한다. 이번에는 기존 구현을 커밋으로 보존하고 최신 develop을 통합한다. 새로운 상담 기능 완료나 실제 API/LLM/PG 재실행으로 세지 않는다.

기준 HEAD/원격 G8은 4173f36658fb96086388971ceb927a651deb147b, fetch로 확인한 develop은 f5adb4e60202bdc4c98bdefe36669f96f90e9b55다. 구현·테스트 9개와 문서·증빙 4개를 분리 보존한다. 검증 소스는 trace의 scope_n02_final_source에 기록된 9개 파일과 동일하며 trace 형식 전환은 trace-format-migration.json으로 식별한다.

커밋 전 검사(2026-11-26 13시 KST 실행, 13:10 이전 종료): npm run check -- -- --runInBand --silent는 타입·린트·105 suites/1,320 tests 통과(114.875초). chatbot에서 기존 G7 잠금 venv를 UV_PROJECT_ENVIRONMENT로 지정한 uv run --frozen ruff check . 및 uv run --frozen lint-imports는 통과(3 KEPT). 최초 uv run --frozen pytest -q -p no:cacheprovider는 1,448 통과·99 건너뜀·17 setup 오류(55.87초): 공용 pytest 임시 폴더의 WinError 5이며 통과로 세지 않는다. --basetemp에 새 GUID 임시 경로를 지정한 전체 재실행은 1,465 통과·99 건너뜀(48.68초). PG 등 환경 필요 99건은 이번 실행에서 검증하지 않았다. 테스트별 정확한 시작 시각은 별도 보존하지 않았다.

Gitleaks 8.30.1 dir 검사: 변경 13개 파일 중 trace는 신규 53개만 복사하고 기존 설정·빈 ignore·redact로 검사하여 exit 0. 게시 prefix 156개는 유지한다. git diff --check 통과. 최신 develop에는 PR #296의 정확한 fingerprint 예외 및 증빙 도구 외에 PR #297의 HEAD 이력 검사 범위와 룩 상담 데이터 API 등 팀 변경도 있다. 이를 임의 재구현하지 않고 통합 후 검증한다. push·G8 PR 생성·배포는 이번 실행에 포함하지 않는다.

### 로컬 커밋 보존·develop 통합 검증 — 2026-11-26 13:15 KST

구현·테스트 commit 8ca23b3, 문서·증빙 commit f3fe8ab로 보존했다. f5adb4e60202bdc4c98bdefe36669f96f90e9b55를 --no-commit --no-ff로 병합해 충돌 0건을 확인했다. 자동 병합된 types/index.ts와 4개 번역에서 G8 계약을 보존했다. chatbot 소스는 병합 전과 동일하고 backend/api 전체는 develop과 동일하다. 병합 검증 후 별도 merge commit으로 보존하며 push·G8 PR·배포는 하지 않는다.

검증은 f3fe8ab + 위 develop의 미커밋 자동 병합 결과를 대상으로 13:10~13:15 KST에 실행했다. 임의 기능 수정은 없고 두 부모와 merge 결과로 소스를 재현할 수 있다.

- 앱: npm run check -- -- --runInBand --silent 통과. 타입·린트, 107 suites/1,325 tests, 129.574초.
- chatbot: 기존 G7 venv와 uv run --frozen 사용. ruff check ., lint-imports(3 KEPT), ruff format --check .(153 files) 통과. pytest -q -p no:cacheprovider --basetemp <새 GUID 임시 경로>: 1,465 통과·99 건너뜀, 38.52초.
- API: 현재 uv.lock과 SHA256이 동일한 skin-conversation-api venv 사용. ruff check ., lint-imports(3 KEPT), ruff format --check .(329 files) 통과. 같은 pytest 명령: 628 통과·52 건너뜀·2 실패, 67.06초. test_celebrity_videos_endpoint_uses_client_contract 및 test_style_looks_endpoint_uses_client_field_names는 기본 로컬 PostgreSQL 인증 실패로 HTTP 500. 환경 차단이며 전체 API 통과로 기록하지 않는다. 기존 DB 계정·데이터는 변경하지 않았다. test_look_consult_api.py 집중 재실행은 4 통과, 0.39초(계약·모의 검증).
- 증빙 도구: 저장소 루트에서 GITLEAKS_BINARY=8.30.1 실행 파일을 지정하고 python -m unittest discover -s scripts -p test_g8_evidence.py, 5 통과/13.215초. 22개 과거 해시 재계산과 가상 비밀 키 차단을 포함한다. 최초 chatbot 하위 폴더 실행은 Git 경로 기준 때문에 1 실패·1 건너뜀이었으며 성공으로 세지 않는다.
- Gitleaks 8.30.1: 병합 양쪽 부모를 --log-opts="--full-history --diff-filter=tuxdb HEAD origin/develop"로 검사, 87 commits/0 leaks/exit 0. 설정은 develop의 병합된 .gitleaksignore와 .gitleaks.toml 그대로다. 최초 출력 수집은 Windows cp949 decode 오류(스캐너 exit 0)가 발생해 UTF-8로 다시 실행한 결과를 채택했다. 민감한 탐지값은 출력하지 않았다.
- git diff --cached --check 통과. 실제 모델/API/PG 상담 재실행, 실기기 앱, 전체 G8 평가는 NOT_RUN. 기존 live 증빙은 그대로 유지한다.

현재 위치 상세: ① 착수 설계와 ② 계약 및 ③ 첫 실행 구조는 존재하며 ④ 첫 복합 상담은 구현·부분 실제 검증 상태다. ⑤-1 N01은 지식→조건→옵션 요청·후속 저장 연결을 확인했으나 원래 들뜸 사례의 설명 근거·품질과 조건 충족 카드가 남았다. ⑤-2 N02는 보유품→검수 룩→부족 부위→정확한 상품·호수의 첫 연결만 구현했다. 일반 대체품 적합성, 후속 턴, 실제 Catalog/PG/모델 검증은 남았다. E01/B01 전체, 재계획·취소·재개도 남아 있다. ⑥ 통합 평가 및 ⑦ G8 PR 인계는 미완료다.

다음 기능 순서: N02의 G7 룩 선택·동의 기억 저장/복원 실제 경로 확인 → 필요한 상품만 조회하는 실제 연결과 후속 조건 검증. 병행할 N01 근거 보완 후보는 develop의 검수된 troubleshooting/룩 태그 API이며 아직 chatbot에서 연결하지 않았다. 데이터·근거 계약을 먼저 대조한다. 로컬 API 환경 차단 2건은 통합 검증의 미해결 항목으로 유지한다. 보안 우회나 광범위 제외는 추가하지 않는다.

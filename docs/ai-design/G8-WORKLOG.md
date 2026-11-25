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

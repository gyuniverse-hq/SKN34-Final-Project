# G8 진행 기록

## 현재 진행판 — 2026-11-27

전체: ① 설계 → ② 기준·계약 → ③ 실행 구조 → ④ 첫 복합 상담 → **⑤ 협력 완성** → ⑥ 통합 검증 → ⑦ PR 인계. 아래의 과거 날짜별 기록은 당시 상태로 보존한다.

| ⑤ 내부 순서 | 상태 | 남은 일 |
| --- | --- | --- |
| A 공통 부모와 N01·N02, 목표·후속 질문 연결 | 부모 후속 오분기·설명 철회 수정 및 회귀 통과 | 범용 목표 분해와 실행 재개 미완료 |
| B N02 보유품·조건·단계별 상품 사용 근거 | 3개 룩 범위 부분 실제 검증 | 추가 2개 룩에서 동일 옵션 보유·미보유 확인, 다른 보유품은 활용 후보로만 안내 |
| C 실행 기준 확정 및 판매 옵션/AR 정보 분리 | 이번 범위 구현·검증 완료 | C1/C2 실행 기준 확인, C3-2 검수 조건/판매 옵션/AR 분리, C4-2 실제 3턴·회귀 완료 |
| D 실제 상담→상품 카드→저장·복원 | 판매 optionId 상세·장바구니에 이어 상담·명시 보유 기억·N02 입력 연결 실제 API/PG 통과 | 옵션 결제 제한 유지. Expo Go 및 로그인 앱 종단 미실행 |
| E 남은 협력·E01/B01·취소·재개 | 후속 | 개별 사례 통과와 전체 완료 구분 |

### 이번 보완 — 부모 후속·판매 옵션 상담/기억 (2026-11-27)

기준 feat/compound-consultation / c4fe95497538e7c26e62c8ff27ad6bcff6c70672, 미커밋 변경. 기존 두 게시 커밋은 2ee4d3d(구현·테스트), c4fe954(문서·증빙)이며 당시 원격 동일 SHA/clean을 확인했다. 이번 원격 develop 재조회·merge·commit·push·PR 없음. 이번 source manifest와 diff는 reports/g8/parent/followup-option-*에 보존한다.

변경: skin 부모의 설명 후속이 Style로 오분기하지 않도록 현재 룩/부모 작업 종류를 확인한다. N02 설명 철회 시 추가 G5를 생략하고 이전 작업은 superseded로 둔다. 판매 optionId를 카드/룩 결과→상세→상담 entry/screen→서버 맥락→보유 제안/승인→N02로 연결했다. 같은 상품의 옵션 A/B와 legacy 기억은 구분하며 사라진 AR 색상을 보유 사실의 삭제 조건으로 쓰지 않는다. 상품 상담의 구조화 기억 진입은 명시적 선택 옵션 보유 요청에만 제한했다. 자동 기억 적용/AR 실행/결제 확대는 없다.

승인 범위에 추가로 StyleRecipeResult.tsx 및 신규 styleRecipeResult.test.tsx를 사용자 승인받았다. 테스트 파일이 기존에 없음을 확인해 신규 파일로 생성했다. 제공 AGENTS.md의 파일 범위 규칙을 적용했다. 개발 하위 에이전트는 사용하지 않았다.

실제 실행 결과:
- 챗봇 관련 모의 회귀 133 pass/4 skip. 실제 부모/N01/N02 코드, 계획·G5·Catalog는 모의. 전체 챗봇 1,539 pass/107 skip, 외부 모델 0회.
- 실제 Catalog HTTP + PostgreSQL: 1 pass. 19831의 기존 현재 소스 API(상품 DB 15434/vishue_db는 읽기 전용)와 별도 15434/vishue_chat_test를 사용했다. 격리 DB가 없어 신규 생성하고 기존 Alembic 마이그레이션을 적용했다. AR 없는 A000000162667-012 및 -001을 정상 /api/chat에서 각각 제안, 명시 승인, 저장/복원하고 영상 L8RvSmdkR2g의 N02 O1 입력에 두 옵션이 유지됨을 확인했다. API 테스트 인증은 합성 fixture, 모델 설정 mock-configured/FakeLlm, 실제 외부 모델 호출 0회. 로그인된 실사용자 앱 종단 검증은 아니다.
- G7 실제 PG 회귀 36 pass/8 skip. Catalog/모델은 모의. 첫 실행 25 pass/11 fail/8 skip은 새 DB의 LangGraph checkpoints 미초기화가 원인이었다. 기존 app.jobs.init_chat_checkpoints를 실행한 뒤 재검증했다. 제품 코드로 환경 실패를 숨기지 않았다.
- 앱 관련 7 suites/193 pass. 타입 검사와 lint 통과. React renderer 모의이며 실제 기기 검증과 구분한다. 상세→상담 ID/이름, 같은 상품의 옵션 변경, 카드/룩 결과 상세 콜백, 기존 장바구니/AR 회귀를 포함한다.

재실행 경위: 초기 합성 Catalog에 get_product_option 모의 누락, 신규 테스트 필수 version/reason 누락, 번역 모의의 매개변수 미반영을 바로잡았다. 실제 연결에서는 최초 모의 모델 configured=False를 정상 mock-configured로 바꿨고, 기존 general-only 구조화 제안 제한 때문에 상품 옵션 요청의 제안이 없던 경로를 위의 좁은 계약으로 보완했다. 이전 기록의 설윤 룩 ID를 추정 사용한 조회는 404였고, 현재 Catalog에서 실제 옵션 연결 룩 L8RvSmdkR2g를 확인해 사용했다. 브라우저에서는 오래된 Expo 번들이 optionId 없는 URL로 이동하여 현재 워크트리의 검증 서버를 캐시 초기화 후 재시작했다.

Aside 실제 웹 DOM 검증: 캐시 초기화 후 실제 옵션 상세의 VISHUE 상담 버튼이 /chat?productId=oy-a000000162667&optionId=A000000162667-012로 이동했고, 상담 대상에 “[단품] 07 웜 베이지”가 표시됐다. 게스트·읽기 전용 화면 확인이며 발화를 전송하지 않았다. 증빙 followup-option-browser.json.

보안: Gitleaks 8.30.1/저장소 설정/빈 ignore로 변경 소스·문서·신규 증빙 42파일 통과 후, 같은 방식으로 새 trace 행을 별도 검사하여 append했다. 신규 trace의 실제 연결 기록은 합성 테스트 사용자/동의 기록이며 실제 사용자 대화·인증정보·얼굴 자료를 포함하지 않는다. 기존 trace/보안 설정/이력은 수정하지 않았다. source exact-byte manifest 29파일 일치 확인, 미커밋 tracked diff와 신규 테스트 원문을 보존했다. 실행 명령/시각/결과는 followup-option-*.xml·app-tests.json·browser.json·security.log 및 신규 trace에 기록했다.

이번 운영 변경은 없음. 실제 LLM·Expo Go·로그인 앱에서 승인 버튼까지의 전체 종단은 NOT_RUN. 전체 G8/⑤/N02 완료가 아니다. 다음 우선순위는 N02 같은 부위 내 여러 상품 역할의 필요/충족 판정과 부모 완료 판정 보완, 이어 E01/B01 전체 및 취소/재개다.

C1/C2 결과: Docker Desktop이 중지된 것을 확인하고 기존 서비스 복구 승인 범위에서 시작했다. 이전 8082는 vishue-pr233-api(2026-11-16 생성, 이미지 revision 라벨 42af81d06bf1d84bd51636543eeb5014acaebf7b)이며 vishue-pr233-postgres/vishue_db를 사용한다. 별도 G5 DB 15441과 동일하지 않다. 기본 vishue-api-1(2026-11-24 생성)은 vishue-postgres-0033/vishue_db를 사용한다. 이미지 라벨만으로 소스 commit 전체를 독립 검증했다고 주장하지 않는다.

실제 연결 DB의 읽기 전용 SQL 비교: PR233 DB는 products 8,533/shades 10,239, 기본 API DB는 products 9,035/shades 11,231이다. 원본 옵션은 각각 21,951행이다. 기본 DB에는 세잔느 A000000216419와 shade 4개가 있고 실제 영상 HTTP 응답에도 상품 링크가 나온다. PR233에는 상품이 없다. 롬앤 A000000201055의 makeup_zone은 PR233에서 NULL, 기본 DB에서 contour다. 앞선 '실제 롬앤 부위 누락'은 구버전 환경의 관측으로 범위를 정정한다. 부위 누락 시 검수 근거가 있어도 N02 추천이 탈락하는 모의 재현 자체는 별개로 유효하다.

실행 소스 파일 비교: 두 컨테이너 모두 현재 작업의 app/services/option_search_service.py가 없다. verified_video_product_repository.py도 현재 작업 bytes와 다르다. 따라서 기본 API도 최신 G8 검증 서버로 간주하지 않는다. 데이터 공급 경로 조사와 현재 구현의 종단 검증을 분리한다. 두 API의 실제 응답·관련 파일 존재/해시·이미지/DB 대상은 parent trace G8-RUNTIME-BASELINE-CORRECTION에 보존한다. 초기 파일 해시 조사에서 없는 옵션 서비스 파일을 읽다가 exit 1이 났으며, 존재 여부를 구분한 최종 수집으로 재실행했다.

C3 당시 계획(아래 C3-2에서 승인·구현 반영): 먼저 검수된 단계별 사용 근거가 있고 Catalog makeupZone만 비어 있을 때의 N02 판정 수정 범위를 제시했다. 이전 승인에 없던 owned_look_consultation_service.py 추가 수정은 승인 대기다. 판매 optionId와 선택적 AR shadeId 분리는 영상 매핑/API, 옵션 조회, N02, 카드·저장 계약을 함께 대조한 뒤 별도 파일 범위를 확정한다. 데이터 재수집·색상 임의 생성·기존 DB 덮어쓰기 없이 진행한다. C4는 실제 데이터 형태(옵션 존재/색 없음, 부위 NULL, 명시 옵션 충돌)로 검증한다.

이번 실행은 실제 컨테이너/HTTP/DB 조사이며 코드 회귀·실제 LLM·현재 G8 종단 검증은 미실행이다. DB 쓰기·배포 재빌드·commit/push/PR 없음. 외부 모델 호출 0회. 기존 미커밋 작업을 보존했다. 새 증빙은 Gitleaks 검사 후 append한다.

### ⑤ 게시 준비·회귀 재확인 — 2026-11-27

사용자 승인: 신규 trace 보안 검사 후 구현·테스트와 문서·증빙 두 커밋으로 feat/compound-consultation에 push. PR 생성 금지. 기존 기준 fc1b6279에서 구현 커밋 `2ee4d3df6b5958791d52be613a6d1fd03ba8daba`를 생성했다. 개발 미리보기의 필수 require 대상 sale-card-replay.json은 구현 커밋에 포함했다. 나머지 문서/증빙은 두 번째 커밋이다. 이 기록 시점 push는 대기 상태이며 실제 원격 확인 결과는 게시 보고로 구분한다. 최신 조회 develop은 991dd634dba33b99ceeb1c03de4dd8d921ce07f9이고 이번에 병합하지 않았다.

소스 61개 exact-byte manifest는 이전 실제 검증 이후 변경 없음. 커밋 전 npm run check의 타입/린트 통과, jest 병렬 1,334 pass/기존 AR 1 timeout(5초). 코드·timeout을 바꾸지 않고 npm test -- --runInBand로 107 suites/1,335 pass(75.689초). backend 두 서비스 모두 uv run ruff check . / uv run lint-imports 통과(각 3 KEPT).

API 전체 uv run pytest: 653 pass/45 skip/5 fail. catboost 선택 그룹 누락 3건, 기본 DB 인증 실패 1건, HTTP 하위 실행 25초 timeout 1건이었다. 기존 recommendation 그룹을 --frozen으로 사용해 test_ar_palette_ml.py 및 test_ingredient_http_integration.py를 재실행해 22 pass(55.30초). DB 사례는 현재 Catalog DB 15434의 read-only engine으로 단독 재실행해 1 pass(0.63초). 실패한 5건 모두 재검증 통과했으나 전체 API 단일 실행 통과로 표현하지 않는다. pyproject/lock 변경 없음. 챗봇 전체 1,526 pass/106 skip(85.50초). skip된 실제 연결 검사를 통과로 기록하지 않는다. 이번 게시 검사 모델 호출 0회.

보안: 신규 trace 14행 JSON 확인, 비어 있지 않은 인증정보 필드/개인키 헤더 0. 이메일 형태 67건은 모두 Python 데코레이터 코드였다. Gitleaks 8.30.1/저장소 설정/빈 ignore로 게시 대상 83파일 통과. 기존 Git 이력은 CI 조건(--full-history --diff-filter=tuxdb)과 저장소 fingerprint ignore로 666 commits/63.50MB 통과. 공용 보안 설정 변경 없음. 중간 사용량 한도로 자동 승인 검토가 실행되지 못했으며, 재개 지시 후 같은 이력 검사가 정상 실행됐다. 우회 실행하지 않았다.

원본 명령/시각/결과: reports/g8/parent의 g8-publish-* 로그·JUnit과 publish-validation.json, 신규 append trace 참조. 임시 파일 생성 권한 실패는 정상 권한 실행으로 재시도했다. 현재 전체 단계는 여전히 ⑤ 협력 완성(D 상세·장바구니 부분 실제 검증), Expo Go·로그인 상담 종단·E01/B01·범용 재계획/취소/재개·⑥ 전체 통합·⑦ PR 인계는 남아 있다.

### ⑤-D 판매 optionId 상세·장바구니 연결 — 2026-11-27

전체 순서는 ①→②→③→④→⑤ 협력 완성→⑥ 통합 검증→⑦ PR 인계다. 현재 A 공통 부모/후속 계약 부분 구현, B 3개 룩·보유품 범위 실제 검증, C 검수 조건/판매 옵션/AR 분리, D 이번 상세·장바구니 연결 완료 및 부분 실제 검증, E E01/B01·범용 재계획·취소/재개 후속이다. G8/N02 전체 완료가 아니다.

기준 feat/compound-consultation / fc1b6279e2a8cca3b899dd255aa8a1ee4156b459 위 미커밋 변경. 원격 develop 재조회 없음. 기존 변경을 보존했으며 commit/push/PR 없음. 승인된 파일 범위와 추가 승인된 __tests__/useArRouteSelection.test.tsx, __tests__/chatUiPreview.test.tsx만 수정했다. 변경 소스 목록·정확 바이트 해시·tracked diff는 이번 trace/증빙에 남긴다.

구현: 별도 상품 판매 옵션 API/서비스/스키마, 소속·활성 조회, 옵션 이미지 유형·기록 가격·AR 연결 독립 응답. N01/N02 카드와 상세 경로 optionId 전달. 장바구니 옵션별 분리·동일 옵션 합산·기존 저장소 복원. 가격/이미지 없음을 대표 값으로 채우지 않음. 판매 옵션을 포함한 혼합 장바구니 결제 제한(버튼·직접 checkout·주문 생성 핸들러), 기존 결제 확인 경로 보존. 옵션 미지원 비교/장바구니 추천은 제한한다. 정책/설정 상세는 SPEC의 같은 날짜 계약을 따른다.

모의 검사:
- 최초 관련 앱 검사 74 pass/3 fail은 기대값 수정 중 일반 shade 선택 콜백까지 optionId를 기대한 실수였다. 범위를 고쳐 재실행했다.
- 앱 전체 첫 검사 1,328 pass/7 fail(107 suites 중 2 fail). 기존 미리보기 모의 useLocalSearchParams 누락 1건, 새 상세 조회 훅 useProductOption 모의 누락 6건. 사용자 추가 승인 후 모의 설정만 보완했다. 최초 명령 npm run check -- --runInBand는 npm 경고와 함께 jest 병렬로 실행돼 순차 실행이라고 기록하지 않는다.
- 보완 후 npm test -- --runInBand: 107 suites / 1,335 pass, 64.437초. 이후 최종 가격 기준 enum·담기 상태·조회 오류 처리 보완에 대해 관련 8 suites / 91 pass, 7.897초 재확인. 최종 npm run typecheck 및 npm run lint 통과. 원본 g8-sale-option-jest-final.log / g8-sale-option-final-focused.log / typecheck·lint 로그.
- API ruff check 전체 및 lint-imports 3 KEPT, 관련 test_product_options/test_option_search/test_verified_video_product_links 59 pass. 첫 회귀는 임시 폴더 접근 오류로 57 pass/2 setup error였고 전용 basetemp로 59 pass. 최종 XML g8-sale-option-api-final.xml(0.58초). 초기 uv 캐시 권한 오류도 있었고 승인된 로컬 실행으로 해결했다.
- 정확 옵션 경로·옵션별 합산/분리·version1 재수화·가격 UNKNOWN·미연결 AR·checkout 혼합 장바구니 차단·기존 구매/AR 회귀를 포함한다. 테스트 구현/저장 mock을 실제 PG나 실제 결제로 기록하지 않는다.

실제 조회: 현재 소스 API 19831, 읽기 전용 vishue-postgres-0033/vishue_db(15434). 기존 실행 스크립트의 read-only session override 사용, DB 쓰기 없음. sale-option-live.json에 최초/최종 두 실행 시각과 5개 요청/응답을 보존했다. A000000162667-012 17,000원/arShadeId null, A000000183683-004 11,900원/arShadeId 06, A000000180532-023 23,800원/arShadeId null. 모두 color_chip 자료. 다른 상품 소속 옵션과 없는 옵션은 404. 가격 기준은 collected_snapshot이며 실제 실시간 가격 검증이 아니다. 데이터 근거는 응답별 observedAt/sourceUrl과 기존 DB 기준으로 구분한다.

실제 앱: Aside skill/CLI 지속 REPL, 390×844 웹. 과거 실제 상담 응답 재생 카드→상품 보기 클릭의 URL에 optionId=A000000162667-012 유지. 상세 07 웜 베이지·발색 참고 이미지·17,000원·기준일 표시, AR 버튼 없음. 담기 클릭 후 cart로 전체 페이지 이동/재로드해 동일 옵션·수량 1 복원, 주문 버튼 disabled. 장바구니의 상세 보기 클릭도 같은 optionId 유지. 최종 소스 서버 재시작 후 상세/장바구니 재로드 재확인. 인증 없는 로컬 브라우저 저장이며 실제 사용자 로그인 상담·G7 종단을 새로 검증한 것이 아니다. 모델 설정 not_used, 실제 호출 0회. 원본 snapshots는 sale-option-browser.json. 첫 ref는 언어 복원 후 stale이 되어 새 snapshot으로 재시도했다. screenshot은 CDP 30초 timeout으로 실패했고 PNG 증빙 없음. DOM상 표시와 이미지 URL 계약만 확인했으며 픽셀 품질 검증으로 기록하지 않는다.

남은 항목: Expo Go 실기기, 변경 후 로그인 상담→G7→카드 종단, 옵션 주문/결제 서버 계약(이번 범위 제외), 상품 이미지 자체의 육안 품질, E01/B01·범용 재계획·취소/재개, 전체 G8 통합 평가와 사람 검토. 다음 우선순위는 D 실기기/실제 상담 확인 및 E 협력 잔여 범위 정리. 사용자 추가 판단 현재 없음. 보안: Gitleaks 8.30.1/빈 ignore/--redact로 변경·신규 82개 파일 검사 exit 0, 신규 trace도 별도 scan 통과 후 append. source manifest 61개와 tracked diff/untracked 원문을 보존했다. WSL Git은 Windows worktree 포인터를 해석하지 못해 파일 목록은 Windows Git으로 수집하고 WSL에서는 같은 파일을 검사했다. 보안 로그 sale-option-security.log.

### ⑤-B/D 추가 검증: 다른 룩·보유품·실행 앱 — 2026-11-27

이번 추가 변경 범위는 승인받은 app/chat-ui-preview.tsx, backend/chatbot/tests/test_g8_owned_look.py, 이 문서와 reports/g8/parent/ 증빙이다. feat/compound-consultation / fc1b6279e2a8cca3b899dd255aa8a1ee4156b459 위 미커밋 변경이며 기존 사용자·G8 변경을 보존했다. commit/push/PR 없음. 원격 develop은 이번에 재조회하지 않았다.

앱 개발 전용 경로 /chat-ui-preview?g8=sale에 앞서 실제 Catalog로 생성한 응답의 판매 옵션 카드 재생을 추가했다. 기본 미리보기 동작과 production Redirect를 유지한다. 실제 상담·인증·모델 호출은 이 화면에서 하지 않는다. 화면의 상품 보기 버튼은 실제 앱과 같은 productHref(id, shadeId, undefined, true)를 사용한다. 재생 자료는 sale-card-replay.json이며 실사용자 대화가 아닌 검증용 예시다.

확장된 실제 Catalog 검증: kWI7_DkDjZ0(청초 물복숭아 메이크업)의 oy-a000000183683 / A000000183683-004와 EiYeC-hlMNQ(서늘한 냉미녀 메이크업)의 oy-a000000180532 / A000000180532-023. 각 룩에서 미보유면 해당 옵션 추천, 동일 옵션 보유면 추가 추천 제외·적용 기억 표시를 확인했다. 립 룩에서는 다른 보유품 oy-a000000158896을 같은 부위 활용 후보로 안내하되 substitutionStatus=unverified, 자동 대체·동일 표현 보장·추가 구매 추천 없음도 확인했다. Catalog는 current-source 실제 HTTP/DB read-only, 보유 기억은 합성 동의 fixture, 모델은 미사용(실제 외부 호출 0)이다. 따라서 실제 사용자의 기억·인증 종단 검증이라고 하지 않는다.

실행 원본: C:/Users/playdata2/AppData/Local/Temp/g8-other-looks.xml (2026-11-27 12:40:04 KST, 2 tests/5 cases 통과, 42.169초), g8-other-looks-mock.xml (12:41:34 KST, 57 통과·4 skip, 0.533초). 첫 실행은 저장소 루트에서 backend 명령을 실행해 ruff 미발견/테스트 미수집으로 실패했고 올바른 chatbot 위치에서 실행했다. ruff check·lint-imports 3 KEPT, 앱 typecheck/lint 통과. 카드/대화 스토어 51 tests는 최초 기존 사례 1건의 5초 timeout 후 설정을 바꾸지 않고 재실행해 51 통과(4.167초, g8-other-card-tests.log). 전체 G8 평가는 재실행하지 않았다.

브라우저 환경과 구분: 기존 Chrome 검증은 URL 판별 안전장치로 중단되어 완료 처리하지 않았다. 이후 Aside Windows 창에서 실제 카드 화면과 마우스 상품 보기 → 상품 상세 이동, 스크롤·스크린샷이 확인됐다. 직접 브라우저 탭 연결은 당시 목록에 없었고 사용자 지적 후 로컬 aside-browser skill과 PATH 밖 CLI를 발견해 전용 REPL 검증으로 전환했다. Aside skill 경로: C:/Users/playdata2/.agents/skills/aside-browser/SKILL.md; CLI 1.26.1126.1735. 사전 catalog 호출의 CORS 헤더 누락을 발견해 검증용 API 프로세스에만 CORS_ORIGINS=[http://localhost:19832]를 설정했다. 최종 실제 GET 200 및 Access-Control-Allow-Origin 일치를 확인했다. 저장소·운영 CORS 변경 없음.

발견한 미완료 사용자 경험: 카드의 실제 옵션명은 [단품] 07 웜 베이지다(이전 보고의 '월 베이지'는 잘못 옮긴 표기). 상세 URL은 /product/oy-a000000162667?requireShade=1이며 optionId가 없고, 상세 대표 이미지는 #11 애플 블러쉬를 표시한다. 상세는 상품 단위 참고 가격 17,000원과 공통 정보를 표시하며 07 옵션을 선택·유지하지 않는다. AR 색상은 0개여서 AR 적용/호수 선택 UI는 나타나지 않는다. 따라서 상품 상세 도달만 PASS이고 정확한 판매 옵션의 상세·장바구니 유지 및 옵션별 이미지/가격 연결은 미구현이다. 장바구니 담기·구매는 실행하지 않았다.

Aside 전용 최종 검증: aside guide 및 guide repl을 읽고 명시 프로필로 실행했다. listBrowserTabs는 빈 배열이어서 승인된 로컬 앱을 새 REPL 탭으로 열었다. 390×844 viewport에서 카드 snapshot → 실제 상품 보기 click → 상세 snapshot이 통과했고 reports/g8/parent/aside-verification.log에 원본 tree/diff와 URL을 저장했다. 전용 CLI page.screenshot은 CDP timeout으로 실패했고 이 실패를 성공으로 기록하지 않는다. 별도 Aside Windows 창에서는 실제 카드/상세 스크린샷이 이 대화의 도구 결과로 표시돼 상품 공통 이미지 #11과 카드 옵션 #07 차이를 육안 확인했다. 파일로 저장된 PNG는 없다. 모바일 폭의 웹 검증이며 Expo Go 실기기 검증은 아니다.

최종 증빙/보안: parent trace에 G8-N02-OTHER-LOOKS-ASIDE-UI 1행을 신규 Gitleaks 검사 후 append했다. 과거 trace 보존. 변경·신규 44개 파일 전체도 Gitleaks 8.30.1 / 저장소 설정 / 빈 ignore / --redact 검사 exit 0. 원본 로그 C:/Users/playdata2/AppData/Local/Temp/g8-aside-security.log. 검증 서버는 사용자 Aside 확인을 위해 유지했다.

다음 우선순위: 판매 optionId의 상품 상세·장바구니 공용 계약과 정확 옵션 표시/이미지/가격 범위를 정리한 뒤 수정 범위 승인을 받는다. 이후 실제 모바일 Expo Go 확인과 E01/B01·취소/재개 등 ⑤ 잔여 및 ⑥ 전체 통합 평가로 이어간다. 이번 검증으로 N02 또는 ⑤ 전체 완료를 선언하지 않는다.

### ⑤-C3-2/C4-2 및 D 일부: 검수 조건·판매 옵션·AR 분리 — 2026-11-27

사용자 승인 범위에서 API 옵션/영상 연결, N02 및 스타일 서비스·기억 registry, 응답 스키마·카드, 관련 테스트와 이 문서를 수정했다. 기존 공통 부모·레시피 작업은 보존했다. feat/compound-consultation HEAD fc1b6279e2a8cca3b899dd255aa8a1ee4156b459 위 미커밋 변경이다. 로컬 origin/develop 참조는 f5adb4e60202bdc4c98bdefe36669f96f90e9b55이며 이번 실행에서 원격 최신 조회는 하지 않았다. PR·commit·push·운영 반영 없음.

변경: 일반 가이드·연결 상품 조회를 검수 레시피 유무로 막던 조건을 제거했다. 영상 실제 사용법·대체품의 동일 표현·AR 적합성은 별도 근거로 판단한다. API는 활성 판매 옵션 소속을 검증해 catalogOptionId를 반환하고 optionScope에 AR shade가 없어도 정확한 옵션을 조회한다. N02는 이를 실제 다음 옵션 요청에 넘기며 optionName을 카드·저장 응답으로 연결한다. 성분 근거가 없으면 UNKNOWN, 옵션 자체가 없거나 소속이 다르면 추천 근거로 사용하지 않는다. 옵션이 있다는 이유로 성분 검수나 AR 색상이 생기지 않는다.

실제 검증: 현재 작업 소스 API를 임시 localhost:19831로 실행해 vishue-postgres-0033/vishue_db(15434)에 read-only 연결했다. 기존 8082/8080 이미지를 현재 소스로 간주하지 않았다. AG03mUj4vnY의 삐아 oy-a000000162667 / A000000162667-012 / [단품] 07 월 베이지를 대상으로 AR shade 없음·검수 recipe 없음 상태에서 추천 양성을 확인했다. 정상 ChatService의 3턴은 추천 → 향료 제외 추가(근거 부족으로 미확인·추천 제외) → 제외 조건 해제(다시 추천)다. 각 턴 O1/S1/N1/P1/V1/R1 입력·결과, 응답과 옵션 요청은 parent trace에 보존한다. 실제 모델 호출은 0회, 모델 설정 disabled/not_used이며 모의 모델의 응답을 실제 LLM 결과로 기록하지 않는다.

실제 저장: 별도 일회용 PostgreSQL vishue_chat_test를 로컬 임시 포트로 시작하고 chatbot alembic head 적용 후 같은 실제 Catalog 3턴을 ConversationService로 실행했다. 응답 ownedLookOptions와 재조회 displayPayload 일치, optionId 유지·shadeId 없음, styleRecipe 의미 일치와 후속 조건 복원을 확인했다. 인증은 mock, DB는 실제 일회용, Catalog는 실제 HTTP/기존 DB read-only, 외부 모델 호출 0회다. 생성한 임시 DB 컨테이너는 종료·자동 제거했다. 기존 DB 쓰기나 데이터 재수집은 하지 않았다.

검증 결과와 경위:
- API 전체 pytest: 646 통과·52 skip·1 실패. 실패는 기존 celebrity endpoint 테스트의 기본 DB 인증 설정 불일치다. 같은 테스트를 현재 DB 설정/read-only로 재실행하여 1 통과. 전체 단일 실행을 무실패였다고 기록하지 않는다. 판매 옵션/성분 UNKNOWN/동일 상품의 색상 없는 여러 옵션·생산 환경 합성근거 차단 신규 테스트 포함.
- chatbot 전체: 1,524 통과·103 skip. 이후 추가한 기억 및 보유 옵션 사례 집중 검사: 66 통과·2 skip. 정상 ChatService 실제 Catalog 3턴: 1 통과. 실제 Catalog+일회용 PG 3턴: 1 통과. 처음 PG 비교는 저장 시 null 생략과 응답의 명시 null을 그대로 비교해 실패했고 스키마 모델로 의미를 비교하도록 테스트 수정 후 재실행했다.
- 앱 npm run check: typecheck/lint 통과, 병렬 Jest 1,326 통과·2 실패. 같은 전체 테스트 npm test -- --runInBand 재실행 107 suites / 1,328 tests 통과(77.865초). 이후 typecheck/lint 재확인 통과. 최초 병렬 실패를 기능 결함 또는 시간초과로 확정하지 않는다.
- backend ruff check 및 lint-imports 양쪽 통과(각 3 KEPT), git diff --check 통과. 앱 카드/스토어는 모의 renderer·저장 테스트이며 Expo Go 실제 화면 검증이 아니다.

원본 XML/로그: C:/Users/playdata2/AppData/Local/Temp/g8-sale-{api,chat,final-focused,live-chatservice,live-pg-final}.xml, g8-sale-api-db-retry.xml, g8-sale-app-sequential.log. XML에 실행 시각과 개별 테스트 결과가 있다. trace G8-N02-SALE-OPTION-AR-SEPARATION은 소스 exact-byte manifest, 미커밋 diff, JUnit 요약 및 실제 입력/결과를 보존한다. 데이터 배포 버전 필드가 없어 실제 응답과 sourceVersion을 증거로 남기며 별도 데이터 릴리스를 확인했다고 하지 않는다.

보안: 신규 trace는 Gitleaks 8.30.1, 저장소 .gitleaks.toml, 빈 ignore, --redact 검사 통과 후 1행 append했다. 과거 trace는 변경하지 않았다. 최종 변경·신규 41개 파일 전체도 같은 설정/빈 ignore 검사 exit 0 (C:/Users/playdata2/AppData/Local/Temp/g8-sale-security.log). 신규 증빙의 소스 37개 해시가 현재 파일과 모두 일치한다. 이번 검증용 API 프로세스도 종료했다.

남은 일: 실제 앱 시각/상세 이동 확인, 옵션 자동 선택(이번 변경은 옵션 표시와 상품 상세 연결), 다른 룩과 보유 대체품 사례 확대, N01/N02 공통 부모의 범용 재계획·중단/재개, E01/B01 및 전체 ⑥ 평가. ⑤ 전체 완료 아님. 사용자 추가 판단은 현재 없음.

### ⑤-C3-1/C4-1: N02 부위 NULL 보완 완료 — 2026-11-27

사용자의 후속 승인으로 owned_look_consultation_service.py, test_g8_owned_look.py 및 기존 SPEC/WORKLOG/parent trace를 갱신했다. HEAD fc1b6279e2a8cca3b899dd255aa8a1ee4156b459, feat/compound-consultation의 기존 미커밋 변경을 보존했다. 원격 develop 최신 상태는 재조회하지 않았다.

최종 상품 판정에서 Catalog makeupZone이 NULL일 때만 검수된 단계별 productUsages를 보조 근거로 허용한다. verified recipe/evidence, 상품·호수 일치, 유효 stepOrder와 같은 단계 zone, 비어 있지 않은 개별 근거·출처가 모두 필요하다. 기존 Catalog 부위가 다른 값이면 허용하지 않는다. 후보 재조회에서 정확한 호수가 사라지거나 옵션 조건 검증이 실패해도 선택하지 않는다. AR eligibility는 변경하지 않았다. 새 설정·제한값은 추가하지 않았다.

모의 검증 7개 조합은 기존 복수 부위 미확인/명확한 부위/검수 연결 양성에 NULL+근거 양성, NULL+근거 없음, 명시 부위 충돌, 재조회 옵션 소실을 추가했다. 유효 근거와 NULL 조합에서는 추천이 유지되지만 해당 상품의 AR은 false다. 검증한 전문 작업 입출력·응답은 trace mockCases에 보존한다. API 생성 합성 응답은 이전 g8-usage-api-pass.xml을 G8_RECIPE_API_JUNIT으로 재생했으며 새 실제 API 검증이라고 부르지 않는다.

실제 데이터 기준: 현재 작업 디렉터리 backend/api/app/services/style_look_service.py를 로드하고 기본 API와 같은 vishue-postgres-0033/vishue_db(호스트 127.0.0.1:15434)에 SQLAlchemy 읽기 전용 연결했다. default_transaction_read_only=on, statement_timeout=10000으로 실행했다. 현재 StyleLookService/VerifiedVideoProductRepository/CatalogRepository가 반환한 AG03mUj4vnY 및 표본 상품을 보존했다. 롬앤 contour/6 shades, 삐아 NULL/0 shades, 세잔느 highlighter/4 shades, 키스미 brow/1 shade를 확인했다. 현재 소스의 대상 영상 recipe는 없음이다. 이것은 현재 소스→실제 DB 조회 검증이며 현재 HTTP 서버 배포, 실제 검수 레시피 N02 양성, PG 대화 저장 검증은 아니다. 자격증명은 컨테이너 설정에서 메모리로만 전달하고 출력/증빙에 넣지 않았다.

검사: 집중 55 통과·1 skip(g8-zone-fallback-focused.xml), 최종 챗봇 전체 1,523 통과·102 skip/41.31초(g8-zone-fallback-all.xml). ruff check, lint-imports 3 KEPT, 앱 npm run typecheck/lint 통과. XML 및 실제 DB 조회 g8-current-source-db.json은 C:/Users/playdata2/AppData/Local/Temp/ 아래에 있다. parent trace G8-N02-REVIEWED-ZONE-FALLBACK에 실행 시각·명령·XML 해시, 최종 소스 21개 exact-byte manifest와 diff, 모의/실제 DB 증거를 구분해 저장했다. 신규 trace는 Gitleaks 8.30.1/빈 ignore 검사 후 append했다.

미실행: 실제 N02 양성, 실제 LLM, 최신 변경의 G7 PG 저장·복원, 앱 시각 확인, 사람 검수. 외부 모델 호출 0회. API 코드 변경/DB 쓰기/레지스트리 등록/commit/push/PR 없음. C3-2 판매 옵션과 AR shade의 분리는 아직 미구현이며 이번 보완으로 해결됐다고 표시하지 않는다. 다음은 영상 매핑→판매 옵션 조회→N02→응답·카드·저장 전체의 optionId 중심 계약과 수정 파일 범위를 확정하는 작업이다.

최종 보안 검사: 변경·신규 25개 파일을 Gitleaks 8.30.1/빈 ignore/--redact로 검사해 exit 0. 로그 C:/Users/playdata2/AppData/Local/Temp/g8-zone-fallback-security.log. 신규 trace의 소스 21개 해시가 현재 bytes와 모두 일치하고 git diff --check 통과했다.

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

## N02 정상 API·실제 PG 경계 검증 — 2026-11-26 13:23 KST

전체: ① 설계 → ② 기준·계약 → ③ 실행 구조 → ④ 첫 복합 상담 → **⑤ 협력 완성(N02 첫 연결의 영속 검증)** → ⑥ 통합 검증 → ⑦ PR 인계. 기준 HEAD 09d7f02001b7cf1374af2e03523587f50ea0b24b, develop 통합 기준 f5adb4e. 사용자 승인 범위에서 test_g7_memory_api_pg.py, reports/g8/n02/trace.jsonl 및 기존 두 설계·작업 문서를 수정했다. 서비스 코드는 변경하지 않았다. 미커밋이며 push·PR 없음.

새 격리 PG는 WSL vishue-g5의 /tmp/g8-n02-validation-20261126, localhost 전용 56947/vishue_chat_test다. 기존 서비스 DB와 분리해 initdb, 기존 alembic upgrade head 및 app.jobs.init_chat_checkpoints를 실행했다. 이전 임시 DB 경로 재사용은 확인되지 않아 새 환경을 사용했다. 합성 인증 verifier와 합성 상품·룩만 사용했다.

검증 경로: 일반 상담 생성 → 상품/호수 선택 → 명시적 기억 요청 → 제안 승인 → 별도 일반 상담 생성 → select_look → 정상 /api/chat N02 실행 → 답변/상품/기억 참조 저장 → 동일 요청 재전송 → 소유권 차단 → 후속 턴 → 기억 사용 거부 → 룩 화면 직접 진입 경계. 이전 테스트처럼 서버 기억을 요청 객체에 직접 주입하지 않고 기존 G7 저장·복원 경로를 실행했다. 립 보유 대조 후 블러셔만 추가 조회, 위조한 클라이언트 룩 대신 서버 룩 사용, 재전송 추가 작업 0회, 다른 사용자 404를 확인했다.

실행 명령: backend/chatbot에서 UV_PROJECT_ENVIRONMENT를 기존 G7 검토 venv로, TEST_CHAT_DATABASE_URL을 위 격리 DB로 지정. uv run --frozen python -c에서 WindowsSelectorEventLoopPolicy를 설정하고 pytest.main(['-q','-p','no:cacheprovider','tests/test_g8_owned_look.py','tests/test_g8_compound_consultation.py','tests/test_g7_memory_api_pg.py::test_n02_consented_inventory_selected_look_persistence_and_replay','tests/test_g7_memory_api_pg.py::test_consent_ownership_idempotency_and_redaction','--tb=short','-o','junit_family=legacy','--junitxml=<local-temp>/g8-n02-final.xml']) 실행. 13:22~13:23 KST 최종 결과 69 통과/3.14초. 시작 시각은 분 단위 관측값이다. ruff check . 및 lint-imports(3 KEPT), npm run typecheck, npm run lint 통과. 전체 앱 테스트·전체 백엔드는 이번 테스트 전용 변경에서 재실행하지 않았다.

초기 준비 오류를 구분한다: 모델 금지 대역을 기억 등록 준비에도 사용해 503이 발생했고 준비 단계만 FakeLlm으로 분리했다. 이후 상품명만 요청해 shadeId가 없었으며, 실제 계약에 맞게 정확한 호수명을 입력했다. 서비스나 조건 검사를 완화하지 않았다. 최종 테스트·기존 회귀가 통과한 실행만 최종 증거다.

신규 trace는 정상 경로에서 관측한 전문 작업 입력·결과·답변·상품과 소스 6개 exact-byte 해시, 미커밋 테스트 diff 해시, JUnit 해시를 포함한다. 모델 설정은 mock이며 N02 본 작업은 호출 금지 대역, 실제 외부 모델 호출은 턴별 0회다. 실제는 PostgreSQL 저장/복원이며 Catalog HTTP·실제 LLM·실기기·실사용자 인증은 NOT_RUN. g8_evidence.append_record의 Gitleaks 8.30.1·빈 ignore 검사 통과 후 새 trace에 저장했다. 기존 N01 trace는 변경하지 않았다.

남은 사용자 경험: 후속 턴에서 룩·보유 기억은 복원하지만 명시적 미보유('블러셔는 없어')는 저장되지 않아 다시 묻는다. 이를 N02 후속 완성으로 처리하지 않는다. subject=look의 직접 진입은 기존 G7 정책상 보유 기억을 소비하지 않는다. 다음은 N02 미보유 조건의 출처·상태·해제·목표 변경 계약을 구현 범위로 정리하고, 실제 Catalog 환경에서 동일 연결을 검증하는 작업이다. N01의 새 troubleshooting API는 일반 지식 근거이며 상품 사실로 승격하지 않는다는 경계를 확인했으나 아직 연결하지 않았다. N01/N02 전체·E01/B01·재계획/취소/재개·⑥ 전체 평가·⑦ 인계는 미완료다.

검증 종료 후 이번 전용 PG를 정상 종료했고 데이터·로그를 보존했다. 기존 서비스 DB는 변경하지 않았다.

## N02 미보유 조건 구현·실제 Catalog 연결 — 2026-11-26 13:45 KST

전체: ① 설계 → ② 기준·계약 → ③ 실행 구조 → ④ 첫 복합 상담 → **⑤ 협력 완성(N02 후속 조건)** → ⑥ 통합 검증 → ⑦ PR 인계. HEAD 09d7f02001b7cf1374af2e03523587f50ea0b24b와 통합된 develop f5adb4e 기준. 직전 미커밋 테스트·증빙을 보존하고 사용자가 승인한 후속 구현을 추가했다. commit/push/PR/배포는 하지 않았다.

변경: 신규 schemas/owned_look_context.py, schemas/chat.py 및 conversation.py의 내부 전달/저장 계약, services/conversation_context.py의 복원·최종 저장·룩 변경 무효화, services/owned_look_consultation_service.py의 사용자 명시 선언 유지/변경/해제, services/consultation_memory.py의 N02 후속 기억 선택, repositories/conversation_repository.py의 ownedLook 허용 필드, tests/test_g8_owned_look.py와 test_g7_memory_api_pg.py, 기존 두 문서와 N02 trace. 새 공용 채팅 응답 필드·DB migration·외부 모델 호출은 추가하지 않았다.

실제 PG 정상 경로에서 '블러셔는 없어' → 같은 조건 추천 → '블러셔는 이제 있어' → 개별 조건 해제 → 다시 미보유 → 전체 해제를 검증했다. 보유 립 대조 후 필요한 블러셔만 실제 다음 Tool 입력으로 전달되며, present/해제에서는 해당 추가 조회가 사라진다. 상품·호수 없는 present는 정확한 일치로 승격하지 않는다. 같은 요청 재전송은 추가 작업 0회, 다른 소유자는 404다. 기억 사용 거부·직접 룩 subject의 기존 제한을 유지한다. 별도 계약으로 룩 변경·선택 해제·레시피 변경·무관한 질문·질문형/인용/타인/실행 혼합을 확인했다. 일시 Catalog 실패에서도 기존 조건을 보존하고 해제를 처리한다.

실제 Catalog 검증은 기존 localhost:8082의 공개 GET만 사용했다. catalog 룩 0개, 영상 룩 73개, 검수 recipe 0개를 확인했다. 정확한 룩 연결 립/호수를 찾는 최초 opt-in 사례는 데이터 부족으로 1건 SKIPPED였다. 이 상태를 통과로 바꾸지 않고 별도 검증 목적을 명시했다: 실제 립 상품/호수와 실제 영상 룩을 각각 조회하되 둘의 대체 적합성은 주장하지 않고, 정상 API+PG에서 조건 유지·변경·해제와 evidence_missing을 검증한다. 이 별도 실제 경로는 최종 성공했다. 검수된 실제 룩에서 상품 추천 카드가 나오는 양성 검증은 BLOCKED(검수 레시피/정확한 룩 상품 근거 부족)다. 합성 Catalog의 양성 통과로 대체하지 않는다. 실행 중인 Catalog 서버의 소스 commit은 독립 확인하지 않았으며 응답 스냅샷 SHA256과 실제 식별자를 trace에 기록했다.

검증 환경: WSL vishue-g5 /tmp/g8-n02-state-20261126, localhost:56947/vishue_chat_test, PostgreSQL 17.12 (Ubuntu 17.12-1.pgdg24.04+1), 실제 PG 스키마는 기존 alembic 및 checkpoint 초기화 명령으로 생성. 합성 verifier/계정만 사용했다. N02 LLM은 mock 또는 호출 금지 대역, 실제 외부 모델 호출은 모든 턴 0회. 원래 서비스 DB와 Catalog 데이터는 수정하지 않았다. 검증 종료 후 이번 전용 PG를 정상 종료하고 데이터·로그는 보존했다.

최종 검증(소스 9개 실행 전후 exact-byte 해시 동일):
- 집중 81 통과/30.09초. backend/chatbot에서 기존 G7 venv를 UV_PROJECT_ENVIRONMENT로 지정, TEST_CHAT_DATABASE_URL을 격리 DB, G8_N02_LIVE_CATALOG=http://127.0.0.1:8082로 지정. uv run --frozen python -c에서 WindowsSelectorEventLoopPolicy 설정 후 pytest.main: -q -p no:cacheprovider tests/test_g8_owned_look.py tests/test_g8_compound_consultation.py tests/test_g7_memory_api_pg.py::test_n02_consented_inventory_selected_look_persistence_and_replay tests/test_g7_memory_api_pg.py::test_n02_live_catalog_pg_evidence_boundary tests/test_g7_memory_api_pg.py::test_consent_ownership_idempotency_and_redaction --tb=short -o junit_family=legacy --junitxml=<local-temp>/g8-n02-state-final.xml. JUnit 원본 실행 시각/해시와 속성 관측값을 trace에 연결했다.
- 전체 챗봇: 외부 연동 env 없는 별도 프로세스에서 uv run --frozen pytest -q -p no:cacheprovider --basetemp <새 GUID 임시 경로> --tb=short, 1,476 통과·101 건너뜀/38.71초. 실제 PG/Catalog 성공은 위 집중 실행과 구분한다.
- ruff check ., ruff format --check .(154 files), lint-imports(3 KEPT) 통과. npm run typecheck 및 npm run lint 통과. 앱 전체 Jest/실기기 표시·실사용자 인증·실제 LLM·전체 G8 평가는 이번에 NOT_RUN.
- 초기 구현에서 상태 변수와 부위 판정 변수 이름 충돌, 저장소의 새 필드 허용 누락으로 PG 503이 발생했다. 변수 분리와 ownedLook 한 필드 허용으로 수정했고 최종 PG 경로에서 재검증했다. 마지막 보유 기억 선택 범위를 N02 요청으로 좁힌 뒤 집중·전체를 모두 다시 실행했다. 이전 실행을 최종 소스 통과로 혼동하지 않는다.

증빙: reports/g8/n02/trace.jsonl 기존 1개 기록을 byte prefix 그대로 보존하고 신규 2개(모의 Catalog+실제 PG 양성, 실제 Catalog+실제 PG 근거 부족)를 추가했다. 전문 작업별 입력/결과, 응답·상품, 조건 유지·변경·해제, 턴별 모델 설정/실제 호출 수, 소스 9개 식별값과 JUnit 해시를 저장했다. 신규 기록은 g8_evidence.append_record의 Gitleaks 8.30.1 빈 ignore 검사 통과 후 append했다. 현재 3개 trace SHA256: ed48f9ed731143ce5ac8d02209528409d2fa1d3874bdf0e3b34538d69b6edf34. 기존 N01 증빙은 수정하지 않았다.

남은 범위: 검수된 실제 룩/상품 근거를 통한 추가 추천 양성, 일반 대체품 적합성·예산/성분 조건의 N02 연결, 더 넓은 후속 표현, 앱 표시와 사람 검토, N01 원래 들뜸 근거 보완, 공통 부모 재계획/취소/미완료 실행 재개, E01/B01 전체, ⑥·⑦. 이번 구현은 N02 후속 조건의 한 계약을 완성한 것이며 G8 전체 완료가 아니다. 현재 사용자 판단 필요 없음. 실제 양성 데이터가 준비되지 않은 항목은 BLOCKED로 유지한다.


## N02 예산·성분 조건과 대체품 계약 — 2026-11-26 14:20 KST

전체 ① 설계 → ② 기준·계약 → ③ 실행 구조 → ④ 첫 복합 상담 → **⑤ 협력 완성(N02)** → ⑥ 통합 검증 → ⑦ PR 인계. HEAD 09d7f02001b7cf1374af2e03523587f50ea0b24b, 통합 develop f5adb4e60202bdc4c98bdefe36669f96f90e9b55. 이전 승인 미커밋 변경을 보존했다. 이번에도 commit/push/PR/배포는 하지 않았다.

변경: services/owned_look_filters.py를 추가하고 schemas/owned_look_context.py, schemas/owned_look_consultation.py, services/owned_look_consultation_service.py, tests/test_g8_owned_look.py, tests/test_g7_memory_api_pg.py 및 기존 두 문서·N02 trace를 보완했다. 사용자 조건의 저장·변경·해제, P1→V1 실제 옵션 입력, 정확한 상품·호수 판정과 대체 적합성 미확인 계약이다. G7 저장 경계와 기존 미보유 선언을 유지한다. 같은 룩의 레시피 개정에서도 명시적인 구매 조건은 유실하지 않는다. 이름 길이 초과를 유효한 접미사로 잘못 파싱하지 않는 경계 테스트도 포함한다.

실제 연결: 기존 localhost:8082는 상품/룩 GET은 응답하지만 options/search가 404였다. 현재 HEAD의 API를 localhost:19829에 별도 실행했다. 최초 DATABASE_URL만 주입한 실행은 성분 매핑 설정이 없어 HTTP 200이나 옵션 결과 ERROR였으며 통과로 인정하지 않는다. 원본은 로컬 임시 g8-n02-live-filters-mapping-unset.xml이다. 이후 기존 .env.local의 INGREDIENT_MAPPING_PATH도 메모리에 전달하고 재시작했다. 설정 파일·Catalog 데이터는 변경하지 않았다. API DB 연결은 default_transaction_read_only=on, refresh=false, G5=false로 실행했다. API 소스 변경 없음. PostgreSQL 17.12, 매핑 pr233-reviewed-mapping.json SHA256 3f10755e88e78ee46f6c38b3337b34fe02c4abc6abe7edffbb1c60c9247a4a1f. 응답에 남은 rights_unverified 제한은 그대로 보존하며 기존 외부 전송 승인을 번복하는 의미로 해석하지 않는다.

실제 옵션 3회: 2만원 이하 → SUCCESS/ELIGIBLE, 1만원 이하+향료 제외 → PARTIAL/REFERENCE_ONLY(성분 UNKNOWN, 가격 MATCH), 성분 해제 → SUCCESS/ELIGIBLE. 실제 응답/effectiveRequest/근거/조회 범위는 trace에 보존했다. 이 실행은 실제 상품의 직접 옵션 계약 검증이며 검수 룩 양성을 뜻하지 않는다. 실제 영상 룩에 검수 레시피가 없어 룩 기반 추가 추천 양성은 여전히 BLOCKED다.

실제 PG: 이전 임시 DB 경로가 없어 시작 실패 및 503이 발생한 실행은 환경 실패로 분리했다. 새 격리 WSL vishue-g5 /var/tmp/g8-n02-filters-20261126, localhost:56947/vishue_chat_test에 기존 migration/checkpoint를 적용했다. 정상 ChatService/API 경로에서 합성 Catalog+실제 PG로 2만원/향료 제외 저장 → 예산만 1만원 변경(성분 유지) → 전체 상품 조건 해제를 확인했다. 별도 실제 Catalog+PG 경로는 근거 부족과 기존 미보유 상태 계약을 검증했다. 인증은 합성 verifier이며 실사용자 인증 검증은 아니다.

최종 소스 11개 exact-byte 식별값은 실행 전후 동일하다. 신규 trace 4개에 각 실행의 소스 manifest와 JUnit 원본 위치/해시/시각, 전문 작업 입력·결과·답변·상품을 기록했다. 기존 3개 기록 byte prefix를 그대로 유지했다. 모델 설정(mock/호출 금지)과 실제 외부 호출 0회를 구분한다. 실제 LLM 호출은 이번에 없었다.

최종 검증:
- 집중 91 통과/41.40초, JUnit 시작 2026-11-26T14:19:22.984181+09:00. backend/chatbot에서 기존 G7 venv를 UV_PROJECT_ENVIRONMENT로, TEST_CHAT_DATABASE_URL을 격리 DB로, G8_N02_LIVE_CATALOG=http://127.0.0.1:19829로 지정했다. uv run --frozen python -c에서 WindowsSelectorEventLoopPolicy 설정 후 pytest.main(['-q','-p','no:cacheprovider','tests/test_g8_owned_look.py','tests/test_g8_compound_consultation.py','tests/test_g7_memory_api_pg.py::test_n02_consented_inventory_selected_look_persistence_and_replay','tests/test_g7_memory_api_pg.py::test_n02_live_catalog_pg_evidence_boundary','tests/test_g7_memory_api_pg.py::test_consent_ownership_idempotency_and_redaction','--tb=short','-o','junit_family=legacy','--junitxml=C:/Users/playdata2/AppData/Local/Temp/g8-n02-filters-final.xml']). 합성 양성·실제 PG·실제 HTTP 범위는 trace의 catalogMode/postgresMode로 분리한다.
- 같은 최종 소스로 외부 연동 env 없는 별도 프로세스의 uv run --frozen pytest -q -p no:cacheprovider --basetemp <새 GUID 임시 경로> --tb=short: 1,485 통과·102 건너뜀/36.74초. 14:19 KST 실행. 건너뛴 연동을 통과로 세지 않는다.
- uv run --frozen ruff check ., ruff format --check .(155 files), lint-imports(3 KEPT) 통과. 앱 npm run typecheck와 npm run lint 통과. 앱 소스 변경 없음. 앱 전체 Jest/실기기 화면/실제 LLM/전체 G8 평가/사람 검토는 이번에 NOT_RUN.
- 마지막 재실행 전 샌드박스의 uv 캐시·임시 manifest 쓰기 권한 실패가 발생했다. 승인 범위의 로컬 검증을 권한 상승으로 재실행해 위 결과를 얻었다. 실패한 준비 명령은 통과로 세지 않는다.
- 신규 trace는 g8_evidence.append_record의 Gitleaks 8.30.1·빈 ignore 검사 후 추가했다. 현재 7개 trace SHA256 5fd0e811fb8b16d67b089ca6d0902cbf23f2b80a906e616ab1fdd910b0ecd700. N01 이력은 변경하지 않았다.

남은 사용자 경험: 검수된 실제 룩 데이터로 추가 추천 양성 및 다른 제품의 색·제형·사용법 대체 적합성 확인, 더 넓은 조건 표현, 앱 표시/사람 검토가 남았다. N01 원래 들뜸 설명 품질, 공통 재계획·취소·재개와 E01/B01 및 ⑥ 전체 평가도 미완료다. 다음은 검수 룩 근거 확보와 N02 종단 양성 검증이며, 데이터와 독립적인 E01/B01 회귀를 이어갈 수 있다. 사용자 판단 필요 없음.

최종 정리: 변경·신규 14개 파일 전체를 임시 디렉터리에 복사하여 Gitleaks 8.30.1 dir, 저장소 config, 빈 ignore, --redact로 검사했고 exit 0이다. git diff --check 통과. 이번 전용 API와 격리 PG를 종료했으며 기존 서비스는 유지하고 검증 DB·로그를 보존했다.


## N02 두 커밋 게시 준비 — 2026-11-26 14:28 KST

현재 단계는 ⑤ 협력 완성 중 N02다. 사용자 지시에 따라 구현·테스트를 d5942bf646868e508a50588a7256c7412d6e8bc4로 보존하고 이 문서·설계·신규 N02 trace를 별도 문서 커밋으로 준비한다. fetch로 확인한 원격 feat/compound-consultation은 4173f36658fb96086388971ceb927a651deb147b이며 원격 전용 변경 0개다. 기존 로컬 8ca23b3, f3fe8ab, 09d7f02와 develop 통합 이력도 이번 정상 fast-forward push에 포함된다. 공용 보안 설정 변경·force push·PR 생성·배포는 하지 않는다. 이 절은 push 전 기록이며 실제 원격 도달 SHA는 push 후 조회로 확인한다.

게시 전 재검증(14:24~14:28 KST): npm run check -- -- --runInBand --silent는 타입·린트 및 107 suites/1,325 tests 통과(146.419초). 변경 chatbot에서 기존 잠금 venv와 uv run --frozen ruff check ., lint-imports(3 KEPT), pytest -q -p no:cacheprovider --basetemp <새 GUID 임시 경로> --tb=short는 1,485 통과·102 건너뜀(45.67초). 테스트 대상은 d5942bf와 동일한 소스이며 직전 실제 연결 기록의 최종 11개 exact-byte 소스 해시도 모두 일치했다. 이번 게시 검증에서는 실제 Catalog/PG/LLM을 재실행하지 않았다.

신규 N02 trace 7건 전체에서 비어 있지 않은 인증정보 필드가 발견되지 않았다. 변경·신규 14개 파일을 임시 복사하고 Gitleaks 8.30.1 dir, 저장소 config, 빈 ignore, --redact 검사 exit 0을 확인했다. 기존 trace 3건과 신규 4건을 재작성하지 않았다. git diff --check 및 첫 커밋 staged 검사 통과. 실제 조건 UNKNOWN, 검수 룩 양성 BLOCKED, 실기기·전체 G8 미실행 상태는 유지한다.


## N02 조건 순서·검증 옵션의 응답/저장/카드 연결 — 2026-11-26

전체 ① 설계 → ② 기준·계약 → ③ 실행 구조 → ④ 첫 복합 상담 → **⑤ 협력 완성(N02 사용자 결과 연결)** → ⑥ 통합 검증 → ⑦ PR 인계. 작업/원격 기준 7b4b599ed585078bd54fac2b095f923ce942bff0, branch feat/compound-consultation, develop 통합 기준 f5adb4e. 이번 작업에서 원격 최신 develop을 다시 fetch하거나 통합하지 않았다. 사용자 승인한 조건 처리·가격 기준·미확인 문구와 옵션 전달 범위를 구현했다. commit/push/PR/배포 없음.

수정 범위: backend/chatbot의 services/owned_look_filters.py, owned_look_consultation_service.py, conversation_context.py, schemas/owned_look_context.py, chat.py, repositories/conversation_repository.py, tests/test_g8_owned_look.py 및 test_g7_memory_api_pg.py. 앱 types/index.ts, types/chatConversation.ts, store/chatConversationStore.ts, app/chat.tsx, components/chat/ChatProducts.tsx, lib/i18n 4개 사전, __tests__/chatProducts.test.ts·chatConversationStore.test.ts·chatScreen.test.ts. 기존 두 G8 문서와 reports/g8/n02/trace.jsonl을 갱신한다. 선택적 공개 ownedLookOptions 외 기존 API 응답·DB migration·AR 실행 계약 변경 없음.

조건 해제/설정을 등장 순서대로 적용한다. 전체 해제→새 예산/성분, 성분 설정→전체 해제, 반대 순서, 예산만 변경을 확인했다. 현재가 단독 요청은 옵션 조회 대상이며, 근거가 없으면 충족 추천하지 않는다. 다른 보유품은 상품 식별 미확인과 룩 대체 적합성 미확인을 구분해 설명한다.

공개 옵션 결과: 정확한 상품·호수·옵션 selections와 각 원본 batch의 요청/가격/조건 판정/근거/조회 범위 및 실패 상품을 보존한다. 여러 배치를 단일 요청으로 합치지 않는다. G7 displayPayload의 허용 필드와 nullable 근거를 보존해 저장·복원한다. 앱은 일반 상품 재조회 카드를 생략하고 정확히 일치하는 옵션의 검증 가격을 표시한다. 모의 카드 테스트에서 대표가격 5,900원 대신 판매 옵션 7,600원, 해당 호수 상세 진입, 잘못된 호수/현재가 배치 차단을 확인했다. 화면 라우트의 실제 계약은 shade이며 최초 새 테스트가 shadeId를 예상한 1건 실패는 테스트를 바로잡아 해결했다. 서비스 라우트를 바꾸지 않았다.

실제 연결 환경: 기존 전용 WSL PG /var/tmp/g8-n02-filters-20261126를 재사용했다. 최초 포트 미지정 시작은 기본 5432의 기존 서비스와 충돌해 실패했으며 기존 서비스에 영향 없이 localhost 56947로 다시 시작했다. DB vishue_chat_test, PostgreSQL 17.12. 실제 Catalog는 현재 HEAD와 동일한 API 소스, localhost 19829, 기존 .env.local의 DATABASE_URL/INGREDIENT_MAPPING_PATH를 메모리에만 사용했다. DB default_transaction_read_only=on, refresh=false, G5=false. 기존 매핑 파일과 데이터는 수정하지 않았다. 모델은 N02에서 호출하지 않으며 실제 외부 모델 호출 0회. 합성 인증/계정을 사용했다.

실제 API로 발견한 차이: 현재가 단독 요청은 Catalog에서 예산 상한이 없어 price check와 price를 반환하지 않으면서 ELIGIBLE일 수 있었다. 최초 검증에서 UNKNOWN price check가 있을 것이라는 기대가 실패했다(97 통과·1 실패). 이를 단순 기대 변경만으로 처리하지 않고 N02의 실제 현재가 근거 부재를 별도로 차단했다. 원본 API 결과는 그대로 보존하고 V1 제한·답변·선택 목록·앱 카드에서 현재가 충족으로 승격하지 않는다. 공용 Catalog 구현은 변경하지 않았다. 모의 Catalog에도 가격 검사 생략 동작을 재현해 추천이 비는 것을 검증했다.

최종 백엔드 검증: 98 통과/51.57초(집중, 실제 HTTP/PG와 모의 범위 분리), 전체 챗봇 1,492 통과·102 건너뜀/41.93초. ruff check ., ruff format --check .(155 files), lint-imports(3 KEPT) 통과. 최초 포맷 후 긴 줄/비교식 린트 2건은 수정 후 재검증했다. 최종 소스 20개를 실행 전에 고정하고 trace에서 exact-byte 해시로 식별한다.

집중 명령: backend/chatbot에서 UV_PROJECT_ENVIRONMENT=기존 g7-pr-review 잠금 venv, TEST_CHAT_DATABASE_URL=격리 PG, G8_N02_LIVE_CATALOG=http://127.0.0.1:19829. uv run --frozen python -c에서 WindowsSelectorEventLoopPolicy 설정 후 pytest.main(['-q','-p','no:cacheprovider','tests/test_g8_owned_look.py','tests/test_g8_compound_consultation.py','tests/test_g7_memory_api_pg.py::test_n02_consented_inventory_selected_look_persistence_and_replay','tests/test_g7_memory_api_pg.py::test_n02_live_catalog_pg_evidence_boundary','tests/test_g7_memory_api_pg.py::test_consent_ownership_idempotency_and_redaction','--tb=short','-o','junit_family=legacy','--junitxml=C:/Users/playdata2/AppData/Local/Temp/g8-n02-delivery-final.xml']). 전체 회귀는 실제 연동 env 없는 별도 프로세스의 uv run --frozen pytest -q -p no:cacheprovider --basetemp <새 GUID 임시 경로> --tb=short. XML의 정확한 시작 시각/해시는 신규 trace에 기록한다.

검증 범위: 실제 PG+모의 Catalog는 정상 ChatService에서 조건 순서·검증 옵션 공개 응답의 저장/복원·같은 요청 재전송 추가 호출 0회를 확인한다. 실제 Catalog 직접 옵션 5턴은 예산/성분 변경·전체 해제 후 예산 재설정·현재가 단독 요청의 실제 입력과 결과를 확인한다. 실제 Catalog+PG는 실제 상품/룩 근거 부족 보존을 확인한다. 합성 검수 룩의 양성을 실제 룩 양성으로 기록하지 않는다. 실기기 UI·실사용자 인증·실제 LLM·사람 검토·전체 G8 평가는 NOT_RUN, 검수 룩+정확한 상품/호수 근거가 필요한 N02 종단 양성은 BLOCKED다.

다음 작업: 실제 룩의 근거 확보와 종단 앱 검증, 공통 부모의 목표/작업/부족 입력/후속 제안 계약 및 N01/N02 어댑터 연결. 일반 대체품 적합성, N01 원래 상담 품질, E01/B01 전체, 취소·미완료 실행 재개는 남아 있다. 이번 변경으로 ⑤ 또는 G8 전체를 완료 처리하지 않는다.

최종 앱 검증: npm run typecheck 및 npm run lint 통과. npm test -- --runInBand --silent --json --outputFile=C:/Users/playdata2/AppData/Local/Temp/g8-n02-delivery-app-final.json: 107 suites/1,328 tests 통과, 113.416초. 최초 전체 앱 실행도 1,328 통과였으나 마지막 현재가 차단 수정 시점과 겹쳐 최종 증빙으로 사용하지 않고 고정 소스로 재실행했다. 별도 집중 162건도 통과했다. 원본 Jest 시작 시각/해시와 최종 소스 20개를 trace에 남겼다. 최종 백엔드 집중 시작은 2026-11-26T15:33:09.761918+09:00이다.

신규 trace는 실제/모의 backend 5건과 앱 자동 검증 1건 총 6건을 추가해 13건이다. 이전 7건의 byte prefix를 보존했으며 새 기록마다 Gitleaks 8.30.1 빈 ignore 검사를 통과했다. trace SHA256: 5bad16e6151011bc1c6521e97634b3fa731a09ef82a10b1af584f658320db496. 기존 환경 자격증명 값을 출력하지 않고 trace와 대조해 불포함을 확인했다. 매핑 파일 SHA256은 이전 기록과 동일했다. 검증용 API·PG는 종료했고 격리 DB·로그는 보존했다. 실제 모델 호출 0회이며 실기기 확인으로 기록하지 않는다.

최종 변경 파일 전체 23개를 Gitleaks 8.30.1 dir, 저장소 config, 빈 ignore, --redact로 검사하여 exit 0을 확인했다. git diff --check 통과. 현재 미커밋이며 push·PR 생성은 하지 않았다.


## N02 옵션 전달 보완 게시 전 검증 — 2026-11-26 15:42 KST

사용자 승인에 따라 구현·테스트·번역 20개 파일을 6399b2c367a5e9c5f45302fb1aa99dacd28ff20e로 보존하고 설계·작업 기록·신규 증빙을 별도 문서 커밋으로 분리한다. fetch한 원격 feat/compound-consultation은 7b4b599ed585078bd54fac2b095f923ce942bff0이며 시작 시 로컬과 차이 0개다. 이 절은 push 전 상태이며 게시 후 원격 HEAD를 별도 조회해 확인한다. PR 생성·강제 push·운영 반영 없음. 현재 단계는 ⑤ 협력 완성 중 N02이며 기존 미완료 항목을 유지한다.

게시 전 검사(15:39~15:42 KST): npm run check -- -- --runInBand --silent는 타입·린트·107 suites/1,328 tests 통과(119.052초). backend/chatbot에서 기존 잠금 venv를 UV_PROJECT_ENVIRONMENT로 지정한 uv run --frozen ruff check ., lint-imports(3 KEPT), pytest -q -p no:cacheprovider --basetemp <새 GUID 임시 경로> --tb=short는 1,492 통과·102 건너뜀(52.90초). 소스는 6399b2c와 같으며 신규 trace 6건의 20개 exact-byte manifest와도 모두 일치했다. 이번 게시 검사에서는 실제 Catalog/PG/LLM을 재실행하지 않았다.

신규 trace 6건의 인증정보 필드 검사와 환경 비밀값 대조에서 노출을 발견하지 않았다(값 자체는 출력하지 않음). 이전 7건의 byte prefix SHA256 5fd0e811fb8b16d67b089ca6d0902cbf23f2b80a906e616ab1fdd910b0ecd700을 유지했다. 변경 파일 23개 전체를 Gitleaks 8.30.1 dir, 저장소 config, 빈 ignore, --redact로 재검사해 exit 0을 확인했다. git diff --check와 구현 커밋 staged 검사 통과. 커밋 후 CI와 같은 HEAD 전체 이력 보안 검사를 통과한 경우에만 정상 push한다.

## 공통 부모 A–E 구현·검증 — 2026-11-26

전체: ① 설계 → ② 기준·계약 → ③ 실행 구조 → ④ 첫 복합 상담 → **⑤ 협력 완성(공통 부모 첫 연결)** → ⑥ 통합 검증 → ⑦ PR 인계. 원래 N01·성분 하위 사례·N02·전체 G8 완료는 각각 구분하며 이번에 완료로 승격하지 않는다.

기준: feat/compound-consultation, HEAD fc1b6279e2a8cca3b899dd255aa8a1ee4156b459. 시작 시 변경 없음. 로컬 origin/develop 및 기존 통합 기준은 f5adb4e60202bdc4c98bdefe36669f96f90e9b55이며 이번에는 fetch하지 않아 최신 원격 develop이라고 주장하지 않는다. 승인된 구현·증빙은 미커밋 상태로 남긴다. commit/push/PR/배포 없음. 개발 하위 에이전트 위임 없이 메인 에이전트가 수행했다.

수정: backend/chatbot/app/schemas/consultation_parent.py(신규), chat.py, conversation.py; services/consultation_parent_graph.py(신규), chat_service.py, conversation_context.py; repositories/conversation_repository.py; tests/test_g8_consultation_parent.py(신규), test_g7_memory_api_pg.py. 문서는 기존 SPEC/WORKLOG를 갱신하고 신규 reports/g8/parent/trace.jsonl 및 implementation.patch를 추가했다. 앱·Catalog API·공용 보안 설정·기존 N01/N02 trace는 수정하지 않았다.

A 계약: 부모의 목표·작업 상태·결과 참조·질문·plan version을 서버 스키마로 정의했다. B 연결: 기존 N01과 N02 전문 실행을 부모에 연결했으며 저장 책임을 중복하지 않는다. C 실행: 부모의 assess가 N02 결과를 G5의 구조화 참조 맥락에 연결하고 요청된 설명을 추가 실행한다. D 후속: 같은 룩의 단일 부위 질문을 저장·복원해 짧은 명시 답을 연결하고, 상품 중단→순서만 안내 및 레시피 변경→종속 지식 결과 무효화를 구현했다. E 검증: 아래 범위에서 실행했다. 임의 목표 전체 분해/자동 작업 제안 채택/중단 실행 재개(F)는 미구현이며 고정 역할 네 종류를 전체 Supervisor 완성으로 표현하지 않는다.

실제 PG: WSL vishue-g5의 기존 전용 /var/tmp/g8-n02-filters-20261126, localhost:56947/vishue_chat_test를 재사용했다. PostgreSQL은 실제, 인증·Catalog·G5는 모의다. 일반 /api/chat 경로에서 등록 동의된 립 + 선택 룩 → 블러셔 보유 질문·추가 설명 → “없어”의 부위 복원과 추가 추천 → “상품은 됐고 사용 순서만”의 카드 생략을 확인했다. G5 모의 호출은 첫 턴만 발생하고 외부 모델 호출은 매 턴 0회다. 기존 소유권·동의·재전송 테스트도 통과했다. 새 질문 문구를 단일 부위로 바꾼 후 기존 PG 기대 문구 1건이 실패해 기대 문구를 수정하고 재실행했다. 신규 3턴 자체는 이 실패 전에도 통과했지만 최종 집중 실행 전체가 통과하기 전에는 완료 증빙으로 쓰지 않았다.

모의 계약: 룩 레시피 설명을 변경하면 G5 경계의 referenceContext 실제 인자가 바뀐다. 지식 조회 실패 시 상품 결과를 보존한다. 예산만 변경하면 기존 설명 참조를 보존하고 지식 재호출을 생략한다. 레시피 내용이 달라지면 종속 결과를 superseded로 표시한다. 다른 룩/모호한 답/구버전 작업 결과 거부, 원래 N01 발화의 ChatService→부모 상황 질문 진입을 확인했다. 최초 Style 어댑터는 기존 함수의 (응답, ToolResult) 튜플을 처리하지 못했고, 순서 전용 턴에도 기존 상품 목록이 남는 문제가 있어 수정 후 통과했다. 원래 N01 진입 테스트의 locale 누락도 ko로 바로잡았다. 실제 LLM 품질 검증은 아니다.

최종 집중 실행: 2026-11-26 16:09:02 KST 시작, **104 통과·1 건너뜀, 9.855초**. backend/chatbot에서 UV_PROJECT_ENVIRONMENT를 기존 g7-pr-review 잠금 venv로, TEST_CHAT_DATABASE_URL을 위 격리 DB로 지정했다. uv run --frozen python에서 WindowsSelectorEventLoopPolicy를 설정하고 pytest.main으로 test_g8_consultation_parent.py, test_g8_owned_look.py, test_g8_compound_consultation.py, test_g7_memory_api_pg.py의 test_n02_consented_inventory_selected_look_persistence_and_replay 및 test_consent_ownership_idempotency_and_redaction을 실행했다. 옵션은 -q -p no:cacheprovider --tb=short --show-capture=no -o junit_family=legacy. 원본 XML은 C:/Users/playdata2/AppData/Local/Temp/g8-parent-final-pass.xml이며 전체 명령·시각·SHA·9개 최종 소스 exact-byte manifest·전문 작업 입력/결과·답변은 신규 trace에 보존했다. 미커밋 tracked diff는 implementation.patch, 신규 소스 식별값은 manifest에 있다.

전체 챗봇 회귀: 실제 연동 env 없는 프로세스에서 uv run --frozen pytest -q -p no:cacheprovider --basetemp <새 GUID 임시 경로> --tb=short --junitxml=C:/Users/playdata2/AppData/Local/Temp/g8-parent-all.xml, **1,500 통과·102 건너뜀/53.68초**. 이후 바뀐 코드는 없고 건너뛴 PG 테스트의 질문 문구 기대만 수정되어 위 최종 집중 실행으로 확인했다. xunit2/record_property 경고 15건이 있어 최종 집중 증빙은 legacy로 생성했다. ruff check/format check(158 files), lint-imports(3 KEPT), 앱 npm run typecheck 및 npm run lint 통과. 앱 소스 변경 없음. 이번 앱 전체 Jest/실기기 UI/실제 G5·LLM/전체 G8 평가/사람 검토는 NOT_RUN이다.

실제 룩 준비: 16:02:41 KST localhost:8082 HTTP 조회로 catalog 룩 0, 영상 룩 73, 반환 검수 레시피 0을 확인했다. 서버 소스 및 데이터 릴리스 버전은 미확인이다. 로컬 검토 원본 24건은 승인/검토자/룩 연결 모두 0건이다. 저장소 API StyleLook에는 recipe 필드가 없고 정적 목록 서빙이며, 기존 apply_look_recipe는 AR geometry 반영 작업이다. 따라서 과거 “검수 룩 데이터 부족”을 **자료 검수·상품 호수 연결 부족 + 상담 레시피 API 서빙 계약 공백**으로 구체화한다. 데이터나 승인 상태를 임의 생성하지 않았다. 실제 검수 룩 종단 양성은 BLOCKED이며 모의 양성으로 대체하지 않는다.

새 trace는 credential-shaped 필드 검사를 하고 g8_evidence.append_record의 Gitleaks 8.30.1/저장소 config/빈 ignore/--redact 검사를 통과한 뒤 기록했다. trace SHA256은 1f3f8d22e260df8b682b40a66feeab4632365fd89de7c4a874ce4dc7ddd64391이다. 과거 이력은 재작성하지 않았다.

다음 작업: 실제 룩 1개의 단계·출처·검수자·상품/호수 근거 준비와 상담 레시피 API 서빙 연결을 분리해 진행하고, 그 후 실제 G5/Catalog/PG/앱 양성을 확인한다. 병행 가능한 범위는 부모의 더 넓은 목표 변경·전문 작업 제안 계약 및 E01/B01이다. 현재 즉시 필요한 사용자 판단은 없으며 실제 자료 검수자의 승인 사실은 근거를 확보하기 전 주장하지 않는다.

최종 정리: 변경·신규 13개 파일 전체를 임시 복사하여 Gitleaks 8.30.1/빈 ignore/--redact로 검사했고 exit 0이다(로컬 원본 C:/Users/playdata2/AppData/Local/Temp/g8-parent-security.log). 최종 검증 manifest의 소스 9개가 모두 현재 bytes와 일치하며, 기존 N01·N02·first-compound trace는 HEAD bytes와 일치한다. git diff --check 통과. 이번에 시작한 전용 PG만 정상 종료했고 DB 파일은 보존했다.

## 상담 레시피 API 계약·N02 전달 검증 — 2026-11-26

전체 ① 설계 → ② 기준·계약 → ③ 실행 구조 → ④ 첫 복합 상담 → **⑤ 협력 완성(레시피 서빙 연결)** → ⑥ 통합 검증 → ⑦ PR 인계. 기준 HEAD fc1b6279e2a8cca3b899dd255aa8a1ee4156b459/feat/compound-consultation, 기존 develop 통합 f5adb4e. 원격 fetch 없음. 이전 공통 부모 미커밋 변경을 보존하고 이번 승인 범위를 추가했다. 커밋·push·PR·배포 없음.

변경한 7개 코드/자료 파일: backend/api/app/schemas/consultation_recipe.py(신규), schemas/style_look.py, repositories/style_look_repository.py, catalog_data/reviewed_style_recipes.json(신규 빈 목록), backend/api/tests/test_style_looks.py, types/index.ts, backend/chatbot/tests/test_g8_recipe_delivery.py(신규). 기존 SPEC/WORKLOG 및 parent trace만 갱신했다. API 라우트·DB·AR geometry·기존 영상 메타 원본은 변경하지 않았다.

API는 별도 검수 레지스트리와 같은 lookId를 연결한다. 미승인·검수자/근거 누락·잘못된 단계 순서·다른 룩·합성 자료·중복 버전은 제공하지 않고 기존 룩은 유지한다. 챗봇이 이미 지원하는 ReviewedRecipe와 같은 응답 계약이다. 정상 API 라우트가 만든 JSON을 다른 프로세스의 챗봇 검증에 넘겨, 실제 CatalogClient 파싱→N02 레시피/정확한 호수→부모 결과까지 확인했다. HTTP 전송·Catalog 데이터·검수자·상품은 모의이며 실제 모델 호출 0회, 이번 PG 저장/실기기/실제 G5 검증은 NOT_RUN이다.

실제 자료 준비: 기존 검토 자료 24건에 승인/검수자/룩 연결이 없음을 유지한다. 현재 영상 목록과 교집합인 뉴트럴 바닐라 메이크업(1qj6SactPVM, 초안 9단계) 등은 준비 후보일 뿐 원문 영상 검토·단계 설명·상품/호수 증빙을 확보한 완료 자료가 아니다. 실제 영상은 이번에 시청하지 않았다. 서빙 레지스트리는 0건이며 합성 fixture를 실제 자료로 등록하지 않았다. 실제 양성 BLOCKED 원인 중 API 코드 공백은 보완됐지만 데이터/사람 검토 공백은 남는다.

검증:
- API 집중 12 통과, 16:27:23 KST 시작. 원본 C:/Users/playdata2/AppData/Local/Temp/g8-recipe-api-pass.xml. uv run --frozen pytest -q -p no:cacheprovider tests/test_style_looks.py --basetemp <새 임시 경로> --tb=short -o junit_family=legacy --junitxml=<위 경로>.
- 챗봇 집중 57 통과·1 건너뜀, 16:28:09 KST 시작. G8_RECIPE_API_JUNIT에 위 API XML을 전달하고 test_g8_recipe_delivery.py, test_g8_consultation_parent.py, test_g8_owned_look.py 실행. 원본 g8-recipe-chatbot.xml(같은 임시 디렉터리). 마지막 파일의 opt-in 실제 Catalog 검사는 미실행으로 건너뛴다.
- 챗봇 전체 1,501 통과·102 건너뜀/48.79초. uv run --frozen pytest -q -p no:cacheprovider --basetemp <새 임시 경로> --tb=short --show-capture=no -o junit_family=legacy --junitxml=<g8-recipe-chat-all.xml>. 같은 API XML을 전달했다.
- API 전체 638 통과·52 건너뜀·1 실패/88.42초. uv run --frozen pytest -q -p no:cacheprovider --basetemp <새 임시 경로> --tb=short --show-capture=no --maxfail=5 --junitxml=<g8-recipe-api-full.xml>. 실패는 test_celebrity_videos_endpoint_uses_client_contract의 기본 로컬 DB 인증 오류다. 기존 검증 설정을 메모리에만 읽고 read-only PG 연결로 해당 1건을 재시도했으나 localhost:15441 연결 거절로 실패했다(g8-recipe-api-db-retry.xml). API 전체 통과로 기록하지 않으며 DB 환경 복구 후 재검증이 남았다. 자격증명은 출력·파일 기록하지 않았다.
- API/챗봇 ruff check 및 lint-imports 각각 3 KEPT, 앱 npm run typecheck/lint 통과. 처음 API 응답 형식 검사가 DB 인증에 의존해 실패해, 승인된 test_style_looks.py 안에서 DB 없는 서비스 주입으로 계약 테스트를 분리했다. 별도 유명인 API 테스트는 수정하지 않았다. httpx TestClient deprecation 및 전체 API xunit2/record_property 경고는 기능 통과와 분리한다.

UV_PROJECT_ENVIRONMENT는 API의 기존 skin-conversation-api venv, 챗봇의 기존 g7-pr-review venv를 사용했으며 --frozen으로 실행했다. 최종 미커밋 소스 16개 exact-byte manifest와 tracked diff, 원본 XML 해시·시각, API JSON·전문 작업별 입력/결과는 parent trace의 G8-RECIPE-API-DELIVERY에 보존했다. 이전 parent trace 첫 기록의 bytes를 보존했으며 신규 기록은 Gitleaks 8.30.1/빈 ignore 검사를 통과한 뒤 추가했다.

다음: 실제 룩 한 개의 사람 검토 가능한 자료 준비, 레지스트리 등록 근거 확인, 실제 상품/호수와 Catalog→G7→앱 양성. 공통 부모의 범용 목표 분해·실행 취소/재개·E01/B01·⑥ 전체 검증은 여전히 후속 범위다.

최종 보안 확인: 이전 공통 부모 변경을 포함한 변경·신규 20개 파일 전체를 Gitleaks 8.30.1/빈 ignore/--redact로 검사해 exit 0을 확인했다. 로그는 C:/Users/playdata2/AppData/Local/Temp/g8-recipe-security.log. 검증 manifest의 소스 16개 모두 현재 bytes와 일치하며 git diff --check 통과. API 환경 실패는 해결되지 않은 상태로 유지한다.

## 실제 룩 준비 및 WSL 조회 경로 확인 — 2026-11-26

전체 ①→②→③→④→**⑤ 협력 완성: 실제 룩 검수 준비**→⑥ 통합 검증→⑦ PR 인계. HEAD/branch와 이전 구현 변경은 유지했다. 이번에는 코드·서빙 자료·승인 상태를 변경하지 않고 기존 WORKLOG/SPEC/parent trace에 조사 증빙만 추가한다. commit/push/PR 없음.

사용자가 주소 탐색·필요한 서비스 시작을 지시해 환경을 직접 조사했다. Windows localhost:8082/19829/15441의 접근 실패만으로 서비스 중단을 단정할 수 없었다. WSL vishue-g5 안에서 g5integration PostgreSQL 15441과 기존 Catalog 8082가 동작하고 HTTP 조회가 가능했다. 현재 코드의 임시 Windows API 19829도 읽기 전용 DB 설정으로 실행했으나 Windows→WSL 접속이 실패해 종료했다. 기존 WSL 서비스는 유지했으며 DB 초기화·설정 변경은 하지 않았다. Windows localhost 전달 문제 자체가 해결된 것은 아니다. Docker ps는 응답하지 않아 해당 조사 명령만 중단했다.

자료 비교: description-rules 초안 24건과 현재 영상 목록 73건의 교집합은 11건이다. 정적 CSV는 결정/검토자가 없는 과거 후보이며 실제 API의 확인된 연결과 구분했다. 실제 WSL Catalog에서 DiDEgRAin9g와 AG03mUj4vnY에 각각 정확한 호수 연결 1건을 확인했다. 전자는 3CE 화이트 컨실러, 후자는 롬앤 컨투어 그레이 쿨이다. 과거 CSV의 눈썹 상품 후보 호수는 확인된 연결이 아니며 검수 근거로 사용하지 않았다.

웹 도구는 YouTube 페이지를 가져오지 못했고 브라우저 도구는 초기화 단계에서 실패했다. WSL의 공개 watch 페이지에서 원본 설명을 읽는 경로는 성공했다. DiDEgRAin9g의 원본 설명에는 키스미 눈썹 제품 05 라이트 브라운이 있어 과거 후보의 그레이시 베이지와 달랐다. 저장소 목록의 '원문에 명시 정보 없음'도 최신 원문 확인 결과와 달랐다. 원본 설명과 후보의 출처를 구분하며 기존 수집 자료를 임의 수정하지 않았다. 공개 한국어 자막 트랙 요청은 빈 응답이었다. 영상 재생·화면 속 실제 사용 동작은 확인하지 않았다.

우선 검수 대상: **사진발 윤곽 보정 메이크업**, AG03mUj4vnY, 원본 https://www.youtube.com/watch?v=AG03mUj4vnY . 원본 설명의 롬앤 베러 댄 컨투어 02그레이쿨과 실제 Catalog의 productId=oy-a000000201055 / shadeId=A000000201055-002 / 호수명 그레이 쿨이 일치한다. API mappingVerified=true이며 상품 상세에도 해당 호수가 존재한다. 색상 측정은 estimated/color_compare이므로 실제 발색 검증으로 확대하지 않는다. 실행 중인 기존 API의 소스 SHA·데이터 릴리스 버전은 미확인이다.

| 준비 항목 | 확인 결과 | 남은 확인 |
| --- | --- | --- |
| 원문 상품·호수 ↔ 실제 Catalog | 일치 확인 | 해당 상품을 쓰는 실제 영상 구간 |
| 02:56 초안 | 베이스·윤곽이 같은 시각으로 중복 | 두 작업의 순서와 실제 설명 |
| 04:41·08:21·09:51·11:13·13:38 | 원문 설명에 여러 윤곽 관련 구간 존재 | 단계 반복/부위/사용 상품을 직접 확인 |
| 16:47·17:44·22:13 | 설명에서 블러셔·눈·하이라이터 구간 확인 | 실제 사용법과 단계별 상품 |
| 완료 레시피 | 미등록, 승인자 없음 | 원문 구간·방법·근거 검토 후 등록 |

기존 초안 5단계는 키워드가 처음 등장한 시각만 남긴 결과다. 전체 영상의 완전한 단계나 관찰한 사용법으로 취급하지 않는다. 원문 제목·장 목록만으로 바르는 위치/방향/양/순서를 만들어내지 않는다. 레시피 registry는 계속 0건이고 실제 N02 양성은 아직 BLOCKED다.

증빙: parent trace의 G8-REAL-LOOK-READINESS에 실제 HTTP 상품/호수 응답, 원문 설명의 SHA와 필요한 상품명 한 줄, 장 시작 시각, 기존 초안, 관련 로컬 원본 5개 exact-byte manifest를 저장했다. 원문 전체·공개 연락처·자격증명은 저장하지 않았다. 모델 호출 0회. Windows 임시 Gitleaks 실행 파일이 없어 첫 append는 쓰기 전에 실패했다. 기존 WSL의 Gitleaks 8.30.1로 동일한 helper/빈 ignore 검사를 수행해 통과 후 추가했다. 이번은 조사·근거 검증이며 코드 회귀/실제 LLM/PG 저장/앱 UI는 재실행하지 않았다.

다음: 위 영상의 실제 사용 구간을 확인해 검토 가능한 단계별 설명을 채우고, 상품 사용 구간과 출처를 연결한 뒤 승인 자료만 레지스트리에 등록한다. 원본에 없는 설명을 보충하거나 이 단계에서 verified를 설정하지 않는다.

## 실제 영상 미리보기 관찰·부위 해석 결함 — 2026-11-26

현재는 ⑤ 협력 완성 중 실제 룩 검수 준비다. 이전 구현과 승인 레지스트리는 유지했다. 이번 변경은 기존 SPEC/WORKLOG/parent trace의 조사 기록이며 코드 수정·commit/push/PR은 없다.

Windows computer-use 스킬을 읽고 native 도구 초기화를 시도했으나 내장 브라우저와 같은 kernel assets 경로 오류로 실패했다. 공개 YouTube watch 페이지가 제공하는 level 3 storyboard는 정상 응답했다. 320×180 프레임, 10초 간격, 3×3 묶음의 미리보기 10장을 임시 검토 폴더에서 직접 확인했다. 연속 영상/음성/전체 프레임을 본 것으로 기록하지 않는다. source 영상은 AG03mUj4vnY이며 이미지 source SHA와 명목 시각은 trace에 있다.

검토 가능한 관찰 초안(시각은 미리보기의 명목 시각):

| 구간 | 화면에서 직접 확인한 내용 | 확정하지 않은 내용 |
| --- | --- | --- |
| 약 04:00 | 퍼프가 볼 부위에 닿는 장면 | 바르는 양·횟수·해당 쿠션 호수 |
| 약 05:20 | 스틱이 관자놀이 주변에 닿는 장면 | 전체 이동 방향과 반복 |
| 약 11:40 | 팔레트를 펼쳐 보여 주며 화면에 롬앤 표기가 나타남 | 작은 호수 글자의 독립 판독 |
| 약 12:00~12:30 | 브러시가 눈 앞머리·콧대 주변·코 옆에 닿는 장면 | 각 부위의 적용량과 연속 동작 |
| 약 14:10~14:50 | 목 앞쪽에 스틱, 턱선 아래에 브러시가 닿는 장면 | 모든 구간이 동일 상품인지 여부 |
| 약 15:40~16:10 | 이마에 밝은 제형, 턱에 퍼프가 닿는 장면 | 제형의 정확한 상품·호수와 두드림 횟수 |
| 약 17:10~17:40 | 블러셔 팬 제시 후 볼 앞쪽에 브러시가 닿는 장면 | 실제 색 재현·사용량 |
| 약 18:10~18:50 | 브러시가 윗눈꺼풀과 아래 눈가에 닿는 장면 | 팔레트 개별 칸과 모든 단계 순서 |
| 약 21:20 | 속눈썹 부근에 도구를 대는 장면 | 연속 부착 과정과 재료 규격 |
| 약 21:50~22:10 | 입술 가장자리 펜슬·입술 어플리케이터 장면 | 정확한 덧바름 횟수 |
| 약 22:40 | 작은 브러시가 눈 앞머리에 닿는 장면 | 사용량 및 전체 하이라이터 범위 |

이 표는 AI 관찰 초안이다. 사람 검수·완성 레시피·효능 평가가 아니다. 원문 설명의 롬앤 02그레이쿨과 실제 Catalog의 정확한 호수 연결은 앞 조사 근거로 유지하며, 미리보기의 작은 호수 문자를 읽었다고 확대하지 않는다. 불명확한 상품/사용법을 채워 verified 레지스트리에 넣지 않았다.

실제 데이터 연결과 관련된 별도 코드 문제를 발견했다. 기존 style_recipe_service.source_zone('베이스·윤곽 베이스 메이크업') 호출 결과가 foundation임을 uv run --frozen python으로 실행해 확인했다. source_zone은 먼저 발견한 부위를 택하며, video 상품의 zone+category 조합에도 사용된다. 해당 값이 RecipeProduct.zone에 들어가므로 N02의 contour 단계와 정확한 상품/호수를 연결하지 못하거나 foundation으로 분류할 수 있다. 실제 전체 N02 오추천을 실행한 결과로 확대하지 않으며, 함수 출력과 연결 코드로 확인한 위험이다.

권장 다음 수정: 상품의 복수 부위 표기를 모호함으로 보존하고, 상품 이름·기본 Catalog 부위만으로 영상 사용 부위를 확정하지 않는다. 명확한 단일 부위의 기존 동작은 유지한다. N02는 모호한 상품을 정확한 단계 충족·AR 가능 결과로 승격하지 않고 근거 부족으로 남긴다. 정확한 사용 부위는 별도 검수 근거가 확보된 뒤 연결한다. 수정 예정 파일은 backend/chatbot/app/services/style_recipe_service.py, tests/test_style_recipe.py, tests/test_g8_owned_look.py이며 새 수정 범위 승인을 받기 전에는 변경하지 않았다.

증빙은 C:/Users/playdata2/AppData/Local/Temp/g8-look-review-20261126의 원본 미리보기·manifest와 parent trace의 G8-REAL-LOOK-FRAME-REVIEW다. 17개 관찰 기록과 이미지 10장의 SHA, 코드 재현 입력/결과를 보존한다. 임시 이미지가 없어지면 해시만으로 재열람은 불가능하므로 필요 시 공개 원본에서 다시 확인해야 한다. repository에는 원본 이미지나 영상 전체를 넣지 않았다. 신규 trace는 기존 Linux Gitleaks 8.30.1/빈 ignore 검사 후 append했다. 이번에 실제 모델 호출·코드 회귀·앱 UI 검증은 실행하지 않았다.

## 복수 영상 상품 부위 수정 및 검증 — 2026-11-26

전체 ① 설계 → ② 기준·계약 → ③ 실행 구조 → ④ 첫 복합 상담 → **⑤ 협력 완성** → ⑥ 통합 검증 → ⑦ PR 인계. 사용자 승인 후 앞 절의 세 파일(style_recipe_service.py, test_style_recipe.py, test_g8_owned_look.py)을 수정했다. branch feat/compound-consultation, HEAD fc1b6279e2a8cca3b899dd255aa8a1ee4156b459. 기존 확인 develop f5adb4e60202bdc4c98bdefe36669f96f90e9b55이며 이번에 원격 최신 여부를 다시 확인하지 않았다. 이전 공통 부모/API 변경을 보존한 미커밋 작업이다. commit/push/PR 없음.

변경: 영상 상품 메타데이터의 서로 다른 부위를 모아 복수이면 unknown으로 유지한다. 같은 부위 별칭은 하나로 계산한다. 정확한 상품·호수 연결은 보존하지만 Catalog 기본 부위/상품명으로 모호함을 지우거나 AR 가능으로 승격하지 않는다. 일반 발화의 기존 source_zone 선택은 유지했다. N02는 이 상품으로 단계를 충족하거나 추가 상품을 추천하지 않고 evidence_missing을 반환하며 다른 유효한 상품은 보존한다. 새 공용 스키마/제한값은 없다.

실제 실행 결과:
- 집중 테스트: 109 통과·2 skip. 17:23:12 KST 시작, 원본 C:/Users/playdata2/AppData/Local/Temp/g8-zone-focused.xml. 명령: uv run --frozen pytest -q -p no:cacheprovider tests/test_style_recipe.py tests/test_g8_owned_look.py tests/test_g8_consultation_parent.py --tb=short --show-capture=no -o junit_family=legacy --junitxml=<위 경로>.
- 챗봇 전체: 1,507 통과·103 skip·실패 0, 17:23:33 KST 시작, 약 46초. 원본 C:/Users/playdata2/AppData/Local/Temp/g8-zone-all.xml. 명령: uv run --frozen pytest -q -p no:cacheprovider --basetemp <새 임시 경로> --tb=short --show-capture=no -o junit_family=legacy --junitxml=<위 경로>. 이번에는 G8_RECIPE_API_JUNIT을 설정하지 않아 해당 opt-in 연결 검사는 skip했다. 이전 실행과 skip 수 차이를 성공으로 합산하지 않는다.
- chatbot ruff check ., lint-imports(3 KEPT), 앱 npm run typecheck 및 npm run lint 통과. 기존 g7-pr-review venv를 UV_PROJECT_ENVIRONMENT로 지정하고 --frozen 사용. API 코드는 이번에 수정하지 않았으며 앞선 API 전체 실패를 해결했다고 주장하지 않는다.
- 모의 검증: 복수 부위 네 경우·동일 부위 별칭, 합성 검수 영상의 모호/명확 부위 두 경우. 후자의 전문 작업 입력·결과·최종 응답은 JUnit 속성과 trace mockCases에 보존했다. 모호한 블러셔의 evidence_missing과 정상 립 결과 보존, 명확한 블러셔의 미보유 추천을 확인했다. 실제 검수 자료가 아니다.
- 실제 HTTP: WSL 내부 Catalog 8082의 /api/style-looks 응답 중 AG03mUj4vnY / oy-a000000201055 / A000000201055-002를 현재 스키마와 video_product_zone에 전달해 (None, True)를 확인했다. 현재 코드의 전체 N02 서비스 배포 검증이 아니며 실행 중 API 소스 SHA·데이터 버전은 미확인이다. 원본 C:/Users/playdata2/AppData/Local/Temp/g8-zone-live.json.

증빙: reports/g8/parent/trace.jsonl의 G8-AMBIGUOUS-VIDEO-ZONE에 미커밋 소스 19개 exact-byte manifest, tracked 구현 diff, XML 해시·실행 시각·명령, 모의 입출력, 실제 HTTP 부위 해석 결과를 보존했다. 신규 기록은 Gitleaks 8.30.1/빈 ignore 검사 통과 후 append했으며 과거 기록을 수정하지 않았다. 외부 모델 호출 0회. 실제 LLM/PG 저장/앱 표시/사람 검토는 이번에 NOT_RUN이다.

남은 작업: 실제 영상 사용 부위와 단계 설명·상품/호수의 검수 근거를 확보하고 승인 레지스트리 등록 후 실제 Catalog→N02→G7→앱 양성을 검증한다. registry는 여전히 0건이며 실제 룩 양성은 BLOCKED다. 공통 부모의 범용 목표 분해·미완료 실행 재개·E01/B01·⑥ 통합 검증은 후속 범위다. 현재 수정에 추가 사용자 판단은 필요하지 않으며 실제 자료를 사람 검수 완료로 임의 승격하지 않는다.

최종 확인: 변경·신규 23개 파일을 Gitleaks 8.30.1/빈 ignore/--redact로 검사해 exit 0을 확인했다. 로그는 C:/Users/playdata2/AppData/Local/Temp/g8-zone-security.log. 처음 Windows subprocess의 cp949 출력 디코딩 및 제한 환경 WSL 호출이 실패해 검사가 완료됐다고 취급하지 않았으며, bytes 출력과 승인된 WSL 실행으로 재시도했다. 소스 manifest 19개가 현재 bytes와 모두 일치하고 git diff --check도 통과했다.

## 실제 룩 검수 자료와 단계별 상품 연결 공백 — 2026-11-26

현재 ⑤ 협력 완성, branch/HEAD 및 미커밋 구현 유지. 기존 프레임 원본 10개가 모두 존재하며 저장된 SHA와 일치함을 재확인했다. page7/8/9를 다시 열어 관찰했다. 약 11:40에는 팔레트 제시, 12:00~13:20에는 코 주변 브러시 접촉, 14:10에는 목 앞 스틱 접촉, 14:50에는 턱 아래 브러시 접촉이 있다. 서로 다른 상품이 사용되므로 전체 윤곽 구간을 롬앤 단일 상품 사용으로 합치지 않는다. 프레임 관찰은 연속 영상·음성·사람 검수 완료가 아니다.

검수 순서와 필요한 산출물:
1. 원본 AG03mUj4vnY의 11:30~13:30 구간: 팔레트 제시와 코 주변 사용의 연속성을 확인하고 정확한 상품/호수 및 적용 방법을 연결한다. 현재 설명/Catalog로 확인한 oy-a000000201055 / A000000201055-002를 후보로만 둔다.
2. 13:30~15:00 구간: 목 스틱과 턱 브러시를 별도 단계로 검토한다. 동일 상품이라고 추정하지 않는다.
3. 나머지 베이스·블러셔·눈·립·하이라이터를 검토해 전체 단계의 누락 여부를 확인한다. 코 윤곽 일부만으로 전체 영상 레시피를 verified 처리하지 않는다.

코드에서 확인한 추가 공백: API ConsultationStep과 챗봇 RecipeStep/ReviewedRecipe는 단계 설명과 레시피 단위 evidence를 전달하지만 단계별 정확한 상품·호수·사용 부위 연결을 담지 않는다. Style 실행은 상품 부위를 기존 영상 메타데이터에서 별도로 해석하고 N02 _exact_links는 link.zone 일치를 요구한다. 따라서 현재 복수 부위 방어는 유지하면서, 추후 실제 검수로 부위를 확정할 수 있는 명시적 입력 계약이 필요하다. 레지스트리에 단계 설명만 등록하는 것으로 해결되지 않는다.

다음 구현 제안(아직 미적용): 검수 레시피에 선택적 단계별 상품 연결을 추가하고 stepOrder/productId/shadeId/evidenceId/source를 보존한다. 참조 단계의 부위와 정확한 Catalog 상품/호수 존재를 검증하며, 충돌·부재·무효 연결은 기존 unknown/evidence_missing을 유지한다. 기존 레시피는 필드 생략 시 동작을 유지한다. 연결 근거가 있어도 AR 색/제형 적합성이나 대체품 효능 근거를 자동 승인하지 않는다. 실제 자료 승인과 계약의 합성 검증은 분리한다.

이번은 기존 자료/코드 대조 및 검수 계획 정리다. 코드·레지스트리 변경, 신규 모델 호출, 실제 PG/앱 검증, commit/push/PR 없음. 테스트를 새로 통과했다고 기록하지 않는다. 다음 계약 수정 파일 범위를 제시하고 승인 후 구현한다.

## 검수 단계별 상품 사용 연결 구현 — 2026-11-26

전체 ①→②→③→④→**⑤ 협력 완성: N02 검수 근거 연결**→⑥→⑦. 사용자 승인 후 제시한 API 스키마/테스트, 챗봇 스키마/Style 서비스/관련 세 테스트, types/index.ts와 기존 문서·증빙을 수정했다. feat/compound-consultation / fc1b6279e2a8cca3b899dd255aa8a1ee4156b459의 미커밋 변경이며 앞선 공통 부모·API 작업을 보존했다. develop의 원격 최신 여부는 재조회하지 않았다. commit/push/PR 없음.

완료: 선택적 productUsages(stepOrder/productId/shadeId/evidenceId/source)로 단계 설명과 정확한 옵션의 사용 근거를 연결했다. 검수 레시피·mappingVerified·실제 Catalog 반환 상품/호수 일치가 필요하다. 부위 충돌·옵션 부재·미검수는 채택하지 않는다. 같은 상품의 다른 호수를 구분하고, 특정 영상의 기존 예외가 검수 연결을 덮지 않게 했다. 기존 레시피는 새 필드 없이 유지된다. 근거를 상품 응답에 담으며 응답 직렬화 복원과 근거 변경에 따른 레시피 버전 변경을 검증했다. 실제 G7 PG 저장 완료를 뜻하지 않는다.

검증 결과:
- API 집중 최종 17 통과(17:36:02 KST 시작). g8-usage-api-pass.xml. 최초 g8-usage-api.xml은 기존 pytest 임시 폴더 권한으로 3 통과/14 setup 오류였으며, 고유 --basetemp로 재실행했다. fixture가 임시 레지스트리를 대체하며 실제 서빙 데이터는 변경하지 않았다.
- 챗봇 최종 집중 113 통과·2 skip(17:38:06 KST 시작). g8-usage-final-focused.xml. test_style_recipe.py, test_g8_owned_look.py, test_g8_recipe_delivery.py 실행. 정상/잘못된 옵션/부위 충돌/옵션 부재/미검수/여러 부위/동일 상품 다른 옵션/기존 영상 예외/잘못된 단계 참조·중복을 확인했다.
- 챗봇 최종 전체 1,519 통과·102 skip/41.21초. g8-usage-final-all.xml. 첫 전체 실행 1,517 통과 이후 옵션/예외 경계를 추가하고 최종 상태를 재실행했다. 첫 결과를 최종 소스 증거로 사용하지 않는다.
- API 전체 643 통과·52 skip·1 실패/51.18초. g8-usage-api-all.xml. 기존 test_celebrity_videos_endpoint_uses_client_contract의 PostgreSQL 인증 실패다. 이번 계약 검증 실패와 구분하며 API 전체 통과로 표시하지 않는다.
- 양쪽 backend ruff check 및 lint-imports 각각 3 KEPT, 앱 npm run typecheck/lint 통과. 코드 변경은 승인한 범위이며 새 UI/API 호출 라이브러리는 추가하지 않았다.

원본 XML은 C:/Users/playdata2/AppData/Local/Temp/ 아래에 있다. API uv 환경은 기존 skin-conversation-api, 챗봇은 기존 g7-pr-review의 .venv를 UV_PROJECT_ENVIRONMENT로 지정했다. 모두 uv run --frozen pytest -q -p no:cacheprovider, JUnit은 -o junit_family=legacy 사용. API 집중은 tests/test_style_looks.py, 전체는 테스트 경로 생략. 전체/최종 API 집중은 고유 --basetemp 사용, 출력은 --show-capture=no. 정확한 실행 시각·XML 해시·명령과 최종 소스 exact-byte manifest/diff는 parent trace의 G8-REVIEWED-PRODUCT-USAGE에 기록한다.

모의/실제 구분: API TestClient의 합성 검수 응답을 G8_RECIPE_API_JUNIT=g8-usage-api-pass.xml로 전달해 실제 CatalogClient 코드의 MockTransport에서 재생했다. API 경로→챗봇→N02 추가 상품 응답에 사용 근거가 유지되고, 모호함만 있으면 조회가 생략되지만 유효 근거가 추가되면 실제 모의 Catalog 검색 인자가 바뀌는 것을 확인했다. 합성 승인 메타데이터는 서빙 스키마 검증용이며 사람 검수가 아니다. 모델 configured mode=not_used, 실제 외부 모델 호출 0회. 실제 Catalog HTTP/LLM/PG 저장/앱 UI/사람 검토는 이번에 NOT_RUN. registry 0건을 유지한다.

설계 결정: 최대 사용 연결 100, ID 128자 제한·초과 처리·조정 기준은 SPEC에 기록했다. 같은 옵션이 실제 여러 부위에 쓰이는 경우 현재 단일 zone 구조에서 임의 선택하지 않고 미확인으로 보존한다. 효능·대체 적합성·AR 색 검사를 완화하지 않았다.

다음: 실제 영상 검수 구간과 단계별 옵션 사용 근거를 확보한 뒤 승인 자료를 등록하고 실제 Catalog→N02→G7→앱을 검증한다. API 전체의 DB 인증 환경 실패도 남는다. 범용 부모 계획/실행 재개/E01/B01 및 ⑥ 전체 검증은 여전히 후속 범위다.

최종 증빙 검사: 신규 trace는 Gitleaks 8.30.1/빈 ignore 검사 후 append했고, 변경·신규 24개 파일 전체도 같은 scanner/빈 ignore/--redact로 exit 0을 확인했다. 로그 C:/Users/playdata2/AppData/Local/Temp/g8-usage-security.log. 신규 trace 소스 20개 exact-byte 해시 모두 현재 파일과 일치하며 git diff --check 통과. 과거 trace는 보존했다.

## 실제 룩 전체 상품·옵션 준비도 확인 — 2026-11-26

현재 ⑤ 협력 완성 중 실제 데이터 준비. 기존 branch/HEAD/미커밋 구현 유지. WSL 내부 Catalog 8082의 /api/style-looks와 대상 상품 상세를 읽기 전용으로 조회했다. AG03mUj4vnY의 14개 상품 중 정확한 옵션 연결 1개, 상품만 연결 11개, 상품 연결 없음 2개다. 연결된 상품 12개는 모두 상세 응답의 ID가 요청 ID와 일치했다. 조회 실패는 없었다. 실행 API 소스 SHA·데이터 릴리스 버전은 여전히 미확인이다.

| 영상 항목 | 실제 Catalog 준비 상태 | 남은 준비 |
| --- | --- | --- |
| 2 롬앤 컨투어 02그레이쿨 | oy-a000000201055 / A000000201055-002 존재 | 영상 단계별 사용 검수; 같은 이름의 다른 옵션으로 교체 금지 |
| 1 쿠션, 3 헤어섀도, 4 컨실러, 5 파우더, 6 치크, 7 아이팔레트, 8 라이너, 9 마스카라, 11 샤인밤, 13 틴트 | 상품 상세 존재, 현재 응답 shades가 비어 있음 | 정확한 판매 옵션 데이터와 원본 사용 호수 연결 |
| 10 키스미 눈썹 펜슬 03호 | 상품 상세 존재, 반환된 호수는 12/그레이시 베이지 | 영상 03호와 동일 옵션임을 확인할 수 없음; 첫 호수 선택 금지 |
| 12 밀크터치 립 펜슬, 14 세잔느 하이라이터 | 영상→상품 연결 없음 | 상품 정체성·옵션·사용 구간 근거 |

후보 변경이 문제를 해결하는지도 확인했다. 영상 73개 중 정확한 옵션 링크 메타데이터를 가진 영상은 4개이며 각각 1개뿐이다. DiDEgRAin9g 1/10, AG03mUj4vnY 1/14, SeBpQnxm_4Q 1/18, ZAozXs-ZZik 1/24다. 이 순위는 목록 메타데이터 비교이며 다른 세 영상의 모든 상품 상세 검증은 아니다. 단순히 후보를 바꾸는 것으로 전체 단계의 옵션 공백이 해결되지 않아 기존 검수 후보를 유지한다.

결론: 사람 검수만 기다리는 문제가 아니라 현재 실행 데이터의 판매 옵션 공백도 있다. 전체 룩의 모든 상품이 준비돼야 일부 유효 결과를 반환할 수 있다는 뜻은 아니다. 근거 있는 단계는 활용하고 나머지는 evidence_missing으로 보존하는 부분 성공 계약을 유지한다. 다만 미검수 자료를 등록해 실제 양성으로 만들거나 한 구간만으로 전체 영상의 완료 레시피를 선언하지 않는다.

증빙: parent trace G8-REAL-LOOK-OPTION-READINESS에 실제 14개 항목의 상태, 상품 상세의 옵션 ID/이름, 73개 영상 메타데이터 비교, 확인 시각과 현재 관련 소스 3개 해시를 추가했다. Gitleaks 8.30.1/빈 ignore 검사 후 append했다. 3개 병렬 읽기·요청당 20초는 이번 조사에만 사용한 실행 설정이며 제품의 새 제한값이 아니다. 실제 모델 호출 0회, 연속 영상 재생/사람 검수/N02 전체/PG/앱은 NOT_RUN. 웹 도구의 원본 YouTube 페이지 조회는 실패했으며 이를 영상 검수 증거로 사용하지 않았다.

다음 작업은 두 갈래로 구분한다. (A) 기존 영상 관찰 구간의 사용법·상품 연결 검수 자료 준비, (B) 실행 Catalog와 저장소 데이터의 옵션 공급 경로 대조 및 정확한 옵션 준비 가능 여부 확인. 데이터가 준비되지 않은 항목을 미확인으로 유지하면서 E01/B01과 후속 통합 검증은 독립적으로 진행할 수 있다. 이번에 API/DB 데이터·소스 코드·레지스트리 변경, commit/push/PR은 하지 않았다.

공급 경로의 코드 확인: 현재 CatalogService.get_product는 저장소 상세를 직접 읽고 이미지 보강 후 반환한다. CatalogRepository.get_product는 PG ProductRow를 읽는다. 따라서 현재 코드 기준으로 단순 목록 캐시 비우기가 옵션 공백의 해결책이라고 볼 근거가 없다. OyCatalogRepository는 원본 옵션/색상 테이블을 읽는 별도 경로이며 VerifiedVideoProductRepository에는 확인된 상품의 미해결 호수를 원본 옵션 근거로 해석하는 경로가 있다. 실행 서버가 이 현재 소스와 일치하는지는 미확인이므로 원본 DB의 해당 옵션 존재 여부와 서빙 반영 여부를 다음에 나누어 확인한다. 이번에 원본 테이블을 직접 조회하거나 import job을 실행하지 않았다. 문서/증빙 변경 뒤 git diff --check 및 신규 trace 소스 해시 일치를 확인했다.

## 정정: 원본 판매 옵션과 AR 서빙 shade의 차이 — 2026-11-26

사용자 요청으로 원본→서빙→영상 매핑을 추가 조사했다. 앞 절의 '옵션 연결 1개'는 로컬 HTTP 응답의 catalogShadeId 기준 관측이며 전체 원본 판매 옵션 부족을 뜻하지 않는다. 원본 데이터가 없다는 결론으로 확대하면 잘못이다. 현재 ⑤ 협력 완성 중 계약/데이터 경계 조사이며 기능·데이터 수정은 하지 않았다.

실제 읽기 전용 PostgreSQL: 기존 프로젝트 .env.local의 vishue_g5_integration(15441)에 연결해 products 9,031 / shades 11,231 / raw_oy_product 8,215 / raw_oy_product_option 21,951행을 확인했다. 모든 SQL은 default_transaction_read_only와 statement_timeout을 적용했다. 인증정보는 기록하지 않았다. 이 DB가 8082 API의 실제 연결 DB인지는 아직 입증하지 못했다. Docker CLI는 제한 시간 내 응답하지 않았으며 WSL 안에서 API 프로세스/소켓을 식별하지 못했다. 다만 세 표본의 seed/catalog.json·이 DB의 serving shade·8082 응답 내용은 일치한다.

확인된 사례:
- 키스미 A000000137019 원본에는 03 애쉬 브라운(A000000137019-001)을 포함한 6개 옵션이 실제 존재한다. 03~09 옵션은 유효 HEX 행 0개, 12 그레이시 베이지는 1개다. 서빙 shades에는 id=12만 있다. 영상 매핑은 상품 confirmed이지만 oy_option_id는 NULL이다. 원본 옵션 존재와 영상→정확한 판매 옵션 확정은 별개다.
- 삐아 아이팔레트는 영상 매핑에 A000000162667-012가 이미 confirmed로 존재한다. 그런데 앞선 HTTP에는 catalogProductId만 있고 catalogShadeId가 없었다. 따라서 '정확한 옵션 매핑 자체가 전부 없다'는 해석도 틀리다.
- 롬앤은 A000000201055-002의 원본 옵션/confirmed 영상 매핑/서빙 shade/API 연결이 이어진다.
- 쿠션 등 YouTube 출처 상품에는 원본 option_name이 있으나 색상값이 없다. 이를 판매 옵션 정보가 전혀 없다고 표현하지 않는다. 별도 판매 옵션 정체성/출처 검증 없이 option_name만으로 임의 ID를 만들지도 않는다.
- 세잔느는 이 DB의 영상 매핑에 상품 A000000216419 confirmed가 있으나 앞선 API에 상품 링크가 없었다. 서빙 ProductRow 포함 여부와 실행 환경 차이는 추가 확인 대상이다.

코드 근거: app/services/oy_catalog.py의 build_oy_catalog는 유효 HEX가 없는 옵션을 shades에서 제외한다. app/repositories/verified_video_product_repository.py는 confirmed 원본 옵션을 서빙 ShadeRow.id와 연결하고, 실패 시 색 근거를 요구하는 video_shade_resolution fallback을 사용한다. 즉 판매 옵션 전체와 AR 색상 표현이 가능한 shade 목록은 동일하지 않다. API/N02가 catalogShadeId만 정확한 옵션의 근거로 요구하면 판매 옵션이 존재해도 상담 연결이 막힐 수 있다. 최근 추가한 productUsages.shadeId 역시 현재 서빙 shade 계약이므로 이 구분을 보완해야 한다.

권장 후속 설계: 검증된 판매 optionId와 선택적 AR shadeId를 구분한다. 원본 confirmed 판매 옵션은 별도의 근거 계약으로 상담에 전달하고 AR은 기존 색상·제형·부위 검증을 그대로 적용한다. 색상값을 만들어 shades에 넣거나 미확인 매핑을 자동 승인하는 해결책은 사용하지 않는다. 기존 카드/저장/옵션 가격·성분 조회 계약과의 영향 범위를 먼저 정리한 뒤 수정한다. 이번 조사만으로 데이터 재수집·DB import·매핑 변경을 실행하지 않았다.

증빙: parent trace G8-RAW-VERSUS-SERVING-OPTIONS에 실행한 SELECT, 실제 원본/서빙/영상 매핑 결과, DB 식별 범위, 관련 코드와 seed exact-byte 해시를 저장했다. Gitleaks 8.30.1/빈 ignore 검사 통과 후 append. 모델 호출 0, 신규 기능 회귀/앱/실제 N02 종단 검증은 NOT_RUN. 기존 데이터 준비도 기록은 당시 API 관측으로 보존하며 본 절에서 의미를 정정한다.


### 부모 후속·옵션 기억 게시 전 검사 — 2026-11-27T14:51:27.899992+09:00

전체 ①→②→③→④→⑤ 협력 완성→⑥ 통합 검증→⑦ PR 인계 중 ⑤를 유지한다. 사용자 지시로 구현·테스트와 문서·증빙을 두 커밋으로 분리한다. 첫 구현·테스트 커밋은 3ba5d56bd37940bd8412a04d19a935b65159002e (29파일). 원격 시작점 c4fe954 및 최신 develop 991dd634dba33b99ceeb1c03de4dd8d921ce07f9를 fetch로 확인했다. develop 병합은 하지 않았다.

커밋 전 npm run check: 타입·lint 및 108 suites/1,338 tests 통과. 챗봇 ruff/레이어 3개 통과. 전체 pytest는 1,538 pass/107 skip/1 fail: 기존 하위 HTTP 서버 readiness 제한 시간 초과였다. 코드를 바꾸지 않고 해당 사례만 단독 실행해 1 pass(7.07초). 전체 단일 실행 통과로 표현하지 않는다. 실제 외부 모델 호출 0회. 원본 명령·시각은 followup-publish-* 로그/JUnit 및 publication trace 참조.

이전 trace 15행은 그대로 보존됐고 신규 1행의 인증정보·얼굴 데이터 필드/개인키 헤더 0, 소스 해시 29개 일치를 확인했다. Gitleaks 8.30.1/빈 ignore로 신규 trace 원문을 포함한 게시 파일 검사를 통과했다. 이후 추가하는 게시 기록도 별도 검사 후 append한다. 공용 보안 설정 변경 없음. 이 기록 시점에는 두 번째 문서 커밋·최종 이력 검사·push 대기 상태이며 실제 게시 결과는 완료 보고의 원격 SHA를 기준으로 확인한다. PR은 생성하지 않는다.

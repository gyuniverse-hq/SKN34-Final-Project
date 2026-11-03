# PR #197 병합 전 수정·검증 기록

## 범위와 승인

- 기준: `feat/chat-ui`, `ede56bac6959664198e9399972075efc52579a4e`; PR의 최신 HEAD도 동일함을 확인.
- 사용자 승인: 확인된 결함의 로컬 수정·테스트·에뮬레이터 검증 후 해당 PR 브랜치에 commit·push. **PR 병합·배포 금지.**
- 실제 운영 DB·인증은 변경하지 않는다. 설치는 하지 않는다. 실제 모델 검증은 사용자가 추가 승인한 `gpt-6-luna`, **총 $5 이내**에서만 가능하며, 검증 가능한 단가·토큰 상한·누적 비용을 확보하지 못하면 호출하지 않는다.
- 기존 미추적 `docs/ar-integration-manifest.json`, `reports/ingredients/`와 사용자가 제공한 원본 3개를 보존하고 커밋에서 제외한다. 원본의 저장소 게시 권한은 확인되지 않았다.
- 원본 3개 SHA-256 재확인: 입력 `9223ad217cc1f8cfe6274479256cb4c3473be858d05da0512b7f0d6353e0113a`, world `3dce47c2419032f7bd0b6f500b9a02f301609725dbab9de6a9ea636c01d4a803`, 검수 `a517e742a285054166000407f8fa607285a54ccd226af2dd1bc44373f7ba0490`.

## 재현 결과

1. P1: 성분 제외 후 후보 `a`만 남아도 가격 재검색에서 `a,b`가 반환되며 추가 성분 검증 0회. 성분 조건이 세션 필터에 저장되지 않는다.
2. P2: 두 후보의 호수를 선택한 상태에서 가격·성분 필터로 후보를 줄이면 제거된 후보의 호수가 남아 `422 chat_catalog_changed`.
3. P2: 상품·스타일 상세 이동에서 호수 인자를 누락. 상세 화면의 기본 첫 호수 선택과 결합하여 장바구니에 다른 호수가 담길 수 있다.
4. P2: 성분 매핑 경로는 `os.environ`만 읽으며 Settings·Compose와 연결되지 않는다. 미검수 자료의 UNKNOWN 동작은 정상이며 보존한다.
5. P1: 평가 검증기가 원본 world를 읽고 패치본의 `A_UNDO_READY`를 검사하여 KeyError. 결과 파일을 기본적으로 덮어쓰는 부작용도 있다.
6. P2(조건부): production 설정의 Mock HTTP에서도 `synthetic=true`, `status=ok`, `verdict=MATCH`, `reason=verified_evidence`. 실제 운영에 합성 매핑이 적재됐다는 증거는 없다.
7. P1(개발·스테이징 AR): 계정 A→B 전환 후 지연 응답/렌더 확정 모두 이전 제안이 적용됨을 실제 훅·API 코드와 Mock 인증/렌더러로 재현. 운영 AR 명령·ACK 503 제한은 보존한다.

## 수정 전 기준 검사

- TypeScript·ESLint·Jest: 통과, 62 suites·615 tests. 전체 ESLint 오류 0·기존 경고 12.
- API: Ruff 통과, 계층 계약 3개 통과, pytest 213 통과·PostgreSQL 필요 2개 건너뜀.
- 챗봇: Ruff 통과, 계층 계약 3개 통과, pytest 315 통과·실제 Redis 통합 1개 건너뜀.
- 이 세션의 앞선 검토에서 PostgreSQL 17 마이그레이션·모델 일치·DB 테스트 2개와 실제 Redis/HTTP 12개 시나리오는 통과했으나, 수정 후 결과와 구분한다.

## 진행 상태

아래는 중간 이력이며, 현재 결과는 뒤의 **최종 로컬 검증**을 우선한다. 원격 HEAD·CI 완료 결과는 이 작업 채팅에도 기록한다.

- API 네 파일의 Ruff `--fix`/`format`은 자동 승인 검토가 직접 사용자 승인 근거를 요구하며 두 번 거절했다. 재시도·다른 방법에 의한 우회는 하지 않는다. 상위 후속 지시도 해당 작업의 보류를 확인했다.
- 이후 사용자의 새 구체적 승인 “그거 승인할게 그런걸로 보류하지마”를 전달받아 1회 재검토했고 허용됐다. 대상 네 파일의 Ruff 정리가 완료되어 **API Ruff 오류 0**. 이 차단은 해소됐다.
- 당시 보류 경로(해소됨): `backend/api/app/core/config.py`, `backend/api/app/repositories/ingredient_repository.py`, `backend/api/app/services/ingredient_service.py`, `backend/api/tests/test_ingredient_api.py`.
- API 성분 관련 테스트 71개 통과. 해당 테스트 파일의 함수 선언 길이(E501) 1건은 승인 후 포맷으로 해소됐다.
- 챗봇 수정 후 pytest 318 통과·실제 Redis 통합 1개 건너뜀, 계층 계약 3개 통과.
- 앱 수정 후 전체 Jest 첫 실행: 605 통과·14 실패. 실패는 AR 통합 테스트의 새 인증 구독 Mock 누락이며 보완 중이다. TypeScript의 테스트 타입 자기 참조와 nullable shade 인자도 확인하여 수정한다.
- ADB 진단: 실행 중인 디바이스 없음. 설치된 AVD는 `VISHUE_API_35`이며 설치·초기화는 하지 않았다.
- 이후 기존 AVD를 headless로 시작해 `emulator-5554`의 부팅·ADB 연결을 확인했다. Expo Go SDK 58 번들(2108 모듈) 실행 성공. API·인증은 실제 서비스 대신 loopback Mock으로 격리한다.
- 실제 LLM 테스트 준비: 백엔드 설정에 모델·키가 없고 저장소 루트 `.env`도 없다. 유료 호출 0건, 비용 $0. 다른 위치의 비밀을 탐색하거나 다른 모델로 대체하지 않는다.
- 정정: Expo의 환경 로딩 로그에서 루트 `.env.local`을 확인했고, 그 파일의 서버 설정에 `gpt-6-luna`와 키가 있었다. 호스트·모델·키 존재 여부만 확인하고 비밀 값은 출력하지 않았다. 이후 승인 예산 안에서 아래 실제 모델 검증을 수행했다.

## 최종 로컬 검증 (2026-11-03)

| 영역 | 실제 실행 명령 | 결과 |
|---|---|---|
| 앱 전체 | `npm run check -- -- --runInBand --silent --no-cache` | TypeScript·Expo ESLint 통과, 63 suites·624 tests 통과 |
| 전체 폴더 ESLint | `node node_modules/eslint/bin/eslint.js . --no-cache` | 오류 0·기존 경고 12 |
| API (`backend/api`) | `.venv/Scripts/python.exe -B -m ruff check . --no-cache`, `ruff format --check . --no-cache`, `.venv/Scripts/lint-imports.exe --no-cache --no-logo`, `pytest -q -p no:cacheprovider --basetemp=<새 OS 임시 경로> --tb=short` | Ruff·format·계층 계약 3개 통과, 216 tests 통과·PostgreSQL 필요 2개 건너뜀 |
| 챗봇 (`backend/chatbot`) | 같은 Ruff·format·계층 검사 및 `VISHUE_RUN_REDIS_INTEGRATION=1`으로 `pytest -q -p no:cacheprovider --tb=short` | Ruff·format·계층 계약 3개 통과, **321 tests 전부 통과**. 실제 격리 Redis·두 HTTP 프로세스의 12개 세션 시나리오 포함 |
| 평가기 | `python -B -m unittest discover -s docs/ai-alignment/01_run_1A -p 'test_*.py' -v` | 12 tests 통과 |
| 원본·매니페스트 | `python -B docs/ai-alignment/01_run_1A/validate_fixture_package.py` | 원본 3개 SHA-256·359건·8건 맥락 패치·world 차이·매니페스트 통과. 결과 파일 덮어쓰기 없음 |
| 확장 평가기 | `run_evals_v1.3.py --inputs <패치 입력> --world <패치 world> --self-test` | 359건 구조·의도된 음성 사례 2개·자체 회귀 통과. 실제 359건 모델 평가가 아님 |
| Compose | 기본/선택적 설정의 `docker compose ... config --format json` | 기본 실행에 마운트 없음. 선택적 마운트 `read_only=true`, `create_host_path=false` 확인 |

`uv`의 샌드박스 캐시 권한 문제 때문에 설치된 각 uv 프로젝트의 기존 가상환경 실행 파일을 직접 사용했다. 의존성·lock 파일은 변경하거나 새로 설치하지 않았다. 실제 운영 DB는 변경하지 않았으며 PostgreSQL 검사는 이번 최종 실행에서 명시적으로 건너뛰었다.

### 변경 내용과 영향

- `backend/chatbot/app/schemas/{chat,supervisor}.py`, `services/beauty_consultation_service.py`, `types/index.ts`, `lib/chatConditions.ts`: 성분 포함/제외 조건을 서버 세션에 보존하고 검색마다 재검증한다. 명시적 해제와 같은 성분 조건의 교체만 반영하며 최대 6개로 제한한다. 새 검색에서 호수가 없거나 근거가 불확실하면 UNKNOWN/clarification이며 조건 충족 추천으로 표시하지 않는다. 후보 밖 상품의 선택 호수·선택 상품을 응답 전에 정리한다.
- `app/chat.tsx`, `components/chat/{ChatProducts,StyleRecipeResult}.tsx`: 선택한 유효 호수를 상품 상세까지 전달한다. 상품 상세·실제 장바구니 store까지 회귀 검사했다.
- `lib/api.ts`, `hooks/useArCommand.ts`: 인증 변경 epoch와 실제 요청 소유권을 응답·렌더 확정 시점에 검사한다. A→B→A 지연 응답도 취소하며 같은 사용자의 토큰 갱신은 허용한다. 기존 실패 복원·ACK 소유권 제한·녹화 연동은 회귀 테스트로 보존한다.
- `backend/api/app/core/config.py`, `repositories/ingredient_repository.py`, 환경 예시·Compose·배포 문서: 일반 `.env` 설정과 선택적 읽기 전용 파일 전달을 연결한다. 경로 직접 주입이 우선하며 미설정·누락·형식·버전 오류와 미검수 UNKNOWN을 보존한다.
- API 성분 서비스·챗봇 계약·성분 UI: 운영 합성 근거의 검증 판정·목록 공개를 UNKNOWN으로 강등한다. 비합성 검증 근거 및 개발용 순수 Mock 알고리즘 검사는 유지한다.
- 평가 검증기·단위 검사·매니페스트·README·`.gitattributes`: 원본과 패치본의 역할을 분리하고 해시를 검사한다. 권리 미확인 원본은 외부 필수 입력으로 명시하고 Git에서 제외한다. 배포하지 않는 캐시·별도 프롬프트 항목을 매니페스트에서 제거하고 LF를 고정하여 플랫폼별 해시 차이를 방지한다.

### 에뮬레이터

- 기존 `VISHUE_API_35` / Expo Go에서 SDK 58 번들 실행 성공. 실제 API·인증 설정은 끄고 loopback guest-only 서버의 **명시적 가상 상품** 두 호수만 사용했다.
- `demo-plum` 딥링크 → 상품 상세에서 `FAKE TEST PLUM` 선택 표시 → 장바구니에 같은 호수·수량 1 유지 확인. 채팅/스타일 카드의 호수 전달은 Jest에서 별도로 확인했다.
- 상품 상세 → AR 진입에서 같은 상품·호수 유지 및 카메라 동의 화면 확인. 실제 얼굴 추적·화질·녹화/공유·실기기 렌더 ACK는 검증하지 않았다.
- 로컬 증빙: `pr197-product-selected.png`, `pr197-cart-selected.png`, `pr197-ar-entry.png`. 저장소에는 추가하지 않았다.
- 이번 실행의 가상 장바구니 항목·포트 reverse·테스트 서버를 정리하고 직접 시작한 에뮬레이터를 종료했다. AVD 초기화·앱 설치는 하지 않았다.

### 실제 모델·예산

공식 `api.openai.com`의 모델 조회로 `gpt-6-luna` 접근을 확인했다. [공식 가격 문서](https://developers.openai.com/api/docs/pricing.md)를 직접 읽어 단가를 확인한 뒤, 기존 LlmClient를 통해 호출했다. 검색 도구의 HTML 캐시가 오래된 모델 표를 보여 Markdown 원문으로 재확인했다.

- 최대 8회·회당 출력 1024 tokens·`service_tier=default`·`reasoning_effort=none`·`store=false`로 제한. 입력 UTF-8 바이트+여유분, 더 높은 단가와 10% 여유를 적용해 호출 전에 비용을 예약했다. 자동 재시도 없음.
- 실제 모델 8회/8개 시나리오 통과: 상품 검색, 알코올 제외, 가격 재검색의 조건 유지, 명시적 조건 해제, 두 번째 상품, 선택 상품의 가격, 립 강도 0%/100% 제안.
- Catalog·성분 근거·Redis·인증은 합성 Mock이며 실제 상품 근거 검수나 실기기 AR 렌더 검증을 뜻하지 않는다.
- 실제 사용량 합계: 입력 4,853 tokens, 출력 184 tokens. 사용량 기반 **추정 비용 $0.0005773**. 사전 예약 최대 비용 합계 **$0.03092056**, 승인 상한 $5. 청구서의 실제 결제 금액은 조회하지 않았다.

| 호출 | 입력 tokens | 출력 tokens | 사용량 기반 추정 USD |
|---|---:|---:|---:|
| 1 | 618 | 24 | 0.0000738 |
| 2 | 703 | 31 | 0.0000858 |
| 3 | 726 | 21 | 0.0000831 |
| 4 | 737 | 28 | 0.0000877 |
| 5 | 700 | 16 | 0.0000780 |
| 6 | 701 | 12 | 0.0000761 |
| 7 | 334 | 25 | 0.0000459 |
| 8 | 334 | 27 | 0.0000469 |

정적 검사·Mock/인프라 회귀 및 위 제한된 실제 모델 smoke test는 PASS. 전체 병합 판단은 **CONDITIONAL**: 검수된 실제 성분 자료·Gold 승인·실기기 화질/녹화/공유는 남아 있다. 운영 AR 명령·ACK의 503 제한은 해제하지 않는다. PR 병합·배포는 하지 않는다.

## 독립 재검토 후 추가 수정 (2026-11-03)

기준 HEAD `d1fc475`에서 기존 수정이 누락한 실제 세션 분기를 재현했다. 앞 절의 통과 결과만으로 모든 분기가 해결됐다고 해석하지 않는다.

- **P1:** `ChatService._answer_session`이 `search/catalog`로 해석된 독립 검색에서 `chat_context=None`을 대입해 저장된 성분 조건까지 버렸다. `refine/catalog`와 달리 성분 확인 없이 `recommendations`를 반환했다. 새 세션 통합 회귀는 수정 전 실패했다.
- **P3:** 저장된 조건을 재사용하는 가격 재검색에서 요청 로컬 성분명은 `None`이었다. 복수 조건의 설명이 `None: ...조건을 충족합니다`로 출력되는 것도 수정 전 재현했다.
- `backend/chatbot/app/services/chat_service.py`: 새 검색에 빈 후보·범위·선택·호수와 현재 시각을 사용하되, 서버 스냅샷의 성분 조건만 깊은 복사로 보존한다. 삭제된 과거 Catalog 상품이 새 검색을 막지 않으며 가격·카테고리 등 일반 새 검색 초기화와 명시적 `clearFilters: [ingredientConditions]` 해제는 유지한다. 클라이언트가 보낸 조건 삭제는 서버 조건을 덮어쓰지 않는다.
- `backend/chatbot/app/services/beauty_consultation_service.py`: 실제 근거 응답의 각 성분명과 해당 판정으로 설명을 만든다. 복수 조건을 각각 표시하며 이름이 없는 fallback에서도 `None`을 출력하지 않는다.
- `backend/chatbot/tests/test_chat_sessions.py`: 실제 `ChatService.answer`와 세션 저장소 경로로 search/refine 분류, 조건 유지·해제, 정확한 호수 미지정 UNKNOWN, 명시 호수 재조회 후 제외 대상 제거, 삭제 상품 복구, 클라이언트 필터 변조 무시, 응답/저장 스냅샷 정합성, 복수 조건 설명·불충족 제외를 검사한다. LLM·Catalog·기본 Redis는 명시적인 테스트 더블이며 실제 모델 판정 품질 검사가 아니다.

검증 명령과 결과:

- 수정 전 `pytest tests/test_chat_sessions.py -k 'ingredient_filter_survives or new_search_keeps_server or persisted_multiple' -q -p no:cacheprovider --tb=short`: **실패 3·통과 1**, 두 결함 재현.
- 수정 후 `pytest tests/test_chat_sessions.py -q -p no:cacheprovider --tb=short`: **37 통과**.
- 챗봇 기존 가상환경에서 `python -B -m ruff check . --no-cache`, `ruff format --check . --no-cache`, `lint-imports --no-cache --no-logo`: 모두 통과, 계층 계약 3개 유지. `VISHUE_RUN_REDIS_INTEGRATION=1` 및 `python -B -m pytest -q -p no:cacheprovider --tb=short`: **324 통과**, 실제 격리 Redis/HTTP 시나리오 포함.
- API 같은 정적 검사·계층 계약 통과. 최초 pytest는 공용 OS 임시 폴더의 WinError 5로 준비 오류 22개(194 통과·2 건너뜀)가 발생했다. 새 작업 전용 OS 임시 경로를 `--basetemp`로 지정하여 테스트를 제외하지 않고 다시 실행: **216 통과·PostgreSQL 필요 2개 건너뜀**.
- 평가기 unittest **12 통과**, 원본 3개·359건·매니페스트 검증 통과. 원본·기존 미추적 자료는 변경하거나 커밋하지 않는다.
- 앱 `npm run check -- -- --runInBand --silent --no-cache`: TypeScript·ESLint 및 **63 suites·624 tests 통과**. 새 원격 HEAD의 CI는 이 채팅에도 기록한다.

이번 추가 수정에서 실제 모델 호출·재시도는 **0회**, 추가 추정 비용 **$0**. 이전 8회 포함 누적 사용량 기반 추정 비용 **$0.0005773**, 이전 예약 상한 합계 **$0.03092056**을 그대로 유지하며 $5 예산을 초기화하지 않았다. 청구액은 조회하지 않았다. 에뮬레이터·실기기는 재실행하지 않았으며 앞 절의 제한이 유지된다. 운영 AR/ACK 503 제한·의존성·DB·렌더러·기존 테스트를 변경하지 않는다. 병합·배포는 하지 않는다.

## 해석상의 제한

- Gold 승인 0건. Mock/평가기 통과를 실제 LLM 품질 또는 AR 화질 통과로 해석하지 않는다.
- 제품 없는 룩 색상은 AR_SPEC 6-5-12의 기존 예외이며 이번 수정에서 바꾸지 않는다.
- 첨부 Library ID `libfile_4849be7138148191a32e9859252668f0`의 원문 파일은 이 호스트에서 확인하지 못했다. 지원되는 materialization 도구가 현재 제공되지 않아, 전달된 기존 지시문·세션 기록·7개 독립 지적을 코드에서 직접 재검증한다.

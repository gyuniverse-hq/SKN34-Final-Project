# G2 멀티턴 핵심 구현

기준: 2026-11-16. 부모 PR #244 / `feat/vishue-supervisor` /
`f2e25eaaf48064ab940d632683f9be225c049608`. 시작 및 PR 준비 시 GitHub에서 같은 HEAD,
Draft, develop 미병합을 확인했다. G2 브랜치는 `feat/vishue-multiturn`이며 부모 브랜치를
base로 하는 Draft Stacked PR이다. 부모가 통합되기 전 develop 대상 PR로 바꾸지 않는다.

## 변경 사항

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

## 영향 범위

- `backend/chatbot/app/schemas/chat.py`: 플래그 ON 한국어 chat의 요청 ID·세션 파싱.
- `backend/chatbot/app/services/chat_service.py`: 기존 세션 경로 연결과 일반 설명의 문맥 보존.
- `backend/chatbot/tests/test_chat.py`: OFF 한국어 chat의 잘못된 legacy 필드 무시 회귀.
- `backend/chatbot/tests/test_g2_multiturn.py`: G2 최소 계약 및 명시적으로 실행하는 실모델 smoke.
- 이 문서. 프론트·API 서비스·Redis 저장소·배포 설정·기능 플래그 기본값은 변경하지 않는다.

## 검증

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
실제 Redis, 앱 전송/카드/상세 연결, Expo Go, 비한국어 확대, 장기 이력 및 통합 리뷰는 후속이다.

# I-3 평가 후보 패키지 v1

이 패키지는 **36개 시나리오·47개 턴의 정답 후보**다. Gold 승인 0건이다.
AIHub QA 원문이나 검수 결론을 포함하지 않는다. 실제 QA 5건 검수와 별도 작업이다.
기준 계약: PR #229, `5a112874578069dab10bd6eaebbbd50e54d71db2`.
현재 체크아웃에 그 계약이 없으면 해당 환경의 통과를 주장하지 않는다.

## 파일과 권위

| 파일 | 역할 |
|---|---|
| `cases.candidate.jsonl` | 신규 작성 질문, 필수 조건, 허용/금지 답변, 상태 변화, 자동 assertion, 사람 기준 |
| `reuse_map.json` | 기존 359건 중 우선 재사용 후보 28건. 완전한 관련 사례 총수가 아님 |
| `fixtures.synthetic.json` | 합성 옵션·사전·발행·세션 환경 명세. 실제 데이터 또는 실행 결과가 아님 |
| `schema.json` | Case/Observation Pydantic 모델에서 생성한 JSON Schema. 모델과 일치하는지 테스트 |
| `backend/chatbot/tests/i3_eval_adapter.py` | 원 관측을 보존하는 검증·정규화 및 독립 assertion |
| `backend/chatbot/tests/run_i3_eval.py` | 실행 기록을 입력받는 오프라인 채점 CLI. stdout만 출력 |
| `backend/chatbot/tests/test_i3_eval_grader.py` | 평가기 오류를 유도하는 검증. 챗봇 실행 성능 시험이 아님 |

원 359건은 기존35·의도확장138·외국어84·멀티턴40·현실입력22·추가행동20·시스템12·보완8이다.
승인 후보25·정책보류10·미검수324이며 승인 assertion은 0건이었다.
재사용 후보28건은 승인 후보5·정책보류2·미검수21이다. `E-PR-04/06`은 정책 보류다.
`sourceCaseIds`는 주제별 잠정 연결이며 문장별 동등성 또는 정답 승계를 뜻하지 않는다.
기존 멀티턴160턴은 40개 시나리오의 보조 자료이므로 사례 수에 중복 합산하지 않는다.

## 평가 구분

| 모드 | 기록 요건 | 해석 |
|---|---|---|
| `synthetic_contract` | `planner=fixture`, `dataKind=synthetic` | 통제한 해석 결과 뒤의 계약·로직 평가. LLM 질문 해석 성능이 아님 |
| `real_llm` | `planner=real_llm`, 실제 모델/프롬프트/설정/실행 출처 | 실제 질문부터 얻은 결과 평가. 기본 3회 반복 |

`real_llm`에서도 합성 데이터 또는 실제 미발행 데이터일 수 있다. `dataKind`로 구분한다.
실제 LLM + 합성 근거는 실제 근거의 정확도를 증명하지 않는다.
기록의 provenance는 수집자가 제출하는 감사 정보이며 모델 호출을 암호학적으로 증명하지 않는다.
실행 로그와 `executionRef`는 사람이 대조한다. 임의 라벨만 바꾼 기록은 인정하지 않는다.

이 CLI는 모델/API/Redis/DB를 호출하지 않는다. 네트워크 비용, 운영 쓰기, 자동 발행이 없다.
현재 승인 범위는 평가 후보와 평가기이며 운영 서비스 관측 코드 추가는 포함하지 않는다.
PR #229 테스트 환경에서 기록을 수집하거나 승인된 외부 수집기를 사용해야 한다.
기존 `PlanLlm` 통합 테스트 기록을 `real_llm`으로 분류하지 않는다.
CLI가 fixture로 정답 응답을 만들어 스스로 채점하는 경로는 제공하지 않는다.

## 구성과 지금 평가 가능한 범위

| 그룹 | 수 | 핵심 |
|---|---:|---|
| Q | 6 | 설명/회피/추천, 포함·제외·가격, 모호함·모순, 외국어 |
| E | 6 | 명시적 발행, 권리, 용도, 적용 조건, 조회 실패 |
| I | 6 | 부분 존재/전체 부재, 표준명, 동일 옵션·버전 |
| O | 10 | 현재/수집가, 경계·결측·재고, 조건 합성, 범위·오류 |
| M | 8 | 순번·조건 유지/해제·가격 전환·재시도·철회·세션 |

M01~M04/M08은 2턴, M05~M07은 초기 검색→상세→같은 요청 재전송의 3턴이다.
`variants`는 후속 확장 명세이며 이 버전 실행 분모에 넣지 않는다. 변형을 실행하려면
질문·fixture·assertion을 명시한 개정본과 새 해시가 필요하다. 모호함/모순/비교 경로의
기대 응답도 정책 승인 전 후보다. 구현에 맞추기 위해 조용히 완화하지 않는다.

현재 가능한 것: 근거 부재 처리, 임의 근거 방지, 실제 LLM 조건 해석, 합성 계약 경계,
옵션·상태 관계, 오류·비전수 표시. 실제 승인·발행 근거 기반 내용 정확도는 보류한다.
`realEvidenceRequiredForPositiveContent`가 참이면 실제 긍정 내용 검증이 별도로 필요하다.
현재 모든 사례의 `goldQuality`는 BLOCKED다. 자동 assertion 통과는 후보와 관측의 일치일 뿐이다.

## 합성 fixture 구성 방법

`baseOptions`와 `basePublication`은 논리적 입력 명세다. 실제 DB 스키마의 seed 파일이 아니다.
`scenarios[fixtureRef]`의 baseOptions 선택→overrides 적용→turnSetup 순서로 격리 수집기가 구성한다.
선택하지 않은 옵션은 검색 범위에서 제외한다. 원시 QA 내용은 만들거나 넣지 않는다.
현재 예산은 currentSalePriceKRW, 수집가 예산은 collectedSalePriceKRW와 시각으로 판정한다.
상품 참고가는 옵션 예산 판정에 쓰지 않는다. O06은 동일 상품의 서로 다른 옵션을 의도한다.
O09 generateOptions는 160개 고유 optionId를 만들며 페이지당 32개, 4페이지 경계를 관측한다.

`rights=synthetic_test_only`는 실제 발행 권리가 아니다. #229의 격리 fixture 발행 경로에만
매핑하며 기본 HTTP/운영 발행으로 노출하지 않는다. 합성 식약처 ID도 실제 ID가 아니다.
서비스가 요구하는 나머지 category/표준명/표시 순번/버전 필드는 수집기의 테스트 fixture로
일관되게 구성하고 실제 스냅샷 해시를 기록한다. 이 명세만으로 DB 통합 검증이 끝난 것이 아니다.

`turnSetup`의 followup은 직전 실제 응답 context를 사용한다. replay는 지정 턴의
requestId·본문·기준 context를 그대로 재사용한다. 철회·503은 그 뒤 테스트 환경에 주입한다.
M01은 클라이언트 후보 순서만 뒤집고 서버 상태는 보존한다. M08 기본형은 낡은 버전 충돌이다.
상세·이전 범위는 저장된 정확한 옵션을 재조회한다. 검색/상세가 만든 실제 상태를 다음 턴에
연결해야 하며 기대 결과로 stateBefore/stateAfter를 만들지 않는다.

## 실행 기록 수집 계약

한 JSONL 행은 `(caseId, turn, repeat)` 한 실행이다. 중복·알 수 없는 ID·반복 번호는 오류다.
동일 반복의 멀티턴은 runId가 같고 이전 stateAfter와 다음 stateBefore가 같아야 한다.
사례·반복 사이에는 새 격리 세션을 사용한다. 기록은 schema.json의 Observation을 따른다.

- provenance: mode/planner/dataKind, SUT commit, model, promptHash, 설정, 실행 시각,
  executionRef, fixtureHash, 실제 데이터 스냅샷 해시, 사전 해시.
- request: 실제 전송한 요청. 사례에 지정한 message/locale/requestType와 일치해야 한다.
  requestId/chatContext는 실행에서 얻는다. 인증키와 sessionToken은 출력하지 않는다.
- response/httpStatus: 실제 응답 원형. optionSearch/publishedClaims/optionClaimLinks를 보존한다.
- trace.plan: 실제 해석 결과의 camelCase SearchPlan. 정답 슬롯을 복사하지 않는다.
- trace.claimRequests: 실제 근거 조회 요청(용도·조건·발행 ID). 결과만 보고 역산하지 않는다.
- trace.identity.status / trace.comparison.sameEvidenceReused: 수집기에서 실제 표준명 조회와
  옵션별 근거 ID 대조를 관측한 값. 관측할 수 없다면 필드를 생략한다.
- trace.priorResponse: replay 대상이 된 실제 이전 응답. 토큰은 동일한 방식으로 제거한다.
- stateBefore/stateAfter: Redis에서 읽은 상태의 안정된 투영. stateVersion/resultSetId,
  candidateIds/selectedProductId/optionSelections/ingredientConditions/maxPriceKRW/
  priceBasis/requireInStock를 포함한다. null은 상태 미관측이며 '변화 없음' 증거가 아니다.

단계별 격리 실행 결과와 실제 전체 실행을 섞지 않는다. 앞 단계가 실패해 뒤 단계 검증이
불가능하면 그 단계 관측을 생성하지 않는다. 기능별 NOT_OBSERVABLE과 원인 로그를 함께 읽고,
필요하면 별도 통제 실행으로 해당 단계를 진단한다. 없는 의도·실행 결과를 추정해서 채우지 않는다.
공개 응답만 수집하면 내부 계획·Redis 상태 평가는 NOT_OBSERVABLE이 될 수 있다.

## 반복 채점 명령

backend/chatbot 디렉터리에서 기존 uv 환경을 사용한다. 의존성 추가는 없다.
기록 경로는 접근 통제된 기존 파일을 명시한다. 도구는 출력 파일을 만들지 않는다.

```powershell
$env:PYTHONDONTWRITEBYTECODE='1'
uv run --no-sync python -B -m tests.run_i3_eval --mode synthetic_contract --validate-only
uv run --no-sync python -B -m tests.run_i3_eval --mode synthetic_contract --observations <private-synthetic-observations.jsonl>
uv run --no-sync python -B -m tests.run_i3_eval --mode real_llm --observations <private-real-llm-observations.jsonl> --repeats 3
uv run --no-sync python -B -m pytest tests/test_i3_eval_grader.py -q -p no:cacheprovider
```

기록을 지정하지 않으면 synthetic은 47턴, real_llm은 141턴 모두 BLOCKED로 보고한다.
기본 시나리오 분모는 각각 36개·108회다. 턴 수로 멀티턴 사례를 과대 가중하지 않는다.
종료 코드: 0=검증 성공 또는 자동 후보 assertion 전부 통과, 1=실패, 2=관측 누락/차단.
종료 코드 0도 사람 의미 평가 또는 Gold 승인을 뜻하지 않는다.
보고서는 모드·파일 해시·턴/시나리오별 상태·축별 상태·Gold 보류·사람 검토 대기를 구분한다.

## 판정과 승인

자동: 계획 슬롯, 근거 용도/상태, 조건별 판정, 동일 옵션 연결, 가격 경계, 검색 범위,
상태 관계. 누락 필드는 empty와 다르며 NOT_OBSERVABLE이다. bool은 숫자로 인정하지 않는다.
추천 카드는 MATCH만 허용하지만 product_detail은 미충족/미확인 사실 설명을 허용한다.
연결 ID가 존재한다고 과학적 타당성까지 통과시키지 않는다. 사전/권리/적용 조건의 실제
유효성은 근거 서비스 관측과 사람 검토가 함께 필요하다.

사람: 근거 충실성·조건/범위 준수·불확실성·질문 충족·명료성 각 0~2점.
권리 없는 원문 노출, 근거 없는 효능/안전 보장, 다른 옵션 혼합, 철회 근거 재사용은 중대 실패다.
LLM judge는 보조 의견만 허용하며 Gold 승인이나 최종 사람 판정을 대신하지 않는다.
별도 QA 5건의 검수 완료만으로 이 36개 사례를 승인하지 않는다. 용도·권리·적용 범위·발행,
옵션 연결과 질문별 기대 결과를 각각 검토한다. 후보 파일의 status는 계속 candidate로 유지한다.
향후 Gold 승인 저장 방식은 별도 승인 범위다. 현재 schema는 approved 상태 자체를 거부한다.

제안 통과선(팀 승인 전): 결정적 필수 assertion 100%, 중대 실패 0건, 실제 LLM 핵심 슬롯
전체 일치율 95% 이상(3회 반복), 부정/가격 기준/조건 임의 변경 0건, 후속 필수 assertion 100%.
사람 평균 9/10 이상이며 근거·범위·불확실성은 각 2점. 실제 근거 보류 건수와 실행 누락을 공개한다.
36건은 초기 회귀 후보이며 일반적 안전성/정확도의 통계적 입증으로 사용하지 않는다.

## 보존과 한계

운영 서비스와 기존 359개 자료는 수정하지 않는다. 신규 질문과 합성 데이터만 공개 저장소에 둔다.
실제 QA 원문·권리 미확인 발췌·실제 응답 로그·토큰은 이 패키지에 넣지 않는다.
실제 기록은 권한이 있는 저장소에서 관리하고 식별자·해시로 추적한다.
이 버전의 자동 채점은 명시한 assertion과 공통 불변식의 범위다. 모든 자연어 의미나 전체
공개 API schema를 검증하는 대체물이 아니다. 실제 서비스 schema 검증은 실행 환경에서 수행한다.
비교/모순 처리·외국어 변형·변동 카탈로그·실기기 카드 표시는 별도 확인 공백으로 남는다.

## 이번 작성 단계 검증 기록 (2026-11-11)

| 검사 | 관측 결과 |
|---|---|
| 패키지 검증 | VALID, 36개 후보, 47턴, Gold 0, 서비스 실행 false |
| 최종 평가기 테스트 | 40 passed. 합성 단위 입력으로 채점기 오류 검증 |
| 신규 Python 3개 파일 Ruff | 통과 |
| 챗봇 계층 검사 | 3 kept, 0 broken |
| 전체 챗봇 pytest | 609 passed, 1 skipped, 1 failed. 추가 평가기 5개 검증 전 전체 실행 결과이며 최종 평가기 40개는 별도 통과 |
| 실패 재현 | 기존 test_style_recipe의 실제 로컬 HTTP 서버 기동 테스트가 12초 기동 제한으로 실패. 단독 재실행에서도 같은 실패 |
| 전체 챗봇 Ruff | 실행 당시 운영 beauty_consultation_service.py의 기존 E501 5건. 신규 파일 최종 검사와 구분 |
| 앱 typecheck | npm run typecheck 통과 |
| 앱 ESLint, 캐시 없음 | scripts/evaluate-skin-fusion.mjs의 Buffer no-undef 1개 오류, 경고 31개. 이 작업 범위 밖이므로 수정하지 않음 |
| 원 평가 자료 보존 | 기존 평가 디렉터리 31개 파일의 시작/검증 시점 SHA-256 일치 |

작업 중 다른 작업의 운영 서비스·앱 파일 변경이 관측됐다. 해당 파일을 수정/되돌리지 않았다.
전체 검사 결과는 그 시점의 공유 작업트리 결과이며 이번 8개 파일만의 회귀라고 단정하지 않는다.
실제 LLM, #229 합성 서비스 통합 실행, 실제 승인·발행 근거 평가는 이번에 실행하지 않았다.
관측 미제공 시 BLOCKED 분모를 유지하는 동작은 평가기 테스트로 검증했다.

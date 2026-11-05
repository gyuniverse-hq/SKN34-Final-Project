# Codex 작업지시서 — VISHUE 1-A Mock 평가 준비 및 실행

## 목표

현재 열려 있는 **`llm-ar-command` 계열 로컬 Codex worktree**의 실제 코드에 대해, `/api/chat`의 **립 절대 강도 명령 제안**이 올바른지 Mock 평가를 수행한다. 원래 코드와 기존 테스트를 손상하지 않고 현재 구현·목표 설계·미지원 기능을 구분해 결과를 보고한다.

## 작업 전에 꼭 알아야 할 사실

2026-10-30 연결된 GitHub `develop`에서 확인한 `backend/chatbot/app/routers/chat.py`는 `/api/chat`을 노출하지만, `schemas/chat.py`의 `ChatRequest`는 `message`, `locale`, `skin` 중심이고 **`arContext`가 없다**. `services/chat_service.py`는 그래프 상품 검색·LLM 답변 중심이다. **별도 로컬 1-A worktree는 이 대화에서 직접 확인하지 못했으므로, 사용자가 열어 둔 로컬 작업트리를 먼저 확인해야 한다.** GitHub develop을 로컬 구현으로 대체해서는 안 된다.

## 실행 순서

### 0. 읽기 전용 사전 조사

- 현재 작업 경로, 브랜치, HEAD, `git status --short`, Python, `uv` 설치 여부 기록
- `/api/chat` 라우터·요청·응답 schema, AR 분기·파서·검증기, 의존성 주입, 테스트 더블, 오류 스키마, API 인증·rate limit 확인
- `arContext` 분기, `action_proposed` 등 실제 반환 상태/필드를 코드 위치와 함께 정리
- 이전 `/api/chat` 일반 대화 경로를 회귀 테스트 대상으로 유지
- **1-A 코드가 없다면 이 단계에서 중단하고 '현재 해당 worktree에 구현 없음' 보고. 구현을 새로 작성하지 말 것.**

### 1. 평가 입력 계약 매핑

- 이 패키지의 `1A_mock_contract_cases_11.jsonl`을 사용한다.
- `request_contract_status=LOCAL_CODE_INSPECTION_REQUIRED`이므로 **입력 JSON을 그대로 보내지 않는다.** 실제 `arContext` schema에 맞는 요청/검증 도우미를 작성한다.
- 원래 359건의 리뷰 기록·정답 초안은 바꾸지 않는다.
- 다음 11개 하위 사례를 실험: E-AR-01·02·03·04·06·07-A·07-B·11·12, 0%·100% 경계값. E-AR-02는 현재 A2의 빈 레이어 조건에서만 검사한다.
- E-AR-07-A/B는 API 사용자 메시지로 깨진 JSON을 보내는 시험이 **아니다**. Fake LLM 또는 파서/검증기에 **잘못된 모델 출력**을 주입해야 한다. 주입 불가하면 `NOT_EXECUTED`로 보고한다.

### 2. Mock 테스트 작성·실행

- 실제 LLM API, Neo4j, Redis, 외부 인터넷, AR 렌더러를 호출하지 않는 독립 테스트 환경에서 실행
- 기존 테스트 더블 및 dependency override가 있다면 우선 재사용
- 테스트 시 **명령 제안만**, 앱 상태·상품·호수 변경 없이 그대로 유지하는지 별도 store/mock 관측으로 확인
- 지원 범위 밖/범위 초과/부정 발화/감탄/모델 출력 오류에 대해 명령 0개를 확인
- 0%·100% 경계값이 허용되는지 실제 계약과 비교, 다르면 **정책 또는 구현 차이로 분류**
- 결과를 `회귀 테스트 기존 `/api/chat``와 분리하여 기록. 기존 일반 대화 회귀 테스트 필수

### 3. 정규화된 평가 결과 생성

`evaluate_1a_predictions.py`가 읽는 `normalized_predictions.jsonl`을 생성한다. 각 줄은 다음 필드를 가진다.

```json
{
  "id":"E-AR-01",
  "test_mode":"MOCK",
  "outcome":"PROPOSAL",
  "commands":[{"targetZone":"lip","action":"set_intensity","value":0.5,"expectedStateVersion":3}],
  "claims_applied":false,
  "response_schema_valid":true,
  "side_effects":{"observed":true,"ar_state_changed":false,"source":"independent_mock_store_snapshot"},
  "answer":"립 강도 50% 변경을 제안할게요.",
  "injection_tested":false
}
```

- 위 JSON은 **평가용 정규화 형식**이며 실제 `/api/chat` 응답 형식으로 가정하지 않는다. `raw_responses.jsonl`도 따로 보존한다.
- `side_effects`의 결과는 **앱/스토어/Tool mock의 독립 관측**으로 넣는다. 응답 텍스트만 보고 `observed=true`를 지정하는 것은 금지.
- 주입 시험 E-AR-07은 `injection_tested=true`를 실제 주입 성공 시에만 기록.
- 원본 요청/응답에서 개인정보·토큰·얼굴 이미지·실제 음성은 저장하지 않는다.

### 4. 평가 실행

의존성이 이미 존재한다면 다음을 실행한다. 설치가 필요하면 먼저 목록·영향을 보고하고 승인받는다. `pyproject.toml`, `uv.lock`, 원래 worktree 및 전역 Python을 변경하지 않는다.

```bash
python -m unittest -v test_evaluate_1a_predictions.py
python evaluate_1a_predictions.py \
  --cases 1A_mock_contract_cases_11.jsonl \
  --predictions normalized_predictions.jsonl \
  --out 1a_results.csv
```

윈도우 PowerShell에서는 긴 명령을 한 줄로 입력해도 된다.

### 5. 최종 제출물

- 로컬 worktree/브랜치/HEAD와 읽은 파일 목록·실제 지원 범위
- 실제 요청·응답 스키마와 평가 정규화 필드의 매핑표
- **11개별 결과:** `MOCK_CONTRACT_OK_GOLD_PENDING`, `FAIL`, `NOT_EXECUTED`, `CONTRACT_ONLY_OBSERVATION_MISSING` 구분
- 분류별 실패 이유: `구현 미지원`, `코드/계약 불일치`, `Mock/fixture 오류`, `실제 기능 오류`, `정책 미확정`
- 일반 `/api/chat` 회귀 결과, 테스트 로그·명령·환경 차이
- 변경 파일 경로와 변경 이유, 테스트를 재현할 정확한 명령
- **기능 코드 변경·의존성 설치는 사용자 승인 전 수행하지 말 것.** 새로운 테스트 파일만 별도 worktree에 작성 가능. 사용자 기존 파일 수정 금지.

## 완료 기준(Definition of Done)

1. 현재 1-A 구현 존재 여부를 코드 근거로 확인한다.
2. 실행 가능한 각 사례에서 실제 Mock 반환과 가상 상태 변경 여부를 **독립 관측**으로 확인한다.
3. 지원되지 않는 사례는 억지로 PASS 처리하지 않고 `NOT_EXECUTED` 또는 목표-구현 차이로 기록한다.
4. 성공처럼 보여도 모든 결과는 `Gold 승인 대기` 상태로 남긴다.
5. 외부 호출·설치·원본 서비스 파일 변경 0건, 기존 일반 챗봇 회귀 경로 보존.

## 참조 코드 경로 (GitHub develop에서 확인, 로컬은 별도)

- `backend/chatbot/app/routers/chat.py` — `/api/chat`
- `backend/chatbot/app/schemas/chat.py` — 현재 공개 요청/응답
- `backend/chatbot/app/services/chat_service.py` — 상품 검색+LLM 응답 서비스
- `backend/chatbot/tests/test_chat.py` — 기존 일반 채팅 회귀 테스트
- `backend/chatbot/pyproject.toml`, `backend/chatbot/uv.lock` — 기존 환경, 설치 승인 조건 준수

기존 1-A 구현을 찾을 때는 `rg "arContext|action_proposed|set_intensity|expectedStateVersion|requestType" backend docs` 같은 문자열 검색을 활용할 것.

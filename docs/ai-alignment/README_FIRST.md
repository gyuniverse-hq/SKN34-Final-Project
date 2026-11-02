# VISHUE Codex 인계 패키지 — 2026-10-31

## 지금 무엇을 해야 하나

**목표:** 현재 로컬 `llm-ar-command` 작업트리에서 VISHUE `/api/chat`의 **립 절대 강도 명령 제안(1-A)** 구현 여부를 확인하고, 구현된 범위 안에서 **실제 Fake/Mock 실행 11건**을 평가한다. AR 앱 실제 적용(1-B), 외부 LLM/DB 호출, 359건 전체 평가를 이 작업으로 혼동하지 않는다.

1. **`CODEX_TASK_PROMPT.md`**를 Codex에 붙여넣고 이 폴더를 Codex가 접근할 수 있는 로컬 경로에 배치한다.
2. Codex가 현재 worktree/브랜치/HEAD와 `/api/chat`의 **실제 로컬 API 계약**을 읽도록 한다. GitHub `develop`의 2026-10-30 시점 schema에는 `arContext`가 없었으며 로컬 worktree는 확인하지 못했다.
3. 1-A 구현 확인 시 `01_run_1A/1A_mock_contract_cases_11.jsonl` → 실제 요청/응답 계약에 매핑 → Fake/Mock 테스트 → `evaluate_1a_predictions.py` 채점 순서로 진행한다. **본 문서는 11건이 이미 실제 코드에서 통과했다는 주장이 아니다.**
4. 끝나면 테스트 결과·근거 파일 경로·구현 부재/기능 버그/fixture 문제를 구분해 보고한다. 코드 수정은 사용자 승인 후 별도 단계다.

## 파일별 권위(source of truth)

| 목적 | 기준 파일 | 다른 파일과 관계 |
|---|---|---|
| **현재 검수 상태** | `02_latest_review/VISHUE_review_cumulative_359_20261030.jsonl` | 승인 후보 25·보류 10·미검수 324. **Gold 승인 0, 실사용 테스트 0** |
| **전체 사례 정의** | `03_future_full_eval/cases_v1.3.jsonl` | 359개 전체 설계·평가 필드를 가진 이전 버전 정의. 현재 검수 상태는 위 최신본을 우선한다. **ID로 조인** |
| **현재 테스트 입력 fixture** | `01_run_1A/fixtures_world_patched.json` + `resolved_inputs_359_fixture_patch.jsonl` | 8개 사례 맥락 수정 사본. 원본 평가 질문과 정답 초안은 유지 |
| **1-A 현재 실행 후보** | `01_run_1A/1A_mock_contract_cases_11.jsonl` | 359개 중 일부 + 경계값 하위 사례. `LOCAL_CODE_INSPECTION_REQUIRED` 확인 뒤 매핑해야 함 |
| **1-A 평가기** | `01_run_1A/evaluate_1a_predictions.py` | 서비스 구현 코드가 아닌 독립 채점기. 단위 테스트를 실제 1-A 통과로 오해 금지 |
| **보류와 팀 질문** | `02_latest_review/VISHUE_hold_resolution_10_20261030.json`, `01_run_1A/02_팀에_확인할_질문.md` | 코드를 추측해서 정책을 정하지 말고 팀 확인 |
| **842 발화 색인** | `03_future_full_eval/source_U842_link_review_v1.3.jsonl` | ID·의도 연결만 확인. `original_text=null` 842건, **문장별 의미 검수 미완료** |
| **후속 확장 평가** | `03_future_full_eval/run_evals_v1.3.py`, `multiturn_160_turn_review_v1.3.jsonl` | 현재 1-A 작업에 즉시 실행하거나 전체 통과를 주장하지 않음 |

## 작업 순서(순차 + 병행)

- **지금:** 1-A 존재 여부/계약 확인 → Mock 11개 결과 생성 → 독립 관측을 포함해 채점 → 기존 `/api/chat` 회귀 확인.
- **병행:** AR-02/13/14, PR-04/06/08, ST-01/03/07/08 팀 정책·fixture 보류 확인.
- **후속:** 1-B 실제 적용/ACK → 통합 평가 → 나머지 324건 Gold 검수·842개 의미 대응.

## 금지·주의

- `develop`에 없는 `arContext`를 로컬 구현에 있다고 가정하지 않는다.
- Fake 샘플 결과를 실제 LLM/AR 통과로 보고하지 않는다.
- `APPROVAL_CANDIDATE`를 최종 Gold 승인으로 간주하지 않는다.
- 사용자 허가 없이 원본 worktree, 실제 기능 파일, `uv.lock`, `pyproject.toml`을 수정하거나 의존성을 설치하지 않는다.
- 화면·LLM·카탈로그·호수 데이터의 가상 ID를 운영 데이터로 오인하지 않는다.
- 기존 일반 `/api/chat` 회귀를 건너뛰지 않는다.

## 패키지 구성

- `01_run_1A/`: 지금 실행할 1-A Mock 자료·평가기·기존 Codex 상세 지시서·팀 질문
- `02_latest_review/`: 최신 누적 검수·보류 10건·사람 검토용 Excel
- `03_future_full_eval/`: 전체 359건 설계·842 U-ID 색인·160턴·46 TC·전면 평가 도구
- `MANIFEST_SHA256.json`: 전달 파일 SHA-256 무결성 목록
- `VALIDATION.json`: 구조·건수·검사 결과

**전달 시 추천:** Codex에 이 전체 폴더와 `CODEX_TASK_PROMPT.md`를 함께 전달. 루트에서 자료를 읽고, 테스트 코드는 별도 평가 디렉터리에서 실행할 것.

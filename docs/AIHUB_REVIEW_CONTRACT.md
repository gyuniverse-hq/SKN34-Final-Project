# AIHub I-1 데이터 검수 계약

AIHub 71961 「문제성 피부 메이크업 추천 데이터」의 등록, 근거 검수, 발행 기준을 정의합니다.
검수자는 국내 로컬 PostgreSQL에서 전체 QA 목록과 개별 검수 기록을 조회하고 관리할 수 있습니다.
보관 범위와 원문 접근 기준은 [데이터 이용권한 결정](AIHUB_DATA_RIGHTS.md)을 따릅니다.
원본 구조와 적재 경로는 [적재 README](../scripts/data/aihub/README.md)에 있습니다.

## 1. 등록과 검수 상태

| 대상 | 저장 위치 | 식별자와 상태 |
| --- | --- | --- |
| 배포본과 원본 QA | `aihub_dataset_release`, `aihub_qa_case_raw` | 배포본 해시, 원본 `SEQ`, 분할, QA별 SHA-256. 등록 시 배포본 권리는 `local_only` |
| 전체 검수 목록 | `aihub_qa_case` | 원본 `SEQ`, 고민 유형 코드 13종, `review_progress` |
| 원본 출처 | `aihub_qa_source_link` | `(seq, source_position)`와 파일 연결 결과. `quote_match_status`는 인용 확인 결과 |
| 문서 개정본 | `aihub_knowledge_document` | `document_id`와 내용 SHA-256. 판본이 식별되면 `(source_identifier, source_version)`으로 묶음 |
| 주장 개정본 | `aihub_claim_version` | 논리 ID `claim_key`, 개정 번호 `revision`, 물리 ID `claim_version_id`, 적용 조건 및 허용 용도 |
| QA와 주장의 관계 | `aihub_qa_claim` | `(seq, claim_version_id)`, 원본 안의 위치 `answer_locator`. QA 하나에 여러 주장, 주장 하나에 여러 QA 연결 가능 |
| 개별 근거 판정 | `aihub_claim_review` | `claim_id`로 검수 기록 식별. 주장 개정본, 원본 출처 자리, 검토한 문서 개정본, 위치와 연구 유형 기록 |

QA와 주장에는 진행 상태가 각각 있습니다. `not_started`에서 시작하고, 작업을 시작하면
`in_progress`, 검토가 끝나면 `completed`로 기록합니다. QA의 완료는 답변의 주장 식별과
검토 기록이 끝났음을 표시합니다. 기존 `qa_case.review_status`와 이전 근거 기록은
이력과 호환성을 위해 보존합니다.

주장 승인 결과인 `approval_status`는 진행 상태가 완료되기 전까지 비어 있습니다.
완료 시 검수자, 검수 시각, 사유와 함께 `approved`, `limited_approved`, `on_hold`,
`excluded` 중 하나를 기록합니다. 승인·제한 승인은 `explain`, `rank`, `avoid` 중
허용한 용도를 지정합니다. 제한 승인에는 대상, 사용 부위, 제형, 농도 등 근거의 적용
조건을 구조화해 남깁니다. 보류·제외의 허용 용도는 빈 배열입니다.

| 근거 판정 | 의미 |
| --- | --- |
| `pending` | 아직 근거를 판정하지 않음 |
| `direct` | 해당 조건의 주장을 직접 뒷받침 |
| `limited` | 일부 대상·제형·조건에서 뒷받침 |
| `indirect` | 다른 대상·제형 등에서 관련성을 제시 |
| `insufficient` | 판단할 근거가 부족함 |
| `contradicting` | 해당 주장을 반박하는 근거가 있음 |
| `unverifiable` | 출처를 찾을 수 없거나 본문을 확인할 수 없음 |

`direct`, `limited`, `indirect`, `contradicting`에는 검토한 문서 ID, 문서 내 위치,
연구 유형이 필요합니다. 판정에는 검수자, 날짜, 한계나 사유를 담은 메모가 필요합니다.
원본 출처가 미연결이면 문서 ID 없이 해당 출처 자리에 `pending`을 기록할 수 있습니다.
`match_status`, `support_status`, `approval_status`, `rights_status`는 각각 따로 판정합니다.

동일 주장을 다시 검토하거나 문구·조건·근거를 바꾸면 같은 `claim_key`에 다음
`revision`을 추가합니다. 새 개정본은 미승인으로 시작하며, 연결할 QA와 근거를 새
개정본에 기록합니다. 같은 자료의 새 판본은 다른 문서 ID에 같은 `source_identifier`와
새 `source_version`을 기록합니다. 근거 검수는 매칭 결과가 갱신된 뒤에도 검토 당시의
`document_id`와 내용 해시로 추적합니다. 검수 전인 원본 문서는 확인 가능한 버전 정보가
생길 때까지 두 버전 필드를 비워 둡니다.

성분 표기 검수는 기존 `aihub_ingredient_mention.mapping_review_status`를 사용합니다.
성분 ID를 연결하려면 검수자와 검수 날짜가 포함된 승인 기록이 필요합니다.

## 2. 로컬 등록과 검증

`backend/api`에서 격리한 PostgreSQL을 `DATABASE_URL`로 지정하고
`uv run alembic current`, `uv run alembic heads`로 이력을 확인합니다.
`develop`의 `0018` 다음 리비전은 `aihub_claim_review_v1`입니다. 앞선 별도 이력의
`0019`는 이 리비전과 다르므로 대상의 리비전이 `0019`라면 이력을 먼저 대조합니다.
기존 성분 언급에 동일한 `(seq, mention_type, raw_text)`가 여러 번 저장된 DB는 중복
행의 검수 기록을 대조한 뒤 마이그레이션을 재시도해야 합니다. 마이그레이션은 해당
상태에서 행을 보존하고 중단합니다. 다운그레이드도 I-1 검수나 문서 버전 기록이
있으면 중단합니다.

```powershell
uv run alembic upgrade head
uv run --group data python ..\..\scripts\data\aihub\analyze_qa.py --register "$dataDir" --port 15434 --database vishue_i1 --user vishue_i1
uv run python ..\..\scripts\data\aihub\analyze_qa.py --port 15434 --database vishue_i1 --user vishue_i1 --inventory --verify-release
```

`$dataDir`에는 본인이 받은 AIHub `3.개방데이터\1.데이터` 경로를 지정합니다.
`--register`는 기존 `load_all.py`를 이용해 QA, 문서, 출처 매칭, 성분 언급을 등록합니다.
동일한 ZIP 집합을 다시 지정하면 기존 배포본을 재사용합니다. 이미 끝난 단계는 건너뛰고,
실패해 남은 단계는 재시도합니다. 서로 다른 원본 해시나 기존 배포본 중복이 있으면
이력을 확인할 수 있도록 중단합니다. 최초 등록과 재등록의 진입점으로 `--register`를
사용합니다.

배포본 1건은 동일한 ZIP 집합의 등록 이력 1건을 뜻합니다. 등록된 배포본의 권리는
`local_only`입니다. 주장 승인은 검수 결과에서 따로 집계하며, 서비스 발행은 명시적인
후속 작업입니다.

`--verify-release` 검증은 DB를 읽어 초기 적재 기준과 대조하며 불일치 시 종료 코드 1을
반환합니다. 검수 중에 문서 판본을 추가하거나 출처를 교정하면 현재 집계가 초기 기준과
달라질 수 있습니다.

기준은 QA 9,031건(학습 8,031, 검증 1,000), 출처 참조 9,181개(연결 8,957, 미연결
224), 고유 문서 3,108개, 문서 파일 6,245개, 성분 언급 18,062개입니다. 문서가 연결된 QA는 8,821건,
연결 문서가 없는 QA는 210건입니다. 진행 상태와 주장 승인 건수는 작업 중 달라질 수
있어서 집계에 표시하고 기준 건수 대조에서는 제외합니다.

`--inventory --list`는 전체 QA의 ID, 분할, 배포본, 유형, 진행 상태와 출처 연결 여부를
출력합니다. `--qa SEQ`를 반복하면 지정한 QA의 출처와 주장별 개정 이력을 함께 볼 수
있습니다. 응답에는 원본 본문과 발췌를 포함하지 않습니다.

```powershell
uv run python ..\..\scripts\data\aihub\analyze_qa.py --port 15434 --database vishue_i1 --user vishue_i1 --inventory --qa "$qaSeq"
```

권한 있는 검수자는 원문을 국내 로컬 DB에서 직접 확인하고 같은 트랜잭션으로 기록을
남깁니다. 아래는 psql에서 `seq`, `claim_key`(UUID), `canonical_text`,
`answer_locator`, `source_position` 변수를 설정한 뒤 최초 검수 후보를 저장하는 예입니다.
개정본을 추가할 때는 기존 논리 ID를 쓰고 개정 번호를 늘립니다. 여러 작업자가 같은
주장을 개정하면 `(claim_key, revision)` 고유 제약에 맞춰 최신 개정 번호를 다시 확인합니다.

```sql
BEGIN;
WITH version AS (
    INSERT INTO public.aihub_claim_version (claim_key, revision, canonical_text)
    VALUES (:'claim_key'::uuid, 1, :'canonical_text')
    RETURNING claim_version_id
), qa_claim AS (
    INSERT INTO public.aihub_qa_claim (seq, claim_version_id, answer_locator)
    SELECT :'seq', claim_version_id, :'answer_locator' FROM version
    RETURNING seq, claim_version_id
)
INSERT INTO public.aihub_claim_review (seq, claim_version_id, source_position, document_id)
SELECT qc.seq, qc.claim_version_id, s.source_position, s.document_id
FROM qa_claim qc
JOIN public.aihub_qa_source_link s ON s.seq = qc.seq
WHERE s.source_position = :'source_position'::smallint;

UPDATE public.aihub_qa_case
SET review_progress = 'in_progress'
WHERE seq = :'seq' AND review_progress = 'not_started';
COMMIT;
```

검수 후에는 `aihub_claim_review`에 출처별 판정·검수 근거를 기록하고
`aihub_claim_version`의 진행 상태와 승인 결과를 함께 갱신합니다. 판정이 끝난 개정본의
결론을 바꾸려면 새 개정본을 만듭니다. 검수자의 쓰기 경로는 I-1에서 로컬 SQL입니다.

### 격리 DB 복구 확인

본인에게 이용 권한이 있는 국내 격리 환경에서, 비어 있는 별도 DB에 원본과 검수 기록을
함께 복구합니다. 아래 명령은 로컬 검증 컨테이너 내부에서 백업을 스트리밍합니다.

```powershell
docker exec vishue-i1-postgres sh -ec 'createdb -U vishue_i1 vishue_i1_restore && pg_dump -U vishue_i1 -Fc vishue_i1 | pg_restore -U vishue_i1 -d vishue_i1_restore --exit-on-error --no-owner --no-privileges'
uv run python ..\..\scripts\data\aihub\analyze_qa.py --port 15434 --database vishue_i1_restore --user vishue_i1 --inventory --verify-release
```

복구본의 Alembic 리비전, 배포본 수와 권리, QA 진행 상태, 주장 개정과 근거 판정을
원본 DB와 대조합니다. 복구본에 같은 ZIP 집합으로 `--register`를 실행하면 기존 배포본을
재사용합니다. 원본 자료, 덤프와 접속 정보는 국내의 접근 통제된 저장소에만 보관합니다.

## 3. I-3의 승인된 주장 조회 계약

서비스 조회의 입력은 고민 코드, 적용 조건, 사용 용도입니다. 발행 대상에는 다음 조건이
모두 필요합니다.

1. `claim_key`의 최신 개정본이 `completed`이며 `approved` 또는 `limited_approved`입니다.
   요청 용도가 `approved_uses`에 있고, 요청 조건이 그 개정본의 `applicability`에 들어갑니다.
2. 같은 개정본에 문서 ID, 문서 내 위치, 연구 유형, 한계가 검수된 근거가 있습니다. 직접
   근거를 기본으로 쓰고, 제한·간접 근거는 검수자가 명시한 적용 조건과 허용 용도 안에서
   제시합니다. 상충하는 근거가 발견되면 새 개정본에서 재검토합니다.
3. 연결된 배포본, 사용하려는 문서 개정본과 근거에 `service_approved` 권리가 확인됩니다.
   권리 확인에는 발행하려는 요약·서지정보의 사용 목적과 범위도 포함합니다.
4. 해당 `claim_version_id`와 근거 ID를 명시적으로 발행 대상으로 등록합니다. 검수 승인
   이후에 수행하는 발행 작업이며 I-3에서 구현합니다.

발행 결과의 `facts`는 승인된 요약, `claimKey`, `revision`, `approvedUses`,
`applicability`, `reviewedAt`을 담습니다. `evidence`는 발행이 허용된 서지 정보,
`documentId`, `sourceVersion`, `supportStatus`, 연구 유형과 한계를 담습니다.
서비스 응답에서 원본 QA ID, 대상자 ID, 질문·답변 원문, 인용문, 파일 경로는 제외합니다.
원본 자료의 본문 색인이나 외부 전송은 별도의 이용권한 확인을 거칩니다.

| 조회 상태 | 뜻 |
| --- | --- |
| `approved_evidence` | 조건에 맞는 승인·발행 개정본이 있음 |
| `no_match` | 조건에 맞는 후보가 없음 |
| `evidence_pending` | 근거·검수·발행 확인이 남아 있음 |
| `rights_blocked` | 사용 권리가 미확정이거나 사용 제한에 해당함 |

I-2는 기존 카탈로그를 정본으로 상품 ID, 옵션 ID, 전성분 출처, 옵션별 전성분 확보 여부의
계약을 정합니다. 전성분이 미확보된 상품·옵션의 성분 포함 여부는 미확인으로 전달합니다.
I-3은 승인·발행 근거와 I-2 계약을 상담에 연결하고 근거 부족 및 미확인 데이터의 응답을
검증합니다.

## 4. 검수 후보와 작업량

기존 적재 환경에서 측정한 수치입니다. 표기 분류와 문서 확인은 고유 항목을 묶어
진행할 수 있습니다. 주장에 대한 판단은 각 주장 개정본과 연결된 근거에 남깁니다.

| 대상 | 전체 | 실제 검수 단위 |
| --- | ---: | ---: |
| 성분 표기 | 18,062건 | **고유 4,095종** |
| 그중 식약처 표준명 일치 | 4,560건 (25.2%) | 표준명 일치 후보 |
| 그 밖의 표기 | 13,502건 (74.8%) | 사람 판정 필요 |
| 지식 문서 | 3,108개 | QA 참조 **1,230개** 우선 |
| QA 사례 | 9,031건 | 근거 연결된 **8,821건** |

성분 표기의 모양별 분포입니다. 유형마다 판정 방법이 다릅니다.

| 모양 | 건수 | 비율 | 판정 방법 |
| --- | ---: | ---: | --- |
| 영문·학명만 | 5,679 | 31.4% | 영문명·학명을 한글 표준명에 대응. 자동 매칭 금지 |
| 식약처 표준명 일치 | 4,560 | 25.2% | 표준명 일치 후보 |
| 한글 단일어 | 3,508 | 19.4% | 표기 변형 또는 성분군 |
| 한글+공백 | 3,063 | 17.0% | 수식어 결합 가능성 |
| 한글+괄호 | 1,185 | 6.6% | 괄호 안이 수식어인지 다른 이름인지 |
| 비한글 혼합 | 67 | 0.4% | 개별 확인 |

**영문명 자동 매칭을 하지 않습니다.** 식약처 자료에서 `Water` 의 영문명을 따라가면
`탄산수` 가 나오고 정답은 `정제수` 입니다. 기존 성분 매핑 작업에서 확인된 사실이며
같은 규칙을 적용합니다. 자세한 기준은 `scripts/data/ingredients/README.md` 에 있습니다.

성분군으로 보이는 표기(`레티노이드`, `계면활성제`, `파라벤`, `합성타르색소` 등)는 단일
성분이 아니므로 하나의 식약처 성분에 연결하지 않습니다. 범위를 정의해야 합니다.

## 5. 평가 자료로 쓸 때의 제약

제공된 학습·검증 분할을 그대로 평가에 쓰면 사람 단위로 샙니다.

| 항목 | 값 |
| --- | ---: |
| 학습 QA / 고유 대상자 | 8,031 / 5,719 |
| 검증 QA / 고유 대상자 | 1,000 / 928 |
| 양쪽에 걸친 대상자 | **339** |
| 그 대상자의 검증 QA | **403 / 1,000 (40.3%)** |
| 질문·답변이 양쪽 분할에 등장 | 0 |

**검증 1,000건 중 403건이 학습과 같은 대상자에게서 나왔습니다.** 완전히 같은
질문·답변의 교차 중복은 없지만, 같은 사람의 다른 질문이므로 유사도 누출 위험이
있습니다. 평가에 쓰려면 **대상자 ID 단위로 다시 분할**해야 합니다.

추천 성분과 주의 성분이 같은 문자열인 QA 가 4건 있습니다. 요청서의 기존 자동 검사
결과와 같습니다.

## 6. I-1에서 관리하는 범위

I-1은 QA 9,031건의 국내 로컬 등록과 전체 상태 조회, 그리고 개별 주장·출처 개정본의
검수 기록 저장을 제공합니다. 주장 검수는 검수자가 시작하며 등록과 동시에 생성되는
승인·발행 기록은 없습니다. 검수 승인, 권리 확인, 발행은 각각 별도 결정입니다.
I-2에서는 상품·옵션 계약을 정하고 I-3에서는 승인 지식 조회를 상담에 연결합니다.

# AI-Hub Review Status and Knowledge Query Contract

AI-Hub 데이터의 검수 상태 전환 규칙과, 지식 조회를 쓰는 쪽에 주는 계약입니다.
`VISHUE_AIHUB_DB_Handoff_20261102` 요청서의 **2단계 산출물**입니다.

**이 문서는 설계이며 서비스 활성화가 아닙니다.** 현재 승인된 자료는 0건이고 조회
인터페이스는 구현되어 있지 않습니다.

- 저장·권한 결정: `docs/AIHUB_DATA_RIGHTS.md`
- 적재 결과: `docs/AIHUB_INGEST_REPORT.md`
- 스키마와 실행: `scripts/data/aihub/README.md`

## 1. 상태 축이 네 개입니다

한 축에 몰아넣지 않았습니다. 섞으면 "원본이 읽혔다" 와 "근거가 검증됐다" 를 구분할 수
없게 됩니다.

| 축 | 컬럼 | 대상 |
| --- | --- | --- |
| QA 검수 | `qa_case.review_status` | 상담 사례 9,031건 |
| 문서 검수 | `knowledge_document.review_status` | 지식 문서 3,108건 |
| 이용권한 | `knowledge_document.rights_status`, `dataset_release.rights_status` | 문서·배포본 |
| 성분 표기 검수 | `ingredient_mention.mapping_review_status` | 성분 언급 18,062건 |
| 주장·근거 판정 | `claim_review.support_status` | 개별 주장 |

### 요청서의 두 목록을 어떻게 대응시켰는지

요청서에 상태 목록이 둘 있습니다. 01 문서의 검수 수명주기와 03 문서의 보고용 품질
상태입니다. 아래처럼 해석했습니다. **AI 담당 확인이 필요한 부분입니다.**

| 03 문서의 품질 상태 | 이 설계에서 | 근거 |
| --- | --- | --- |
| `parsed` | 컬럼 없음 | 9,031건 전부 파싱 성공이라 구분이 무의미 |
| `source_matched` | `qa_source_link.match_status = 'matched'` 로 유도 | QA 단위가 아니라 출처 자리 단위 속성 |
| `claim_review_pending` | `claim_review.support_status = 'pending'` | |
| `evidence_approved` | `qa_case.review_status = 'approved'` | |
| `blocked` | `review_status = 'rejected'` 또는 `'rights_blocked'` | 사유를 구분하기 위해 둘로 나눔 |

## 2. 전환 규칙

### QA 검수 (`qa_case.review_status`)

| 상태 | 뜻 | 다음으로 가는 조건 |
| --- | --- | --- |
| `ingested` | 원본만 보존 | 기본값. 적재 자체는 승인이 아님 |
| `needs_review` | 검토 대상으로 지정 | 사람이 검토 대기열에 올림 |
| `approved` | 사용 조건과 근거 검증 통과 | 아래 네 조건을 **모두** 충족 |
| `rejected` | 사용하지 않음 | 주제 불일치·근거 격차 등으로 판정 |
| `rights_blocked` | 권리 미확정·불가 | 연결 문서의 `rights_status` 가 승인 아님 |

`approved` 로 올리는 조건입니다. 하나라도 빠지면 올리지 않습니다.

1. `qa_source_link` 에 `match_status = 'matched'` 인 출처가 하나 이상 있다
2. 그 출처의 문서가 `rights_status = 'service_approved'` 이다
3. 그 QA 에 대한 `claim_review.support_status` 가 `direct` 또는 `indirect` 이고,
   `reviewer` 와 `reviewed_at` 이 채워져 있다
4. 배포본의 `dataset_release.rights_status` 가 `service_approved` 이다

**`parsed` 나 `source_matched` 가 자동으로 `approved` 가 되는 규칙을 만들지 않습니다.**
출처가 연결됐다는 것은 파일이 이어졌다는 뜻이지 그 문서가 주장을 입증한다는 뜻이
아닙니다.

### 문서 검수 (`knowledge_document`)

`rights_status` 는 `pending_confirmation` 에서 시작합니다. `service_approved` 로
올리려면 두 가지가 필요합니다.

1. `purpose_raw` 와 `cautions_raw` 가 있고, 그 내용이 서비스 이용을 막지 않는다
2. 배포본 수준의 이용권한이 확인되었다

**메타데이터가 없는 문서 124개는 이용조건을 확인할 수 없으므로 올리지 않습니다.**

**QA 가 참조하지 않는 문서 1,878개(전체의 60%)는 QA 를 통한 검증 경로가 없습니다.**
고유 문서 3,108개 중 QA 가 가리키는 것은 1,230개입니다. 이 문서들을 QA 연결 문서와
같은 등급으로 두지 않습니다.

### 성분 표기 검수 (`ingredient_mention`)

| 상태 | 뜻 |
| --- | --- |
| `pending` | 분류·검수 전. 기본값 |
| `approved` | 사람이 원료로 확정하고 식약처 성분에 연결 |
| `rejected` | 원료가 아니거나 연결 불가로 판정 |

`entity_kind` 는 식약처 현행 표준명과 정확히 일치할 때만 `ingredient` 이고 나머지는
`unknown` 입니다. 영문명·학명·성분군·수식어가 붙은 표기를 자동 판정하지 않습니다.

`mfds_ingredient_id` 는 `mapping_review_status = 'approved'` 이고 `reviewer` 와
`reviewed_at` 이 있을 때만 채울 수 있습니다. 테이블 제약으로 강제합니다.

### 주장·근거 판정 (`claim_review`)

| 상태 | 뜻 |
| --- | --- |
| `pending` | 판정 전 |
| `direct` | 근거 문서가 그 주장을 직접 입증 |
| `indirect` | 관련은 있으나 직접 입증은 아님 |
| `insufficient` | 근거가 부족 |
| `contradicting` | 근거가 주장과 상충 |

표본 검증 26건에서 실제로 나온 판정 유형을 그대로 씁니다. `pending` 이 아니면
`reviewer` 와 `reviewed_at` 이 반드시 있어야 하며 제약으로 강제합니다.

## 3. 지식 조회 계약

구현 전 설계이며 서버 API 가 준비되었다는 뜻이 아닙니다.

조회하는 쪽에 주는 식별자는 다음과 같습니다. **원문 발췌는 주지 않습니다.**

| 필드 | 출처 |
| --- | --- |
| `caseId` | `qa_case.seq` |
| `skinType` | `skin_type.skin_type_normalized` (4종) |
| `skinConcern` | `skin_concern.concern_code` (13종) |
| `evidenceId` | `knowledge_document.document_id` |
| `sourceTitle` | `knowledge_document.title_raw` |
| `sourceYear` | `knowledge_document.publication_year_raw` |
| `sourceType` | `knowledge_document.source_type_raw` |
| `supportStatus` | `claim_review.support_status` |
| `rightsStatus` | `knowledge_document.rights_status` |
| `reviewedAt` | `claim_review.reviewed_at` |
| `studyLimit` | 근거의 한계. 문서 메타에 있으면 함께 |

응답 상태는 네 가지입니다.

| `status` | 조건 |
| --- | --- |
| `approved_evidence` | 승인된 근거가 있음 |
| `no_match` | 조건에 맞는 사례가 없음 |
| `evidence_pending` | 사례는 있으나 근거 검증 전 |
| `rights_blocked` | 이용권한 미확정 또는 불가 |

**현재는 모든 질의가 `evidence_pending` 또는 `rights_blocked` 입니다.** 승인된 자료가
0건이기 때문입니다.

조회 대상은 `review_status = 'approved'` 인 QA 와 `rights_status = 'service_approved'`
인 문서로 한정합니다. 그 외는 조회 결과에 포함하지 않습니다.

**제품 정보는 이 경로로 주지 않습니다.** 상품·호수·가격·전성분의 정본은 `products`,
`shades`, `raw_oy_option_ingredient` 입니다. AI-Hub 의 추천 성분이 상품 전성분을
대체하지 않으며, 전성분이 미확보된 상품에 대해 '해당 성분 없음' 으로 단정하지 않습니다.

## 3-1. 샘플 조회 결과 (마스킹)

**원문 발췌를 포함하지 않습니다.** 인용문(`quote_raw`)과 질문·답변 본문은 조회 결과에
넣지 않으며, 이 문서에도 싣지 않습니다. 내부 식별자와 검수 상태만 오갑니다.

### 지금 상태에서 실제로 나오는 응답

조건: 복합성 피부, 홍조(`05`), 볼 부위.

```json
{
  "status": "evidence_pending",
  "intent": "makeup_advice",
  "skinType": { "value": "combination", "source": "user_report" },
  "skinConcerns": ["05"],
  "facts": [],
  "evidence": [],
  "rightsStatus": "pending_confirmation",
  "limitations": [
    "근거 검증 전",
    "이용권한 확인 전"
  ]
}
```

`facts` 와 `evidence` 가 빈 이유는 조회할 자료가 없어서가 아니라 **승인된 자료가 0건**
이기 때문입니다. 해당 조건의 QA 는 실제로 존재하며 `review_status = 'ingested'` 입니다.

조회 대상을 세는 질의입니다. 이 값이 0 이 아니게 되려면 §2 의 `approved` 조건 네 가지를
모두 통과해야 합니다.

```sql
SELECT COUNT(*) AS approved_cases
FROM public.aihub_qa_case q
JOIN public.aihub_skin_type t ON t.skin_type_raw = q.skin_type_raw
WHERE t.skin_type_normalized = 'combination'
  AND q.concern_code = '05'
  AND q.review_status = 'approved';
```

### 승인 이후에 나올 모양

아직 발생하지 않은 응답의 형태입니다. 값은 자리표시자입니다.

```json
{
  "status": "approved_evidence",
  "intent": "makeup_advice",
  "skinType": { "value": "combination", "source": "user_report" },
  "skinConcerns": ["05"],
  "facts": [
    { "caseId": "<qa_case.seq>", "reviewedAt": "<claim_review.reviewed_at>" }
  ],
  "evidence": [
    {
      "evidenceId": "<knowledge_document.document_id>",
      "sourceTitle": "<knowledge_document.title_raw>",
      "sourceYear": "<knowledge_document.publication_year_raw>",
      "sourceType": "<knowledge_document.source_type_raw>",
      "supportStatus": "direct",
      "rightsStatus": "service_approved",
      "studyLimit": "<근거의 한계. 있으면 그대로>"
    }
  ],
  "rightsStatus": "service_approved",
  "limitations": [
    "상담 사례이며 의학적 진단이 아님"
  ]
}
```

`supportStatus` 가 `indirect` 인 근거는 `limitations` 에 그 사실을 적습니다.
`insufficient` 와 `contradicting` 은 `evidence` 에 넣지 않습니다.

### 사람이 원문을 확인하는 경로

검수자는 DB 에서 직접 읽습니다. 조회 API 를 거치지 않습니다.

```powershell
uv run python ..\..\scripts\data\aihub\browse_qa.py --database vishue_db --port 15432 --concern 05 --limit 10 --out ..\..\data\aihub-qa-05.txt
```

출력 파일은 저장소에 커밋하지 않습니다(`data/` 는 추적되지 않습니다).

## 4. 검수 후보와 작업량

측정된 수치입니다. 검수는 건수가 아니라 고유 표기·고유 문서 단위로 합니다.

| 대상 | 전체 | 실제 검수 단위 |
| --- | ---: | ---: |
| 성분 표기 | 18,062건 | **고유 4,095종** |
| 그중 식약처 표준명 일치 | 4,560건 (25.2%) | 자동 분류됨 |
| 그 밖의 표기 | 13,502건 (74.8%) | 사람 판정 필요 |
| 지식 문서 | 3,108개 | QA 참조 **1,230개** 우선 |
| QA 사례 | 9,031건 | 근거 연결된 **8,821건** |

성분 표기의 모양별 분포입니다. 유형마다 판정 방법이 다릅니다.

| 모양 | 건수 | 비율 | 판정 방법 |
| --- | ---: | ---: | --- |
| 영문·학명만 | 5,679 | 31.4% | 영문명·학명을 한글 표준명에 대응. 자동 매칭 금지 |
| 식약처 표준명 일치 | 4,560 | 25.2% | 완료 |
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

## 6. 서비스가 활성화되지 않았다는 근거

| 항목 | 현재 |
| --- | --- |
| `qa_case.review_status = 'approved'` | **0건** (전부 `ingested`) |
| `knowledge_document.rights_status = 'service_approved'` | **0건** |
| `claim_review` 행 수 | **0** |
| `ingredient_mention.mfds_ingredient_id` 가 채워진 행 | **0** |
| 공용 DB 의 `aihub` 스키마 | **없음** (생성하지 않음) |
| 원본·발췌를 읽는 API·서비스 코드 | 없음 |
| 벡터 색인·임베딩 | 없음 |

조회 인터페이스는 설계만 있고 구현되어 있지 않습니다. 활성화는 국외 반출 또는 국내
보관 위치 확정, 데이터셋 개별 이용조건 확인, 근거 검토 통과를 모두 거친 뒤 별도
작업으로 분리합니다.

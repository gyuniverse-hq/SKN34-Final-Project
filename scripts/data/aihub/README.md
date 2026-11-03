# AI-Hub 문제성 피부 메이크업 추천 데이터

AI-Hub 「문제성 피부 메이크업 추천 데이터」(datasetSn 71961)를 로컬 DB 의 `aihub`
스키마에 보존하고 구조화합니다.

- 이용권한과 보관 위치 결정: `docs/AIHUB_DATA_RIGHTS.md`
- 적재 결과와 수량 대조: `docs/AIHUB_INGEST_REPORT.md`

## 원본은 공용 DB 에 올리지 않습니다

AI-Hub 이용정책은 국외 반출에 수행기관 및 한국지능정보사회진흥원과의 별도 합의를
요구하고, 그 합의가 없습니다. 공용 Supabase 프로젝트는 도쿄 리전입니다.

그래서 이 스키마는 **마이그레이션이 아니라 SQL 파일**로 만듭니다. 마이그레이션으로
만들면 `dev-data` 워크플로가 공용 DB 에도 테이블을 만들고, 빈 테이블이 있으면 나중에
누군가 모르고 채울 수 있습니다.

`setup_schema.py` 와 적재 스크립트는 **로컬이 아닌 host 에 연결하지 않습니다.** 공용
반영이 허용되면 그때 이 제한을 명시적으로 풉니다.

`aihub` 는 `public` 이 아니므로 `alembic check` 의 비교 대상이 아닙니다(`env.py` 가
`include_schemas` 를 쓰지 않습니다). CI 를 깨뜨리지 않는 것을 실행으로 확인했습니다.

## 데이터를 공유하지 않고 절차를 공유합니다

원본 ZIP 을 팀원끼리 주고받지 않습니다. 각자 본인 AI-Hub 계정으로 내려받고, 저장소의
스크립트로 같은 로컬 DB 를 만듭니다.

## 실행 순서

`backend/api` 에서 실행합니다. 모든 스크립트가 미리보기 기본이며 `--apply` 로만
기록합니다. `DATA` 를 원본 폴더로 바꿔 쓰세요.

```
DATA = C:\...\02.문제성 피부 메이크업 추천 데이터\3.개방데이터\1.데이터
```

원본 구조 검증 (DB 없이, 표준 라이브러리만 사용):

```powershell
python ..\..\scripts\data\aihub\verify_source.py --data-dir "%DATA%" --out ..\..\data\aihub-source-verify.txt
```

스키마 생성 (사전 2종 포함, 재실행 안전):

```powershell
uv run python ..\..\scripts\data\aihub\setup_schema.py --database vishue_v29 --port 15432 --apply
```

QA 적재:

```powershell
uv run python ..\..\scripts\data\aihub\load_qa.py --data-dir "%DATA%" --database vishue_v29 --port 15432 --apply
```

지식 문서 적재:

```powershell
uv run python ..\..\scripts\data\aihub\load_documents.py --data-dir "%DATA%" --database vishue_v29 --port 15432 --apply
```

출처를 문서에 연결:

```powershell
uv run python ..\..\scripts\data\aihub\match_sources.py --database vishue_v29 --port 15432 --apply
```

QA 를 사람이 읽을 수 있게 뽑기 (고민 13종에서 2건씩):

```powershell
uv run python ..\..\scripts\data\aihub\browse_qa.py --database vishue_v29 --port 15432 --out ..\..\data\aihub-qa-sample.txt
```

## 테이블

| 테이블 | 내용 | 행 수 |
| --- | --- | ---: |
| `dataset_release` | 배포본과 이용권한 상태 | 1+ |
| `qa_case_raw` | QA 원문 JSONB, 파일 경로, 내용 해시 | 9,031 |
| `qa_case` | 조회용 정규화 | 9,031 |
| `qa_source_link` | QA 와 근거 문서의 연결 | 9,181 |
| `knowledge_document` | 내용 해시 기준 고유 문서 | 3,108 |
| `knowledge_document_file` | 원본 파일 경로별 레코드 | 6,245 |
| `skin_concern` | 피부 고민 13종 | 13 |
| `skin_type` | 기본 피부 타입 4종 | 4 |
| `ingredient_mention` | 추천·주의 성분 후보 | 0 |
| `claim_review` | 주장·근거 검수 | 0 |

고민 13종과 피부 타입 4종은 **서로 다른 축**입니다. 합본 분류가 아니며 교차 조건으로
씁니다. 개인의 피부 질환 진단으로 쓰지 않습니다.

문서는 내용 해시로 하나로 묶고 경로는 따로 추적합니다. 같은 문서가 원문 폴더와
사용·미사용 폴더에 중복으로 들어 있기 때문입니다.

## 쓰기 전에 알아야 할 것

**QA 9,031건은 전부 `review_status = 'ingested'` 입니다.** 원본만 보존했다는 뜻이고
승인이 아닙니다. `parsed` 나 `source_matched` 가 자동으로 승인이 되는 규칙을 만들지
않습니다.

**QA 가 참조하지 않는 문서가 1,878개(60%)입니다.** 고유 문서 3,108개 중 QA 가 실제로
가리키는 것은 1,230개입니다. 이 문서들은 QA 를 통한 검증 경로가 없으므로 근거 등급을
QA 연결 문서와 같게 두지 않습니다.

**문서별 이용조건을 보존합니다.** `knowledge_document.purpose_raw` 와 `cautions_raw` 에
원문 그대로 들어갑니다(`연구·학습에만 사용 가능`, `재판매, 2차 저작물 제작 등은 금지`
같은 값). 일반 조항보다 좁을 수 있어 문서 단위로 확인해야 합니다. 메타데이터가 없는
124개 문서는 이용조건을 알 수 없으므로 `rights_status` 를 올리지 않습니다.

**추천·주의 성분은 원문 문자열로만 보존했습니다.** `qa_case.recommended_raw` 와
`avoid_raw` 입니다. 아직 분해하지 않았습니다. 원문에 원료명, 제품 특성(논코메도제닉),
의약품명이 섞여 있어 구분자를 측정한 뒤 처리합니다. 추측으로 쪼개면 성분이 아닌 값이
성분으로 들어갑니다.

**AI-Hub 의 추천 성분은 상품의 전성분이 아닙니다.** 상품 전성분의 정본은
`raw_oy_option_ingredient` 입니다. `aihub` 는 `products`, `shades`, `raw_oy_*`,
`raw_mfds_*` 를 변경하지 않고 상품 테이블과 외래키를 만들지 않습니다.

**`raw_mfds_ingredient` 에 직접 외래키를 걸지 않습니다.**
`ingredient_mention.mfds_ingredient_id` 는 사람이 승인한 경우에만 채워지며 제약으로
강제합니다.

## 출처 한 자리에 파일명이 둘입니다

`File NameN_1` 은 `.doc` 원문, `File NameN_2` 는 같은 이름의 `.json` 메타입니다.
9,181건 중 9,180건은 이름이 같고 **1건(`A002263_01_QA1` 위치 1)만 서로 다른 문서를
가리킵니다.**

연결은 `_1` 로만 합니다. `_2` 로 연결하면 그 1건에서 근거 없는 연결이 생깁니다. `_1`
로 안 붙고 `_2` 로만 붙는 행은 0건이므로 잃는 연결은 없습니다. 두 값 모두 보존합니다.

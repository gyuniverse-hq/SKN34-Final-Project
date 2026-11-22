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

적재 스크립트는 **로컬이 아닌 host 에 연결하지 않습니다.** 다만 테이블 생성은 이제
alembic 이 하므로 그 가드가 걸리지 않습니다. `alembic upgrade head` 가 도는 곳에는
빈 `aihub_*` 테이블이 생길 수 있고 공용 DB도 그에 해당합니다. **데이터는 들어가지
않습니다** — 적재 스크립트가 로컬만 허용하기 때문입니다. 공용
반영이 허용되면 그때 이 제한을 명시적으로 풉니다.

`aihub` 는 `public` 이 아니므로 `alembic check` 의 비교 대상이 아닙니다(`env.py` 가
`include_schemas` 를 쓰지 않습니다). CI 를 깨뜨리지 않는 것을 실행으로 확인했습니다.

## 초기 데이터 공유 정책 (2026-11-04)

초기 정책에서는 원본 ZIP 을 팀원끼리 주고받지 않았습니다. 현재 G5 팀 데이터 공유에 대한 사용자 확인은 `docs/AIHUB_DATA_RIGHTS.md`를 따릅니다. 당시에는 각자 본인 AI-Hub 계정으로 내려받고, 저장소의
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

테이블 생성. 2026-11-04 부터 alembic 이 만든다. 전용 `aihub` 스키마에서 `public` 의
`aihub_` 접두사 테이블로 옮겼고, 분류 축 2종(고민 13종, 기본 피부 타입 4종)도
마이그레이션 `0014` 가 함께 넣는다. `setup_schema.py` 와 `schema.sql` 은 없앴다.

```powershell
uv run alembic upgrade head
```

QA 적재:

```powershell
uv run python ..\..\scripts\data\aihub\load_qa.py --data-dir "%DATA%" --database vishue_db --port 15432 --apply
```

지식 문서 적재:

```powershell
uv run python ..\..\scripts\data\aihub\load_documents.py --data-dir "%DATA%" --database vishue_db --port 15432 --apply
```

출처를 문서에 연결:

```powershell
uv run python ..\..\scripts\data\aihub\match_sources.py --database vishue_db --port 15432 --apply
```

추천·주의 성분 언급 적재:

```powershell
uv run python ..\..\scripts\data\aihub\load_mentions.py --database vishue_db --port 15432 --apply
```

누출·구분자 측정 (집계와 예시를 다른 파일로 씁니다):

```powershell
uv run python ..\..\scripts\data\aihub\analyze_qa.py --database vishue_db --port 15432 --out ..\..\data\aihub-qa-analysis.txt --samples-out ..\..\data\aihub-mention-samples.txt
```

QA 를 사람이 읽을 수 있게 뽑기 (고민 13종에서 2건씩):

```powershell
uv run python ..\..\scripts\data\aihub\browse_qa.py --database vishue_db --port 15432 --out ..\..\data\aihub-qa-sample.txt
```

## ERD

```mermaid
erDiagram
    dataset_release ||--o{ qa_case_raw : "배포본"
    qa_case_raw ||--|| qa_case : "정규화"
    qa_case_raw ||--o{ qa_source_link : "출처 1~5"
    qa_case_raw ||--o{ ingredient_mention : "추천·주의 성분"
    qa_case_raw ||--o{ claim_review : "주장 검수"
    skin_concern ||--o{ qa_case : "고민 13종"
    skin_type ||--o{ qa_case : "피부 타입 4종"
    knowledge_document ||--o{ knowledge_document_file : "파일 경로"
    knowledge_document ||--o{ qa_source_link : "근거 문서"
    knowledge_document ||--o{ claim_review : "문서 검수"

    dataset_release {
        bigserial release_id PK
        text dataset_id
        text release_version
        date received_at
        text source_sha256
        text rights_status
        text storage_region
    }
    skin_concern {
        text concern_code PK
        text major_category
        text label_ko
        text label_en
    }
    skin_type {
        text skin_type_raw PK
        text skin_type_normalized
        text display_label_ko
    }
    qa_case_raw {
        text seq PK
        text split
        text source_archive
        text source_file_path
        text sha256
        jsonb raw_json
        bigint release_id FK
    }
    qa_case {
        text seq PK,FK
        text subject_id
        text concern_code FK
        text skin_type_raw FK
        text question_text
        text answer_text
        text recommended_raw
        text avoid_raw
        text review_status
    }
    qa_source_link {
        text seq PK,FK
        smallint source_position PK
        text quote_raw
        text source_title_raw
        text file_name_raw
        text file_name_raw_2
        bigint document_id FK
        text match_status
    }
    knowledge_document {
        bigserial document_id PK
        text content_sha256 UK
        text title_raw
        text publication_year_raw
        text purpose_raw
        text cautions_raw
        text rights_status
        text review_status
    }
    knowledge_document_file {
        bigserial file_id PK
        bigint document_id FK
        text source_file_path UK
        text file_name
        text meta_json_path
        text meta_match_status
    }
    ingredient_mention {
        bigserial mention_id PK
        text seq FK
        text mention_type
        text raw_text
        text entity_kind
        bigint mfds_ingredient_id
        text mapping_review_status
    }
    claim_review {
        bigserial claim_id PK
        text seq FK
        bigint document_id FK
        text support_status
        text rights_status
        text reviewer
        date reviewed_at
    }
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
| `ingredient_mention` | 추천·주의 성분 후보 | 18,062 |
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

**추천·주의 성분은 쪼개지 않습니다.** 문자열 18,062개를 측정한 결과 구분자 후보를
무엇으로 바꿔도 문자열당 토큰이 1.0 이었습니다. 쉼표는 633번, 줄바꿈은 1번만 나옵니다.
**한 문자열이 곧 한 성분**이므로 `ingredient_mention` 에 1:1 로 넣습니다. 쪼개는 규칙을
만들면 괄호 안 수식어나 학명의 마침표를 잘못 자릅니다.

**`entity_kind` 는 식약처 현행 표준명과 정확히 일치할 때만 `ingredient` 입니다.**
나머지 74.8% 는 `unknown` 입니다. 영문명·학명·성분군(`레티노이드`, `계면활성제`,
`파라벤` 등)·수식어 결합 표기를 자동 판정하지 않습니다. 검수 기준과 작업량은
`docs/AIHUB_REVIEW_CONTRACT.md` 에 있습니다.

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

## G5 지식 상담과 영구 검색 색인

G5는 별도 로컬 PostgreSQL에서 검증한다. 아래 Compose는 포트 15435와
`vishue-g5-rag_g5-data` 볼륨을 사용한다. 이전 로컬 G5 DB의 `0024`와 최신
일반 스키마의 `0024`는 다른 변경이다. 이전 DB에서는 일반 Alembic 업그레이드나
버전 스탬프를 실행하지 않는다. 원문 사본이 필요한 경우 읽기 전용 트랜잭션에서
문서·파일·추출·블록을 논리 복사하며, QA 비교에는 해당 문서에 연결된 QA를 복사한다.

PR #260이 develop에 병합된 후 통합 순서는 일반 Alembic의 `0028`(영상 태그) →
`0029`(피부 추천 이벤트) → `0030`(원문 추출) → `0031`(발췌 연결)이다.
G5 청크·벡터는 일반 이력의 `0032`에서 생성한다. PostgreSQL에 pgvector 0.8.2가 필요하다.
통합 전 G5의 `0027`·`0028`과 구형 D: DB의 `0029`(원문 추출)·`0030`(발췌 연결)은
새 번호와 내용이 다르다. 기존 D: DB에는 직접 업그레이드하거나 스탬프하지 않고,
신규 격리 DB에 일반 마이그레이션을 적용한 뒤 허용된 데이터를 준비·대조한다. 기존 별도 이력을 사용한 DB는 테이블 정의와 데이터 보존을 검증하기 전에는 업그레이드하거나 스탬프하지 않는다.

### 팀 로컬 데이터 덤프 복원

공유 데이터 전용 덤프는 스키마와 Alembic 이력을 포함하지 않는다. `aihub_*`
테이블의 원문·발췌·QA·청크·벡터와 시퀀스가 들어 있으며, Git이나 공개 채널에
올리지 않는다. 공유 범위와 이전 결정은 `docs/AIHUB_DATA_RIGHTS.md`를 따른다.

1. 새 빈 로컬 DB를 PostgreSQL 17·pgvector 0.8.2로 준비한다. 기존 팀 DB나 기존
   볼륨에 덮어쓰지 않는다.
2. `backend/api`에서 `uv run alembic upgrade head`를 실행하고 일반 이력
   `0032`가 적용됐는지 확인한다. 기존 별도 G5 이력 DB는 직접 upgrade/stamp하지 않는다.
3. 빈 DB에 마이그레이션이 기본 생성한 피부 고민 13개와 피부 타입 4개는 덤프에도
   있으므로 복원 전 중복을 처리한다. 실험에서는 **새 빈 격리 DB에서만**
   `DELETE FROM aihub_skin_concern; DELETE FROM aihub_skin_type;`를 실행했다.
   데이터가 이미 있는 DB에서는 실행하지 않는다.
4. `pg_restore --data-only --disable-triggers --exit-on-error --no-owner
   --no-privileges -U <복원계정> -d <새DB> <덤프파일>`로 복원한다. 이 검증은
   superuser 권한을 사용했다. 다른 권한·환경에서는 별도 검증이 필요하다.
5. 복원 후 트리거가 모두 활성 상태인지, 데이터 참조와 ID 시퀀스가 보존됐는지
   확인한다. 실패하면 부분 복원된 DB를 운영에 사용하지 않는다.
6. 검증에 사용한 덤프 기준은 문서 3,108, 원문 추출 3,105, 원문 블록 447,122,
   청크 36,167, 고유 벡터 36,040건이다. QA 원본과 조회용은 각각 9,031건이다.
   원본과 각 테이블의 ID·행 해시, 원문 좌표와 검색 결과를 대조한다. 새 덤프의
   파일 SHA-256도 전달 시 확인한다.

검증한 덤프 SHA-256:
`2225608363AA64B6EE855AC848BF7BA7CD4B8A1447A7A871CB3FB7DB783CB856`.
원문·청크·벡터 등 15개 테이블의 건수와 ID 포함 행 해시가 일치했고 저장 벡터
1개를 사용한 정확 검색 상위 5건의 청크·문서·거리·좌표 해시가 일치했다. 이는
새 질문의 상담 품질 검증이 아니다. 원본은 일반 이력 번호가 달라 새 DB로 복사했다.
추출·연결 통합 테스트는 포트 `15549`, DB `g5_extraction_test`, 사용자 `g5_test`,
`cluster_name=g5-integration-test`인 별도 클러스터에서만 허용한다.
`G5_EXTRACTION_TEST_DATABASE_URL`은 테스트의 고정 URL과 같아야 하며, 기존 DB나
Docker 볼륨을 재사용하지 않는다. 빈 DB에서 #260의 `0029`까지 구성한 뒤
G5의 업그레이드·다운그레이드·재적용과 원문 좌표·해시·연결 정합성을 확인한다.
G5를 되돌린 뒤에도 `0029`의 피부 추천 이벤트 테이블이 유지되는지 확인한다.

```powershell
docker compose -f infra/compose/compose.g5.yaml up -d --wait
$env:DATABASE_URL = 'postgresql+asyncpg://vishue:g5-local-development@127.0.0.1:15435/vishue_g5_rag'
Push-Location backend/api
uv run alembic upgrade head
# 기존 데이터 관리 절차에 따라 이 검증 DB에만 평가 원문을 준비한다.
$env:G5_ALLOW_LOCAL_SOURCES = 'true'
uv run python -m app.jobs.index_knowledge --local --document-ids 171 179 267 757 1322 2647
Pop-Location
```

`G5_OPENAI_API_KEY`는 적재 프로세스와 두 백엔드에 서버 비밀로 공급한다.
API·챗봇의 `G5_ENABLED`는 기본 OFF이며, 검증에서 활성화할 때
`G5_INTERNAL_TOKEN`을 양쪽에 같은 서버 비밀로 공급한다. 챗봇의
`CATALOG_API_URL`은 API의 내부 주소다. API의 `G5_ALLOW_LOCAL_SOURCES`는
`ENV=local`에서만 작동한다. 서비스 조회에는 권리 및 문서 검수 상태를 다시 적용한다.

일반 뷰티 상담은 설정된 일반 상담 모델로 처리하며 G5 검색을 자동 호출하지 않는다.
D: 로컬 검증에서는 일반 모델을 `gpt-6-luna`로 설정했다. 한국어·G1 ON에서는 최근
사용자 질문과 어시스턴트 답변을 신뢰할 수 없는 대화 문맥으로 전달하며, 이를 AIHub
원문 근거로 취급하지 않는다. 최근 대화는 최대 8개·합계 8,000자다.

명시적 `knowledge_consultation`은 라우팅 보호 조건을 거쳐 기존 G5 검색·인용을 사용할
수 있다. 이 요청 유형만으로 상품 가격·전성분·옵션·쇼핑 세션·스타일·AR 경로를
우회하지 않는다. G1 OFF의 기존 이력 처리와 G2의 Redis 세션·권한·만료 계약을
유지하며, 명시적 G5 요청은 `clarificationId`나 AR 실행 권한을 부여하지 않는다.

AIHub 원문은 저장된 Luna 답변을 별도로 대조하는 데 사용했다. 원문에 없는 주장은
오답으로 확정하지 않고 지지 여부를 확인하지 못한 것으로 구분한다. 답변을 반복 평가하는
자동 평가기는 운영 경로에 완성되지 않았다. D: 실제 상담 4문항은 소량 확인이며,
원문 대조는 작성자 확인이다. 앱 응답에서 모델 사용 토큰을 확보하지 못해 질문별
실제 비용은 측정하지 못했다.

청크는 문서·추출 버전, 3,200 UTF-16 단위의 원문과 블록 범위를 저장한다.
벡터는 입력 해시와 모델·버전·차원별로 재사용한다. 현재 서비스 기준선인 `large`는
단일 모델·색인 버전의 3,072차원 `halfvec`를 정확 코사인 거리순으로 검색하고 기본
상위 20개를 제공한다. 키워드 병합·RRF·문서 분산을 적용하지 않는다. HNSW 인덱스는
존재하지만, 비교에서 필요한 근거를 놓친 사례 때문에 현재 경로는 정확 검색을 유지한다.
`section`·`qa`는 로컬 조회 모드에서만 허용하는 실험 경로이며 서비스 조회 모드에서는
거부한다. 챗봇은 내부 검색 HTTP와 원문 복원 HTTP를 호출하고,
Terra가 선택한 인용을 실제 원문과
대조한 뒤 1,050토큰 범위에서 문맥을 붙인다. 주장 검사는 인용을 확인하고 지원되지 않는
주장을 표시·제외한다. 생성형 재작성 단계는 없다.

전체 적재는 `--all --dry-run`으로 대상과 미적재 입력 수를 확인할 수 있다.
배치별로 완성 벡터를 커밋하고, 문서별 청크를 트랜잭션으로 반영한다. 중단 후에는
같은 인자로 재실행한다. 아래 표는 6개 문서를 사용한 과거 소량 검증 기록이다.
전체 적재·검색·상담 검증은 각각 별도 실행 증거로 구분하고, 아래 수치를 현재 HEAD의
전체 코퍼스 품질이나 운영 지연으로 사용하지 않는다.

### 실험용 QA 제외 정책

현재 `qa_seeds()`는 질문의 완전 일치 또는 유사도 0.7 이상인 행이 상위 QA 후보
160개 안에 있으면 해당 `subject_id`의 후보를 모두 제외한다. 현재 후보 자신도
이 조건에 포함된다. 이는 같은 대상자의 질문·답변에 의한 평가 누출을 차단하는
조건이며, 같은 청크를 한 번만 남기는 일반 중복 제거와 다르다. 실사용 QA 검색에도
적절한 정책인지 확정한 상태는 아니다.

다음은 실제 SQL의 `NOT EXISTS` 조건을 고정 점수로 대조한 사례다. 실제 코퍼스의
pg_trgm 점수나 검색 성능을 측정한 결과는 아니다.

| 후보 | 고정 조건 | 제외 조건의 결과 |
|---|---|---|
| A의 완전 일치 질문 | 완전 일치, 유사도 1.0 | 자기 자신 때문에 제외 |
| A의 다른 질문 | 유사도 0.3, 위 질문과 같은 대상자 | 같은 대상자이므로 제외 |
| B의 높은 유사도 질문 | 유사도 0.8 | 자기 자신 때문에 제외 |
| C의 낮은 유사도 질문 | 유사도 0.6, 같은 대상자의 차단 행 없음 | 이 제외 조건은 통과 |

조건 통과 이후에도 검증된 원문 추출·발췌 연결과 문서 이용 상태를 충족해야 한다.
아래 QA 결과에는 이 제외 정책의 영향이 포함되므로 QA 방식 자체가 열등하다는
결론을 내리지 않는다. 실사용 검색과 평가 누출 방지의 범위를 구분하고 회귀 검증한
뒤 별도 비교해야 한다. 이번 PR 보완에서는 SQL이나 검색 전략을 변경하지 않는다.

### 과거 비교 기록과 현재 실행

검증 컴포즈와 API를 시작한 뒤, 승인된 질문 JSON을 사용한다. JSON은 질문 ID로
찾을 수 있는 객체이며, 각 항목에는 `question`과 선택적으로 `has_reference`가 있다.
평가 정답이나 좌표는 검색과 생성에 전달하지 않는다. 출력에 원문과 응답이 포함되므로
로컬 사본에서만 보관한다.

아래 명령은 현재 코드의 세 전략을 실행한다. 과거 혼합 검색 표를 동일하게 재현하려면
당시 코드·데이터·후보·설정 스냅샷이 별도로 필요하다. 현재 `large`의 정확 벡터 검색과
과거 혼합 검색의 결과를 같은 실행 결과로 취급하지 않는다.

```powershell
backend/chatbot/.venv/Scripts/python.exe -B scripts/data/aihub/evaluate_rag.py <local-question-json>
```

2026-11-19에 원문 6개를 사용해 245개 청크와 고유 벡터 220개를 적재했다.
입력 437,181토큰과 임베딩 12회에 약 $0.05683이 들었다. 별도 DB 재시작 후
청크·벡터 개수가 유지됐고 같은 입력을 재실행했을 때 API 호출은 0회였다.
별도 사본 문단의 한 글자를 변경했을 때 벡터 1개만 새로 생성되고, 복원할 때
기존 벡터를 재사용했다. HNSW 인덱스는 1,768 kB였다.

| 22문항 실행 | 큰 청크 | 문단+같은 절 | QA+검증 원문 |
|---|---:|---:|---:|
| 답변 가능 18개 중 answered | 17 | 12 | 0 |
| 답변 가능 18개 중 검사기가 충분으로 분류한 문맥 | 18 | 14 | 0 |
| 근거 부족 4개 중 근거 부족 반환 | 4 | 4 | 4 |
| 총 시간 중앙값 | 28.34초 | 25.68초 | 13.00초 |
| API 호출 수 | 86 | 64 | 38 |
| API 비용 추정 | $1.39454 | $0.37833 | $0.10225 |

`answered`와 문맥 충분성은 당시 시스템의 상태·자동 판정이며 정답률이 아니다.
28.34초 등의 중앙값도 당시 소량 실험의 값으로, 현재 지연시간·P95·SLA를 나타내지 않는다.

위 표는 저장한 6개 문서에서 실행한 상태 및 자동 판정이다. 기존 3,105개 문서
임시 검색 실험과 검색 범위가 다르고, 독립적인 사람 평가와 전체 운영 지연 검증이
남아 있다. 직접 대조에서는 문단+같은 절 방식이 제목만 나왔던 촬영 질문의 본문
`267` ¶5929–5930을 찾았고, 큰 청크 혼합 검색이 선크림 질문의 영문 원문
`2647` ¶35를 회수했다. 이 혼합 검색의 관찰을 현재 정확 벡터 경로의 재검증 결과로
인용하지 않는다.

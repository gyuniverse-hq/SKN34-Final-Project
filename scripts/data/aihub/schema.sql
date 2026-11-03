-- AI-Hub 「문제성 피부 메이크업 추천 데이터」(datasetSn 71961) 보관 스키마
--
-- public 이 아니라 aihub 스키마에 둔다. 이유는 두 가지다.
--   1. alembic/env.py 는 include_schemas 를 쓰지 않아 public 만 비교한다. 여기 테이블은
--      alembic check 의 대상이 아니므로 CI 를 깨뜨리지 않는다.
--   2. 마이그레이션이 아니므로 dev-data 워크플로가 공용 DB 에 만들지 않는다.
--      AI-Hub 원본은 국외 리전에 두지 않는다(docs/AIHUB_DATA_RIGHTS.md).
--
-- 설계 원칙은 인수인계 요청서를 따른다.
--   - 원본 보존(qa_case_raw)과 정규화 조회(qa_case)를 분리한다.
--   - 문서와 QA 는 다대다로 연결한다.
--   - 출처 없는 승인을 만들지 않는다.
--   - QA 와 상품 사이에 직접 외래키를 만들지 않는다.
--
-- 재실행해도 안전하다(IF NOT EXISTS).

CREATE SCHEMA IF NOT EXISTS aihub;

-- 배포본과 이용권한 ---------------------------------------------------------

CREATE TABLE IF NOT EXISTS aihub.dataset_release (
    release_id      bigserial PRIMARY KEY,
    dataset_id      text NOT NULL,
    dataset_name    text NOT NULL,
    release_version text,
    received_at     date NOT NULL,
    source_archive  text NOT NULL,
    source_sha256   text,
    -- local_only: 국내 로컬 보관만 허용. service_approved 는 국외 반출 합의와
    -- 데이터셋 개별 이용조건 확인 이후에만 부여한다.
    rights_status   text NOT NULL,
    storage_region  text NOT NULL,
    rights_note     text,
    CONSTRAINT ck_dataset_release_rights CHECK (
        rights_status IN ('pending_confirmation', 'local_only', 'service_approved', 'blocked')
    )
);

-- 분류 축 두 개 -------------------------------------------------------------
-- 피부 고민 13종과 기본 피부 타입 4종은 서로 다른 축이다. 합본 분류가 아니다.

CREATE TABLE IF NOT EXISTS aihub.skin_concern (
    concern_code   text PRIMARY KEY,
    major_category text NOT NULL,
    label_ko       text NOT NULL,
    label_en       text
);

CREATE TABLE IF NOT EXISTS aihub.skin_type (
    skin_type_raw        text PRIMARY KEY,
    skin_type_normalized text NOT NULL,
    display_label_ko     text NOT NULL
);

-- 원본 보존 -----------------------------------------------------------------

CREATE TABLE IF NOT EXISTS aihub.qa_case_raw (
    seq              text PRIMARY KEY,
    split            text NOT NULL,
    source_archive   text NOT NULL,
    source_file_path text NOT NULL,
    sha256           text NOT NULL,
    raw_json         jsonb NOT NULL,
    release_id       bigint NOT NULL REFERENCES aihub.dataset_release (release_id),
    ingested_at      timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT ck_qa_case_raw_split CHECK (split IN ('train', 'validation'))
);

-- 조회용 정규화 --------------------------------------------------------------
-- 원문 값은 _raw 로 보존하고, 표준화 값은 사전 테이블을 참조한다.

CREATE TABLE IF NOT EXISTS aihub.qa_case (
    seq               text PRIMARY KEY REFERENCES aihub.qa_case_raw (seq),
    -- SEQ 앞부분의 대상자 ID. 학습·검증 분리 평가에 쓴다. 실제 이용자가 아니다.
    subject_id        text NOT NULL,
    concern_code      text NOT NULL REFERENCES aihub.skin_concern (concern_code),
    concern_label_raw text,
    skin_type_raw     text REFERENCES aihub.skin_type (skin_type_raw),
    skin_brightness_raw text,
    area_raw          text,
    question_text     text,
    answer_text       text,
    -- 추천·주의 성분은 원문 문자열로 보존한다. 분해한 후보는 ingredient_mention 에 있다.
    recommended_raw   text,
    avoid_raw         text,
    -- 검수 수명주기. approved 는 출처 연결과 근거 검토를 통과한 뒤에만 준다.
    review_status     text NOT NULL DEFAULT 'ingested',
    -- 배제했으면 왜 배제했는지가 남아야 한다. 상태만으로는 사유를 알 수 없다.
    exclusion_reason  text,
    CONSTRAINT ck_qa_case_review CHECK (
        review_status IN ('ingested', 'needs_review', 'approved', 'rejected', 'rights_blocked')
    ),
    CONSTRAINT ck_qa_case_exclusion CHECK (
        review_status NOT IN ('rejected', 'rights_blocked') OR exclusion_reason IS NOT NULL
    )
);

CREATE INDEX IF NOT EXISTS ix_aihub_qa_case_concern ON aihub.qa_case (concern_code);
CREATE INDEX IF NOT EXISTS ix_aihub_qa_case_skin_type ON aihub.qa_case (skin_type_raw);
CREATE INDEX IF NOT EXISTS ix_aihub_qa_case_subject ON aihub.qa_case (subject_id);
CREATE INDEX IF NOT EXISTS ix_aihub_qa_case_review ON aihub.qa_case (review_status);

-- 지식 문서 -----------------------------------------------------------------
-- 내용 해시로 고유 문서를 식별하고(3,108), 원본 파일 경로는 따로 추적한다(6,245).
-- 같은 문서가 사용·미사용 폴더에 중복으로 들어 있을 수 있다.

CREATE TABLE IF NOT EXISTS aihub.knowledge_document (
    document_id          bigserial PRIMARY KEY,
    content_sha256       text NOT NULL UNIQUE,
    title_raw            text,
    author_raw           text,
    publisher_raw        text,
    -- 0 이나 누락을 실제 출판연도로 간주하지 않기 위해 문자열로 보존한다.
    publication_year_raw text,
    -- Data_info.Status (도서 구분) 과 Source_info.Source (출처 종류) 는 다른 값이다.
    status_raw           text,
    source_type_raw      text,
    language_raw         text,
    country_raw          text,
    application_raw      text,
    token_count_raw      text,
    main_keywords_raw    text,
    -- 문서별 이용조건. 일반 조항보다 좁을 수 있어 그대로 보존한다.
    purpose_raw          text,
    cautions_raw         text,
    rights_status        text NOT NULL DEFAULT 'pending_confirmation',
    review_status        text NOT NULL DEFAULT 'ingested',
    CONSTRAINT ck_knowledge_document_rights CHECK (
        rights_status IN ('pending_confirmation', 'local_only', 'service_approved', 'blocked')
    ),
    exclusion_reason     text,
    CONSTRAINT ck_knowledge_document_review CHECK (
        review_status IN ('ingested', 'needs_review', 'approved', 'rejected', 'rights_blocked')
    ),
    CONSTRAINT ck_knowledge_document_exclusion CHECK (
        review_status NOT IN ('rejected', 'rights_blocked') OR exclusion_reason IS NOT NULL
    )
);

CREATE TABLE IF NOT EXISTS aihub.knowledge_document_file (
    file_id           bigserial PRIMARY KEY,
    document_id       bigint REFERENCES aihub.knowledge_document (document_id),
    source_file_path  text NOT NULL UNIQUE,
    file_name         text NOT NULL,
    file_extension    text NOT NULL,
    byte_size         bigint,
    -- 연결된 메타데이터 JSON 의 경로. 파일명만으로 확정되지 않으면 연결하지 않는다.
    meta_json_path    text,
    meta_match_status text NOT NULL DEFAULT 'not_attempted',
    meta_match_reason text,
    CONSTRAINT ck_knowledge_document_file_meta CHECK (
        meta_match_status IN ('matched', 'unmatched', 'ambiguous', 'not_attempted')
    )
);

CREATE INDEX IF NOT EXISTS ix_aihub_doc_file_document ON aihub.knowledge_document_file (document_id);
CREATE INDEX IF NOT EXISTS ix_aihub_doc_file_name ON aihub.knowledge_document_file (file_name);

-- QA 와 근거 문서의 연결 ------------------------------------------------------
-- Source_info1~5 는 모든 QA 에 블록으로 존재하지만 실제 참조는 9,181건이다.
-- 참조가 없는 자리는 행을 만들지 않는다.

CREATE TABLE IF NOT EXISTS aihub.qa_source_link (
    seq                  text NOT NULL REFERENCES aihub.qa_case_raw (seq),
    source_position      smallint NOT NULL,
    quote_raw            text,
    source_title_raw     text,
    author_raw           text,
    publisher_raw        text,
    publication_year_raw text,
    -- 출처 한 자리에 파일명이 둘이다. _1 은 .doc 원문, _2 는 같은 이름의 .json 메타다.
    -- 9,181건 중 9,180건은 이름이 같고 1건(A002263_01_QA1 위치 1)만 서로 다른 문서를
    -- 가리킨다. 임의로 하나로 합치지 않고 둘 다 보존한다.
    file_name_raw        text,
    file_extension_raw   text,
    file_name_raw_2      text,
    file_extension_raw_2 text,
    status_raw           text,
    document_id          bigint REFERENCES aihub.knowledge_document (document_id),
    -- 파일명만으로 연결되지 않으면 근거 없는 연결을 만들지 않고 사유를 남긴다.
    match_status         text NOT NULL DEFAULT 'not_attempted',
    match_reason         text,
    -- 파일이 이어진 것과 인용문이 그 문서에 실제로 있는 것은 다르다. 따로 센다.
    -- .doc 본문을 아직 추출하지 않아 현재는 전부 not_attempted 이다.
    quote_match_status   text NOT NULL DEFAULT 'not_attempted',
    quote_match_note     text,
    PRIMARY KEY (seq, source_position),
    CONSTRAINT ck_qa_source_link_position CHECK (source_position BETWEEN 1 AND 5),
    CONSTRAINT ck_qa_source_link_match CHECK (
        match_status IN ('matched', 'unmatched', 'ambiguous', 'not_attempted')
    ),
    -- 연결됐다고 표시하려면 실제로 문서가 붙어 있어야 한다.
    CONSTRAINT ck_qa_source_link_matched_has_document CHECK (
        match_status <> 'matched' OR document_id IS NOT NULL
    ),
    CONSTRAINT ck_qa_source_link_quote CHECK (
        quote_match_status IN ('matched', 'not_found', 'partial', 'unverifiable', 'not_attempted')
    ),
    -- 인용 일치를 판정했으면 어느 문서에 대해 판정한 것인지가 있어야 한다.
    CONSTRAINT ck_qa_source_link_quote_target CHECK (
        quote_match_status = 'not_attempted' OR document_id IS NOT NULL
    )
);

CREATE INDEX IF NOT EXISTS ix_aihub_source_link_document ON aihub.qa_source_link (document_id);
CREATE INDEX IF NOT EXISTS ix_aihub_source_link_match ON aihub.qa_source_link (match_status);

-- 추천·주의 성분 후보 ---------------------------------------------------------
-- 원문에 원료명, 제품 특성(논코메도제닉), 의약품명이 섞여 있다. 분류 전에는 unknown.
-- raw_mfds_ingredient 에 직접 외래키를 걸지 않는다. 검증된 뒤에만 id 를 채운다.

CREATE TABLE IF NOT EXISTS aihub.ingredient_mention (
    mention_id            bigserial PRIMARY KEY,
    seq                   text NOT NULL REFERENCES aihub.qa_case_raw (seq),
    mention_type          text NOT NULL,
    raw_text              text NOT NULL,
    entity_kind           text NOT NULL DEFAULT 'unknown',
    mfds_ingredient_id    bigint,
    mapping_review_status text NOT NULL DEFAULT 'pending',
    reviewer              text,
    reviewed_at           date,
    note                  text,
    CONSTRAINT ck_ingredient_mention_type CHECK (mention_type IN ('recommended', 'avoid')),
    CONSTRAINT ck_ingredient_mention_kind CHECK (
        entity_kind IN ('unknown', 'ingredient', 'product_attribute', 'medication', 'other')
    ),
    CONSTRAINT ck_ingredient_mention_review CHECK (
        mapping_review_status IN ('pending', 'approved', 'rejected')
    ),
    -- 성분 id 를 채우려면 사람이 승인해야 한다.
    CONSTRAINT ck_ingredient_mention_mapped CHECK (
        mfds_ingredient_id IS NULL
        OR (mapping_review_status = 'approved' AND reviewer IS NOT NULL AND reviewed_at IS NOT NULL)
    )
);

CREATE INDEX IF NOT EXISTS ix_aihub_mention_seq ON aihub.ingredient_mention (seq);
CREATE INDEX IF NOT EXISTS ix_aihub_mention_type ON aihub.ingredient_mention (mention_type, entity_kind);

-- 주장·근거 검수 --------------------------------------------------------------
-- 원본과 분리해 저장한다. parsed 나 source_matched 가 자동으로 승인이 되지 않는다.

CREATE TABLE IF NOT EXISTS aihub.claim_review (
    claim_id       bigserial PRIMARY KEY,
    seq            text REFERENCES aihub.qa_case_raw (seq),
    document_id    bigint REFERENCES aihub.knowledge_document (document_id),
    claim_ref      text,
    -- 26건 표본 검증에서 관찰된 판정 유형을 그대로 쓴다.
    support_status text NOT NULL DEFAULT 'pending',
    rights_status  text NOT NULL DEFAULT 'pending_confirmation',
    reviewer       text,
    reviewed_at    date,
    notes          text,
    CONSTRAINT ck_claim_review_support CHECK (
        support_status IN ('pending', 'direct', 'indirect', 'insufficient', 'contradicting')
    ),
    CONSTRAINT ck_claim_review_rights CHECK (
        rights_status IN ('pending_confirmation', 'local_only', 'service_approved', 'blocked')
    ),
    -- 검수 대상이 QA 든 문서든 최소 하나는 있어야 한다.
    CONSTRAINT ck_claim_review_target CHECK (seq IS NOT NULL OR document_id IS NOT NULL),
    -- 판정을 내렸으면 누가 언제 했는지 남아야 한다.
    CONSTRAINT ck_claim_review_reviewed CHECK (
        support_status = 'pending' OR (reviewer IS NOT NULL AND reviewed_at IS NOT NULL)
    )
);

CREATE INDEX IF NOT EXISTS ix_aihub_claim_seq ON aihub.claim_review (seq);
CREATE INDEX IF NOT EXISTS ix_aihub_claim_document ON aihub.claim_review (document_id);

-- 이미 만들어진 스키마에도 같은 열이 생기도록 한다(재실행 안전).
ALTER TABLE aihub.knowledge_document ADD COLUMN IF NOT EXISTS status_raw text;
ALTER TABLE aihub.knowledge_document ADD COLUMN IF NOT EXISTS application_raw text;
ALTER TABLE aihub.knowledge_document ADD COLUMN IF NOT EXISTS token_count_raw text;
ALTER TABLE aihub.knowledge_document ADD COLUMN IF NOT EXISTS main_keywords_raw text;
ALTER TABLE aihub.qa_source_link ADD COLUMN IF NOT EXISTS file_name_raw_2 text;
ALTER TABLE aihub.qa_source_link ADD COLUMN IF NOT EXISTS file_extension_raw_2 text;
ALTER TABLE aihub.qa_case ADD COLUMN IF NOT EXISTS exclusion_reason text;
ALTER TABLE aihub.knowledge_document ADD COLUMN IF NOT EXISTS exclusion_reason text;
ALTER TABLE aihub.qa_source_link ADD COLUMN IF NOT EXISTS match_reason text;
ALTER TABLE aihub.qa_source_link
    ADD COLUMN IF NOT EXISTS quote_match_status text NOT NULL DEFAULT 'not_attempted';
ALTER TABLE aihub.qa_source_link ADD COLUMN IF NOT EXISTS quote_match_note text;
ALTER TABLE aihub.knowledge_document_file ADD COLUMN IF NOT EXISTS meta_match_reason text;

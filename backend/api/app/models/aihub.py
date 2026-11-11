"""AI-Hub 「문제성 피부 메이크업 추천 데이터」(datasetSn 71961) 보관 테이블.

2026-11-04 에 `aihub` 전용 스키마에서 `public` 으로 옮기고 `aihub_` 접두사를 붙였다.
전용 스키마를 쓴 이유는 공용 DB(도쿄 리전)에 만들지 않기 위해서였는데, 공용 DB를 쓰지
않고 각자 국내 로컬에 두기로 바뀌어 그 이유가 없어졌다(docs/AIHUB_DATA_RIGHTS.md).

접두사를 붙인 이유는 두 가지다.
  1. 출처별 접두사(raw_oy_, raw_mfds_, rec_, oy_)를 쓰는 기존 관례와 맞춘다.
     `skin_concern` 은 `rec_concern` 과, `ingredient_mention` 은 성분 테이블들과 혼동된다.
  2. 팀원에게 주는 덤프에서 `--exclude-table='aihub_*'` 한 줄로 전부 제외된다.
     AI-Hub 원본은 이용정책상 승인받지 않은 제3자에게 제공할 수 없다. 각자 본인 계정으로
     받아 적재한다. 스키마는 마이그레이션으로 공유하고 데이터는 공유하지 않는다.

설계 원칙은 인수인계 요청서를 따른다.
  - 원본 보존(aihub_qa_case_raw)과 정규화 조회(aihub_qa_case)를 분리한다.
  - 문서와 QA 는 다대다로 연결한다.
  - 출처 없는 승인을 만들지 않는다.
  - QA 와 상품 사이에 직접 외래키를 만들지 않는다.
"""

from datetime import date, datetime
from uuid import UUID

from sqlalchemy import (
    ARRAY,
    BigInteger,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    SmallInteger,
    Text,
    UniqueConstraint,
    Uuid,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base

RIGHTS = "('pending_confirmation', 'local_only', 'service_approved', 'blocked')"
REVIEW = "('ingested', 'needs_review', 'approved', 'rejected', 'rights_blocked')"
MATCH = "('matched', 'unmatched', 'ambiguous', 'not_attempted')"
REVIEW_PROGRESS = "('not_started', 'in_progress', 'completed')"
CLAIM_DECISIONS = "('approved', 'limited_approved', 'on_hold', 'excluded')"
LEGACY_SUPPORT = "('pending', 'direct', 'indirect', 'insufficient', 'contradicting')"


class AihubDatasetReleaseRow(Base):
    """배포본과 이용권한."""

    __tablename__ = "aihub_dataset_release"
    __table_args__ = (
        CheckConstraint(f"rights_status IN {RIGHTS}", name="ck_aihub_dataset_release_rights"),
    )

    release_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    dataset_id: Mapped[str] = mapped_column(Text, nullable=False)
    dataset_name: Mapped[str] = mapped_column(Text, nullable=False)
    release_version: Mapped[str | None] = mapped_column(Text, nullable=True)
    received_at: Mapped[date] = mapped_column(Date, nullable=False)
    source_archive: Mapped[str] = mapped_column(Text, nullable=False)
    source_sha256: Mapped[str | None] = mapped_column(Text, nullable=True)
    # local_only: 국내 로컬 보관만 허용. service_approved 는 데이터셋 개별 이용조건
    # 확인 이후에만 부여한다.
    rights_status: Mapped[str] = mapped_column(Text, nullable=False)
    storage_region: Mapped[str] = mapped_column(Text, nullable=False)
    rights_note: Mapped[str | None] = mapped_column(Text, nullable=True)


class AihubSkinConcernRow(Base):
    """피부 고민 13종. 기본 피부 타입과 다른 축이며 합본 분류가 아니다."""

    __tablename__ = "aihub_skin_concern"

    concern_code: Mapped[str] = mapped_column(Text, primary_key=True)
    major_category: Mapped[str] = mapped_column(Text, nullable=False)
    label_ko: Mapped[str] = mapped_column(Text, nullable=False)
    label_en: Mapped[str | None] = mapped_column(Text, nullable=True)


class AihubSkinTypeRow(Base):
    """기본 피부 타입 4종. 원본 값 '정상' 과 표시명 '중성' 을 분리해 저장한다."""

    __tablename__ = "aihub_skin_type"

    skin_type_raw: Mapped[str] = mapped_column(Text, primary_key=True)
    skin_type_normalized: Mapped[str] = mapped_column(Text, nullable=False)
    display_label_ko: Mapped[str] = mapped_column(Text, nullable=False)


class AihubQaCaseRawRow(Base):
    """원본 보존. 파싱 결과가 아니라 원문 JSON 을 그대로 둔다."""

    __tablename__ = "aihub_qa_case_raw"
    __table_args__ = (
        CheckConstraint("split IN ('train', 'validation')", name="ck_aihub_qa_case_raw_split"),
    )

    seq: Mapped[str] = mapped_column(Text, primary_key=True)
    split: Mapped[str] = mapped_column(Text, nullable=False)
    source_archive: Mapped[str] = mapped_column(Text, nullable=False)
    source_file_path: Mapped[str] = mapped_column(Text, nullable=False)
    sha256: Mapped[str] = mapped_column(Text, nullable=False)
    raw_json: Mapped[dict] = mapped_column(JSONB, nullable=False)
    release_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("aihub_dataset_release.release_id"), nullable=False
    )
    ingested_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class AihubQaCaseRow(Base):
    """조회용 정규화. 원문 값은 _raw 로 보존하고 표준화 값은 사전을 참조한다."""

    __tablename__ = "aihub_qa_case"
    __table_args__ = (
        CheckConstraint(f"review_status IN {REVIEW}", name="ck_aihub_qa_case_review"),
        CheckConstraint(
            f"review_progress IN {REVIEW_PROGRESS}", name="ck_aihub_qa_case_review_progress"
        ),
        # 배제했으면 왜 배제했는지가 남아야 한다. 상태만으로는 사유를 알 수 없다.
        CheckConstraint(
            "review_status NOT IN ('rejected', 'rights_blocked') OR exclusion_reason IS NOT NULL",
            name="ck_aihub_qa_case_exclusion",
        ),
        Index("ix_aihub_qa_case_concern", "concern_code"),
        Index("ix_aihub_qa_case_skin_type", "skin_type_raw"),
        Index("ix_aihub_qa_case_subject", "subject_id"),
        Index("ix_aihub_qa_case_review", "review_status"),
    )

    seq: Mapped[str] = mapped_column(Text, ForeignKey("aihub_qa_case_raw.seq"), primary_key=True)
    # SEQ 앞부분의 대상자 ID. 학습·검증 분리 평가에 쓴다. 실제 이용자가 아니다.
    subject_id: Mapped[str] = mapped_column(Text, nullable=False)
    concern_code: Mapped[str] = mapped_column(
        Text, ForeignKey("aihub_skin_concern.concern_code"), nullable=False
    )
    concern_label_raw: Mapped[str | None] = mapped_column(Text, nullable=True)
    skin_type_raw: Mapped[str | None] = mapped_column(
        Text, ForeignKey("aihub_skin_type.skin_type_raw"), nullable=True
    )
    skin_brightness_raw: Mapped[str | None] = mapped_column(Text, nullable=True)
    area_raw: Mapped[str | None] = mapped_column(Text, nullable=True)
    question_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    answer_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    # 추천·주의 성분은 원문 문자열로 보존한다. 분해한 후보는 aihub_ingredient_mention 에 있다.
    recommended_raw: Mapped[str | None] = mapped_column(Text, nullable=True)
    avoid_raw: Mapped[str | None] = mapped_column(Text, nullable=True)
    # 이전 적재 및 검수 기록. 서비스 승인 판정에는 사용하지 않는다.
    review_status: Mapped[str] = mapped_column(Text, server_default="ingested", nullable=False)
    exclusion_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    review_progress: Mapped[str] = mapped_column(Text, server_default="not_started", nullable=False)


class AihubKnowledgeDocumentRow(Base):
    """내용 해시로 식별하는 고유 문서. 원본 파일 경로는 별도 테이블에서 추적한다."""

    __tablename__ = "aihub_knowledge_document"
    __table_args__ = (
        CheckConstraint(f"rights_status IN {RIGHTS}", name="ck_aihub_knowledge_document_rights"),
        CheckConstraint(f"review_status IN {REVIEW}", name="ck_aihub_knowledge_document_review"),
        CheckConstraint(
            "review_status NOT IN ('rejected', 'rights_blocked') OR exclusion_reason IS NOT NULL",
            name="ck_aihub_knowledge_document_exclusion",
        ),
        CheckConstraint(
            "(source_identifier IS NULL AND source_version IS NULL) OR "
            "(source_identifier IS NOT NULL AND btrim(source_identifier) <> '' "
            "AND source_version IS NOT NULL AND btrim(source_version) <> '')",
            name="ck_aihub_document_source_version",
        ),
        UniqueConstraint("source_identifier", "source_version", name="uq_aihub_document_version"),
    )

    document_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    content_sha256: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    source_identifier: Mapped[str | None] = mapped_column(Text, nullable=True)
    source_version: Mapped[str | None] = mapped_column(Text, nullable=True)
    title_raw: Mapped[str | None] = mapped_column(Text, nullable=True)
    author_raw: Mapped[str | None] = mapped_column(Text, nullable=True)
    publisher_raw: Mapped[str | None] = mapped_column(Text, nullable=True)
    # 0 이나 누락을 실제 출판연도로 간주하지 않기 위해 문자열로 보존한다.
    publication_year_raw: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Data_info.Status(도서 구분)와 Source_info.Source(출처 종류)는 다른 값이다.
    status_raw: Mapped[str | None] = mapped_column(Text, nullable=True)
    source_type_raw: Mapped[str | None] = mapped_column(Text, nullable=True)
    language_raw: Mapped[str | None] = mapped_column(Text, nullable=True)
    country_raw: Mapped[str | None] = mapped_column(Text, nullable=True)
    application_raw: Mapped[str | None] = mapped_column(Text, nullable=True)
    token_count_raw: Mapped[str | None] = mapped_column(Text, nullable=True)
    main_keywords_raw: Mapped[str | None] = mapped_column(Text, nullable=True)
    # 문서별 이용조건. 일반 조항보다 좁을 수 있어 그대로 보존한다.
    purpose_raw: Mapped[str | None] = mapped_column(Text, nullable=True)
    cautions_raw: Mapped[str | None] = mapped_column(Text, nullable=True)
    rights_status: Mapped[str] = mapped_column(
        Text, server_default="pending_confirmation", nullable=False
    )
    review_status: Mapped[str] = mapped_column(Text, server_default="ingested", nullable=False)
    exclusion_reason: Mapped[str | None] = mapped_column(Text, nullable=True)


class AihubKnowledgeDocumentFileRow(Base):
    """문서의 원본 파일 경로별 레코드. 같은 문서가 여러 폴더에 중복될 수 있다."""

    __tablename__ = "aihub_knowledge_document_file"
    __table_args__ = (
        CheckConstraint(
            f"meta_match_status IN {MATCH}", name="ck_aihub_knowledge_document_file_meta"
        ),
        Index("ix_aihub_doc_file_document", "document_id"),
        Index("ix_aihub_doc_file_name", "file_name"),
    )

    file_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    document_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("aihub_knowledge_document.document_id"), nullable=True
    )
    source_file_path: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    file_name: Mapped[str] = mapped_column(Text, nullable=False)
    file_extension: Mapped[str] = mapped_column(Text, nullable=False)
    byte_size: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    # 연결된 메타데이터 JSON 의 경로. 파일명만으로 확정되지 않으면 연결하지 않는다.
    meta_json_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    meta_match_status: Mapped[str] = mapped_column(
        Text, server_default="not_attempted", nullable=False
    )
    meta_match_reason: Mapped[str | None] = mapped_column(Text, nullable=True)


class AihubQaSourceLinkRow(Base):
    """QA 와 근거 문서의 연결. 참조가 없는 자리는 행을 만들지 않는다."""

    __tablename__ = "aihub_qa_source_link"
    __table_args__ = (
        CheckConstraint("source_position BETWEEN 1 AND 5", name="ck_aihub_qa_source_link_position"),
        CheckConstraint(f"match_status IN {MATCH}", name="ck_aihub_qa_source_link_match"),
        # 연결됐다고 표시하려면 실제로 문서가 붙어 있어야 한다.
        CheckConstraint(
            "match_status <> 'matched' OR document_id IS NOT NULL",
            name="ck_aihub_qa_source_link_matched_has_document",
        ),
        CheckConstraint(
            "quote_match_status IN "
            "('matched', 'not_found', 'partial', 'unverifiable', 'not_attempted')",
            name="ck_aihub_qa_source_link_quote",
        ),
        # 인용 일치를 판정했으면 어느 문서에 대해 판정한 것인지가 있어야 한다.
        CheckConstraint(
            "quote_match_status = 'not_attempted' OR document_id IS NOT NULL",
            name="ck_aihub_qa_source_link_quote_target",
        ),
        Index("ix_aihub_source_link_document", "document_id"),
        Index("ix_aihub_source_link_match", "match_status"),
    )

    seq: Mapped[str] = mapped_column(Text, ForeignKey("aihub_qa_case_raw.seq"), primary_key=True)
    source_position: Mapped[int] = mapped_column(SmallInteger, primary_key=True)
    quote_raw: Mapped[str | None] = mapped_column(Text, nullable=True)
    source_title_raw: Mapped[str | None] = mapped_column(Text, nullable=True)
    author_raw: Mapped[str | None] = mapped_column(Text, nullable=True)
    publisher_raw: Mapped[str | None] = mapped_column(Text, nullable=True)
    publication_year_raw: Mapped[str | None] = mapped_column(Text, nullable=True)
    # 출처 한 자리에 파일명이 둘이다. _1 은 .doc 원문, _2 는 같은 이름의 .json 메타다.
    # 9,181건 중 1건만 서로 다른 문서를 가리킨다. 임의로 합치지 않고 둘 다 보존한다.
    file_name_raw: Mapped[str | None] = mapped_column(Text, nullable=True)
    file_extension_raw: Mapped[str | None] = mapped_column(Text, nullable=True)
    file_name_raw_2: Mapped[str | None] = mapped_column(Text, nullable=True)
    file_extension_raw_2: Mapped[str | None] = mapped_column(Text, nullable=True)
    status_raw: Mapped[str | None] = mapped_column(Text, nullable=True)
    document_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("aihub_knowledge_document.document_id"), nullable=True
    )
    match_status: Mapped[str] = mapped_column(Text, server_default="not_attempted", nullable=False)
    match_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    # 파일이 이어진 것과 인용문이 그 문서에 실제로 있는 것은 다르다. 따로 센다.
    quote_match_status: Mapped[str] = mapped_column(
        Text, server_default="not_attempted", nullable=False
    )
    quote_match_note: Mapped[str | None] = mapped_column(Text, nullable=True)


class AihubIngredientMentionRow(Base):
    """추천·주의 성분 후보. 분류 전에는 unknown 이며 성분 id 는 승인 후에만 채운다."""

    __tablename__ = "aihub_ingredient_mention"
    __table_args__ = (
        UniqueConstraint("seq", "mention_type", "raw_text", name="uq_aihub_ingredient_mention_raw"),
        CheckConstraint(
            "mention_type IN ('recommended', 'avoid')", name="ck_aihub_ingredient_mention_type"
        ),
        CheckConstraint(
            "entity_kind IN ('unknown', 'ingredient', 'product_attribute', 'medication', 'other')",
            name="ck_aihub_ingredient_mention_kind",
        ),
        CheckConstraint(
            "mapping_review_status IN ('pending', 'approved', 'rejected')",
            name="ck_aihub_ingredient_mention_review",
        ),
        # 성분 id 를 채우려면 사람이 승인해야 한다.
        CheckConstraint(
            "mfds_ingredient_id IS NULL OR (mapping_review_status = 'approved' "
            "AND reviewer IS NOT NULL AND reviewed_at IS NOT NULL)",
            name="ck_aihub_ingredient_mention_mapped",
        ),
        Index("ix_aihub_mention_seq", "seq"),
        Index("ix_aihub_mention_type", "mention_type", "entity_kind"),
    )

    mention_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    seq: Mapped[str] = mapped_column(Text, ForeignKey("aihub_qa_case_raw.seq"), nullable=False)
    mention_type: Mapped[str] = mapped_column(Text, nullable=False)
    raw_text: Mapped[str] = mapped_column(Text, nullable=False)
    entity_kind: Mapped[str] = mapped_column(Text, server_default="unknown", nullable=False)
    # raw_mfds_ingredient 에 외래키를 걸지 않는다. 검증된 뒤에만 id 를 채운다.
    mfds_ingredient_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    mapping_review_status: Mapped[str] = mapped_column(
        Text, server_default="pending", nullable=False
    )
    reviewer: Mapped[str | None] = mapped_column(Text, nullable=True)
    reviewed_at: Mapped[date | None] = mapped_column(Date, nullable=True)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)


class AihubClaimVersionRow(Base):
    """주장과 적용 범위의 개정본. 검수 결과 변경은 새 개정본으로 남긴다."""

    __tablename__ = "aihub_claim_version"
    __table_args__ = (
        UniqueConstraint("claim_key", "revision", name="uq_aihub_claim_revision"),
        CheckConstraint(
            "revision > 0 AND btrim(canonical_text) <> '' "
            "AND jsonb_typeof(applicability) = 'object'",
            name="ck_aihub_claim_version_content",
        ),
        CheckConstraint(
            "(review_progress IN ('not_started', 'in_progress') AND approval_status IS NULL "
            "AND reviewer IS NULL AND reviewed_at IS NULL AND decision_reason IS NULL) OR "
            f"(review_progress = 'completed' AND approval_status IS NOT NULL "
            f"AND approval_status IN {CLAIM_DECISIONS} "
            "AND reviewer IS NOT NULL AND btrim(reviewer) <> '' AND reviewed_at IS NOT NULL "
            "AND decision_reason IS NOT NULL AND btrim(decision_reason) <> '')",
            name="ck_aihub_claim_version_decision",
        ),
        CheckConstraint(
            "array_position(approved_uses, NULL) IS NULL "
            "AND approved_uses <@ ARRAY['explain', 'rank', 'avoid']::text[] "
            "AND (CASE WHEN approval_status IN ('approved', 'limited_approved') "
            "THEN cardinality(approved_uses) > 0 ELSE cardinality(approved_uses) = 0 END) "
            "AND (approval_status IS DISTINCT FROM 'limited_approved' "
            "OR applicability <> '{}'::jsonb)",
            name="ck_aihub_claim_version_uses",
        ),
    )

    claim_version_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    claim_key: Mapped[UUID] = mapped_column(Uuid, nullable=False)
    revision: Mapped[int] = mapped_column(Integer, nullable=False)
    canonical_text: Mapped[str] = mapped_column(Text, nullable=False)
    applicability: Mapped[dict] = mapped_column(
        JSONB, server_default=text("'{}'::jsonb"), nullable=False
    )
    review_progress: Mapped[str] = mapped_column(Text, server_default="not_started", nullable=False)
    approval_status: Mapped[str | None] = mapped_column(Text, nullable=True)
    approved_uses: Mapped[list[str]] = mapped_column(
        ARRAY(Text), server_default=text("'{}'::text[]"), nullable=False
    )
    reviewer: Mapped[str | None] = mapped_column(Text, nullable=True)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    decision_reason: Mapped[str | None] = mapped_column(Text, nullable=True)


class AihubQaClaimRow(Base):
    """원본 QA에서 개정본을 찾는 연결. 같은 주장을 여러 QA에서 재사용한다."""

    __tablename__ = "aihub_qa_claim"
    __table_args__ = (
        CheckConstraint("btrim(answer_locator) <> ''", name="ck_aihub_qa_claim_locator"),
        Index("ix_aihub_qa_claim_version", "claim_version_id"),
    )

    seq: Mapped[str] = mapped_column(Text, ForeignKey("aihub_qa_case.seq"), primary_key=True)
    claim_version_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("aihub_claim_version.claim_version_id"), primary_key=True
    )
    answer_locator: Mapped[str] = mapped_column(Text, nullable=False)


class AihubClaimReviewRow(Base):
    """주장·근거 검수. parsed 나 source_matched 가 자동으로 승인이 되지 않는다."""

    __tablename__ = "aihub_claim_review"
    __table_args__ = (
        CheckConstraint(
            f"support_status IN {LEGACY_SUPPORT} OR "
            "(claim_version_id IS NOT NULL AND support_status IN ('limited', 'unverifiable'))",
            name="ck_aihub_claim_review_support",
        ),
        CheckConstraint(f"rights_status IN {RIGHTS}", name="ck_aihub_claim_review_rights"),
        # 검수 대상이 QA 든 문서든 최소 하나는 있어야 한다.
        CheckConstraint(
            "seq IS NOT NULL OR document_id IS NOT NULL", name="ck_aihub_claim_review_target"
        ),
        # 판정을 내렸으면 누가 언제 했는지 남아야 한다.
        CheckConstraint(
            "support_status = 'pending' OR (reviewer IS NOT NULL AND reviewed_at IS NOT NULL)",
            name="ck_aihub_claim_review_reviewed",
        ),
        ForeignKeyConstraint(
            ["seq", "claim_version_id"],
            ["aihub_qa_claim.seq", "aihub_qa_claim.claim_version_id"],
            name="fk_aihub_claim_review_qa_claim",
        ),
        ForeignKeyConstraint(
            ["seq", "source_position"],
            ["aihub_qa_source_link.seq", "aihub_qa_source_link.source_position"],
            name="fk_aihub_claim_review_source_position",
        ),
        CheckConstraint(
            "(source_position IS NULL OR (seq IS NOT NULL AND claim_version_id IS NOT NULL)) "
            "AND (claim_version_id IS NULL OR document_id IS NOT NULL "
            "OR source_position IS NOT NULL)",
            name="ck_aihub_claim_review_version_source",
        ),
        CheckConstraint(
            "claim_version_id IS NULL OR support_status = 'pending' OR "
            "(reviewer IS NOT NULL AND btrim(reviewer) <> '' "
            "AND notes IS NOT NULL AND btrim(notes) <> '' "
            "AND (support_status IN ('insufficient', 'unverifiable') OR "
            "(document_id IS NOT NULL AND source_locator IS NOT NULL "
            "AND btrim(source_locator) <> '' AND study_type IS NOT NULL "
            "AND btrim(study_type) <> '')))",
            name="ck_aihub_claim_review_version_finding",
        ),
        Index("ix_aihub_claim_seq", "seq"),
        Index("ix_aihub_claim_document", "document_id"),
        Index("ix_aihub_claim_review_version", "claim_version_id"),
    )

    claim_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    seq: Mapped[str | None] = mapped_column(
        Text, ForeignKey("aihub_qa_case_raw.seq"), nullable=True
    )
    document_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("aihub_knowledge_document.document_id"), nullable=True
    )
    claim_version_id: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey("aihub_claim_version.claim_version_id", name="fk_aihub_claim_review_version"),
        nullable=True,
    )
    source_position: Mapped[int | None] = mapped_column(SmallInteger, nullable=True)
    source_locator: Mapped[str | None] = mapped_column(Text, nullable=True)
    study_type: Mapped[str | None] = mapped_column(Text, nullable=True)
    claim_ref: Mapped[str | None] = mapped_column(Text, nullable=True)
    support_status: Mapped[str] = mapped_column(Text, server_default="pending", nullable=False)
    rights_status: Mapped[str] = mapped_column(
        Text, server_default="pending_confirmation", nullable=False
    )
    reviewer: Mapped[str | None] = mapped_column(Text, nullable=True)
    reviewed_at: Mapped[date | None] = mapped_column(Date, nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)


class AihubClaimPublicationRow(Base):
    """Explicit publication of one reviewed statement with one versioned source."""

    __tablename__ = "aihub_claim_publication"
    __table_args__ = (
        Index(
            "uq_aihub_active_publication",
            "claim_version_id",
            unique=True,
            postgresql_where=text("revoked_at IS NULL"),
        ),
        Index("ix_aihub_publication_ingredient", "ingredient_id"),
        Index("ix_aihub_publication_review", "source_review_id"),
        CheckConstraint(
            "mfds_source_hash ~ '^[0-9a-f]{64}$' AND btrim(summary) <> '' "
            "AND btrim(source_title) <> '' AND btrim(publisher) <> '' "
            "AND (revoked_at IS NULL OR revoked_at >= published_at)",
            name="ck_aihub_publication_content",
        ),
    )

    publication_id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    claim_version_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("aihub_claim_version.claim_version_id"), nullable=False
    )
    source_review_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("aihub_claim_review.claim_id"), nullable=False
    )
    release_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("aihub_dataset_release.release_id"), nullable=False
    )
    ingredient_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("raw_mfds_ingredient.ingredient_id"), nullable=False
    )
    mfds_source_hash: Mapped[str] = mapped_column(Text, nullable=False)
    summary: Mapped[str] = mapped_column(Text, nullable=False)
    source_title: Mapped[str] = mapped_column(Text, nullable=False)
    source_url: Mapped[str] = mapped_column(Text, nullable=False)
    publisher: Mapped[str] = mapped_column(Text, nullable=False)
    published_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    test_only: Mapped[bool] = mapped_column(Boolean, server_default=text("false"), nullable=False)

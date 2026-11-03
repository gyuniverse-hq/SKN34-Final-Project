"""피부 고민별 성분 추천 매핑과 논문 근거.

출처는 팀 전달본 VISHUE_DB_추천매핑_요구사항정합_v1_2_1 이다. 전달본의 등급 컬럼
(mapping_status, human_mapping_review, ai_paper_review, re_review_required,
runtime_enabled)은 소비하는 쪽이 거를 수 있도록 그대로 보존한다.

전달본의 ingredient_id_bridge.csv 와 ingredient_dictionary.csv 의 ingredient_ids 는
구 수집본(out_skincare_v1, out_makeup_v23) 식별자이며 현재 raw_oy_ingredient 와 계보가
다르다. 495건을 전수 대조한 결과 일치가 0건이므로 적재하지 않는다. 성분 코드와 수집
성분의 연결은 이름을 근거로 rec_ingredient_link 에 새로 만든다.
"""

from datetime import date, datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Text,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base

MAPPING_STATUSES = (
    "candidate_after_match",
    "research_only",
    "support_only",
    "formula_evidence_only",
    "excluded_treatment_scope",
    "excluded_wrong_endpoint",
    "excluded_context_mismatch",
)
LINK_METHODS = ("exact_name", "manual", "group_member")


def _in_list(column: str, values: tuple[str, ...]) -> str:
    return f"{column} IN (" + ", ".join(f"'{v}'" for v in values) + ")"


class RecConcernRow(Base):
    """고민 코드와 사용자에게 보여줄 문구. 전달본 recommendation_reason.csv."""

    __tablename__ = "rec_concern"

    target_concern: Mapped[str] = mapped_column(Text, primary_key=True)
    display_label: Mapped[str] = mapped_column(Text, nullable=False)
    recommendation_reason: Mapped[str] = mapped_column(Text, nullable=False)


class RecEvidenceRow(Base):
    """매핑의 근거 논문. 전달본 evidence_sources.csv."""

    __tablename__ = "rec_evidence"

    evidence_id: Mapped[str] = mapped_column(Text, primary_key=True)
    pmid: Mapped[str | None] = mapped_column(Text, nullable=True)
    title: Mapped[str | None] = mapped_column(Text, nullable=True)
    source_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    ai_paper_review: Mapped[str | None] = mapped_column(Text, nullable=True)
    # 연구의 한계. 근거를 과장하지 않으려면 매핑과 함께 읽어야 한다.
    study_limit: Mapped[str | None] = mapped_column(Text, nullable=True)


class RecIngredientDictionaryRow(Base):
    """추천에 쓰는 성분 코드 사전. 전달본 ingredient_dictionary.csv.

    전달본의 ingredient_ids / ingredient_id_count 는 적재하지 않는다(모듈 설명 참고).
    """

    __tablename__ = "rec_ingredient_dictionary"

    ingredient_code: Mapped[str] = mapped_column(Text, primary_key=True)
    # 수집 성분과의 연결 근거가 되는 이름.
    name_ko: Mapped[str] = mapped_column(Text, nullable=False)
    inci_name: Mapped[str | None] = mapped_column(Text, nullable=True)
    # SOURCE_TEXT_IDS_FOUND_DB_CHECK_REQUIRED / NO_STRICT_MATCH_IN_SOURCE /
    # GROUP_NEEDS_EXPLICIT_SUBTYPE_RULE
    source_match_status: Mapped[str | None] = mapped_column(Text, nullable=True)


class RecMappingRow(Base):
    """고민 하나와 성분 구성 하나를 잇는 추천 매핑. 전달본 recommendation_mapping.csv."""

    __tablename__ = "rec_mapping"
    __table_args__ = (
        CheckConstraint(
            "mapping_type IN ('single', 'combination')",
            name="ck_rec_mapping_type",
        ),
        CheckConstraint(
            _in_list("mapping_status", MAPPING_STATUSES),
            name="ck_rec_mapping_status",
        ),
        Index("ix_rec_mapping_concern", "target_concern"),
    )

    mapping_id: Mapped[str] = mapped_column(Text, primary_key=True)
    mapping_type: Mapped[str] = mapped_column(Text, nullable=False)
    target_concern: Mapped[str] = mapped_column(
        Text, ForeignKey("rec_concern.target_concern"), nullable=False
    )
    # 전달본 원문 표기(조합은 여러 코드). 정규화된 구성은 rec_mapping_ingredient 에 있다.
    ingredient_codes: Mapped[str | None] = mapped_column(Text, nullable=True)
    evidence_id: Mapped[str | None] = mapped_column(
        Text, ForeignKey("rec_evidence.evidence_id"), nullable=True
    )
    # 근거 등급. excluded_* / research_only / support_only / formula_evidence_only 는
    # 자동 효과 근거로 쓰지 않는다.
    mapping_status: Mapped[str] = mapped_column(Text, nullable=False)
    human_mapping_review: Mapped[str | None] = mapped_column(Text, nullable=True)
    ai_paper_review: Mapped[str | None] = mapped_column(Text, nullable=True)
    re_review_required: Mapped[bool] = mapped_column(Boolean, nullable=False)
    # 운영 노출 여부. 전달본은 32건 전부 거짓이며 승인 없이 켜지 않는다.
    runtime_enabled: Mapped[bool] = mapped_column(
        Boolean, server_default=text("false"), nullable=False
    )
    requirements_scope: Mapped[str | None] = mapped_column(Text, nullable=True)


class RecMappingIngredientRow(Base):
    """매핑의 구성 성분. 전달본 mapping_ingredients.csv.

    조합은 한 옵션에 구성 성분이 모두 있어야 일치한다. 부분 일치는 인정하지 않는다.
    """

    __tablename__ = "rec_mapping_ingredient"

    mapping_id: Mapped[str] = mapped_column(
        Text, ForeignKey("rec_mapping.mapping_id"), primary_key=True
    )
    ingredient_code: Mapped[str] = mapped_column(
        Text, ForeignKey("rec_ingredient_dictionary.ingredient_code"), primary_key=True
    )
    component_order: Mapped[int] = mapped_column(Integer, nullable=False)


class RecManualReviewCandidateRow(Base):
    """사람이 판정하기 전에는 연결하지 않는 후보. 전달본 manual_review_candidates.csv."""

    __tablename__ = "rec_manual_review_candidate"

    ingredient_code: Mapped[str] = mapped_column(
        Text, ForeignKey("rec_ingredient_dictionary.ingredient_code"), primary_key=True
    )
    # 검수자가 본 원문 표기. 이 이름으로 현재 DB에서 다시 찾아야 한다.
    source_name: Mapped[str] = mapped_column(Text, primary_key=True)
    # 전달본이 참조한 구 수집본 ID. 현재 raw_oy_ingredient 와 계보가 다르므로
    # 외래키를 걸지 않으며 연결에 쓰지 않는다. 검수 기록으로만 남긴다.
    source_ingredient_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    review_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    approved: Mapped[bool] = mapped_column(Boolean, nullable=False)


class RecIngredientLinkRow(Base):
    """추천 성분 코드와 수집 성분의 연결. 전달본이 아니라 이 저장소에서 만든다.

    이름이 정확히 일치하면 exact_name 으로 규칙 연결하고, 표기 변형이나 성분군처럼
    사람이 판단한 경우에만 검수자와 날짜를 남긴다. 성분군은 코드 하나에 여러 수집
    성분이 붙으므로 복합 기본키를 쓴다.
    """

    __tablename__ = "rec_ingredient_link"
    __table_args__ = (
        CheckConstraint(_in_list("link_method", LINK_METHODS), name="ck_rec_link_method"),
        CheckConstraint(
            "link_method = 'exact_name' OR (reviewed_by IS NOT NULL AND reviewed_at IS NOT NULL)",
            name="ck_rec_link_provenance",
        ),
        Index("ix_rec_ingredient_link_oy", "oy_ingredient_id"),
    )

    ingredient_code: Mapped[str] = mapped_column(
        Text, ForeignKey("rec_ingredient_dictionary.ingredient_code"), primary_key=True
    )
    oy_ingredient_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("raw_oy_ingredient.ingredient_id"), primary_key=True
    )
    link_method: Mapped[str] = mapped_column(Text, nullable=False)
    linked_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()"), nullable=False
    )
    reviewed_by: Mapped[str | None] = mapped_column(Text, nullable=True)
    reviewed_at: Mapped[date | None] = mapped_column(Date, nullable=True)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)


class RecConcernMatchRow(Base):
    """매핑의 성분 구성을 모두 갖춘 상품 옵션. 이 저장소에서 계산한다.

    일치한 조합만 행으로 남긴다. 성분은 옵션 단위로 달려 있어(색조는 호수별로 다름)
    옵션 기준으로 계산하며, 상품 단위 노출은 옵션 중 하나라도 일치하는지로 판단한다.
    """

    __tablename__ = "rec_concern_match"
    __table_args__ = (Index("ix_rec_concern_match_option", "option_id"),)

    mapping_id: Mapped[str] = mapped_column(
        Text, ForeignKey("rec_mapping.mapping_id"), primary_key=True
    )
    option_id: Mapped[str] = mapped_column(
        Text, ForeignKey("raw_oy_product_option.option_id"), primary_key=True
    )
    computed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()"), nullable=False
    )

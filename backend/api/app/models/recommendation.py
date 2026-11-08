"""Recommendation knowledge base v0.3. Product and ingredient sources remain read-only."""

from datetime import datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Text,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base

LINK_METHODS = ("standard_id", "exact_name", "verified_alias", "verified_group_member")
STUDY_TYPES = (
    "human_intervention",
    "human_observational",
    "in_vitro",
    "animal",
    "method_validation",
    "review",
    "other",
)


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

    __table_args__ = (
        CheckConstraint(_in_list("study_type", STUDY_TYPES), name="ck_rec_study_type"),
    )
    evidence_id: Mapped[str] = mapped_column(Text, primary_key=True)
    pmid: Mapped[str | None] = mapped_column(Text, nullable=True)
    title: Mapped[str] = mapped_column(Text)
    source_url: Mapped[str] = mapped_column(Text)
    study_type: Mapped[str] = mapped_column(Text)
    publication_year: Mapped[int | None] = mapped_column(Integer)
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


class RecMappingRow(Base):
    """고민 하나와 성분 구성 하나를 잇는 추천 매핑. 전달본 recommendation_mapping.csv."""

    __tablename__ = "rec_mapping"
    __table_args__ = (
        CheckConstraint(
            "mapping_type IN ('single', 'combination')",
            name="ck_rec_mapping_type",
        ),
        CheckConstraint(
            "applicability_scope IN ('ingredient_level', 'formula_specific')",
            name="ck_rec_scope",
        ),
        Index("ix_rec_mapping_concern", "target_concern"),
    )

    mapping_id: Mapped[str] = mapped_column(Text, primary_key=True)
    mapping_type: Mapped[str] = mapped_column(Text, nullable=False)
    target_concern: Mapped[str] = mapped_column(
        Text, ForeignKey("rec_concern.target_concern"), nullable=False
    )
    applicability_scope: Mapped[str] = mapped_column(Text)
    runtime_enabled: Mapped[bool] = mapped_column(Boolean, server_default=text("false"))


class RecMappingIngredientRow(Base):
    """매핑의 구성 성분. 전달본 mapping_ingredients.csv.

    조합은 한 옵션에 구성 성분이 모두 있어야 일치한다. 부분 일치는 인정하지 않는다.
    """

    __tablename__ = "rec_mapping_ingredient"
    __table_args__ = (CheckConstraint("component_order >= 1", name="ck_rec_component_order"),)

    mapping_id: Mapped[str] = mapped_column(
        Text, ForeignKey("rec_mapping.mapping_id"), primary_key=True
    )
    ingredient_code: Mapped[str] = mapped_column(
        Text, ForeignKey("rec_ingredient_dictionary.ingredient_code"), primary_key=True
    )
    component_order: Mapped[int] = mapped_column(Integer, nullable=False)


class RecMappingEvidenceRow(Base):
    __tablename__ = "rec_mapping_evidence"
    __table_args__ = (
        Index("ix_rec_mapping_evidence_evidence_id", "evidence_id"),
        CheckConstraint("jsonb_typeof(study_conditions)='object'", name="ck_rec_study_conditions"),
    )
    mapping_id: Mapped[str] = mapped_column(ForeignKey("rec_mapping.mapping_id"), primary_key=True)
    evidence_id: Mapped[str] = mapped_column(
        ForeignKey("rec_evidence.evidence_id"), primary_key=True
    )
    supported_endpoint: Mapped[str] = mapped_column(Text)
    study_conditions: Mapped[dict] = mapped_column(JSONB, server_default=text("'{}'"))
    applicability_note: Mapped[str] = mapped_column(Text)


class RecIngredientLinkRow(Base):
    __tablename__ = "rec_ingredient_link"
    __table_args__ = (
        CheckConstraint(_in_list("link_method", LINK_METHODS), name="ck_rec_link_method"),
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

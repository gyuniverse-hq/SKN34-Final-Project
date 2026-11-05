"""Verified ingredient-to-concern rules, source evidence, and option matches."""

from datetime import datetime

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Identity,
    Index,
    Integer,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base

STUDY_TYPES = (
    "human_intervention",
    "human_observational",
    "in_vitro",
    "animal",
    "method_validation",
    "review",
    "other",
)
LINK_METHODS = ("standard_id", "exact_name", "verified_alias", "verified_group_member")


class RecConcernRow(Base):
    """Supported concern codes and user-facing descriptions."""

    __tablename__ = "rec_concern"

    target_concern: Mapped[str] = mapped_column(Text, primary_key=True)
    display_label: Mapped[str] = mapped_column(Text, nullable=False)
    recommendation_reason: Mapped[str] = mapped_column(Text, nullable=False)


class RecEvidenceRow(Base):
    """Verifiable publication metadata; study facts are not approval flags."""

    __tablename__ = "rec_evidence"
    __table_args__ = (
        CheckConstraint(
            "study_type IS NULL OR study_type IN "
            "('human_intervention','human_observational','in_vitro','animal','method_validation','review','other')",
            name="ck_rec_evidence_study_type",
        ),
        CheckConstraint(
            "publication_year IS NULL OR publication_year BETWEEN 1800 AND 2200",
            name="ck_rec_evidence_publication_year",
        ),
    )

    evidence_id: Mapped[str] = mapped_column(Text, primary_key=True)
    pmid: Mapped[str | None] = mapped_column(Text, nullable=True)
    title: Mapped[str | None] = mapped_column(Text, nullable=True)
    source_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    study_limit: Mapped[str | None] = mapped_column(Text, nullable=True)
    study_type: Mapped[str | None] = mapped_column(Text, nullable=True)
    publication_year: Mapped[int | None] = mapped_column(Integer, nullable=True)


class RecIngredientDictionaryRow(Base):
    """Canonical ingredient codes used in validated recommendation rules."""

    __tablename__ = "rec_ingredient_dictionary"

    ingredient_code: Mapped[str] = mapped_column(Text, primary_key=True)
    name_ko: Mapped[str] = mapped_column(Text, nullable=False)
    inci_name: Mapped[str | None] = mapped_column(Text, nullable=True)


class RecMappingRow(Base):
    """One validated ingredient composition and concern applicability rule."""

    __tablename__ = "rec_mapping"
    __table_args__ = (
        CheckConstraint("mapping_type IN ('single', 'combination')", name="ck_rec_mapping_type"),
        CheckConstraint(
            "applicability_scope IN ('ingredient_level','formula_specific')",
            name="ck_rec_mapping_applicability_scope",
        ),
        Index("ix_rec_mapping_concern", "target_concern"),
    )

    mapping_id: Mapped[str] = mapped_column(Text, primary_key=True)
    mapping_type: Mapped[str] = mapped_column(Text, nullable=False)
    target_concern: Mapped[str] = mapped_column(
        Text, ForeignKey("rec_concern.target_concern"), nullable=False
    )
    applicability_scope: Mapped[str] = mapped_column(Text, nullable=False)
    runtime_enabled: Mapped[bool] = mapped_column(nullable=False, server_default=text("false"))


class RecMappingIngredientRow(Base):
    """Normalized ingredient members of a rule."""

    __tablename__ = "rec_mapping_ingredient"
    __table_args__ = (
        CheckConstraint("component_order >= 1", name="ck_rec_mapping_ingredient_component_order"),
    )

    mapping_id: Mapped[str] = mapped_column(
        Text, ForeignKey("rec_mapping.mapping_id"), primary_key=True
    )
    ingredient_code: Mapped[str] = mapped_column(
        Text, ForeignKey("rec_ingredient_dictionary.ingredient_code"), primary_key=True
    )
    component_order: Mapped[int] = mapped_column(Integer, nullable=False)


class RecMappingEvidenceRow(Base):
    """Mapping-specific evidence claim, endpoint, and study conditions."""

    __tablename__ = "rec_mapping_evidence"
    __table_args__ = (
        CheckConstraint(
            "length(btrim(supported_endpoint)) > 0", name="ck_rec_map_evidence_endpoint"
        ),
        CheckConstraint(
            "jsonb_typeof(study_conditions) = 'object'", name="ck_rec_map_evidence_conditions"
        ),
        Index("ix_rec_mapping_evidence_evidence_id", "evidence_id"),
    )

    mapping_id: Mapped[str] = mapped_column(
        Text, ForeignKey("rec_mapping.mapping_id", ondelete="CASCADE"), primary_key=True
    )
    evidence_id: Mapped[str] = mapped_column(
        Text, ForeignKey("rec_evidence.evidence_id", ondelete="RESTRICT"), primary_key=True
    )
    supported_endpoint: Mapped[str] = mapped_column(Text, nullable=False)
    study_conditions: Mapped[dict] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    applicability_note: Mapped[str | None] = mapped_column(Text, nullable=True)


class RecIngredientLinkRow(Base):
    """Reproducible link from a canonical code to a current Olive Young ingredient."""

    __tablename__ = "rec_ingredient_link"
    __table_args__ = (
        CheckConstraint(
            "link_method IN ('standard_id','exact_name','verified_alias','verified_group_member')",
            name="ck_rec_link_method",
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
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )


class RecConcernMatchRow(Base):
    """Derived fact that an option contains every member of a mapping composition."""

    __tablename__ = "rec_concern_match"
    __table_args__ = (Index("ix_rec_concern_match_option", "option_id"),)

    mapping_id: Mapped[str] = mapped_column(
        Text, ForeignKey("rec_mapping.mapping_id"), primary_key=True
    )
    option_id: Mapped[str] = mapped_column(
        Text, ForeignKey("raw_oy_product_option.option_id"), primary_key=True
    )
    computed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )


class RecommendationLegacyArchiveRow(Base):
    """Immutable migration snapshot of pre-v0.3 records, not used by serving."""

    __tablename__ = "recommendation_legacy_archive"
    __table_args__ = (
        UniqueConstraint("source_table", "source_key", name="uq_recommendation_archive_key"),
    )

    archive_id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    source_table: Mapped[str] = mapped_column(Text, nullable=False)
    source_key: Mapped[str] = mapped_column(Text, nullable=False)
    row_data: Mapped[dict] = mapped_column(JSONB, nullable=False)
    archived_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )

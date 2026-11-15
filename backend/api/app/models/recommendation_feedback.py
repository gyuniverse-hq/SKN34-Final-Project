"""Historical V2 recommendation decisions and observed user responses."""

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


class RecommendationRequestRow(Base):
    __tablename__ = "recommendation_requests"
    __table_args__ = (
        Index("ix_rec_requests_member_requested", "member_id", "requested_at"),
        Index("ix_rec_requests_session_requested", "session_id", "requested_at"),
        CheckConstraint("jsonb_typeof(input_snapshot) = 'object'", name="ck_rec_requests_input"),
        CheckConstraint("jsonb_typeof(policy_snapshot) = 'object'", name="ck_rec_requests_policy"),
        CheckConstraint(
            "model_manifest IS NULL OR jsonb_typeof(model_manifest) = 'object'",
            name="ck_rec_requests_manifest",
        ),
        CheckConstraint(
            "recommendation_evidence IS NULL OR jsonb_typeof(recommendation_evidence) = 'object'",
            name="ck_rec_requests_evidence",
        ),
        CheckConstraint(
            "completed_at IS NULL OR completed_at >= requested_at",
            name="ck_rec_requests_completed_at",
        ),
    )

    request_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True)
    member_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("members.id", ondelete="CASCADE"), nullable=False
    )
    session_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False)
    requested_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()"), nullable=False
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(Text, nullable=False)
    environment: Mapped[str] = mapped_column(Text, nullable=False)
    input_snapshot: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    primary_concern: Mapped[str] = mapped_column(Text, nullable=False)
    secondary_concern: Mapped[str | None] = mapped_column(Text)
    contract_version: Mapped[str] = mapped_column(Text, nullable=False)
    feature_version: Mapped[str] = mapped_column(Text, nullable=False)
    ranking_policy_version: Mapped[str] = mapped_column(Text, nullable=False)
    v2_model_version: Mapped[str | None] = mapped_column(Text)
    catalog_version: Mapped[str | None] = mapped_column(Text)
    catalog_digest: Mapped[str | None] = mapped_column(Text)
    policy_snapshot: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    model_manifest: Mapped[dict[str, Any] | None] = mapped_column(JSONB(none_as_null=True))
    recommendation_evidence: Mapped[dict[str, Any] | None] = mapped_column(JSONB(none_as_null=True))
    failure_code: Mapped[str | None] = mapped_column(Text)


class RecommendationCandidateRow(Base):
    __tablename__ = "recommendation_candidates"
    __table_args__ = (
        UniqueConstraint("request_id", "option_id", name="uq_rec_candidates_request_option"),
        Index(
            "uq_rec_candidates_final_rank",
            "request_id",
            "final_rank",
            unique=True,
            postgresql_where=text("final_rank IS NOT NULL"),
        ),
        Index(
            "uq_rec_candidates_final_product",
            "request_id",
            "product_id",
            unique=True,
            postgresql_where=text("final_rank IS NOT NULL"),
        ),
        CheckConstraint(
            "final_rank IS NULL OR final_rank BETWEEN 1 AND 5",
            name="ck_rec_candidates_final_rank",
        ),
        CheckConstraint(
            "(final_rank IS NULL AND diversity_penalty IS NULL AND selection_score IS NULL) "
            "OR (final_rank IS NOT NULL AND diversity_penalty IS NOT NULL "
            "AND selection_score IS NOT NULL)",
            name="ck_rec_candidates_selection",
        ),
        CheckConstraint(
            "jsonb_typeof(evidence_snapshot) = 'object'", name="ck_rec_candidates_evidence"
        ),
        CheckConstraint(
            "primary_ingredient_score > '-Infinity'::float8 "
            "AND primary_ingredient_score < 'Infinity'::float8 "
            "AND ingredient_score > '-Infinity'::float8 "
            "AND ingredient_score < 'Infinity'::float8 "
            "AND review_score > '-Infinity'::float8 "
            "AND review_score < 'Infinity'::float8 "
            "AND v2_score > '-Infinity'::float8 AND v2_score < 'Infinity'::float8 "
            "AND (secondary_ingredient_score IS NULL OR "
            "(secondary_ingredient_score > '-Infinity'::float8 "
            "AND secondary_ingredient_score < 'Infinity'::float8)) "
            "AND (diversity_penalty IS NULL OR "
            "(diversity_penalty > '-Infinity'::float8 "
            "AND diversity_penalty < 'Infinity'::float8)) "
            "AND (selection_score IS NULL OR "
            "(selection_score > '-Infinity'::float8 "
            "AND selection_score < 'Infinity'::float8))",
            name="ck_rec_candidates_finite_scores",
        ),
    )

    candidate_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True)
    request_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("recommendation_requests.request_id", ondelete="CASCADE"),
        nullable=False,
    )
    product_id: Mapped[str] = mapped_column(Text, nullable=False)
    option_id: Mapped[str] = mapped_column(Text, nullable=False)
    primary_ingredient_score: Mapped[float] = mapped_column(Float(53), nullable=False)
    secondary_ingredient_score: Mapped[float | None] = mapped_column(Float(53))
    ingredient_score: Mapped[float] = mapped_column(Float(53), nullable=False)
    review_score: Mapped[float] = mapped_column(Float(53), nullable=False)
    v2_score: Mapped[float] = mapped_column(Float(53), nullable=False)
    final_rank: Mapped[int | None] = mapped_column(SmallInteger)
    diversity_penalty: Mapped[float | None] = mapped_column(Float(53))
    selection_score: Mapped[float | None] = mapped_column(Float(53))
    evidence_snapshot: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)


class RecommendationImpressionRow(Base):
    __tablename__ = "recommendation_impressions"
    __table_args__ = (
        UniqueConstraint(
            "candidate_id",
            "view_instance_id",
            "surface",
            name="uq_rec_impressions_view",
        ),
        CheckConstraint("displayed_position > 0", name="ck_rec_impressions_position"),
    )

    impression_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True)
    candidate_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("recommendation_candidates.candidate_id", ondelete="CASCADE"),
        nullable=False,
    )
    view_instance_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False)
    surface: Mapped[str] = mapped_column(Text, nullable=False)
    displayed_position: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    received_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()"), nullable=False
    )
    visibility_policy_version: Mapped[str] = mapped_column(Text, nullable=False)


class UserBehaviorEventRow(Base):
    __tablename__ = "user_behavior_events"
    __table_args__ = (
        Index("ix_behavior_events_member_occurred", "member_id", "occurred_at"),
        Index("ix_behavior_events_session_occurred", "session_id", "occurred_at"),
        Index("ix_behavior_events_impression", "impression_id"),
        Index("ix_behavior_events_order_line", "order_line_id"),
        Index(
            "uq_behavior_events_source_record",
            "event_source",
            "source_record_key",
            unique=True,
            postgresql_where=text("source_record_key IS NOT NULL"),
        ),
        Index(
            "uq_behavior_events_purchase_line",
            "order_line_id",
            unique=True,
            postgresql_where=text("event_type = 'purchase_confirmed'"),
        ),
        CheckConstraint(
            "event_type IN ('product_view', 'save', 'unsave', 'cart_add', "
            "'cart_remove', 'category_view', 'outbound_click', 'not_interested', "
            "'product_use_feedback', 'purchase_confirmed')",
            name="ck_behavior_events_type",
        ),
        CheckConstraint("event_source IN ('client', 'server')", name="ck_behavior_events_source"),
        CheckConstraint(
            "event_type <> 'purchase_confirmed' OR "
            "(event_source = 'server' AND order_line_id IS NOT NULL)",
            name="ck_behavior_events_purchase",
        ),
        CheckConstraint(
            "jsonb_typeof(context_snapshot) = 'object'", name="ck_behavior_events_context"
        ),
    )

    event_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True)
    member_id: Mapped[str | None] = mapped_column(
        String(64), ForeignKey("members.id", ondelete="CASCADE")
    )
    session_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False)
    impression_id: Mapped[UUID | None] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("recommendation_impressions.impression_id", ondelete="CASCADE"),
    )
    order_line_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("order_lines.id"))
    product_id: Mapped[str | None] = mapped_column(Text)
    option_id: Mapped[str | None] = mapped_column(Text)
    event_type: Mapped[str] = mapped_column(Text, nullable=False)
    event_source: Mapped[str] = mapped_column(Text, nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    received_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()"), nullable=False
    )
    attribution_policy_version: Mapped[str | None] = mapped_column(Text)
    source_record_key: Mapped[str | None] = mapped_column(Text)
    event_schema_version: Mapped[str] = mapped_column(Text, nullable=False)
    surface: Mapped[str] = mapped_column(Text, nullable=False)
    context_snapshot: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)

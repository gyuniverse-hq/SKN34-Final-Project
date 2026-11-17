"""AR recommendation exposure and member activity history."""

from datetime import datetime
from uuid import UUID

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


class ArRecommendationRequestRow(Base):
    __tablename__ = "ar_recommendation_requests"
    __table_args__ = (Index("ix_ar_requests_member_created", "member_id", "created_at"),)

    request_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True)
    member_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("members.id", ondelete="CASCADE"), nullable=False
    )
    session_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False)
    makeup_zone: Mapped[str] = mapped_column(String(20), nullable=False)
    strategy: Mapped[str] = mapped_column(String(40), nullable=False)
    policy_version: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()"), nullable=False
    )


class ArRecommendationCandidateRow(Base):
    __tablename__ = "ar_recommendation_candidates"
    __table_args__ = (
        CheckConstraint("rank > 0", name="ck_ar_candidates_rank"),
        UniqueConstraint(
            "request_id", "product_id", "shade_id", name="uq_ar_candidates_request_shade"
        ),
        UniqueConstraint("request_id", "rank", name="uq_ar_candidates_request_rank"),
    )

    candidate_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True)
    request_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("ar_recommendation_requests.request_id", ondelete="CASCADE"),
        nullable=False,
    )
    product_id: Mapped[str] = mapped_column(String(64), nullable=False)
    shade_id: Mapped[str] = mapped_column(String(64), nullable=False)
    rank: Mapped[int] = mapped_column(Integer, nullable=False)


class ArRecommendationImpressionRow(Base):
    __tablename__ = "ar_recommendation_impressions"
    __table_args__ = (
        CheckConstraint("displayed_position > 0", name="ck_ar_impressions_position"),
        UniqueConstraint(
            "candidate_id", "view_instance_id", name="uq_ar_impressions_candidate_view"
        ),
    )

    impression_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True)
    candidate_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("ar_recommendation_candidates.candidate_id", ondelete="CASCADE"),
        nullable=False,
    )
    view_instance_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False)
    displayed_position: Mapped[int] = mapped_column(Integer, nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    received_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()"), nullable=False
    )
    visibility_policy_version: Mapped[str] = mapped_column(String(64), nullable=False)


class ArActivityEventRow(Base):
    __tablename__ = "ar_activity_events"
    __table_args__ = (
        Index("ix_ar_activity_member_occurred", "member_id", "occurred_at"),
        Index("ix_ar_activity_session_occurred", "session_id", "occurred_at"),
        Index("ix_ar_activity_impression", "impression_id"),
        CheckConstraint("event_type IN ('try_on', 'cart_add')", name="ck_ar_activity_events_type"),
    )

    event_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True)
    member_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("members.id", ondelete="CASCADE"), nullable=False
    )
    session_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False)
    product_id: Mapped[str] = mapped_column(String(64), nullable=False)
    shade_id: Mapped[str] = mapped_column(String(64), nullable=False)
    makeup_zone: Mapped[str] = mapped_column(String(20), nullable=False)
    event_type: Mapped[str] = mapped_column(String(40), nullable=False)
    impression_id: Mapped[UUID | None] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("ar_recommendation_impressions.impression_id", ondelete="SET NULL"),
    )
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    received_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()"), nullable=False
    )
    schema_version: Mapped[str] = mapped_column(String(64), nullable=False)

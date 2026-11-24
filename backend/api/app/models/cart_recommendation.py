from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, String, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


class CartRecommendationVisitRow(Base):
    __tablename__ = "cart_recommendation_visits"
    __table_args__ = (
        CheckConstraint("arm IN ('A', 'B')", name="ck_cart_recommendation_arm"),
        Index("ix_cart_recommendation_visit_experiment", "experiment", "created_at"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True)
    member_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("members.id", ondelete="CASCADE"), index=True
    )
    experiment: Mapped[str] = mapped_column(String(16))
    arm: Mapped[str] = mapped_column(String(1))
    basket: Mapped[list[dict[str, Any]]] = mapped_column(JSONB)
    candidates: Mapped[list[dict[str, Any]]] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()")
    )


class CartRecommendationImpressionRow(Base):
    __tablename__ = "cart_recommendation_impressions"
    __table_args__ = (
        UniqueConstraint("visit_id", "candidate_id", name="uq_cart_recommendation_impression"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True)
    visit_id: Mapped[UUID] = mapped_column(
        ForeignKey("cart_recommendation_visits.id", ondelete="CASCADE")
    )
    candidate_id: Mapped[UUID]
    visibility_policy: Mapped[str] = mapped_column(String(32))
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()")
    )

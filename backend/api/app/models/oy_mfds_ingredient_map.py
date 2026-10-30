"""Confirmed mapping from an Olive Young ingredient to an MFDS ingredient."""

from datetime import datetime

from sqlalchemy import BigInteger, CheckConstraint, DateTime, ForeignKey, Index, Text, text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


class OyMfdsIngredientMapRow(Base):
    __tablename__ = "oy_mfds_ingredient_map"
    __table_args__ = (
        CheckConstraint(
            "match_method IN ('exact_name', 'official_synonym', 'manual')",
            name="ck_oy_mfds_ingredient_map_method",
        ),
        CheckConstraint(
            "(match_method = 'manual' AND reviewed_by IS NOT NULL AND reviewed_at IS NOT NULL) "
            "OR (match_method <> 'manual' AND rule_version IS NOT NULL)",
            name="ck_oy_mfds_ingredient_map_provenance",
        ),
        Index("ix_oy_mfds_ingredient_map_mfds_id", "mfds_ingredient_id"),
    )

    # One Olive Young ingredient can have at most one confirmed MFDS match.
    oy_ingredient_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("raw_oy_ingredient.ingredient_id"), primary_key=True
    )
    # Multiple Olive Young names may legitimately resolve to one MFDS ingredient.
    mfds_ingredient_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("raw_mfds_ingredient.ingredient_id"), nullable=False
    )
    match_method: Mapped[str] = mapped_column(Text, nullable=False)
    rule_version: Mapped[str | None] = mapped_column(Text, nullable=True)
    matched_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()"), nullable=False
    )
    reviewed_by: Mapped[str | None] = mapped_column(Text, nullable=True)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    review_note: Mapped[str | None] = mapped_column(Text, nullable=True)

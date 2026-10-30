"""MFDS cosmetic ingredient API data, kept separate from Olive Young ingredient text."""

from datetime import datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    Identity,
    Index,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


class RawMfdsIngredientRow(Base):
    __tablename__ = "raw_mfds_ingredient"
    __table_args__ = (
        UniqueConstraint("name_key", name="uq_raw_mfds_ingredient_name_key"),
        Index("ix_raw_mfds_ingredient_is_current", "is_current"),
    )

    ingredient_id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    name_ko: Mapped[str] = mapped_column(Text, nullable=False)
    # NFKC + whitespace collapse only; punctuation and chemical qualifiers are retained.
    name_key: Mapped[str] = mapped_column(Text, nullable=False)
    name_en: Mapped[str | None] = mapped_column(Text, nullable=True)
    cas_no_raw: Mapped[str | None] = mapped_column(Text, nullable=True)
    origin_ko_raw: Mapped[str | None] = mapped_column(Text, nullable=True)
    synonym_raw: Mapped[str | None] = mapped_column(Text, nullable=True)
    source_payload: Mapped[dict[str, str | None]] = mapped_column(JSONB, nullable=False)
    source_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    first_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    is_current: Mapped[bool] = mapped_column(Boolean, nullable=False)

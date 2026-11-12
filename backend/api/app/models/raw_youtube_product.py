"""Raw YouTube product research, mentions and unconfirmed Olive Young candidates."""

from datetime import date, datetime

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Identity,
    Index,
    Integer,
    String,
    Text,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


class RawYtProductRow(Base):
    __tablename__ = "raw_yt_product"
    __table_args__ = (
        CheckConstraint(
            "hex_code IS NULL OR hex_code ~ '^#[0-9A-Fa-f]{6}$'", name="ck_raw_yt_product_hex"
        ),
        CheckConstraint("price_krw IS NULL OR price_krw >= 0", name="ck_raw_yt_product_price"),
        Index("ix_raw_yt_product_brand_name", "brand_name", "product_name"),
    )

    yt_product_id: Mapped[str] = mapped_column(Text, primary_key=True)
    brand_name: Mapped[str] = mapped_column(Text, nullable=False)
    product_name: Mapped[str] = mapped_column(Text, nullable=False)
    option_name: Mapped[str | None] = mapped_column(Text)
    category: Mapped[str | None] = mapped_column(Text)
    makeup_zone: Mapped[str | None] = mapped_column(Text)
    price_krw: Mapped[int | None] = mapped_column(Integer)
    price_type: Mapped[str | None] = mapped_column(Text)
    volume: Mapped[str | None] = mapped_column(Text)
    texture: Mapped[str | None] = mapped_column(Text)
    hex_code: Mapped[str | None] = mapped_column(Text)
    image_url: Mapped[str | None] = mapped_column(Text)
    image_source_url: Mapped[str | None] = mapped_column(Text)
    product_url: Mapped[str | None] = mapped_column(Text)
    description: Mapped[str | None] = mapped_column(Text)
    checked_at: Mapped[date | None] = mapped_column(Date)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()"), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()"), nullable=False
    )


class RawYtProductMentionRow(Base):
    __tablename__ = "raw_yt_product_mention"
    __table_args__ = (
        Index("ix_raw_yt_mention_product", "yt_product_id"),
        Index("ix_raw_yt_mention_video", "video_id"),
    )

    source_row_id: Mapped[str] = mapped_column(Text, primary_key=True)
    yt_product_id: Mapped[str] = mapped_column(
        Text, ForeignKey("raw_yt_product.yt_product_id"), nullable=False
    )
    source_product_record_id: Mapped[str] = mapped_column(Text, unique=True, nullable=False)
    source: Mapped[str] = mapped_column(Text, nullable=False)
    video_id: Mapped[str] = mapped_column(Text, nullable=False)
    mention_number: Mapped[int] = mapped_column(Integer, nullable=False)
    video_url: Mapped[str] = mapped_column(Text, nullable=False)
    video_playback_status: Mapped[str | None] = mapped_column(Text)
    video_use_evidence: Mapped[str | None] = mapped_column(Text)
    research_status: Mapped[str | None] = mapped_column(Text)
    review_reason: Mapped[str | None] = mapped_column(Text)


class YtOyProductMatchRow(Base):
    __tablename__ = "yt_oy_product_match"
    __table_args__ = (
        Index(
            "uq_yt_oy_match_candidate",
            "yt_product_id",
            "oy_goods_no",
            "oy_option_id",
            unique=True,
            postgresql_nulls_not_distinct=True,
        ),
        CheckConstraint(
            "decision_status IN ('candidate', 'confirmed', 'rejected', 'needs_review')",
            name="ck_yt_oy_match_status",
        ),
        Index("ix_yt_oy_match_product", "yt_product_id"),
        Index("ix_yt_oy_match_oy", "oy_goods_no"),
        Index(
            "uq_yt_oy_match_confirmed",
            "yt_product_id",
            unique=True,
            postgresql_where=text("decision_status = 'confirmed'"),
        ),
    )

    match_id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    yt_product_id: Mapped[str] = mapped_column(
        Text, ForeignKey("raw_yt_product.yt_product_id"), nullable=False
    )
    oy_goods_no: Mapped[str] = mapped_column(
        Text, ForeignKey("raw_oy_product.goods_no"), nullable=False
    )
    oy_option_id: Mapped[str | None] = mapped_column(
        Text, ForeignKey("raw_oy_product_option.option_id")
    )
    candidate_rank: Mapped[int] = mapped_column(Integer, nullable=False)
    match_method: Mapped[str] = mapped_column(Text, nullable=False)
    similarity_score: Mapped[float | None] = mapped_column(Float)
    match_reason: Mapped[str | None] = mapped_column(Text)
    rule_version: Mapped[str | None] = mapped_column(Text)
    decision_status: Mapped[str] = mapped_column(Text, server_default="candidate", nullable=False)
    reviewer: Mapped[str | None] = mapped_column(Text)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class YtCatalogProductLinkRow(Base):
    """Reviewed links from researched YouTube IDs to serving catalog products."""

    __tablename__ = "yt_catalog_product_link"
    __table_args__ = (
        CheckConstraint(
            "link_type IN ('direct', 'merged', 'split', 'corrected')",
            name="ck_yt_catalog_product_link_type",
        ),
        Index("ix_yt_catalog_product_link_serving", "serving_product_id"),
    )

    source_yt_product_id: Mapped[str] = mapped_column(
        Text,
        ForeignKey("raw_yt_product.yt_product_id", ondelete="CASCADE"),
        primary_key=True,
    )
    serving_product_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("products.id", ondelete="CASCADE"), primary_key=True
    )
    link_type: Mapped[str] = mapped_column(Text, nullable=False)
    evidence_url: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()"), nullable=False
    )

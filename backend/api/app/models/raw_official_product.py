"""Source records copied from official brand product pages and reviewed chips."""

from datetime import date

from sqlalchemy import REAL, CheckConstraint, Date, ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


class RawOfficialProductRow(Base):
    __tablename__ = "raw_official_product"

    source_product_id: Mapped[str] = mapped_column(Text, primary_key=True)
    raw_oy_goods_no: Mapped[str] = mapped_column(
        Text, ForeignKey("raw_oy_product.goods_no"), nullable=False
    )
    # Seed import replaces products, so keep a soft reference.
    serving_product_id: Mapped[str] = mapped_column(String(64), nullable=False)
    brand_code: Mapped[str] = mapped_column(
        Text, ForeignKey("raw_oy_brand.brand_code"), nullable=False
    )
    brand_name: Mapped[str] = mapped_column(Text, nullable=False)
    product_name: Mapped[str] = mapped_column(Text, nullable=False)
    category: Mapped[str] = mapped_column(Text, nullable=False)
    texture_code: Mapped[str] = mapped_column(
        Text, ForeignKey("raw_oy_texture_type.texture_code"), nullable=False
    )
    judge_step: Mapped[str] = mapped_column(Text, nullable=False)
    judge_reason: Mapped[str] = mapped_column(Text, nullable=False)
    source_url: Mapped[str] = mapped_column(Text, nullable=False)
    observed_at: Mapped[date] = mapped_column(Date, nullable=False)


class RawOfficialProductOptionRow(Base):
    __tablename__ = "raw_official_product_option"
    __table_args__ = (
        CheckConstraint(
            "selected_hex ~ '^#[0-9A-F]{6}$'",
            name="ck_raw_official_option_selected_hex",
        ),
        CheckConstraint(
            "official_hex ~ '^#[0-9A-F]{6}$'",
            name="ck_raw_official_option_site_hex",
        ),
        UniqueConstraint(
            "source_product_id", "shade_code", name="uq_raw_official_option_product_code"
        ),
        UniqueConstraint(
            "source_product_id",
            "serving_shade_id",
            name="uq_raw_official_option_product_serving_shade",
        ),
    )

    source_option_id: Mapped[str] = mapped_column(Text, primary_key=True)
    source_product_id: Mapped[str] = mapped_column(
        Text,
        ForeignKey("raw_official_product.source_product_id", ondelete="CASCADE"),
        nullable=False,
    )
    raw_oy_option_id: Mapped[str | None] = mapped_column(
        Text, ForeignKey("raw_oy_product_option.option_id"), nullable=True
    )
    serving_shade_id: Mapped[str] = mapped_column(String(64), nullable=False)
    shade_code: Mapped[str] = mapped_column(Text, nullable=False)
    shade_name: Mapped[str] = mapped_column(Text, nullable=False)
    option_name: Mapped[str] = mapped_column(Text, nullable=False)
    official_sku_base_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    official_sku_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    selected_hex: Mapped[str] = mapped_column(String(7), nullable=False)
    official_hex: Mapped[str] = mapped_column(String(7), nullable=False)
    lab_l: Mapped[float | None] = mapped_column(REAL, nullable=True)
    lab_a: Mapped[float | None] = mapped_column(REAL, nullable=True)
    lab_b: Mapped[float | None] = mapped_column(REAL, nullable=True)
    color_method: Mapped[str] = mapped_column(Text, nullable=False)
    color_confidence: Mapped[float | None] = mapped_column(REAL, nullable=True)
    measure_method: Mapped[str] = mapped_column(Text, nullable=False)
    selected_source: Mapped[str] = mapped_column(Text, nullable=False)
    source_url: Mapped[str] = mapped_column(Text, nullable=False)
    observed_at: Mapped[date] = mapped_column(Date, nullable=False)

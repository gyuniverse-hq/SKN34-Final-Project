from typing import Any

from sqlalchemy import Float, ForeignKey, Index, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db import Base

JsonType = JSONB


class ProductRow(Base):
    __tablename__ = "products"
    __table_args__ = (
        Index(
            "ix_products_search_text_trgm",
            "search_text",
            postgresql_using="gin",
            postgresql_ops={"search_text": "gin_trgm_ops"},
        ),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    position: Mapped[int] = mapped_column(Integer, default=0)
    brand: Mapped[str] = mapped_column(String(100))
    name: Mapped[str] = mapped_column(String(200))
    name_ko: Mapped[str] = mapped_column(String(200))
    category: Mapped[str] = mapped_column(String(20), index=True)
    makeup_zone: Mapped[str | None] = mapped_column(String(20))
    texture: Mapped[str | None] = mapped_column(String(20), nullable=True)
    price_krw: Mapped[int] = mapped_column(Integer)
    volume: Mapped[str] = mapped_column(String(50))
    description: Mapped[str] = mapped_column(Text)
    key_ingredients: Mapped[list[str]] = mapped_column(JsonType)
    tags: Mapped[list[str]] = mapped_column(JsonType)
    image_url: Mapped[str] = mapped_column(Text)
    search_keyword: Mapped[str] = mapped_column(String(200))
    # Lowercased brand, names, description, tags and shade names; matched with LIKE + trigram index.
    search_text: Mapped[str] = mapped_column(Text)

    shades: Mapped[list["ShadeRow"]] = relationship(
        order_by="ShadeRow.position", cascade="all, delete-orphan", lazy="selectin"
    )


class ShadeRow(Base):
    __tablename__ = "shades"

    product_id: Mapped[str] = mapped_column(
        ForeignKey("products.id", ondelete="CASCADE"), primary_key=True
    )
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    position: Mapped[int] = mapped_column(Integer, default=0)
    name: Mapped[str] = mapped_column(String(100))
    hex: Mapped[str] = mapped_column(String(7))
    measure_method: Mapped[str | None] = mapped_column(String(20), nullable=True)
    color_source: Mapped[str | None] = mapped_column(String(20), nullable=True)
    color_confidence: Mapped[float | None] = mapped_column(Float, nullable=True)


class LookRow(Base):
    __tablename__ = "looks"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    position: Mapped[int] = mapped_column(Integer, default=0)
    title: Mapped[str] = mapped_column(String(200))
    inspiration: Mapped[str] = mapped_column(String(200))
    description: Mapped[str] = mapped_column(Text)
    thumbnail_url: Mapped[str] = mapped_column(Text)
    tutorial_query: Mapped[str] = mapped_column(String(200))
    makeup: Mapped[dict[str, Any]] = mapped_column(JsonType)
    tags: Mapped[list[str]] = mapped_column(JsonType)

    items: Mapped[list["LookItemRow"]] = relationship(
        order_by="LookItemRow.position", cascade="all, delete-orphan", lazy="selectin"
    )


class LookItemRow(Base):
    __tablename__ = "look_items"

    look_id: Mapped[str] = mapped_column(
        ForeignKey("looks.id", ondelete="CASCADE"), primary_key=True
    )
    position: Mapped[int] = mapped_column(Integer, primary_key=True)
    product_id: Mapped[str] = mapped_column(ForeignKey("products.id"), index=True)
    shade_id: Mapped[str | None] = mapped_column(String(64))
    step: Mapped[str] = mapped_column(String(20))


class StoreRow(Base):
    __tablename__ = "stores"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    position: Mapped[int] = mapped_column(Integer, default=0)
    name: Mapped[str] = mapped_column(String(200))
    address: Mapped[str] = mapped_column(String(300))
    district: Mapped[str] = mapped_column(String(100))
    lat: Mapped[float]
    lng: Mapped[float]
    hours: Mapped[str] = mapped_column(String(100))
    phone: Mapped[str | None] = mapped_column(String(40))
    pickup_available: Mapped[bool]

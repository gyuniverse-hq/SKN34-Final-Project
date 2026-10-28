from sqlalchemy import Boolean, Float, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db import Base


class YoutubeVideoRow(Base):
    __tablename__ = "youtube_videos"
    __table_args__ = (Index("ix_youtube_videos_video_id", "video_id"),)
    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    video_id: Mapped[str] = mapped_column(String(32), unique=True)
    youtube_url: Mapped[str] = mapped_column(Text)
    start_seconds: Mapped[int] = mapped_column(Integer, default=0)
    title: Mapped[str] = mapped_column(String(300))
    channel_name: Mapped[str] = mapped_column(String(200), default="")
    thumbnail_url: Mapped[str] = mapped_column(Text)
    description: Mapped[str | None] = mapped_column(Text)
    published_at: Mapped[str | None] = mapped_column(String(40))
    analysis_status: Mapped[str] = mapped_column(String(32))
    product_mapping_status: Mapped[str] = mapped_column(String(32))


class MakeupLookRow(Base):
    __tablename__ = "makeup_looks"
    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    video_id: Mapped[str] = mapped_column(ForeignKey("youtube_videos.id"), unique=True)
    display_name: Mapped[str] = mapped_column(String(300))
    style_description: Mapped[str] = mapped_column(Text)
    is_published: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    video: Mapped[YoutubeVideoRow] = relationship(lazy="selectin")
    products: Mapped[list["LookProductRow"]] = relationship(
        cascade="all, delete-orphan", lazy="selectin"
    )
    ar_settings: Mapped[list["LookArSettingRow"]] = relationship(
        cascade="all, delete-orphan", lazy="selectin"
    )


class LookProductRow(Base):
    __tablename__ = "look_products"
    __table_args__ = (UniqueConstraint("look_id", "id", name="uq_look_products_look_id_id"),)
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    look_id: Mapped[str] = mapped_column(
        ForeignKey("makeup_looks.id", ondelete="CASCADE"), index=True
    )
    makeup_zone: Mapped[str] = mapped_column(String(20))
    status: Mapped[str] = mapped_column(String(32))
    product_id: Mapped[str | None] = mapped_column(ForeignKey("products.id"), index=True)
    shade_id: Mapped[str | None] = mapped_column(String(64))
    source_type: Mapped[str | None] = mapped_column(String(64))
    source_url: Mapped[str | None] = mapped_column(Text)
    evidence_text: Mapped[str | None] = mapped_column(Text)
    verified: Mapped[bool] = mapped_column(Boolean, default=False)
    similarity_score: Mapped[float | None] = mapped_column(Float)
    recommendation_reason: Mapped[str | None] = mapped_column(Text)


class LookArSettingRow(Base):
    __tablename__ = "look_ar_settings"
    look_id: Mapped[str] = mapped_column(
        ForeignKey("makeup_looks.id", ondelete="CASCADE"), primary_key=True
    )
    makeup_zone: Mapped[str] = mapped_column(String(20), primary_key=True)
    hex: Mapped[str] = mapped_column(String(7))
    intensity: Mapped[float] = mapped_column(Float)
    texture: Mapped[str] = mapped_column(String(20))

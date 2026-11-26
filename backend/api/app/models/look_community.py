from datetime import datetime
from uuid import UUID

from sqlalchemy import DateTime, ForeignKey, Index, String, desc, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


class LookPostRow(Base):
    __tablename__ = "look_posts"
    __table_args__ = (
        Index(
            "look_posts_public_recent",
            desc("created_at"),
            "id",
            postgresql_where=text("NOT hidden"),
        ),
        Index("look_posts_owner_recent", "owner_id", desc("created_at")),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True)
    owner_id: Mapped[str] = mapped_column(String(64), ForeignKey("members.id", ondelete="CASCADE"))
    title: Mapped[str] = mapped_column(String(80))
    description: Mapped[str] = mapped_column(String(500))
    products: Mapped[list[dict[str, str]]] = mapped_column(JSONB)
    photo: Mapped[bytes]
    hidden: Mapped[bool] = mapped_column(server_default=text("false"))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()")
    )


class LookPostVoteRow(Base):
    __tablename__ = "look_post_votes"

    post_id: Mapped[UUID] = mapped_column(
        ForeignKey("look_posts.id", ondelete="CASCADE"), primary_key=True
    )
    member_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("members.id", ondelete="CASCADE"), primary_key=True
    )


class LookPostReportRow(Base):
    __tablename__ = "look_post_reports"

    post_id: Mapped[UUID] = mapped_column(
        ForeignKey("look_posts.id", ondelete="CASCADE"), primary_key=True
    )
    member_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("members.id", ondelete="CASCADE"), primary_key=True
    )
    reason: Mapped[str] = mapped_column(String(300))

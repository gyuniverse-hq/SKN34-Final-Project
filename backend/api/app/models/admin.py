from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


class StaffRoleRow(Base):
    __tablename__ = "staff_roles"
    __table_args__ = (CheckConstraint("role IN ('admin', 'viewer')", name="ck_staff_role"),)
    user_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("members.id", ondelete="CASCADE"), primary_key=True
    )
    role: Mapped[str] = mapped_column(String(16))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    created_by: Mapped[str | None] = mapped_column(String(64))


class AdminAuditLogRow(Base):
    __tablename__ = "admin_audit_log"
    __table_args__ = (Index("ix_admin_audit_target", "target_type", "target_id", "created_at"),)
    id: Mapped[UUID] = mapped_column(PgUUID, primary_key=True, default=uuid4)
    actor_user_id: Mapped[str | None] = mapped_column(
        String(64), ForeignKey("members.id", ondelete="SET NULL")
    )
    action: Mapped[str] = mapped_column(String(80))
    target_type: Mapped[str] = mapped_column(String(40))
    target_id: Mapped[str] = mapped_column(String(128))
    before_json: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    after_json: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    request_id: Mapped[str] = mapped_column(String(128))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), index=True
    )


class ProductAdminStateRow(Base):
    __tablename__ = "product_admin_state"
    __table_args__ = (CheckConstraint("stock IS NULL OR stock >= 0", name="ck_admin_stock"),)
    product_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("products.id", ondelete="CASCADE"), primary_key=True
    )
    is_visible: Mapped[bool] = mapped_column(Boolean, server_default="true")
    stock: Mapped[int | None] = mapped_column(Integer)
    updated_by: Mapped[str | None] = mapped_column(String(64))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class EvalRunRow(Base):
    __tablename__ = "eval_runs"
    __table_args__ = (
        CheckConstraint("kind IN ('human', 'bench', 'judge')", name="ck_eval_kind"),
        CheckConstraint("jsonb_typeof(summary_json) = 'object'", name="ck_eval_summary"),
    )
    id: Mapped[UUID] = mapped_column(PgUUID, primary_key=True, default=uuid4)
    kind: Mapped[str] = mapped_column(String(16))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), index=True
    )
    renderer_commit: Mapped[str] = mapped_column(String(40))
    renderer_dirty: Mapped[bool] = mapped_column(Boolean)
    rubric_version: Mapped[str] = mapped_column(String(64))
    metric_version: Mapped[str] = mapped_column(String(64))
    benchmark_sha256: Mapped[str] = mapped_column(String(64))
    summary_json: Mapped[dict[str, Any]] = mapped_column(JSONB)
    summary_hash: Mapped[str] = mapped_column(String(64), unique=True)
    uploaded_by: Mapped[str | None] = mapped_column(
        String(64), ForeignKey("members.id", ondelete="SET NULL")
    )


class LipEvalProductRow(Base):
    __tablename__ = "lip_eval_products"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    brand: Mapped[str] = mapped_column(String(80))
    name: Mapped[str] = mapped_column(String(160))
    shade: Mapped[str] = mapped_column(String(120))
    sort_order: Mapped[int] = mapped_column(Integer)


class LipEvalSlotRow(Base):
    __tablename__ = "lip_eval_slots"
    __table_args__ = (CheckConstraint("rater_id BETWEEN 1 AND 5", name="ck_lip_eval_rater"),)
    product_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("lip_eval_products.id", ondelete="CASCADE"), primary_key=True
    )
    rater_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    bare_path: Mapped[str | None] = mapped_column(String(512))
    real_path: Mapped[str | None] = mapped_column(String(512))
    ar_path: Mapped[str | None] = mapped_column(String(512))
    technical_json: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    naturalness_json: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    scored_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

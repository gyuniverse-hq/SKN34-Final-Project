from datetime import datetime
from uuid import UUID

from sqlalchemy import CheckConstraint, DateTime, Index, Integer, String, text
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


class AccountDeletionJobRow(Base):
    """Durable deletion progress; independent of the member record being deleted."""

    __tablename__ = "account_deletion_jobs"
    __table_args__ = (
        CheckConstraint("length(owner_id) > 0", name="ck_account_deletion_owner_nonempty"),
        CheckConstraint(
            "status IN ('PENDING', 'IN_PROGRESS', 'RETRY_REQUIRED', 'DONE')",
            name="ck_account_deletion_status",
        ),
        CheckConstraint(
            "phase IN ('BLOCKING', 'PURGING_CHAT', 'DELETING_AUTH', 'DELETING_MEMBER', 'DONE')",
            name="ck_account_deletion_phase",
        ),
        CheckConstraint("(status = 'DONE') = (phase = 'DONE')", name="ck_account_deletion_done"),
        CheckConstraint("attempt_count >= 0", name="ck_account_deletion_attempt_count"),
        CheckConstraint(
            "(status = 'IN_PROGRESS' AND lease_token IS NOT NULL AND lease_until IS NOT NULL) "
            "OR (status <> 'IN_PROGRESS' AND lease_token IS NULL AND lease_until IS NULL)",
            name="ck_account_deletion_lease",
        ),
        Index(
            "ix_account_deletion_ready",
            "next_attempt_at",
            "created_at",
            postgresql_where=text("status IN ('PENDING', 'RETRY_REQUIRED')"),
        ),
        Index(
            "ix_account_deletion_expired_lease",
            "lease_until",
            postgresql_where=text("status = 'IN_PROGRESS'"),
        ),
    )

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True)
    owner_id: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, server_default=text("'PENDING'")
    )
    phase: Mapped[str] = mapped_column(
        String(24), nullable=False, server_default=text("'BLOCKING'")
    )
    attempt_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    next_attempt_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    lease_token: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True))
    lease_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    error_code: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )

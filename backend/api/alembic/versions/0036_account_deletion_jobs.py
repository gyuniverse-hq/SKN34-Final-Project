"""Add durable account deletion job state without changing the existing deletion API."""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "0036"
down_revision = "0035"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "account_deletion_jobs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("owner_id", sa.String(64), nullable=False, unique=True),
        sa.Column("status", sa.String(16), nullable=False, server_default="PENDING"),
        sa.Column("phase", sa.String(24), nullable=False, server_default="BLOCKING"),
        sa.Column("attempt_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "next_attempt_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("lease_token", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("lease_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error_code", sa.String(64), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.CheckConstraint("length(owner_id) > 0", name="ck_account_deletion_owner_nonempty"),
        sa.CheckConstraint(
            "status IN ('PENDING', 'IN_PROGRESS', 'RETRY_REQUIRED', 'DONE')",
            name="ck_account_deletion_status",
        ),
        sa.CheckConstraint(
            "phase IN ('BLOCKING', 'PURGING_CHAT', 'DELETING_AUTH', 'DELETING_MEMBER', 'DONE')",
            name="ck_account_deletion_phase",
        ),
        sa.CheckConstraint("(status = 'DONE') = (phase = 'DONE')", name="ck_account_deletion_done"),
        sa.CheckConstraint("attempt_count >= 0", name="ck_account_deletion_attempt_count"),
        sa.CheckConstraint(
            "(status = 'IN_PROGRESS' AND lease_token IS NOT NULL AND lease_until IS NOT NULL) "
            "OR (status <> 'IN_PROGRESS' AND lease_token IS NULL AND lease_until IS NULL)",
            name="ck_account_deletion_lease",
        ),
    )
    op.create_index(
        "ix_account_deletion_ready",
        "account_deletion_jobs",
        ["next_attempt_at", "created_at"],
        postgresql_where=sa.text("status IN ('PENDING', 'RETRY_REQUIRED')"),
    )
    op.create_index(
        "ix_account_deletion_expired_lease",
        "account_deletion_jobs",
        ["lease_until"],
        postgresql_where=sa.text("status = 'IN_PROGRESS'"),
    )


def downgrade() -> None:
    op.drop_table("account_deletion_jobs")

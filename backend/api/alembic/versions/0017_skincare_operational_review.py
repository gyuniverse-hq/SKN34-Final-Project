"""Separate operator review from the derived runtime flag."""

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

from alembic import op

revision = "0017"
down_revision = "0016"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("rec_mapping", sa.Column("operational_review", JSONB))
    op.add_column("rec_mapping", sa.Column("operational_reviewed_at", sa.DateTime(timezone=True)))
    # Keep legacy values available for the reviewer and for a lossless downgrade.
    op.alter_column("rec_mapping", "runtime_enabled", new_column_name="legacy_runtime_enabled")
    op.add_column(
        "rec_mapping",
        sa.Column("runtime_enabled", sa.Boolean, server_default=sa.false(), nullable=False),
    )


def downgrade():
    op.drop_column("rec_mapping", "runtime_enabled")
    op.alter_column("rec_mapping", "legacy_runtime_enabled", new_column_name="runtime_enabled")
    op.drop_column("rec_mapping", "operational_reviewed_at")
    op.drop_column("rec_mapping", "operational_review")

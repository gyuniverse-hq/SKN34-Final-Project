"""Atomic, versioned skincare serving projection (no personal data)."""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "0011"
down_revision = "0010"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "skincare_serving",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("data_version", sa.String(200), nullable=False),
        sa.Column("payload", postgresql.JSONB(), nullable=False),
        sa.CheckConstraint("id = 1", name="ck_skincare_serving_singleton"),
    )


def downgrade():
    op.drop_table("skincare_serving")

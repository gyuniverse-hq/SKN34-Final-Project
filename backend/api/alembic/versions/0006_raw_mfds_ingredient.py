"""Add the MFDS cosmetic ingredient source table.

Revision ID: 0006
Revises: 0005
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0006"
down_revision: str | Sequence[str] | None = "0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "raw_mfds_ingredient",
        sa.Column("ingredient_id", sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column("name_ko", sa.Text(), nullable=False),
        sa.Column("name_key", sa.Text(), nullable=False),
        sa.Column("name_en", sa.Text(), nullable=True),
        sa.Column("cas_no_raw", sa.Text(), nullable=True),
        sa.Column("origin_ko_raw", sa.Text(), nullable=True),
        sa.Column("synonym_raw", sa.Text(), nullable=True),
        sa.Column("source_payload", postgresql.JSONB(), nullable=False),
        sa.Column("source_hash", sa.String(64), nullable=False),
        sa.Column("first_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("is_current", sa.Boolean(), nullable=False),
        sa.UniqueConstraint("name_key", name="uq_raw_mfds_ingredient_name_key"),
    )
    op.create_index("ix_raw_mfds_ingredient_is_current", "raw_mfds_ingredient", ["is_current"])


def downgrade() -> None:
    op.drop_index("ix_raw_mfds_ingredient_is_current", table_name="raw_mfds_ingredient")
    op.drop_table("raw_mfds_ingredient")

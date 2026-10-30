"""Add confirmed links between Olive Young and MFDS ingredients.

Revision ID: 0007
Revises: 0006
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0007"
down_revision: str | Sequence[str] | None = "0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "oy_mfds_ingredient_map",
        sa.Column(
            "oy_ingredient_id",
            sa.BigInteger(),
            sa.ForeignKey("raw_oy_ingredient.ingredient_id"),
            primary_key=True,
        ),
        sa.Column(
            "mfds_ingredient_id",
            sa.BigInteger(),
            sa.ForeignKey("raw_mfds_ingredient.ingredient_id"),
            nullable=False,
        ),
        sa.Column("match_method", sa.Text(), nullable=False),
        sa.Column("rule_version", sa.Text(), nullable=True),
        sa.Column(
            "matched_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("reviewed_by", sa.Text(), nullable=True),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("review_note", sa.Text(), nullable=True),
        sa.CheckConstraint(
            "match_method IN ('exact_name', 'official_synonym', 'manual')",
            name="ck_oy_mfds_ingredient_map_method",
        ),
        sa.CheckConstraint(
            "(match_method = 'manual' AND reviewed_by IS NOT NULL AND reviewed_at IS NOT NULL) "
            "OR (match_method <> 'manual' AND rule_version IS NOT NULL)",
            name="ck_oy_mfds_ingredient_map_provenance",
        ),
    )
    op.create_index(
        "ix_oy_mfds_ingredient_map_mfds_id",
        "oy_mfds_ingredient_map",
        ["mfds_ingredient_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_oy_mfds_ingredient_map_mfds_id", table_name="oy_mfds_ingredient_map")
    op.drop_table("oy_mfds_ingredient_map")

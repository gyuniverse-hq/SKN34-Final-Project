"""Record ingredient matches made after removing a final concentration annotation.

Revision ID: 0011
Revises: 0010
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0011"
down_revision: str | Sequence[str] | None = "0010"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_constraint("ck_oy_mfds_ingredient_map_method", "oy_mfds_ingredient_map", type_="check")
    op.create_check_constraint(
        "ck_oy_mfds_ingredient_map_method",
        "oy_mfds_ingredient_map",
        "match_method IN ('exact_name', 'official_synonym', "
        "'amount_suffix_exact', 'amount_suffix_synonym', 'manual')",
    )


def downgrade() -> None:
    count = op.get_bind().scalar(
        sa.text(
            "SELECT COUNT(*) FROM oy_mfds_ingredient_map WHERE match_method IN "
            "('amount_suffix_exact', 'amount_suffix_synonym')"
        )
    )
    if count:
        raise RuntimeError("Remove amount-suffix mappings before downgrading to 0010")
    op.drop_constraint("ck_oy_mfds_ingredient_map_method", "oy_mfds_ingredient_map", type_="check")
    op.create_check_constraint(
        "ck_oy_mfds_ingredient_map_method",
        "oy_mfds_ingredient_map",
        "match_method IN ('exact_name', 'official_synonym', 'manual')",
    )

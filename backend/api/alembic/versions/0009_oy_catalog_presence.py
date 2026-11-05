"""Track which Olive Young products are currently in the serving catalog.

Revision ID: 0009
Revises: 0008
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0009"
down_revision: str | Sequence[str] | None = "0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "raw_oy_product",
        sa.Column("is_in_catalog", sa.Boolean(), nullable=False, server_default=sa.text("false")),
    )
    op.execute(
        """
        UPDATE raw_oy_product AS raw
        SET is_in_catalog = EXISTS (
            SELECT 1 FROM products AS product
            WHERE product.id = 'oy-' || lower(raw.goods_no)
        )
        """
    )


def downgrade() -> None:
    op.drop_column("raw_oy_product", "is_in_catalog")

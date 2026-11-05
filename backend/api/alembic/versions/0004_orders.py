"""orders for server-verified payment approval

Revision ID: 0004
Revises: 0003
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0004"
down_revision: str | Sequence[str] | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "orders",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("user_id", sa.String(64), nullable=False),
        sa.Column("amount_krw", sa.Integer(), nullable=False),
        sa.Column("order_name", sa.String(100), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("checkout_token_hash", sa.String(64), nullable=False),
        sa.Column("payment_key", sa.String(200), unique=True),
    )
    op.create_index("ix_orders_user_id", "orders", ["user_id"])
    op.create_index("ix_orders_status", "orders", ["status"])
    op.create_table(
        "order_lines",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "order_id",
            sa.String(64),
            sa.ForeignKey("orders.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("product_id", sa.String(64), nullable=False),
        sa.Column("shade_id", sa.String(64)),
        sa.Column("quantity", sa.Integer(), nullable=False),
        sa.Column("unit_price_krw", sa.Integer(), nullable=False),
    )
    op.create_index("ix_order_lines_order_id", "order_lines", ["order_id"])


def downgrade() -> None:
    op.drop_index("ix_order_lines_order_id", table_name="order_lines")
    op.drop_table("order_lines")
    op.drop_index("ix_orders_status", table_name="orders")
    op.drop_index("ix_orders_user_id", table_name="orders")
    op.drop_table("orders")

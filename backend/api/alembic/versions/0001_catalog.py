"""catalog: products, shades, looks, look_items, stores

Revision ID: 0001
Revises:
Create Date: 2026-10-23
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")

    op.create_table(
        "products",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("position", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("brand", sa.String(100), nullable=False),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("name_ko", sa.String(200), nullable=False),
        sa.Column("category", sa.String(20), nullable=False),
        sa.Column("makeup_zone", sa.String(20), nullable=True),
        sa.Column("texture", sa.String(20), nullable=False),
        sa.Column("price_krw", sa.Integer(), nullable=False),
        sa.Column("volume", sa.String(50), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("key_ingredients", postgresql.JSONB(), nullable=False),
        sa.Column("tags", postgresql.JSONB(), nullable=False),
        sa.Column("image_url", sa.Text(), nullable=False),
        sa.Column("search_keyword", sa.String(200), nullable=False),
        sa.Column("search_text", sa.Text(), nullable=False),
    )
    op.create_index("ix_products_category", "products", ["category"])
    op.create_index(
        "ix_products_search_text_trgm",
        "products",
        ["search_text"],
        postgresql_using="gin",
        postgresql_ops={"search_text": "gin_trgm_ops"},
    )

    op.create_table(
        "shades",
        sa.Column(
            "product_id",
            sa.String(64),
            sa.ForeignKey("products.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("position", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("hex", sa.String(7), nullable=False),
    )

    op.create_table(
        "looks",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("position", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("title", sa.String(200), nullable=False),
        sa.Column("inspiration", sa.String(200), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("thumbnail_url", sa.Text(), nullable=False),
        sa.Column("tutorial_query", sa.String(200), nullable=False),
        sa.Column("makeup", postgresql.JSONB(), nullable=False),
        sa.Column("tags", postgresql.JSONB(), nullable=False),
    )

    op.create_table(
        "look_items",
        sa.Column(
            "look_id",
            sa.String(64),
            sa.ForeignKey("looks.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("position", sa.Integer(), primary_key=True),
        sa.Column("product_id", sa.String(64), sa.ForeignKey("products.id"), nullable=False),
        sa.Column("shade_id", sa.String(64), nullable=True),
        sa.Column("step", sa.String(20), nullable=False),
    )
    op.create_index("ix_look_items_product_id", "look_items", ["product_id"])

    op.create_table(
        "stores",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("position", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("address", sa.String(300), nullable=False),
        sa.Column("district", sa.String(100), nullable=False),
        sa.Column("lat", sa.Float(), nullable=False),
        sa.Column("lng", sa.Float(), nullable=False),
        sa.Column("hours", sa.String(100), nullable=False),
        sa.Column("phone", sa.String(40), nullable=True),
        sa.Column("pickup_available", sa.Boolean(), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("stores")
    op.drop_index("ix_look_items_product_id", table_name="look_items")
    op.drop_table("look_items")
    op.drop_table("looks")
    op.drop_table("shades")
    op.drop_index("ix_products_search_text_trgm", table_name="products")
    op.drop_index("ix_products_category", table_name="products")
    op.drop_table("products")

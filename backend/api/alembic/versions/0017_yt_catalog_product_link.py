"""Link reviewed YouTube source products to serving catalog products.

Revision ID: 0017
Revises: 0016
"""

import sqlalchemy as sa

from alembic import op

revision = "0017"
down_revision = "0016"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "yt_catalog_product_link",
        sa.Column("source_yt_product_id", sa.Text(), nullable=False),
        sa.Column("serving_product_id", sa.String(64), nullable=False),
        sa.Column("link_type", sa.Text(), nullable=False),
        sa.Column("evidence_url", sa.Text()),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "link_type IN ('direct', 'merged', 'split', 'corrected')",
            name="ck_yt_catalog_product_link_type",
        ),
        sa.ForeignKeyConstraint(
            ["source_yt_product_id"],
            ["raw_yt_product.yt_product_id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["serving_product_id"], ["products.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint(
            "source_yt_product_id",
            "serving_product_id",
            name="pk_yt_catalog_product_link",
        ),
    )
    op.create_index(
        "ix_yt_catalog_product_link_serving",
        "yt_catalog_product_link",
        ["serving_product_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_yt_catalog_product_link_serving", table_name="yt_catalog_product_link")
    op.drop_table("yt_catalog_product_link")

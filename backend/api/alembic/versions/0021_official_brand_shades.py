"""Store reviewed official-brand shade colors apart from Olive Young raw data.

Revision ID: 0021
Revises: 0020
"""

import sqlalchemy as sa

from alembic import op

revision = "0021"
down_revision = "0020"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "raw_official_product",
        sa.Column("source_product_id", sa.Text(), primary_key=True),
        sa.Column(
            "raw_oy_goods_no", sa.Text(), sa.ForeignKey("raw_oy_product.goods_no"), nullable=False
        ),
        # Soft reference: seed_catalog replaces all products in one transaction.
        sa.Column("serving_product_id", sa.String(64), nullable=False),
        sa.Column(
            "brand_code", sa.Text(), sa.ForeignKey("raw_oy_brand.brand_code"), nullable=False
        ),
        sa.Column("brand_name", sa.Text(), nullable=False),
        sa.Column("product_name", sa.Text(), nullable=False),
        sa.Column("category", sa.Text(), nullable=False),
        sa.Column("source_url", sa.Text(), nullable=False),
        sa.Column("observed_at", sa.Date(), nullable=False),
    )
    op.create_table(
        "raw_official_product_option",
        sa.Column("source_option_id", sa.Text(), primary_key=True),
        sa.Column(
            "source_product_id",
            sa.Text(),
            sa.ForeignKey("raw_official_product.source_product_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("raw_oy_option_id", sa.Text(), sa.ForeignKey("raw_oy_product_option.option_id")),
        sa.Column("serving_shade_id", sa.String(64), nullable=False),
        sa.Column("shade_code", sa.Text(), nullable=False),
        sa.Column("shade_name", sa.Text(), nullable=False),
        sa.Column("option_name", sa.Text(), nullable=False),
        sa.Column("official_sku_base_id", sa.Text()),
        sa.Column("official_sku_id", sa.Text()),
        sa.Column("source_url", sa.Text(), nullable=False),
        sa.Column("observed_at", sa.Date(), nullable=False),
        sa.UniqueConstraint(
            "source_product_id", "shade_code", name="uq_raw_official_option_product_code"
        ),
        sa.UniqueConstraint(
            "source_product_id",
            "serving_shade_id",
            name="uq_raw_official_option_product_serving_shade",
        ),
    )
    op.create_table(
        "raw_official_option_color",
        sa.Column(
            "source_option_id",
            sa.Text(),
            sa.ForeignKey("raw_official_product_option.source_option_id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("selected_hex", sa.String(7), nullable=False),
        sa.Column("official_hex", sa.String(7), nullable=False),
        sa.Column("lab_l", sa.REAL()),
        sa.Column("lab_a", sa.REAL()),
        sa.Column("lab_b", sa.REAL()),
        sa.Column("color_method", sa.Text(), nullable=False),
        sa.Column("color_confidence", sa.REAL()),
        sa.Column("measure_method", sa.Text(), nullable=False),
        sa.Column("selected_source", sa.Text(), nullable=False),
        sa.Column("source_image_filename", sa.Text()),
        sa.Column("source_image_sha256", sa.String(64)),
        sa.Column("source_image_png", sa.LargeBinary()),
        sa.Column("source_url", sa.Text(), nullable=False),
        sa.Column("observed_at", sa.Date(), nullable=False),
        sa.CheckConstraint("selected_hex ~ '^#[0-9A-F]{6}$'", name="ck_raw_official_selected_hex"),
        sa.CheckConstraint("official_hex ~ '^#[0-9A-F]{6}$'", name="ck_raw_official_site_hex"),
    )
    op.create_table(
        "raw_official_product_texture",
        sa.Column(
            "source_product_id",
            sa.Text(),
            sa.ForeignKey("raw_official_product.source_product_id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column(
            "texture_code",
            sa.Text(),
            sa.ForeignKey("raw_oy_texture_type.texture_code"),
            nullable=False,
        ),
        sa.Column("judge_step", sa.Text(), nullable=False),
        sa.Column("judge_reason", sa.Text(), nullable=False),
        sa.Column("source_url", sa.Text(), nullable=False),
        sa.Column("observed_at", sa.Date(), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("raw_official_product_texture")
    op.drop_table("raw_official_option_color")
    op.drop_table("raw_official_product_option")
    op.drop_table("raw_official_product")

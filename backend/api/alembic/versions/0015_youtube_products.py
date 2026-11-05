"""Store researched YouTube products, video mentions, and Olive Young candidates.

Revision ID: 0015
Revises: 0014
"""

import sqlalchemy as sa

from alembic import op

revision = "0015"
down_revision = "0014"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "raw_yt_product",
        sa.Column("yt_product_id", sa.Text(), primary_key=True),
        sa.Column("brand_name", sa.Text(), nullable=False),
        sa.Column("product_name", sa.Text(), nullable=False),
        sa.Column("option_name", sa.Text()),
        sa.Column("category", sa.Text()),
        sa.Column("makeup_zone", sa.Text()),
        sa.Column("price_krw", sa.Integer()),
        sa.Column("price_type", sa.Text()),
        sa.Column("volume", sa.Text()),
        sa.Column("texture", sa.Text()),
        sa.Column("hex_code", sa.Text()),
        sa.Column("image_url", sa.Text()),
        sa.Column("image_source_url", sa.Text()),
        sa.Column("product_url", sa.Text()),
        sa.Column("description", sa.Text()),
        sa.Column("checked_at", sa.Date()),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "hex_code IS NULL OR hex_code ~ '^#[0-9A-Fa-f]{6}$'", name="ck_raw_yt_product_hex"
        ),
        sa.CheckConstraint("price_krw IS NULL OR price_krw >= 0", name="ck_raw_yt_product_price"),
    )
    op.create_index(
        "ix_raw_yt_product_brand_name", "raw_yt_product", ["brand_name", "product_name"]
    )
    op.create_table(
        "raw_yt_product_mention",
        sa.Column("source_row_id", sa.Text(), primary_key=True),
        sa.Column(
            "yt_product_id",
            sa.Text(),
            sa.ForeignKey("raw_yt_product.yt_product_id"),
            nullable=False,
        ),
        sa.Column("source_product_record_id", sa.Text(), nullable=False, unique=True),
        sa.Column("source", sa.Text(), nullable=False),
        sa.Column("video_id", sa.Text(), nullable=False),
        sa.Column("mention_number", sa.Integer(), nullable=False),
        sa.Column("video_url", sa.Text(), nullable=False),
        sa.Column("video_playback_status", sa.Text()),
        sa.Column("video_use_evidence", sa.Text()),
        sa.Column("research_status", sa.Text()),
        sa.Column("review_reason", sa.Text()),
    )
    op.create_index("ix_raw_yt_mention_product", "raw_yt_product_mention", ["yt_product_id"])
    op.create_index("ix_raw_yt_mention_video", "raw_yt_product_mention", ["video_id"])
    op.create_table(
        "yt_oy_product_match",
        sa.Column("match_id", sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column(
            "yt_product_id",
            sa.Text(),
            sa.ForeignKey("raw_yt_product.yt_product_id"),
            nullable=False,
        ),
        sa.Column(
            "oy_goods_no", sa.Text(), sa.ForeignKey("raw_oy_product.goods_no"), nullable=False
        ),
        sa.Column("oy_option_id", sa.Text(), sa.ForeignKey("raw_oy_product_option.option_id")),
        sa.Column("candidate_rank", sa.Integer(), nullable=False),
        sa.Column("match_method", sa.Text(), nullable=False),
        sa.Column("similarity_score", sa.Float()),
        sa.Column("match_reason", sa.Text()),
        sa.Column("rule_version", sa.Text()),
        sa.Column("decision_status", sa.Text(), server_default="candidate", nullable=False),
        sa.Column("reviewer", sa.Text()),
        sa.Column("decided_at", sa.DateTime(timezone=True)),
        sa.CheckConstraint(
            "decision_status IN ('candidate', 'confirmed', 'rejected', 'needs_review')",
            name="ck_yt_oy_match_status",
        ),
    )
    op.create_index("ix_yt_oy_match_product", "yt_oy_product_match", ["yt_product_id"])
    op.create_index("ix_yt_oy_match_oy", "yt_oy_product_match", ["oy_goods_no"])
    op.create_index(
        "uq_yt_oy_match_candidate",
        "yt_oy_product_match",
        ["yt_product_id", "oy_goods_no", "oy_option_id"],
        unique=True,
        postgresql_nulls_not_distinct=True,
    )
    op.create_index(
        "uq_yt_oy_match_confirmed",
        "yt_oy_product_match",
        ["yt_product_id"],
        unique=True,
        postgresql_where=sa.text("decision_status = 'confirmed'"),
    )


def downgrade() -> None:
    op.drop_table("yt_oy_product_match")
    op.drop_table("raw_yt_product_mention")
    op.drop_table("raw_yt_product")

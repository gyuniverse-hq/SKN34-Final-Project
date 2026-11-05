"""raw oliveyoung: 올리브영 수집 원본 22테이블

Revision ID: 0005
Revises: 0004
Create Date: 2026-10-28

앱 서빙 테이블(products / shades / looks / look_items / stores)은 건드리지 않는다.
이 마이그레이션은 수집 원본(raw_oy_*)만 추가한다. 모델은 app/models/raw_oliveyoung.py.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0005"
down_revision: str | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


TEXTURE_CODES = (
    ("matte", 1),
    ("velvet", 2),
    ("cream", 3),
    ("satin", 4),
    ("sheer", 5),
    ("glossy", 6),
    ("shimmer", None),
)


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")

    op.create_table(
        "raw_oy_crawl_run",
        sa.Column("run_id", sa.BigInteger(), primary_key=True),
        sa.Column("script_version", sa.Text(), nullable=True),
        sa.Column("started_at", sa.DateTime(), nullable=True),
        sa.Column("finished_at", sa.DateTime(), nullable=True),
        sa.Column("status", sa.Text(), nullable=True),
    )

    op.create_table(
        "raw_oy_brand",
        sa.Column("brand_code", sa.Text(), primary_key=True),
        sa.Column("brand_name_ko", sa.Text(), nullable=True),
        sa.Column("brand_name_en", sa.Text(), nullable=True),
    )

    op.create_table(
        "raw_oy_supplier",
        sa.Column("supplier_code", sa.Text(), primary_key=True),
        sa.Column("supplier_name", sa.Text(), nullable=True),
    )

    op.create_table(
        "raw_oy_category",
        sa.Column("category_no", sa.Text(), primary_key=True),
        sa.Column("parent_category_no", sa.Text(), nullable=True),
        sa.Column("depth", sa.Integer(), nullable=True),
        sa.Column("category_name", sa.Text(), nullable=True),
        sa.Column("category_path", sa.Text(), nullable=True),
    )
    op.create_index("ix_raw_oy_category_parent", "raw_oy_category", ["parent_category_no"])

    op.create_table(
        "raw_oy_texture_type",
        sa.Column("texture_code", sa.Text(), primary_key=True),
        sa.Column("gloss_axis", sa.Integer(), nullable=True),
        sa.Column("ar_gloss", sa.REAL(), nullable=True),
        sa.Column("ar_matte", sa.REAL(), nullable=True),
    )

    op.create_table(
        "raw_oy_survey_question",
        sa.Column("question_code", sa.Text(), primary_key=True),
        sa.Column("question_name", sa.Text(), nullable=True),
    )

    op.create_table(
        "raw_oy_survey_answer",
        sa.Column("answer_code", sa.Text(), primary_key=True),
        sa.Column(
            "question_code",
            sa.Text(),
            sa.ForeignKey("raw_oy_survey_question.question_code"),
            nullable=True,
        ),
        sa.Column("answer_name", sa.Text(), nullable=True),
    )
    op.create_index("ix_raw_oy_answer_question", "raw_oy_survey_answer", ["question_code"])

    op.create_table(
        "raw_oy_product",
        sa.Column("goods_no", sa.Text(), primary_key=True),
        sa.Column("brand_code", sa.Text(), sa.ForeignKey("raw_oy_brand.brand_code"), nullable=True),
        sa.Column(
            "supplier_code",
            sa.Text(),
            sa.ForeignKey("raw_oy_supplier.supplier_code"),
            nullable=True,
        ),
        sa.Column(
            "category_no", sa.Text(), sa.ForeignKey("raw_oy_category.category_no"), nullable=True
        ),
        sa.Column("std_category_code", sa.Text(), nullable=True),
        sa.Column("goods_name", sa.Text(), nullable=True),
        sa.Column("product_url", sa.Text(), nullable=True),
        sa.Column("sale_status", sa.Text(), nullable=True),
        sa.Column("is_new", sa.Boolean(), nullable=True),
        sa.Column("registered_at", sa.DateTime(), nullable=True),
        sa.Column("modified_at", sa.DateTime(), nullable=True),
        sa.Column("first_collected_at", sa.DateTime(), nullable=True),
        sa.Column("last_collected_at", sa.DateTime(), nullable=True),
        sa.Column("delisted_at", sa.DateTime(), nullable=True),
    )
    op.create_index("ix_raw_oy_product_brand", "raw_oy_product", ["brand_code"])
    op.create_index("ix_raw_oy_product_supplier", "raw_oy_product", ["supplier_code"])
    op.create_index("ix_raw_oy_product_category", "raw_oy_product", ["category_no"])
    op.create_index("ix_raw_oy_product_stdcat", "raw_oy_product", ["std_category_code"])
    op.create_index(
        "ix_raw_oy_product_active",
        "raw_oy_product",
        ["goods_no"],
        postgresql_where=sa.text("delisted_at IS NULL"),
    )
    op.create_index(
        "ix_raw_oy_product_name_trgm",
        "raw_oy_product",
        ["goods_name"],
        postgresql_using="gin",
        postgresql_ops={"goods_name": "gin_trgm_ops"},
    )

    op.create_table(
        "raw_oy_product_notice",
        sa.Column(
            "goods_no", sa.Text(), sa.ForeignKey("raw_oy_product.goods_no"), primary_key=True
        ),
        sa.Column("volume", sa.Text(), nullable=True),
        sa.Column("main_spec", sa.Text(), nullable=True),
        sa.Column("shelf_life", sa.Text(), nullable=True),
        sa.Column("usage_guide", sa.Text(), nullable=True),
        sa.Column("manufacturer", sa.Text(), nullable=True),
        sa.Column("origin_country", sa.Text(), nullable=True),
        sa.Column("ingredients_raw", sa.Text(), nullable=True),
        sa.Column("notice_extra", sa.Text(), nullable=True),
        sa.Column("collected_at", sa.DateTime(), nullable=True),
    )

    op.create_table(
        "raw_oy_product_option",
        sa.Column("option_id", sa.Text(), primary_key=True),
        sa.Column("goods_no", sa.Text(), sa.ForeignKey("raw_oy_product.goods_no"), nullable=True),
        sa.Column("option_no", sa.Text(), nullable=True),
        sa.Column("barcode", sa.Text(), nullable=True),
        sa.Column("option_name", sa.Text(), nullable=True),
        sa.Column("shade_code", sa.Text(), nullable=True),
        sa.Column("shade_name", sa.Text(), nullable=True),
        sa.Column("sort_seq", sa.Integer(), nullable=True),
        sa.Column("is_representative", sa.Boolean(), nullable=True),
        sa.Column("collected_at", sa.DateTime(), nullable=True),
        sa.Column("delisted_at", sa.DateTime(), nullable=True),
    )
    op.create_index("ix_raw_oy_option_goods", "raw_oy_product_option", ["goods_no"])

    op.create_table(
        "raw_oy_skincare_attr",
        sa.Column(
            "goods_no", sa.Text(), sa.ForeignKey("raw_oy_product.goods_no"), primary_key=True
        ),
        sa.Column("is_functional", sa.Text(), nullable=True),
        sa.Column("functional_types", sa.Text(), nullable=True),
        sa.Column("functional_raw", sa.Text(), nullable=True),
        sa.Column("skin_types", sa.Text(), nullable=True),
        sa.Column("skin_type_raw", sa.Text(), nullable=True),
        sa.Column("spf", sa.Text(), nullable=True),
        sa.Column("pa", sa.Text(), nullable=True),
        sa.Column("collected_at", sa.DateTime(), nullable=True),
    )

    op.create_table(
        "raw_oy_price_snapshot",
        sa.Column("snapshot_id", sa.BigInteger(), primary_key=True),
        sa.Column(
            "option_id", sa.Text(), sa.ForeignKey("raw_oy_product_option.option_id"), nullable=True
        ),
        sa.Column("list_price", sa.Integer(), nullable=True),
        sa.Column("sale_price", sa.Integer(), nullable=True),
        sa.Column("max_benefit_price", sa.Integer(), nullable=True),
        sa.Column("is_discount", sa.Boolean(), nullable=True),
        sa.Column("is_sold_out", sa.Boolean(), nullable=True),
        sa.Column("is_latest", sa.Boolean(), nullable=True),
        sa.Column("collected_at", sa.DateTime(), nullable=True),
        sa.UniqueConstraint("option_id", "collected_at", name="uq_raw_oy_price_option_time"),
    )
    op.create_index("ix_raw_oy_price_option", "raw_oy_price_snapshot", ["option_id"])
    op.create_index(
        "uq_raw_oy_price_latest",
        "raw_oy_price_snapshot",
        ["option_id"],
        unique=True,
        postgresql_where=sa.text("is_latest"),
    )

    op.create_table(
        "raw_oy_option_color",
        sa.Column(
            "option_id",
            sa.Text(),
            sa.ForeignKey("raw_oy_product_option.option_id"),
            primary_key=True,
        ),
        sa.Column("collected_at", sa.DateTime(), primary_key=True),
        sa.Column("hex_code", sa.Text(), nullable=True),
        sa.Column("lab_l", sa.REAL(), nullable=True),
        sa.Column("lab_a", sa.REAL(), nullable=True),
        sa.Column("lab_b", sa.REAL(), nullable=True),
        sa.Column("color_method", sa.Text(), nullable=True),
        sa.Column("color_image_id", sa.BigInteger(), nullable=True),
        sa.Column("color_confidence", sa.REAL(), nullable=True),
        sa.Column("color_note", sa.Text(), nullable=True),
        sa.Column(
            "run_id", sa.BigInteger(), sa.ForeignKey("raw_oy_crawl_run.run_id"), nullable=True
        ),
        sa.Column("is_confirmed", sa.Boolean(), nullable=True),
    )
    op.create_index("ix_raw_oy_color_run", "raw_oy_option_color", ["run_id"])

    op.create_table(
        "raw_oy_product_texture",
        sa.Column(
            "goods_no", sa.Text(), sa.ForeignKey("raw_oy_product.goods_no"), primary_key=True
        ),
        sa.Column("collected_at", sa.DateTime(), primary_key=True),
        sa.Column(
            "texture_code",
            sa.Text(),
            sa.ForeignKey("raw_oy_texture_type.texture_code"),
            nullable=True,
        ),
        sa.Column("judge_step", sa.Text(), nullable=True),
        sa.Column("judge_reason", sa.Text(), nullable=True),
    )

    op.create_table(
        "raw_oy_image",
        sa.Column("image_id", sa.BigInteger(), primary_key=True),
        sa.Column("goods_no", sa.Text(), sa.ForeignKey("raw_oy_product.goods_no"), nullable=True),
        sa.Column(
            "option_id", sa.Text(), sa.ForeignKey("raw_oy_product_option.option_id"), nullable=True
        ),
        sa.Column("image_type", sa.Text(), nullable=True),
        sa.Column("image_url", sa.Text(), nullable=True),
        sa.Column("sort_seq", sa.Integer(), nullable=True),
        sa.Column("collected_at", sa.DateTime(), nullable=True),
    )
    op.create_index(
        "ix_raw_oy_image_identity", "raw_oy_image", ["goods_no", "image_type", "image_url"]
    )
    op.create_index("ix_raw_oy_image_goods", "raw_oy_image", ["goods_no"])
    op.create_index("ix_raw_oy_image_option", "raw_oy_image", ["option_id"])

    op.create_table(
        "raw_oy_image_applied",
        sa.Column("image_url", sa.Text(), primary_key=True),
        sa.Column("applied_type", sa.Text(), nullable=True),
        sa.Column("applied_conf", sa.REAL(), nullable=True),
        sa.Column("judged_at", sa.DateTime(), nullable=True),
    )

    op.create_table(
        "raw_oy_review_summary",
        sa.Column("summary_id", sa.BigInteger(), primary_key=True),
        sa.Column("goods_no", sa.Text(), sa.ForeignKey("raw_oy_product.goods_no"), nullable=True),
        sa.Column("review_count", sa.Integer(), nullable=True),
        sa.Column("rating_avg", sa.REAL(), nullable=True),
        sa.Column("rating_5_pct", sa.REAL(), nullable=True),
        sa.Column("rating_4_pct", sa.REAL(), nullable=True),
        sa.Column("rating_3_pct", sa.REAL(), nullable=True),
        sa.Column("rating_2_pct", sa.REAL(), nullable=True),
        sa.Column("rating_1_pct", sa.REAL(), nullable=True),
        sa.Column("ai_positive_ratio", sa.REAL(), nullable=True),
        sa.Column("ai_negative_ratio", sa.REAL(), nullable=True),
        sa.Column("is_latest", sa.Boolean(), nullable=True),
        sa.Column("collected_at", sa.DateTime(), nullable=True),
        sa.UniqueConstraint("goods_no", "collected_at", name="uq_raw_oy_revsum_goods_time"),
    )
    op.create_index("ix_raw_oy_revsum_goods", "raw_oy_review_summary", ["goods_no"])
    op.create_index(
        "uq_raw_oy_revsum_latest",
        "raw_oy_review_summary",
        ["goods_no"],
        unique=True,
        postgresql_where=sa.text("is_latest"),
    )

    op.create_table(
        "raw_oy_review_ai_feature",
        sa.Column(
            "goods_no", sa.Text(), sa.ForeignKey("raw_oy_product.goods_no"), primary_key=True
        ),
        sa.Column("seq", sa.Integer(), primary_key=True),
        sa.Column("collected_at", sa.DateTime(), primary_key=True),
        sa.Column("title", sa.Text(), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
    )
    op.create_index("ix_raw_oy_revfeat_goods", "raw_oy_review_ai_feature", ["goods_no"])

    op.create_table(
        "raw_oy_review_survey",
        sa.Column(
            "goods_no", sa.Text(), sa.ForeignKey("raw_oy_product.goods_no"), primary_key=True
        ),
        sa.Column(
            "answer_code",
            sa.Text(),
            sa.ForeignKey("raw_oy_survey_answer.answer_code"),
            primary_key=True,
        ),
        sa.Column("collected_at", sa.DateTime(), primary_key=True),
        sa.Column("percentage", sa.REAL(), nullable=True),
    )
    op.create_index("ix_raw_oy_revsurvey_goods", "raw_oy_review_survey", ["goods_no"])
    op.create_index("ix_raw_oy_revsurvey_answer", "raw_oy_review_survey", ["answer_code"])

    op.create_table(
        "raw_oy_ingredient",
        sa.Column("ingredient_id", sa.BigInteger(), primary_key=True),
        sa.Column("ingredient_name", sa.Text(), nullable=True),
        sa.Column("ingredient_norm", sa.Text(), nullable=True),
        sa.UniqueConstraint("ingredient_norm", name="uq_raw_oy_ingredient_norm"),
    )
    op.create_index(
        "ix_raw_oy_ingredient_name_trgm",
        "raw_oy_ingredient",
        ["ingredient_name"],
        postgresql_using="gin",
        postgresql_ops={"ingredient_name": "gin_trgm_ops"},
    )

    op.create_table(
        "raw_oy_option_ingredient",
        sa.Column(
            "option_id",
            sa.Text(),
            sa.ForeignKey("raw_oy_product_option.option_id"),
            primary_key=True,
        ),
        sa.Column(
            "ingredient_id",
            sa.BigInteger(),
            sa.ForeignKey("raw_oy_ingredient.ingredient_id"),
            primary_key=True,
        ),
        sa.Column("seq", sa.Integer(), nullable=True),
    )
    op.create_index("ix_raw_oy_optingr_ingredient", "raw_oy_option_ingredient", ["ingredient_id"])

    op.create_table(
        "raw_oy_crawl_log",
        sa.Column("log_id", sa.BigInteger(), primary_key=True),
        sa.Column(
            "run_id", sa.BigInteger(), sa.ForeignKey("raw_oy_crawl_run.run_id"), nullable=True
        ),
        sa.Column("goods_no", sa.Text(), nullable=True),
        sa.Column("step", sa.Text(), nullable=True),
        sa.Column("http_status", sa.Integer(), nullable=True),
        sa.Column("status", sa.Text(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("logged_at", sa.DateTime(), nullable=True),
    )
    op.create_index("ix_raw_oy_crawllog_run", "raw_oy_crawl_log", ["run_id"])

    # 제형 7종 고정표. ar_gloss / ar_matte 는 팀이 정할 AR 렌더 수치라 비워 둔다.
    op.execute(
        "INSERT INTO raw_oy_texture_type (texture_code, gloss_axis) VALUES "
        + ", ".join(
            f"('{code}', {axis if axis is not None else 'NULL'})" for code, axis in TEXTURE_CODES
        )
        + " ON CONFLICT (texture_code) DO NOTHING"
    )


def downgrade() -> None:
    op.drop_table("raw_oy_crawl_log")
    op.drop_table("raw_oy_option_ingredient")
    op.drop_table("raw_oy_ingredient")
    op.drop_table("raw_oy_review_survey")
    op.drop_table("raw_oy_review_ai_feature")
    op.drop_table("raw_oy_review_summary")
    op.drop_table("raw_oy_image_applied")
    op.drop_table("raw_oy_image")
    op.drop_table("raw_oy_product_texture")
    op.drop_table("raw_oy_option_color")
    op.drop_table("raw_oy_price_snapshot")
    op.drop_table("raw_oy_skincare_attr")
    op.drop_table("raw_oy_product_option")
    op.drop_table("raw_oy_product_notice")
    op.drop_table("raw_oy_product")
    op.drop_table("raw_oy_survey_answer")
    op.drop_table("raw_oy_survey_question")
    op.drop_table("raw_oy_texture_type")
    op.drop_table("raw_oy_category")
    op.drop_table("raw_oy_supplier")
    op.drop_table("raw_oy_brand")
    op.drop_table("raw_oy_crawl_run")

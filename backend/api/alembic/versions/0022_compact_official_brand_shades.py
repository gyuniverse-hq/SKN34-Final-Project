"""Keep official-brand products and shades in two HEX-only source tables.

Revision ID: 0022
Revises: 0021
"""

import sqlalchemy as sa

from alembic import op

revision = "0022"
down_revision = "0021"
branch_labels = None
depends_on = None


def _count(connection: sa.engine.Connection, query: str) -> int:
    return connection.execute(sa.text(query)).scalar_one()


def upgrade() -> None:
    connection = op.get_bind()
    if _count(
        connection,
        """SELECT COUNT(*)
           FROM raw_official_product p
           LEFT JOIN raw_official_product_texture t
             ON t.source_product_id = p.source_product_id
           WHERE t.source_product_id IS NULL
              OR p.source_url IS DISTINCT FROM t.source_url
              OR p.observed_at IS DISTINCT FROM t.observed_at""",
    ):
        raise RuntimeError("Official product/texture sources do not match")
    if _count(
        connection,
        """SELECT COUNT(*)
           FROM raw_official_product_option o
           LEFT JOIN raw_official_option_color c
             ON c.source_option_id = o.source_option_id
           WHERE c.source_option_id IS NULL
              OR o.source_url IS DISTINCT FROM c.source_url
              OR o.observed_at IS DISTINCT FROM c.observed_at""",
    ):
        raise RuntimeError("Official option/color sources do not match")

    op.add_column("raw_official_product", sa.Column("texture_code", sa.Text()))
    op.add_column("raw_official_product", sa.Column("judge_step", sa.Text()))
    op.add_column("raw_official_product", sa.Column("judge_reason", sa.Text()))
    op.execute(
        """UPDATE raw_official_product p
           SET texture_code = t.texture_code,
               judge_step = t.judge_step,
               judge_reason = t.judge_reason
           FROM raw_official_product_texture t
           WHERE p.source_product_id = t.source_product_id"""
    )
    for column in ("texture_code", "judge_step", "judge_reason"):
        op.alter_column("raw_official_product", column, existing_type=sa.Text(), nullable=False)
    op.create_foreign_key(
        "fk_raw_official_product_texture_code",
        "raw_official_product",
        "raw_oy_texture_type",
        ["texture_code"],
        ["texture_code"],
    )

    option_columns = (
        sa.Column("selected_hex", sa.String(7)),
        sa.Column("official_hex", sa.String(7)),
        sa.Column("lab_l", sa.REAL()),
        sa.Column("lab_a", sa.REAL()),
        sa.Column("lab_b", sa.REAL()),
        sa.Column("color_method", sa.Text()),
        sa.Column("color_confidence", sa.REAL()),
        sa.Column("measure_method", sa.Text()),
        sa.Column("selected_source", sa.Text()),
    )
    for column in option_columns:
        op.add_column("raw_official_product_option", column)
    op.execute(
        """UPDATE raw_official_product_option o
           SET selected_hex = c.selected_hex,
               official_hex = c.official_hex,
               lab_l = c.lab_l,
               lab_a = c.lab_a,
               lab_b = c.lab_b,
               color_method = c.color_method,
               color_confidence = c.color_confidence,
               measure_method = c.measure_method,
               selected_source = CASE
                   WHEN c.selected_source = 'user_supplied_png'
                   THEN 'user_reviewed_chip'
                   ELSE c.selected_source
               END
           FROM raw_official_option_color c
           WHERE o.source_option_id = c.source_option_id"""
    )
    for column, data_type in (
        ("selected_hex", sa.String(7)),
        ("official_hex", sa.String(7)),
        ("color_method", sa.Text()),
        ("measure_method", sa.Text()),
        ("selected_source", sa.Text()),
    ):
        op.alter_column(
            "raw_official_product_option",
            column,
            existing_type=data_type,
            nullable=False,
        )
    op.create_check_constraint(
        "ck_raw_official_option_selected_hex",
        "raw_official_product_option",
        "selected_hex ~ '^#[0-9A-F]{6}$'",
    )
    op.create_check_constraint(
        "ck_raw_official_option_site_hex",
        "raw_official_product_option",
        "official_hex ~ '^#[0-9A-F]{6}$'",
    )

    # Dropping this table deliberately discards the three private PNG byte arrays.
    op.drop_table("raw_official_option_color")
    op.drop_table("raw_official_product_texture")


def downgrade() -> None:
    # PNG bytes removed by upgrade cannot be reconstructed on downgrade.
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
    op.execute(
        """INSERT INTO raw_official_product_texture
           (source_product_id, texture_code, judge_step, judge_reason,
            source_url, observed_at)
           SELECT source_product_id, texture_code, judge_step, judge_reason,
                  source_url, observed_at
           FROM raw_official_product"""
    )
    op.execute(
        """INSERT INTO raw_official_option_color
           (source_option_id, selected_hex, official_hex, lab_l, lab_a, lab_b,
            color_method, color_confidence, measure_method, selected_source,
            source_url, observed_at)
           SELECT source_option_id, selected_hex, official_hex, lab_l, lab_a, lab_b,
                  color_method, color_confidence, measure_method, selected_source,
                  source_url, observed_at
           FROM raw_official_product_option"""
    )
    op.drop_constraint(
        "ck_raw_official_option_site_hex",
        "raw_official_product_option",
        type_="check",
    )
    op.drop_constraint(
        "ck_raw_official_option_selected_hex",
        "raw_official_product_option",
        type_="check",
    )
    for column in (
        "selected_source",
        "measure_method",
        "color_confidence",
        "color_method",
        "lab_b",
        "lab_a",
        "lab_l",
        "official_hex",
        "selected_hex",
    ):
        op.drop_column("raw_official_product_option", column)
    op.drop_constraint(
        "fk_raw_official_product_texture_code",
        "raw_official_product",
        type_="foreignkey",
    )
    for column in ("judge_reason", "judge_step", "texture_code"):
        op.drop_column("raw_official_product", column)

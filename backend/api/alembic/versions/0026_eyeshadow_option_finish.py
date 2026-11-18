"""Store reviewed eyeshadow finishes per option.

The texture table describes a product's gloss on the lip scale, but an eyeshadow line mixes
finishes across its shades and its AR finishes (metallic, glitter) are not on that scale. Each
option gets its own finish from a manual review against the AR finish chart. Options that are
not a single shade (tools, palettes, other categories) get a code that says so.
Decided with the data owner on 2026-11-18.

Revision ID: 0026
Revises: 0025
"""

import sqlalchemy as sa

from alembic import op

revision = "0026"
down_revision = "0025"
branch_labels = None
depends_on = None

# (code, gloss order on the AR eyeshadow finish chart, is a finish)
FINISH_CODES = (
    ("matte", 1, True),
    ("satin", 2, True),
    ("shimmer", 3, True),
    ("metallic", 4, True),
    ("glitter", 5, True),
    ("glossy", 5, True),
    ("accessory", None, False),
    ("palette", None, False),
    ("other_category", None, False),
    ("unknown", None, False),
)


def upgrade() -> None:
    finish_type = op.create_table(
        "raw_oy_finish_type",
        sa.Column("finish_code", sa.Text(), primary_key=True),
        sa.Column("gloss_axis", sa.Integer(), nullable=True),
        sa.Column("is_finish", sa.Boolean(), nullable=False),
    )
    op.bulk_insert(
        finish_type,
        [
            {"finish_code": code, "gloss_axis": axis, "is_finish": is_finish}
            for code, axis, is_finish in FINISH_CODES
        ],
    )
    op.create_table(
        "raw_oy_option_finish",
        sa.Column(
            "option_id",
            sa.Text(),
            sa.ForeignKey("raw_oy_product_option.option_id"),
            primary_key=True,
        ),
        sa.Column("collected_at", sa.DateTime(), primary_key=True),
        sa.Column(
            "finish_code",
            sa.Text(),
            sa.ForeignKey("raw_oy_finish_type.finish_code"),
            nullable=False,
        ),
        sa.Column("judge_step", sa.Text(), nullable=False),
        sa.Column("judge_reason", sa.Text(), nullable=True),
        sa.Column("source_file", sa.Text(), nullable=True),
    )


def downgrade() -> None:
    op.drop_table("raw_oy_option_finish")
    op.drop_table("raw_oy_finish_type")

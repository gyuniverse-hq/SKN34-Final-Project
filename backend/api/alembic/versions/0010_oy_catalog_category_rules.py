"""Store category-specific catalog requirements and allow unknown product texture.

Revision ID: 0010
Revises: 0009
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0010"
down_revision: str | Sequence[str] | None = "0009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


# Agreed with the AR team on 2026-10-30. The four out-of-scope categories have no rule.
RULES = (
    ("립틴트", True, True),
    ("쿠션", True, False),
    ("립케어(컬러립밤)", False, True),
    ("블러셔", False, True),
    ("립케어(보습립밤)", False, False),
    ("아이섀도우", False, True),
    ("프라이머/베이스", False, False),
    ("아이브로우", False, False),
    ("마스카라", False, False),
    ("아이라이너", False, False),
    ("파우더/팩트", False, False),
    ("파운데이션", True, False),
    ("립글로스", False, True),
    ("립스틱", True, True),
    ("컨실러", False, False),
    ("하이라이터", False, False),
    ("BB/CC", True, False),
    ("립라이너", False, False),
    ("쉐이딩", False, False),
    ("메이크업 픽서", True, False),
    ("립케어(기타)", True, False),
)


def upgrade() -> None:
    op.create_table(
        "oy_catalog_category_rule",
        sa.Column("std_category_code", sa.Text(), primary_key=True),
        sa.Column("requires_texture", sa.Boolean(), nullable=False),
        sa.Column("requires_color", sa.Boolean(), nullable=False),
    )
    rules = sa.table(
        "oy_catalog_category_rule",
        sa.column("std_category_code", sa.Text()),
        sa.column("requires_texture", sa.Boolean()),
        sa.column("requires_color", sa.Boolean()),
    )
    op.bulk_insert(
        rules,
        [
            {
                "std_category_code": category,
                "requires_texture": texture,
                "requires_color": color,
            }
            for category, texture, color in RULES
        ],
    )
    op.alter_column("products", "texture", existing_type=sa.String(20), nullable=True)
    op.add_column("shades", sa.Column("measure_method", sa.String(20), nullable=True))
    op.add_column("shades", sa.Column("color_source", sa.String(20), nullable=True))
    op.add_column("shades", sa.Column("color_confidence", sa.Float(), nullable=True))


def downgrade() -> None:
    null_count = op.get_bind().scalar(
        sa.text("SELECT COUNT(*) FROM products WHERE texture IS NULL")
    )
    if null_count:
        raise RuntimeError("Cannot downgrade while products with unknown texture exist")
    op.drop_column("shades", "color_confidence")
    op.drop_column("shades", "color_source")
    op.drop_column("shades", "measure_method")
    op.alter_column("products", "texture", existing_type=sa.String(20), nullable=False)
    op.drop_table("oy_catalog_category_rule")

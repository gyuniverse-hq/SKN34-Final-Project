"""Lip AR product panel slots (temporary face refs for eval period).

Revision ID: 0036
Revises: 0035
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql as pg

from alembic import op

revision = "0036"
down_revision = "0035"
branch_labels = None
depends_on = None

_PRODUCTS = [
    ("lip-01-3ce-murmuring", "3CE", "소프트 매트 립스틱", "머머링", 1),
    ("lip-02-romand-cream-buns", "롬앤", "글래스팅 컬러 글로스", "크림 반즈", 2),
    ("lip-03-peripera-kongkong", "페리페라", "무드 글로이 틴트", "콩콩라떼", 3),
    ("lip-04-peripera-hipsaeng", "페리페라", "무드 블러 밤", "힙생힙사", 4),
    (
        "lip-05-lilybyred-vanillabean",
        "릴리바이레드",
        "스윗 라이어 밀키 틴트",
        "바닐라빈 크림인 척",
        5,
    ),
    ("lip-06-peripera-mocha", "페리페라", "무드 블러 틴트", "집에모카", 6),
    ("lip-07-bbia-peanut", "삐아", "오버글레이즈", "땅콩당", 7),
    ("lip-08-wakemake-sootipingk", "웨이크메이크", "소프트 블러링 밤 스틱", "수티핑크", 8),
    ("lip-09-apieu-pecan", "에이쁘", "블러 틴 팟", "피칸버터", 9),
    ("lip-10-hince-raw-rose", "힌스", "로 글로우 젤 틴트", "로 로즈", 10),
    ("lip-11-hince-cinnamon", "힌스", "로 글로우 젤 틴트", "시나몬", 11),
]


def upgrade() -> None:
    op.create_table(
        "lip_eval_products",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("brand", sa.String(80), nullable=False),
        sa.Column("name", sa.String(160), nullable=False),
        sa.Column("shade", sa.String(120), nullable=False),
        sa.Column("sort_order", sa.Integer(), nullable=False),
    )
    op.create_table(
        "lip_eval_slots",
        sa.Column(
            "product_id",
            sa.String(64),
            sa.ForeignKey("lip_eval_products.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("rater_id", sa.Integer(), primary_key=True),
        sa.Column("bare_path", sa.String(512)),
        sa.Column("real_path", sa.String(512)),
        sa.Column("ar_path", sa.String(512)),
        sa.Column("technical_json", pg.JSONB()),
        sa.Column("naturalness_json", pg.JSONB()),
        sa.Column("scored_at", sa.DateTime(timezone=True)),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint("rater_id BETWEEN 1 AND 5", name="ck_lip_eval_rater"),
    )
    op.execute("ALTER TABLE lip_eval_slots ENABLE ROW LEVEL SECURITY")
    products = sa.table(
        "lip_eval_products",
        sa.column("id", sa.String),
        sa.column("brand", sa.String),
        sa.column("name", sa.String),
        sa.column("shade", sa.String),
        sa.column("sort_order", sa.Integer),
    )
    op.bulk_insert(
        products,
        [
            {
                "id": pid,
                "brand": brand,
                "name": name,
                "shade": shade,
                "sort_order": order,
            }
            for pid, brand, name, shade, order in _PRODUCTS
        ],
    )


def downgrade() -> None:
    op.drop_table("lip_eval_slots")
    op.drop_table("lip_eval_products")

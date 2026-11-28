"""Publish the three VISHUE editorial examples without a member account."""

import json
from pathlib import Path

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, UUID

from alembic import op

revision = "0043"
down_revision = "0042"
branch_labels = None
depends_on = None

PHOTOS = Path(__file__).resolve().parents[1] / "assets" / "look-examples"
EXAMPLES = (
    (
        "db12838e-decd-52a4-8ae0-b53d710c8b31",
        "daily-pink",
        "출근길에 가볍게, 데일리 핑크",
        "입술에는 로지타로를 얇게 펴 바르고, 볼에는 연한 핑크를 살짝 올려보세요.",
        "oy-a000001002067",
        "02",
    ),
    (
        "2c0ebff2-a00f-5da0-ba0c-70bd9fdac81d",
        "fresh-coral",
        "햇살에 어울리는 맑은 코랄",
        "코랄 립을 입술 안쪽에 한 번 더 올리고, 볼에는 피치 컬러를 넓게 펴 발라보세요.",
        "oy-a000000255256",
        "902",
    ),
    (
        "a0d0900d-f073-5bb1-8e4f-f424b3ab66d2",
        "muted-rose",
        "오후의 차분한 모브 로즈",
        "모브 립을 한 겹 바른 뒤 경계만 손끝으로 풀어주세요. 눈가에는 옅은 갈색을 더해보세요.",
        "oy-a000001001860",
        "103",
    ),
)

POSTS = sa.table(
    "look_posts",
    sa.column("id", UUID),
    sa.column("title", sa.String),
    sa.column("description", sa.String),
    sa.column("display_name", sa.String),
    sa.column("products", JSONB),
    sa.column("photo", sa.LargeBinary),
    sa.column("owner_id", sa.String),
)


def upgrade() -> None:
    op.alter_column("look_posts", "owner_id", existing_type=sa.String(64), nullable=True)
    for post_id, filename, title, description, product_id, shade_id in EXAMPLES:
        photo = (PHOTOS / f"{filename}.jpg").read_bytes()
        products = [{"productId": product_id, "shadeId": shade_id}]
        op.execute(
            POSTS.insert().values(
                id=sa.cast(op.inline_literal(post_id), UUID),
                title=op.inline_literal(title),
                description=op.inline_literal(description),
                display_name=op.inline_literal("VISHUE 예시"),
                products=sa.cast(op.inline_literal(json.dumps(products)), JSONB),
                photo=sa.func.decode(op.inline_literal(photo.hex()), op.inline_literal("hex")),
            )
        )


def downgrade() -> None:
    op.execute("DELETE FROM look_posts WHERE owner_id IS NULL")
    op.alter_column("look_posts", "owner_id", existing_type=sa.String(64), nullable=False)

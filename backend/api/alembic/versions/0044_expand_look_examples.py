"""Add three editorial looks and stagger the six examples in the feed."""

import json
from pathlib import Path

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, UUID

from alembic import op

revision = "0044"
down_revision = "0043"
branch_labels = None
depends_on = None

PHOTOS = Path(__file__).resolve().parents[1] / "assets" / "look-examples"
EXISTING = (
    ("db12838e-decd-52a4-8ae0-b53d710c8b31", "2026-11-26T08:20:00+09:00", 9),
    ("2c0ebff2-a00f-5da0-ba0c-70bd9fdac81d", "2026-11-24T13:10:00+09:00", 18),
    ("a0d0900d-f073-5bb1-8e4f-f424b3ab66d2", "2026-11-22T16:45:00+09:00", 24),
)
NEW = (
    (
        "692a611b-a121-5797-a5b9-b1dbf3b134de",
        "soft-apricot",
        "수수하게 말린 살구",
        "살구빛 립을 얇게 바르고 복숭아색 블러셔를 볼 중앙에서 바깥쪽으로 풀어줬어요.",
        "oy-a000001001860",
        "114",
        "2026-11-27T09:35:00+09:00",
        3,
    ),
    (
        "4234f3d1-081d-5e9f-bfe9-15da0ff97b11",
        "sheer-berry",
        "찬바람에 물든 베리 립",
        "체리빛 밤을 입술 안쪽에 톡톡 얹고, 볼에도 맑은 핑크를 조금 더했어요.",
        "oy-a000001002067",
        "01",
        "2026-11-25T18:10:00+09:00",
        14,
    ),
    (
        "0882fb6f-999b-57dd-a18b-daef6e327885",
        "warm-brown",
        "저녁 조명 아래 브라운",
        "누디 브라운 립에 은은한 브론즈 섀도를 더해 따뜻한 실내 조명에 어울리게 연출했어요.",
        "oy-a000000241210",
        "02",
        "2026-11-23T20:05:00+09:00",
        11,
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
    sa.column("created_at", sa.DateTime(timezone=True)),
    sa.column("example_votes", sa.Integer),
)


def upgrade() -> None:
    op.add_column(
        "look_posts", sa.Column("example_votes", sa.Integer, nullable=False, server_default="0")
    )
    for post_id, timestamp, votes in EXISTING:
        op.execute(
            POSTS.update()
            .where(
                POSTS.c.id == sa.cast(op.inline_literal(post_id), UUID), POSTS.c.owner_id.is_(None)
            )
            .values(
                display_name=op.inline_literal("VISHUE"),
                created_at=sa.cast(op.inline_literal(timestamp), sa.DateTime(timezone=True)),
                example_votes=op.inline_literal(votes),
            )
        )
    for post_id, filename, title, description, product_id, shade_id, timestamp, votes in NEW:
        photo = (PHOTOS / f"{filename}.jpg").read_bytes()
        products = [{"productId": product_id, "shadeId": shade_id}]
        op.execute(
            POSTS.insert().values(
                id=sa.cast(op.inline_literal(post_id), UUID),
                title=op.inline_literal(title),
                description=op.inline_literal(description),
                display_name=op.inline_literal("VISHUE"),
                products=sa.cast(op.inline_literal(json.dumps(products)), JSONB),
                photo=sa.func.decode(op.inline_literal(photo.hex()), op.inline_literal("hex")),
                created_at=sa.cast(op.inline_literal(timestamp), sa.DateTime(timezone=True)),
                example_votes=op.inline_literal(votes),
            )
        )


def downgrade() -> None:
    new_ids = [sa.cast(op.inline_literal(row[0]), UUID) for row in NEW]
    op.execute(POSTS.delete().where(POSTS.c.id.in_(new_ids), POSTS.c.owner_id.is_(None)))
    op.drop_column("look_posts", "example_votes")

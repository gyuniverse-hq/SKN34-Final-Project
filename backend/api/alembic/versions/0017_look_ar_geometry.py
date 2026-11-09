"""Add a geometry JSON column to look_ar_settings.

룩의 AR 설정에는 색·세기·제형만 있어 하이라이터·쉐딩의 스타일 템플릿 같은 모양 값을 저장할 수
없었다. 앱의 ZoneGeometry를 camelCase JSON 그대로 담는다. 비어 있으면(NULL) 앱 기본 모양을 쓴다.

Revision ID: 0017
Revises: 0016
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0017"
down_revision: str | Sequence[str] | None = "0016"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "look_ar_settings",
        sa.Column(
            "geometry", sa.JSON().with_variant(postgresql.JSONB(), "postgresql"), nullable=True
        ),
    )


def downgrade() -> None:
    op.drop_column("look_ar_settings", "geometry")

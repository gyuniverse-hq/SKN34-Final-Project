"""members: terms consent of Supabase users

Revision ID: 0008
Revises: 0007
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0008"
down_revision: str | Sequence[str] | None = "0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "members",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("terms_version", sa.String(32), nullable=False),
        sa.Column("terms_agreed_at", sa.DateTime(timezone=True), nullable=False),
    )
    # On Supabase (dev) the public schema is served by its Data API to anyone with the
    # publishable key. RLS without policies closes that; the backend owns the table and is exempt.
    op.execute("ALTER TABLE members ENABLE ROW LEVEL SECURITY")


def downgrade() -> None:
    op.drop_table("members")

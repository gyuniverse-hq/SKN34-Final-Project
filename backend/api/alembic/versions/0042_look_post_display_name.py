"""Allow a display name chosen for a community post."""

import sqlalchemy as sa

from alembic import op

revision = "0042"
down_revision = "0041"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("look_posts", sa.Column("display_name", sa.String(24), nullable=True))


def downgrade() -> None:
    op.drop_column("look_posts", "display_name")

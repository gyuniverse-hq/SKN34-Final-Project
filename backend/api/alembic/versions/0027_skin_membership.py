"""Record the first completed analysis and skin subscription expiry per member."""

import sqlalchemy as sa

from alembic import op

revision = "0027"
down_revision = "0026"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("members", sa.Column("first_ar_seen_at", sa.DateTime(timezone=True)))
    op.add_column("members", sa.Column("skin_trial_run", sa.String(128), nullable=True))
    op.add_column(
        "members", sa.Column("skin_subscription_until", sa.DateTime(timezone=True), nullable=True)
    )


def downgrade() -> None:
    op.drop_column("members", "first_ar_seen_at")
    op.drop_column("members", "skin_subscription_until")
    op.drop_column("members", "skin_trial_run")

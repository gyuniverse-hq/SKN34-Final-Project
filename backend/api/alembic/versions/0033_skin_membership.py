"""Record the first completed analysis and skin subscription expiry per member."""

import sqlalchemy as sa

from alembic import op

revision = "0033"
down_revision = "0032"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Some development databases ran the membership migration as 0027 before
    # that revision was assigned to shades.finish on develop.
    op.add_column("shades", sa.Column("finish", sa.String(20)), if_not_exists=True)
    op.add_column(
        "members", sa.Column("first_ar_seen_at", sa.DateTime(timezone=True)), if_not_exists=True
    )
    op.add_column(
        "members", sa.Column("skin_trial_run", sa.String(128), nullable=True), if_not_exists=True
    )
    op.add_column(
        "members",
        sa.Column("skin_subscription_until", sa.DateTime(timezone=True), nullable=True),
        if_not_exists=True,
    )


def downgrade() -> None:
    op.drop_column("members", "first_ar_seen_at")
    op.drop_column("members", "skin_subscription_until")
    op.drop_column("members", "skin_trial_run")

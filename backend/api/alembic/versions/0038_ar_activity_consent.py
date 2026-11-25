"""Record optional AR personalization consent separately from required terms."""

import sqlalchemy as sa

from alembic import op

revision = "0038"
down_revision = "0037"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("members", sa.Column("camera_features_consent", sa.Boolean()))
    op.add_column("members", sa.Column("ar_activity_consented_at", sa.DateTime(timezone=True)))


def downgrade() -> None:
    op.drop_column("members", "camera_features_consent")
    op.drop_column("members", "ar_activity_consented_at")

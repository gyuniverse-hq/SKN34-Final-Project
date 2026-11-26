"""Record optional AR personalization consent separately from required terms."""

import sqlalchemy as sa

from alembic import context, op

revision = "0039"
down_revision = "0038"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Before the branches merged, some local databases recorded the two consent
    # columns as 0038. On develop, 0038 is the published coupon migration.
    if not context.is_offline_mode():
        inspector = sa.inspect(op.get_bind())
        if not inspector.has_table("reward_attendance"):
            member_columns = {column["name"] for column in inspector.get_columns("members")}
            if not {"camera_features_consent", "ar_activity_consented_at"} <= member_columns:
                raise RuntimeError("Unrecognized 0038 schema: missing attendance and consent")
            context.script.get_revision(down_revision).module.upgrade()
    else:
        # A static SQL script cannot inspect the source schema during generation.
        # A legacy 0038 database needs the online repair before advancing.
        op.execute("SELECT 1 FROM reward_attendance, reward_coupons WHERE false")
    op.add_column("members", sa.Column("camera_features_consent", sa.Boolean()), if_not_exists=True)
    op.add_column(
        "members",
        sa.Column("ar_activity_consented_at", sa.DateTime(timezone=True)),
        if_not_exists=True,
    )


def downgrade() -> None:
    op.drop_column("members", "camera_features_consent")
    op.drop_column("members", "ar_activity_consented_at")

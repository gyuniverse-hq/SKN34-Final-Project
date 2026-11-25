"""Add member attendance rewards and order coupon references."""

import sqlalchemy as sa

from alembic import op

revision = "0038"
down_revision = "0037"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "reward_attendance",
        sa.Column("member_id", sa.String(64), nullable=False),
        sa.Column("attendance_date", sa.Date(), nullable=False),
        sa.Column("stamp_goal", sa.SmallInteger(), nullable=False),
        sa.PrimaryKeyConstraint("member_id", "attendance_date"),
        sa.ForeignKeyConstraint(
            ["member_id"], ["members.id"], name="fk_reward_attendance_member", ondelete="CASCADE"
        ),
        sa.CheckConstraint("stamp_goal IN (4, 7)", name="ck_reward_attendance_stamp_goal"),
    )
    op.create_table(
        "reward_coupons",
        sa.Column("id", sa.Uuid(), nullable=False, primary_key=True),
        sa.Column("member_id", sa.String(64), nullable=False),
        sa.Column("source_date", sa.Date(), nullable=False),
        sa.Column("issued_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["member_id", "source_date"],
            ["reward_attendance.member_id", "reward_attendance.attendance_date"],
            name="fk_reward_coupons_attendance",
            ondelete="CASCADE",
        ),
        sa.UniqueConstraint("member_id", "source_date", name="uq_reward_coupons_attendance"),
        sa.CheckConstraint("expires_at > issued_at", name="ck_reward_coupons_expiry"),
    )
    # Member-specific rewards are backend-only, just like members on shared Supabase.
    op.execute("ALTER TABLE reward_attendance ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE reward_coupons ENABLE ROW LEVEL SECURITY")
    op.add_column("orders", sa.Column("reward_coupon_id", sa.Uuid(), nullable=True))
    op.add_column(
        "orders",
        sa.Column("discount_krw", sa.Integer(), nullable=False, server_default=sa.text("0")),
    )
    op.create_foreign_key(
        "fk_orders_reward_coupon",
        "orders",
        "reward_coupons",
        ["reward_coupon_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_check_constraint(
        "ck_orders_discount_krw", "orders", "discount_krw BETWEEN 0 AND 2000"
    )
    op.create_index(
        "ux_orders_active_reward_coupon",
        "orders",
        ["reward_coupon_id"],
        unique=True,
        postgresql_where=sa.text("reward_coupon_id IS NOT NULL AND status <> 'canceled'"),
    )


def downgrade() -> None:
    op.drop_index("ux_orders_active_reward_coupon", table_name="orders")
    op.drop_constraint("ck_orders_discount_krw", "orders", type_="check")
    op.drop_constraint("fk_orders_reward_coupon", "orders", type_="foreignkey")
    op.drop_column("orders", "discount_krw")
    op.drop_column("orders", "reward_coupon_id")
    op.drop_table("reward_coupons")
    op.drop_table("reward_attendance")

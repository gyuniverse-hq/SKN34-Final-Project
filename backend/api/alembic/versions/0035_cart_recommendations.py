"""Record cart recommendation visits and attribute approved orders."""

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

from alembic import op

revision = "0035"
down_revision = "0034"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("ar_recommendation_requests", sa.Column("cart_candidates", JSONB()))
    op.create_table(
        "cart_recommendation_visits",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "member_id",
            sa.String(64),
            sa.ForeignKey("members.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("experiment", sa.String(16), nullable=False),
        sa.Column("arm", sa.String(1), nullable=False),
        sa.Column("basket", JSONB(), nullable=False),
        sa.Column("candidates", JSONB(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.CheckConstraint("arm IN ('A', 'B')", name="ck_cart_recommendation_arm"),
    )
    op.create_index(
        "ix_cart_recommendation_visits_member_id", "cart_recommendation_visits", ["member_id"]
    )
    op.create_index(
        "ix_cart_recommendation_visit_experiment",
        "cart_recommendation_visits",
        ["experiment", "created_at"],
    )
    op.create_table(
        "cart_recommendation_impressions",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "visit_id",
            sa.Uuid(),
            sa.ForeignKey("cart_recommendation_visits.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("candidate_id", sa.Uuid(), nullable=False),
        sa.Column("visibility_policy", sa.String(32), nullable=False),
        sa.Column(
            "occurred_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.UniqueConstraint("visit_id", "candidate_id", name="uq_cart_recommendation_impression"),
    )
    op.add_column("orders", sa.Column("cart_visit_id", sa.Uuid()))
    op.create_foreign_key(
        "fk_orders_cart_visit",
        "orders",
        "cart_recommendation_visits",
        ["cart_visit_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index("ix_orders_cart_visit_id", "orders", ["cart_visit_id"])
    op.add_column("order_lines", sa.Column("cart_recommendation_event_id", sa.Uuid()))
    op.create_foreign_key(
        "fk_order_lines_cart_recommendation_event",
        "order_lines",
        "user_behavior_events",
        ["cart_recommendation_event_id"],
        ["event_id"],
        ondelete="SET NULL",
    )
    op.create_index(
        "ix_order_lines_cart_recommendation_event_id",
        "order_lines",
        ["cart_recommendation_event_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_order_lines_cart_recommendation_event_id", table_name="order_lines")
    op.drop_constraint(
        "fk_order_lines_cart_recommendation_event", "order_lines", type_="foreignkey"
    )
    op.drop_column("order_lines", "cart_recommendation_event_id")
    op.drop_index("ix_orders_cart_visit_id", table_name="orders")
    op.drop_constraint("fk_orders_cart_visit", "orders", type_="foreignkey")
    op.drop_column("orders", "cart_visit_id")
    op.drop_table("cart_recommendation_impressions")
    op.drop_table("cart_recommendation_visits")
    op.drop_column("ar_recommendation_requests", "cart_candidates")

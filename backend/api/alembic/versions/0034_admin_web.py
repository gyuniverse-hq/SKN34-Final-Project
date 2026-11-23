"""Local-first administrator web draft. DB owner review is required before deployment.

Revision ID: 0034
Revises: 0033
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql as pg

from alembic import op

revision = "0034"
down_revision = "0033"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "staff_roles",
        sa.Column(
            "user_id",
            sa.String(64),
            sa.ForeignKey("members.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("role", sa.String(16), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("created_by", sa.String(64)),
        sa.CheckConstraint("role IN ('admin', 'viewer')", name="ck_staff_role"),
    )
    op.create_table(
        "admin_audit_log",
        sa.Column("id", pg.UUID(), primary_key=True),
        sa.Column("actor_user_id", sa.String(64), sa.ForeignKey("members.id", ondelete="SET NULL")),
        sa.Column("action", sa.String(80), nullable=False),
        sa.Column("target_type", sa.String(40), nullable=False),
        sa.Column("target_id", sa.String(128), nullable=False),
        sa.Column("before_json", pg.JSONB()),
        sa.Column("after_json", pg.JSONB()),
        sa.Column("request_id", sa.String(128), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )
    op.create_index("ix_admin_audit_log_created_at", "admin_audit_log", ["created_at"])
    op.create_index(
        "ix_admin_audit_target", "admin_audit_log", ["target_type", "target_id", "created_at"]
    )
    op.create_table(
        "product_admin_state",
        sa.Column(
            "product_id",
            sa.String(64),
            sa.ForeignKey("products.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("is_visible", sa.Boolean(), server_default="true", nullable=False),
        sa.Column("stock", sa.Integer()),
        sa.Column("updated_by", sa.String(64)),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint("stock IS NULL OR stock >= 0", name="ck_admin_stock"),
    )
    op.create_table(
        "eval_runs",
        sa.Column("id", pg.UUID(), primary_key=True),
        sa.Column("kind", sa.String(16), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("renderer_commit", sa.String(40), nullable=False),
        sa.Column("renderer_dirty", sa.Boolean(), nullable=False),
        sa.Column("rubric_version", sa.String(64), nullable=False),
        sa.Column("metric_version", sa.String(64), nullable=False),
        sa.Column("benchmark_sha256", sa.String(64), nullable=False),
        sa.Column("summary_json", pg.JSONB(), nullable=False),
        sa.Column("summary_hash", sa.String(64), nullable=False, unique=True),
        sa.Column("uploaded_by", sa.String(64), sa.ForeignKey("members.id", ondelete="SET NULL")),
        sa.CheckConstraint("kind IN ('human', 'bench', 'judge')", name="ck_eval_kind"),
        sa.CheckConstraint("jsonb_typeof(summary_json) = 'object'", name="ck_eval_summary"),
    )
    op.create_index("ix_eval_runs_created_at", "eval_runs", ["created_at"])
    op.add_column("orders", sa.Column("created_at", sa.DateTime(timezone=True)), if_not_exists=True)
    op.add_column("orders", sa.Column("paid_at", sa.DateTime(timezone=True)), if_not_exists=True)
    op.add_column("order_lines", sa.Column("stock_debited", sa.Integer()), if_not_exists=True)
    op.create_check_constraint(
        "ck_order_line_stock_debited",
        "order_lines",
        "stock_debited IS NULL OR (stock_debited >= 0 AND stock_debited <= quantity)",
    )
    op.create_index("ix_orders_created_at_id", "orders", ["created_at", "id"], if_not_exists=True)
    for table in ("staff_roles", "admin_audit_log", "product_admin_state", "eval_runs"):
        op.execute(sa.text(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY"))


def downgrade() -> None:
    op.drop_constraint("ck_order_line_stock_debited", "order_lines", type_="check")
    op.drop_index("ix_orders_created_at_id", table_name="orders")
    op.drop_column("order_lines", "stock_debited")
    op.drop_column("orders", "paid_at")
    op.drop_column("orders", "created_at")
    for table in ("eval_runs", "product_admin_state", "admin_audit_log", "staff_roles"):
        op.drop_table(table)

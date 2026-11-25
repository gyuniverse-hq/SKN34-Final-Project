"""Add account memory settings and management request receipts."""

import sqlalchemy as sa

from alembic import op

revision = "0005_g7_memory_settings"
down_revision = "0004_g7_structured_memory"
branch_labels = None
depends_on = None

_EXISTING_OPERATIONS = (
    "'chat', 'state_update', 'conversation_create', 'memory_create', 'memory_update', "
    "'memory_delete', 'memory_proposal_edit', 'memory_proposal_decide'"
)
_MANAGEMENT_OPERATIONS = "'memory_settings_update', 'memory_delete_all', 'memory_structured_update'"


def _set_operations(operations: str) -> None:
    op.drop_constraint("chat_turns_operation_check", "chat_turns", type_="check")
    op.create_check_constraint(
        "chat_turns_operation_check", "chat_turns", f"operation IN ({operations})"
    )


def upgrade():
    op.add_column(
        "chat_owner_status",
        sa.Column("memory_enabled", sa.Boolean, nullable=False, server_default=sa.true()),
    )
    op.add_column(
        "chat_owner_status",
        sa.Column("memory_policy_version", sa.BigInteger, nullable=False, server_default="0"),
    )
    op.add_column("chat_owner_status", sa.Column("memory_notice_at", sa.DateTime(timezone=True)))
    _set_operations(f"{_EXISTING_OPERATIONS}, {_MANAGEMENT_OPERATIONS}")


def downgrade():
    populated = op.get_bind().scalar(
        sa.text(
            "SELECT EXISTS (SELECT 1 FROM chat_owner_status WHERE status = 'ACTIVE' "
            "AND (memory_enabled IS FALSE OR memory_policy_version <> 0 "
            "OR memory_notice_at IS NOT NULL)) "
            f"OR EXISTS (SELECT 1 FROM chat_turns WHERE operation IN ({_MANAGEMENT_OPERATIONS}))"
        )
    )
    if populated:
        raise RuntimeError("Use a compatible application to roll back memory settings")
    _set_operations(_EXISTING_OPERATIONS)
    for name in ("memory_notice_at", "memory_policy_version", "memory_enabled"):
        op.drop_column("chat_owner_status", name)

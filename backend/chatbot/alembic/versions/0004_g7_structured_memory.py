"""Store structured memories and independently resolvable proposal items."""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "0004_g7_structured_memory"
down_revision = "0003_g7_memory_provenance"
branch_labels = None
depends_on = None

_LEGACY_OPERATIONS = (
    "'chat', 'state_update', 'conversation_create', "
    "'memory_create', 'memory_update', 'memory_delete'"
)
_STRUCTURED_OPERATIONS = "'memory_proposal_edit', 'memory_proposal_decide'"


def upgrade():
    for column in (
        sa.Column("schema_version", sa.Integer, nullable=False, server_default="1"),
        sa.Column("registry_version", sa.Integer),
        sa.Column("semantic_key", sa.String(128)),
        sa.Column("display_value", sa.Text),
        sa.Column("applicability_json", postgresql.JSONB),
    ):
        op.add_column("chat_memories", column)
    op.create_check_constraint(
        "chat_memories_storage_format_check",
        "chat_memories",
        "(schema_version = 1 AND registry_version IS NULL AND semantic_key IS NULL "
        "AND display_value IS NULL AND applicability_json IS NULL) OR "
        "(schema_version = 2 AND registry_version IS NOT NULL AND semantic_key IS NOT NULL "
        "AND ((revoked_at IS NULL AND value_json IS NOT NULL AND display_value IS NOT NULL "
        "AND applicability_json IS NOT NULL) OR "
        "(revoked_at IS NOT NULL AND value_json IS NULL AND display_value IS NULL "
        "AND applicability_json IS NULL)))",
    )
    op.drop_constraint("chat_turns_operation_check", "chat_turns", type_="check")
    op.create_check_constraint(
        "chat_turns_operation_check",
        "chat_turns",
        f"operation IN ({_LEGACY_OPERATIONS}, {_STRUCTURED_OPERATIONS})",
    )
    op.create_table(
        "chat_memory_proposal_groups",
        sa.Column("id", sa.Uuid, primary_key=True),
        sa.Column(
            "owner_id", sa.String(64), sa.ForeignKey("chat_owner_status.owner_id"), nullable=False
        ),
        sa.Column(
            "conversation_id",
            sa.Uuid,
            sa.ForeignKey("chat_conversations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("origin_request_id", sa.Uuid, nullable=False),
        sa.Column("locale", sa.String(2), nullable=False),
        sa.Column("revocation_epoch", sa.BigInteger, nullable=False),
        sa.Column("memory_generation", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("owner_id", "origin_request_id"),
    )
    op.create_index(
        "chat_memory_groups_room_expiry_idx",
        "chat_memory_proposal_groups",
        ["owner_id", "conversation_id", "expires_at"],
    )
    op.create_table(
        "chat_memory_proposal_items",
        sa.Column("id", sa.Uuid, primary_key=True),
        sa.Column(
            "group_id",
            sa.Uuid,
            sa.ForeignKey("chat_memory_proposal_groups.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("position", sa.Integer, nullable=False),
        sa.Column("semantic_key", sa.String(128), nullable=False),
        sa.Column("version", sa.BigInteger, nullable=False, server_default="1"),
        sa.Column("status", sa.String(16), nullable=False, server_default="pending"),
        sa.Column("payload", postgresql.JSONB),
        sa.Column("source_count", sa.Integer, nullable=False),
        sa.Column("target_id", sa.Uuid),
        sa.Column("target_version", sa.BigInteger),
        sa.CheckConstraint(
            "(status IN ('pending', 'deferred') AND payload IS NOT NULL) OR "
            "(status IN ('approved', 'rejected') AND payload IS NULL)"
        ),
    )
    op.create_index(
        "ix_chat_memory_proposal_items_group_id", "chat_memory_proposal_items", ["group_id"]
    )
    op.create_table(
        "chat_memory_sources",
        sa.Column("id", sa.Uuid, primary_key=True),
        sa.Column(
            "item_id", sa.Uuid, sa.ForeignKey("chat_memory_proposal_items.id", ondelete="CASCADE")
        ),
        sa.Column("memory_id", sa.Uuid, sa.ForeignKey("chat_memories.id", ondelete="CASCADE")),
        sa.Column("message_id", sa.Uuid, sa.ForeignKey("chat_messages.id", ondelete="CASCADE")),
        sa.Column("edit_request_id", sa.Uuid),
        sa.CheckConstraint("(item_id IS NULL) <> (memory_id IS NULL)"),
        sa.CheckConstraint("(message_id IS NULL) <> (edit_request_id IS NULL)"),
    )
    for column in ("item_id", "memory_id", "message_id"):
        op.create_index(f"ix_chat_memory_sources_{column}", "chat_memory_sources", [column])


def downgrade():
    populated = op.get_bind().scalar(
        sa.text(
            "SELECT EXISTS (SELECT 1 FROM chat_memories WHERE schema_version = 2) "
            "OR EXISTS (SELECT 1 FROM chat_memory_proposal_groups) "
            f"OR EXISTS (SELECT 1 FROM chat_turns WHERE operation IN ({_STRUCTURED_OPERATIONS}))"
        )
    )
    if populated:
        raise RuntimeError("Use a compatible application to roll back structured memories")
    op.drop_table("chat_memory_sources")
    op.drop_table("chat_memory_proposal_items")
    op.drop_table("chat_memory_proposal_groups")
    op.drop_constraint("chat_turns_operation_check", "chat_turns", type_="check")
    op.create_check_constraint(
        "chat_turns_operation_check", "chat_turns", f"operation IN ({_LEGACY_OPERATIONS})"
    )
    op.drop_constraint("chat_memories_storage_format_check", "chat_memories", type_="check")
    for name in (
        "applicability_json",
        "display_value",
        "semantic_key",
        "registry_version",
        "schema_version",
    ):
        op.drop_column("chat_memories", name)

"""Create G7 conversation, message, request and memory tables."""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "0001_g7_persistence"
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "chat_owner_status",
        sa.Column("owner_id", sa.String(64), primary_key=True),
        sa.Column("status", sa.String(16), nullable=False, server_default="ACTIVE"),
        sa.Column("revocation_epoch", sa.BigInteger, nullable=False, server_default="0"),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.CheckConstraint("status IN ('ACTIVE', 'DELETING', 'DELETED')"),
    )
    op.create_table(
        "chat_conversations",
        sa.Column("id", sa.UUID, primary_key=True),
        sa.Column(
            "owner_id", sa.String(64), sa.ForeignKey("chat_owner_status.owner_id"), nullable=False
        ),
        sa.Column("thread_id", sa.UUID, nullable=False, unique=True),
        sa.Column("subject_json", postgresql.JSONB, nullable=False),
        sa.Column(
            "context_json", postgresql.JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")
        ),
        sa.Column("schema_version", sa.Integer, nullable=False, server_default="1"),
        sa.Column("conversation_version", sa.BigInteger, nullable=False, server_default="0"),
        sa.Column("accepted_checkpoint_id", sa.Text),
        sa.Column("accepted_checkpoint_version", sa.BigInteger),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column("deleted_at", sa.DateTime(timezone=True)),
    )
    op.create_index(
        "chat_conversations_owner_updated_idx",
        "chat_conversations",
        ["owner_id", sa.text("updated_at DESC")],
        postgresql_where=sa.text("deleted_at IS NULL"),
    )
    op.create_table(
        "chat_messages",
        sa.Column("id", sa.UUID, primary_key=True),
        sa.Column(
            "conversation_id",
            sa.UUID,
            sa.ForeignKey("chat_conversations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("sequence", sa.BigInteger, nullable=False),
        sa.Column("role", sa.String(12), nullable=False),
        sa.Column("text", sa.Text, nullable=False),
        sa.Column(
            "display_payload",
            postgresql.JSONB,
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("request_id", sa.UUID),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.CheckConstraint("role IN ('user', 'assistant')"),
        sa.UniqueConstraint("conversation_id", "sequence"),
    )
    op.create_table(
        "chat_turns",
        sa.Column(
            "owner_id", sa.String(64), sa.ForeignKey("chat_owner_status.owner_id"), primary_key=True
        ),
        sa.Column("request_id", sa.UUID, primary_key=True),
        sa.Column(
            "conversation_id", sa.UUID, sa.ForeignKey("chat_conversations.id", ondelete="CASCADE")
        ),
        sa.Column("operation", sa.String(32), nullable=False),
        sa.Column("fingerprint", sa.String(64), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("base_version", sa.BigInteger),
        sa.Column("committed_version", sa.BigInteger),
        sa.Column("result_resource_id", sa.UUID),
        sa.Column("result_version", sa.BigInteger),
        sa.Column("turn_id", sa.UUID),
        sa.Column("response_message_id", sa.UUID),
        sa.Column("lease_until", sa.DateTime(timezone=True)),
        sa.Column("attempt_count", sa.Integer, nullable=False, server_default="1"),
        sa.Column("error_code", sa.String(64)),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.CheckConstraint("status IN ('IN_PROGRESS', 'COMMITTED', 'FAILED', 'INTERRUPTED')"),
        sa.CheckConstraint(
            "operation IN ('chat', 'state_update', 'conversation_create', "
            "'memory_create', 'memory_update', 'memory_delete')"
        ),
        sa.CheckConstraint(
            "operation NOT IN ('chat', 'state_update') OR "
            "(conversation_id IS NOT NULL AND base_version IS NOT NULL)"
        ),
    )
    op.create_index("chat_turns_conversation_idx", "chat_turns", ["conversation_id", "created_at"])
    op.create_index(
        "chat_turns_one_active_conversation_idx",
        "chat_turns",
        ["conversation_id"],
        unique=True,
        postgresql_where=sa.text(
            "status = 'IN_PROGRESS' AND operation IN ('chat', 'state_update')"
        ),
    )
    op.create_table(
        "chat_memories",
        sa.Column("id", sa.UUID, primary_key=True),
        sa.Column(
            "owner_id", sa.String(64), sa.ForeignKey("chat_owner_status.owner_id"), nullable=False
        ),
        sa.Column("kind", sa.String(24), nullable=False),
        sa.Column("memory_key", sa.String(128), nullable=False),
        sa.Column("value_json", postgresql.JSONB),
        sa.Column("version", sa.BigInteger, nullable=False, server_default="1"),
        sa.Column("consent_scope", sa.String(64), nullable=False),
        sa.Column(
            "source_message_id", sa.UUID, sa.ForeignKey("chat_messages.id", ondelete="SET NULL")
        ),
        sa.Column("confirmed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True)),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.CheckConstraint("kind IN ('preference', 'profile', 'owned_product')"),
    )
    op.create_index(
        "chat_memories_owner_active_key_uidx",
        "chat_memories",
        ["owner_id", "kind", "memory_key"],
        unique=True,
        postgresql_where=sa.text("revoked_at IS NULL"),
    )


def downgrade():
    op.drop_table("chat_memories")
    op.drop_table("chat_turns")
    op.drop_table("chat_messages")
    op.drop_table("chat_conversations")
    op.drop_table("chat_owner_status")

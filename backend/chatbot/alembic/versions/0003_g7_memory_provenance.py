"""Track server-issued memory proposals and message provenance."""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "0003_g7_memory_provenance"
down_revision = "0002_g7_state_update_result"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "chat_turns",
        sa.Column("fingerprint_schema", sa.Integer, nullable=False, server_default="1"),
    )
    op.add_column(
        "chat_messages",
        sa.Column(
            "memory_refs", postgresql.JSONB, nullable=False, server_default=sa.text("'[]'::jsonb")
        ),
    )
    op.create_table(
        "chat_memory_proposals",
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
        sa.Column(
            "source_message_id",
            sa.Uuid,
            sa.ForeignKey("chat_messages.id", ondelete="CASCADE"),
            nullable=False,
            unique=True,
        ),
        sa.Column("kind", sa.String(24), nullable=False),
        sa.Column("memory_key", sa.String(128), nullable=False),
        sa.Column("version", sa.BigInteger, nullable=False, server_default="1"),
        sa.Column("revocation_epoch", sa.BigInteger, nullable=False),
        sa.Column("memory_generation", sa.String(64), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("consumed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
    )
    op.create_index("ix_chat_memory_proposals_owner_id", "chat_memory_proposals", ["owner_id"])


def downgrade():
    op.drop_index("ix_chat_memory_proposals_owner_id", table_name="chat_memory_proposals")
    op.drop_table("chat_memory_proposals")
    op.drop_column("chat_messages", "memory_refs")
    op.drop_column("chat_turns", "fingerprint_schema")

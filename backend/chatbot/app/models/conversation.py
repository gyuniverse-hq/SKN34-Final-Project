from datetime import datetime
from uuid import UUID

from sqlalchemy import UUID as Uuid
from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy import text as sql_text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


class ChatOwnerStatus(Base):
    __tablename__ = "chat_owner_status"
    __table_args__ = (CheckConstraint("status IN ('ACTIVE', 'DELETING', 'DELETED')"),)

    owner_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    status: Mapped[str] = mapped_column(String(16), server_default="ACTIVE")
    revocation_epoch: Mapped[int] = mapped_column(BigInteger, server_default="0")
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ChatConversation(Base):
    __tablename__ = "chat_conversations"
    __table_args__ = (
        Index(
            "chat_conversations_owner_updated_idx",
            "owner_id",
            sql_text("updated_at DESC"),
            postgresql_where=sql_text("deleted_at IS NULL"),
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    owner_id: Mapped[str] = mapped_column(ForeignKey("chat_owner_status.owner_id"))
    thread_id: Mapped[UUID] = mapped_column(Uuid, unique=True)
    subject_json: Mapped[dict] = mapped_column(JSONB)
    context_json: Mapped[dict] = mapped_column(JSONB, server_default=sql_text("'{}'::jsonb"))
    schema_version: Mapped[int] = mapped_column(Integer, server_default="1")
    conversation_version: Mapped[int] = mapped_column(BigInteger, server_default="0")
    accepted_checkpoint_id: Mapped[str | None] = mapped_column(Text)
    accepted_checkpoint_version: Mapped[int | None] = mapped_column(BigInteger)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class ChatMessage(Base):
    __tablename__ = "chat_messages"
    __table_args__ = (
        CheckConstraint("role IN ('user', 'assistant')"),
        UniqueConstraint("conversation_id", "sequence"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    conversation_id: Mapped[UUID] = mapped_column(
        ForeignKey("chat_conversations.id", ondelete="CASCADE")
    )
    sequence: Mapped[int] = mapped_column(BigInteger)
    role: Mapped[str] = mapped_column(String(12))
    text: Mapped[str] = mapped_column(Text)
    display_payload: Mapped[dict] = mapped_column(JSONB, server_default=sql_text("'{}'::jsonb"))
    memory_refs: Mapped[list] = mapped_column(JSONB, server_default=sql_text("'[]'::jsonb"))
    request_id: Mapped[UUID | None] = mapped_column(Uuid)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ChatTurn(Base):
    __tablename__ = "chat_turns"
    __table_args__ = (
        CheckConstraint("status IN ('IN_PROGRESS', 'COMMITTED', 'FAILED', 'INTERRUPTED')"),
        CheckConstraint(
            "operation IN ('chat', 'state_update', 'conversation_create', "
            "'memory_create', 'memory_update', 'memory_delete')"
        ),
        CheckConstraint(
            "operation NOT IN ('chat', 'state_update') OR "
            "(conversation_id IS NOT NULL AND base_version IS NOT NULL)"
        ),
        Index("chat_turns_conversation_idx", "conversation_id", "created_at"),
        Index(
            "chat_turns_one_active_conversation_idx",
            "conversation_id",
            unique=True,
            postgresql_where=sql_text(
                "status = 'IN_PROGRESS' AND operation IN ('chat', 'state_update')"
            ),
        ),
    )

    owner_id: Mapped[str] = mapped_column(
        ForeignKey("chat_owner_status.owner_id"), primary_key=True
    )
    request_id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    conversation_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("chat_conversations.id", ondelete="CASCADE")
    )
    operation: Mapped[str] = mapped_column(String(32))
    fingerprint: Mapped[str] = mapped_column(String(64))
    fingerprint_schema: Mapped[int] = mapped_column(Integer, server_default="1")
    status: Mapped[str] = mapped_column(String(16))
    base_version: Mapped[int | None] = mapped_column(BigInteger)
    committed_version: Mapped[int | None] = mapped_column(BigInteger)
    result_resource_id: Mapped[UUID | None] = mapped_column(Uuid)
    result_version: Mapped[int | None] = mapped_column(BigInteger)
    result_payload: Mapped[dict | None] = mapped_column(JSONB(none_as_null=True))
    turn_id: Mapped[UUID | None] = mapped_column(Uuid)
    response_message_id: Mapped[UUID | None] = mapped_column(Uuid)
    lease_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    attempt_count: Mapped[int] = mapped_column(Integer, server_default="1")
    error_code: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ChatMemory(Base):
    __tablename__ = "chat_memories"
    __table_args__ = (
        CheckConstraint("kind IN ('preference', 'profile', 'owned_product')"),
        Index(
            "chat_memories_owner_active_key_uidx",
            "owner_id",
            "kind",
            "memory_key",
            unique=True,
            postgresql_where=sql_text("revoked_at IS NULL"),
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    owner_id: Mapped[str] = mapped_column(ForeignKey("chat_owner_status.owner_id"))
    kind: Mapped[str] = mapped_column(String(24))
    memory_key: Mapped[str] = mapped_column(String(128))
    value_json: Mapped[dict | None] = mapped_column(JSONB(none_as_null=True))
    version: Mapped[int] = mapped_column(BigInteger, server_default="1")
    consent_scope: Mapped[str] = mapped_column(String(64))
    source_message_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("chat_messages.id", ondelete="SET NULL")
    )
    confirmed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ChatMemoryProposal(Base):
    __tablename__ = "chat_memory_proposals"

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    owner_id: Mapped[str] = mapped_column(ForeignKey("chat_owner_status.owner_id"), index=True)
    conversation_id: Mapped[UUID] = mapped_column(
        ForeignKey("chat_conversations.id", ondelete="CASCADE")
    )
    source_message_id: Mapped[UUID] = mapped_column(
        ForeignKey("chat_messages.id", ondelete="CASCADE"), unique=True
    )
    kind: Mapped[str] = mapped_column(String(24))
    memory_key: Mapped[str] = mapped_column(String(128))
    version: Mapped[int] = mapped_column(BigInteger, server_default="1")
    revocation_epoch: Mapped[int] = mapped_column(BigInteger)
    memory_generation: Mapped[str] = mapped_column(String(64))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    consumed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

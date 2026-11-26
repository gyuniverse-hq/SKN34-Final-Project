"""Transactional owner blocking and removal of G7-owned records."""

from contextlib import asynccontextmanager
from uuid import UUID

from sqlalchemy import delete, func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.db import get_chat_sessionmaker
from app.core.errors import ApiError
from app.models.conversation import (
    ChatConversation,
    ChatMemory,
    ChatMemoryProposal,
    ChatOwnerStatus,
    ChatTurn,
)


async def _lock_owner(session: AsyncSession, owner_id: str) -> None:
    await session.execute(
        select(func.pg_advisory_xact_lock(func.hashtextextended(f"g7:owner:{owner_id}", 0)))
    )


@asynccontextmanager
async def legacy_owner_access(owner_id: str | None, *, conversation_id: UUID | None = None):
    settings = get_settings()
    if conversation_id is not None:
        if owner_id is None:
            raise ApiError(403, "Account is unavailable", "account_unavailable")
        if not settings.g7_persistence_enabled:
            raise ApiError(503, "Persistent chat is disabled", "persistence_disabled")
    if owner_id is None or not (
        settings.g7_persistence_enabled or settings.g7_owner_deletion_guard_enabled
    ):
        yield
        return
    if settings.env not in {"local", "test"} or not settings.chat_database_url:
        raise ApiError(503, "Persistent chat is unavailable", "persistence_unavailable")
    try:
        async with get_chat_sessionmaker().begin() as session:
            await _lock_owner(session, owner_id)
            status = await session.scalar(
                select(ChatOwnerStatus.status)
                .where(ChatOwnerStatus.owner_id == owner_id)
                .with_for_update()
            )
            if status is not None and status != "ACTIVE":
                raise ApiError(403, "Account is unavailable", "account_unavailable")
            if conversation_id is not None:
                # Room deletion takes the same owner row lock before setting deleted_at.
                active_room = await session.scalar(
                    select(ChatConversation.id).where(
                        ChatConversation.id == conversation_id,
                        ChatConversation.owner_id == owner_id,
                        ChatConversation.deleted_at.is_(None),
                    )
                )
                if active_room is None:
                    raise ApiError(409, "Request was interrupted", "request_interrupted")
            yield
    except (SQLAlchemyError, OSError) as exc:
        raise ApiError(503, "Persistent chat is unavailable", "persistence_unavailable") from exc


class OwnerDeletionRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def resume(self, owner_id: str) -> bool:
        """Resume only an already-blocked owner; never create or block a new one."""
        await _lock_owner(self.session, owner_id)
        status = await self.session.scalar(
            select(ChatOwnerStatus.status)
            .where(ChatOwnerStatus.owner_id == owner_id)
            .with_for_update()
        )
        if status == "DELETED":
            return False
        if status != "DELETING":
            raise ApiError(503, "Persistent chat is disabled", "persistence_disabled")
        return True

    async def block(self, owner_id: str) -> bool:
        await _lock_owner(self.session, owner_id)
        await self.session.execute(
            insert(ChatOwnerStatus)
            .values(owner_id=owner_id, status="DELETING")
            .on_conflict_do_nothing()
        )
        owner = await self.session.scalar(
            select(ChatOwnerStatus).where(ChatOwnerStatus.owner_id == owner_id).with_for_update()
        )
        if owner.status == "DELETED":
            return False
        if owner.status == "ACTIVE":
            owner.status = "DELETING"
            owner.revocation_epoch += 1
            owner.updated_at = func.now()
        await self.session.flush()
        return True

    async def threads(self, owner_id: str) -> list[UUID]:
        return list(
            await self.session.scalars(
                select(ChatConversation.thread_id)
                .where(ChatConversation.owner_id == owner_id)
                .order_by(ChatConversation.id)
            )
        )

    async def purge(self, owner_id: str) -> None:
        owner = await self.session.scalar(
            select(ChatOwnerStatus).where(ChatOwnerStatus.owner_id == owner_id).with_for_update()
        )
        if owner is None or owner.status not in {"DELETING", "DELETED"}:
            raise ValueError("Owner is not blocked for deletion")
        if owner.status == "DELETED":
            return
        await self.session.execute(
            delete(ChatMemoryProposal).where(ChatMemoryProposal.owner_id == owner_id)
        )
        await self.session.execute(delete(ChatMemory).where(ChatMemory.owner_id == owner_id))
        await self.session.execute(delete(ChatTurn).where(ChatTurn.owner_id == owner_id))
        await self.session.execute(
            delete(ChatConversation).where(ChatConversation.owner_id == owner_id)
        )
        owner.status = "DELETED"
        owner.memory_enabled = False
        owner.memory_policy_version = 0
        owner.memory_notice_at = None
        owner.updated_at = func.now()
        await self.session.flush()

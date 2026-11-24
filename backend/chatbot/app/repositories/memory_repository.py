from datetime import datetime
from hashlib import sha256
from uuid import UUID

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.conversation import (
    ChatConversation,
    ChatMemory,
    ChatMemoryProposal,
    ChatMessage,
    ChatOwnerStatus,
)


class MemoryRepository:
    """Caller owns consent validation and transaction commit."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def _lock_active(self, owner_id: str) -> bool:
        status = await self.session.scalar(
            select(ChatOwnerStatus.status)
            .where(ChatOwnerStatus.owner_id == owner_id)
            .with_for_update()
        )
        return status == "ACTIVE"

    async def get(self, owner_id: str, memory_id: UUID) -> ChatMemory | None:
        return await self.session.scalar(
            select(ChatMemory)
            .join(ChatOwnerStatus, ChatOwnerStatus.owner_id == ChatMemory.owner_id)
            .where(
                ChatMemory.id == memory_id,
                ChatMemory.owner_id == owner_id,
                ChatMemory.revoked_at.is_(None),
                ChatOwnerStatus.status == "ACTIVE",
            )
        )

    async def list(self, owner_id: str) -> list[ChatMemory]:
        rows = await self.session.scalars(
            select(ChatMemory)
            .join(ChatOwnerStatus, ChatOwnerStatus.owner_id == ChatMemory.owner_id)
            .where(
                ChatMemory.owner_id == owner_id,
                ChatMemory.revoked_at.is_(None),
                ChatOwnerStatus.status == "ACTIVE",
            )
            .order_by(ChatMemory.created_at, ChatMemory.id)
        )
        return list(rows)

    async def owner_epoch(self, owner_id: str) -> int | None:
        return await self.session.scalar(
            select(ChatOwnerStatus.revocation_epoch).where(
                ChatOwnerStatus.owner_id == owner_id, ChatOwnerStatus.status == "ACTIVE"
            )
        )

    async def generation(self, owner_id: str, enabled: bool) -> str:
        if not enabled:
            return sha256(b"disabled").hexdigest()
        rows = await self.session.execute(
            select(ChatMemory.id, ChatMemory.version)
            .where(ChatMemory.owner_id == owner_id, ChatMemory.revoked_at.is_(None))
            .order_by(ChatMemory.id)
        )
        value = "enabled:" + ",".join(f"{row.id}:{row.version}" for row in rows)
        return sha256(value.encode()).hexdigest()

    async def memory_fence(
        self, owner_id: str
    ) -> tuple[dict[str, int], set[str], dict[str, datetime]]:
        rows = await self.session.execute(
            select(
                ChatMemory.id,
                ChatMemory.version,
                ChatMemory.revoked_at,
                ChatMemory.updated_at,
                ChatMemory.source_message_id,
                ChatMessage.conversation_id,
            )
            .outerjoin(ChatMessage, ChatMessage.id == ChatMemory.source_message_id)
            .where(ChatMemory.owner_id == owner_id)
        )
        values = list(rows)
        cutoffs = {}
        for row in values:
            if row.conversation_id and (row.revoked_at is not None or row.version > 1):
                key = str(row.conversation_id)
                cutoff = row.revoked_at or row.updated_at
                if key not in cutoffs or cutoff > cutoffs[key]:
                    cutoffs[key] = cutoff
        return (
            {str(row.id): row.version for row in values if row.revoked_at is None},
            {
                str(row.source_message_id)
                for row in values
                if row.source_message_id and (row.revoked_at is not None or row.version > 1)
            },
            cutoffs,
        )

    async def proposal(self, owner_id: str, proposal_id: UUID) -> ChatMemoryProposal | None:
        return await self.session.scalar(
            select(ChatMemoryProposal)
            .join(ChatConversation, ChatConversation.id == ChatMemoryProposal.conversation_id)
            .where(
                ChatMemoryProposal.id == proposal_id,
                ChatMemoryProposal.owner_id == owner_id,
                ChatConversation.owner_id == owner_id,
                ChatConversation.deleted_at.is_(None),
            )
            .with_for_update(of=ChatMemoryProposal)
        )

    async def create(
        self,
        owner_id: str,
        memory_id: UUID,
        kind: str,
        key: str,
        value: dict,
        consent_scope: str,
        confirmed_at: datetime,
        source_message_id: UUID | None = None,
    ) -> ChatMemory | None:
        if not await self._lock_active(owner_id):
            return None
        if source_message_id is not None:
            source = await self.session.scalar(
                select(ChatMessage.id)
                .join(ChatConversation, ChatConversation.id == ChatMessage.conversation_id)
                .where(
                    ChatMessage.id == source_message_id,
                    ChatConversation.owner_id == owner_id,
                    ChatConversation.deleted_at.is_(None),
                )
            )
            if source is None:
                return None
        row = ChatMemory(
            id=memory_id,
            owner_id=owner_id,
            kind=kind,
            memory_key=key,
            value_json=value,
            consent_scope=consent_scope,
            confirmed_at=confirmed_at,
            source_message_id=source_message_id,
        )
        self.session.add(row)
        await self.session.flush()
        return row

    async def update(
        self, owner_id: str, memory_id: UUID, expected_version: int, value: dict
    ) -> int | None:
        if not await self._lock_active(owner_id):
            return None
        result = await self.session.execute(
            update(ChatMemory)
            .where(
                ChatMemory.id == memory_id,
                ChatMemory.owner_id == owner_id,
                ChatMemory.revoked_at.is_(None),
                ChatMemory.version == expected_version,
            )
            .values(value_json=value, version=expected_version + 1, updated_at=func.now())
            .returning(ChatMemory.version)
        )
        return result.scalar_one_or_none()

    async def revoke(self, owner_id: str, memory_id: UUID) -> bool:
        if not await self._lock_active(owner_id):
            return False
        result = await self.session.execute(
            update(ChatMemory)
            .where(
                ChatMemory.id == memory_id,
                ChatMemory.owner_id == owner_id,
                ChatMemory.revoked_at.is_(None),
            )
            .values(value_json=None, revoked_at=func.now(), updated_at=func.now())
            .returning(ChatMemory.id)
        )
        if result.scalar_one_or_none() is None:
            return (
                await self.session.scalar(
                    select(ChatMemory.id).where(
                        ChatMemory.id == memory_id, ChatMemory.owner_id == owner_id
                    )
                )
            ) is not None
        await self.session.execute(
            update(ChatOwnerStatus)
            .where(ChatOwnerStatus.owner_id == owner_id)
            .values(revocation_epoch=ChatOwnerStatus.revocation_epoch + 1, updated_at=func.now())
        )
        return True

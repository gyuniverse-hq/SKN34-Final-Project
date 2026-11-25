from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID, uuid4

from pydantic import TypeAdapter
from sqlalchemy import and_, delete, func, or_, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.conversation import ChatConversation, ChatMessage, ChatOwnerStatus, ChatTurn
from app.repositories.memory_repository import MemoryRepository
from app.schemas.conversation import ConversationEntry

_ENTRY = TypeAdapter(ConversationEntry)
_CONTEXT_KEYS = {
    "schemaVersion",
    "currentGoal",
    "product",
    "style",
    "styleCandidates",
    "styleConditions",
    "pendingGoal",
    "memoryRevocationEpoch",
    "memoryRefs",
}
_FORBIDDEN = {
    "authorization",
    "sessiontoken",
    "sessionid",
    "resultsetid",
    "faceimage",
    "facevideo",
    "accesstoken",
    "refreshtoken",
    "chatcontext",
    "token",
    "session",
    "apikey",
    "password",
    "secret",
    "prompt",
    "rawtoolresult",
    "image",
    "imagedata",
    "imagebase64",
    "video",
    "videoframe",
}
_DISPLAY_KEYS = {
    "appliedMemories",
    "products",
    "styleCandidates",
    "styleRecipe",
    "optionSearch",
    "ingredientResults",
    "evidence",
    "knowledge",
    "ingredientComparison",
    "fragranceSearchSummary",
    "resultType",
    "styleStatus",
    "styleContext",
    "styleConditions",
    "resultContext",
}


def _check_safe(value: object) -> None:
    if isinstance(value, dict):
        for key, item in value.items():
            if not isinstance(key, str) or key.replace("_", "").lower() in _FORBIDDEN:
                raise ValueError("Sensitive or invalid field in persistent data")
            _check_safe(item)
    elif isinstance(value, list):
        for item in value:
            _check_safe(item)


def _check_display(value: dict) -> None:
    if set(value) - _DISPLAY_KEYS:
        raise ValueError("Unknown display field")
    _check_safe(value)


class ConversationRepository:
    """All writes participate in the caller's transaction and never commit independently."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def ensure_active_owner(self, owner_id: str) -> bool:
        await self.session.execute(
            insert(ChatOwnerStatus).values(owner_id=owner_id).on_conflict_do_nothing()
        )
        status = await self.session.scalar(
            select(ChatOwnerStatus.status)
            .where(ChatOwnerStatus.owner_id == owner_id)
            .with_for_update()
        )
        return status == "ACTIVE"

    async def get(self, owner_id: str, conversation_id: UUID) -> ChatConversation | None:
        return await self.session.scalar(
            select(ChatConversation)
            .join(ChatOwnerStatus, ChatOwnerStatus.owner_id == ChatConversation.owner_id)
            .where(
                ChatConversation.id == conversation_id,
                ChatConversation.owner_id == owner_id,
                ChatConversation.deleted_at.is_(None),
                ChatOwnerStatus.status == "ACTIVE",
            )
        )

    async def list(self, owner_id: str, limit: int = 20) -> list[ChatConversation]:
        rows = await self.session.scalars(
            select(ChatConversation)
            .join(ChatOwnerStatus, ChatOwnerStatus.owner_id == ChatConversation.owner_id)
            .where(
                ChatConversation.owner_id == owner_id,
                ChatConversation.deleted_at.is_(None),
                ChatOwnerStatus.status == "ACTIVE",
            )
            .order_by(ChatConversation.updated_at.desc(), ChatConversation.id.desc())
            .limit(limit)
        )
        return list(rows)

    async def list_page(
        self, owner_id: str, limit: int, before: tuple[datetime, UUID] | None = None
    ) -> list[ChatConversation]:
        stmt = (
            select(ChatConversation)
            .join(ChatOwnerStatus, ChatOwnerStatus.owner_id == ChatConversation.owner_id)
            .where(
                ChatConversation.owner_id == owner_id,
                ChatConversation.deleted_at.is_(None),
                ChatOwnerStatus.status == "ACTIVE",
            )
        )
        if before:
            stmt = stmt.where(
                or_(
                    ChatConversation.updated_at < before[0],
                    and_(ChatConversation.updated_at == before[0], ChatConversation.id < before[1]),
                )
            )
        rows = await self.session.scalars(
            stmt.order_by(ChatConversation.updated_at.desc(), ChatConversation.id.desc()).limit(
                limit
            )
        )
        return list(rows)

    async def first_user_messages(
        self, owner_id: str, conversation_ids: list[UUID]
    ) -> dict[UUID, str]:
        if not conversation_ids:
            return {}
        first_text = (
            select(ChatMessage.text)
            .where(ChatMessage.conversation_id == ChatConversation.id, ChatMessage.role == "user")
            .order_by(ChatMessage.sequence)
            .limit(1)
            .correlate(ChatConversation)
            .scalar_subquery()
        )
        rows = await self.session.execute(
            select(ChatConversation.id, first_text)
            .join(ChatOwnerStatus, ChatOwnerStatus.owner_id == ChatConversation.owner_id)
            .where(
                ChatConversation.id.in_(conversation_ids),
                ChatConversation.owner_id == owner_id,
                ChatConversation.deleted_at.is_(None),
                ChatOwnerStatus.status == "ACTIVE",
                ChatConversation.subject_json["type"].astext == "general",
            )
        )
        return {room_id: text for room_id, text in rows if text is not None}

    async def get_creation(self, owner_id: str, request_id: UUID) -> ChatTurn | None:
        return await self.session.get(ChatTurn, (owner_id, request_id))

    async def _creation_for_room(self, owner_id: str, conversation_id: UUID) -> ChatTurn | None:
        return await self.session.scalar(
            select(ChatTurn).where(
                ChatTurn.owner_id == owner_id,
                ChatTurn.operation == "conversation_create",
                ChatTurn.result_resource_id == conversation_id,
            )
        )

    async def room_deletion_completed(self, owner_id: str, conversation_id: UUID) -> bool:
        creation = await self._creation_for_room(owner_id, conversation_id)
        return creation is not None and creation.result_payload == {"roomDeletionComplete": True}

    async def room_chat_request_ids(self, owner_id: str, conversation_id: UUID) -> list[UUID]:
        return list(
            await self.session.scalars(
                select(ChatTurn.request_id).where(
                    ChatTurn.owner_id == owner_id,
                    ChatTurn.conversation_id == conversation_id,
                    ChatTurn.operation == "chat",
                )
            )
        )

    async def record_creation(
        self, owner_id: str, request_id: UUID, fingerprint: str, conversation_id: UUID
    ) -> None:
        self.session.add(
            ChatTurn(
                owner_id=owner_id,
                request_id=request_id,
                operation="conversation_create",
                fingerprint=fingerprint,
                status="COMMITTED",
                result_resource_id=conversation_id,
                result_version=0,
            )
        )
        await self.session.flush()

    async def create(
        self, owner_id: str, conversation_id: UUID, thread_id: UUID, subject: dict
    ) -> ChatConversation | None:
        validated = _ENTRY.validate_python(subject).model_dump(
            mode="json", by_alias=True, exclude_none=True
        )
        if not await self.ensure_active_owner(owner_id):
            return None
        row = ChatConversation(
            id=conversation_id, owner_id=owner_id, thread_id=thread_id, subject_json=validated
        )
        self.session.add(row)
        await self.session.flush()
        return row

    async def update_context(
        self, owner_id: str, conversation_id: UUID, expected_version: int, context: dict
    ) -> int | None:
        if set(context) - _CONTEXT_KEYS:
            raise ValueError("Unknown conversation context field")
        _check_safe(context)
        if not await self.ensure_active_owner(owner_id):
            return None
        result = await self.session.execute(
            update(ChatConversation)
            .where(
                ChatConversation.id == conversation_id,
                ChatConversation.owner_id == owner_id,
                ChatConversation.deleted_at.is_(None),
                ChatConversation.conversation_version == expected_version,
            )
            .values(
                context_json=context,
                conversation_version=expected_version + 1,
                updated_at=func.now(),
            )
            .returning(ChatConversation.conversation_version)
        )
        return result.scalar_one_or_none()

    async def add_message(self, owner_id: str, conversation_id: UUID, message: ChatMessage) -> bool:
        _check_display(message.display_payload or {})
        if not await self.ensure_active_owner(owner_id) or not await self.get(
            owner_id, conversation_id
        ):
            return False
        if message.conversation_id != conversation_id:
            raise ValueError("Message conversation mismatch")
        self.session.add(message)
        await self.session.flush()
        return True

    async def messages(
        self, owner_id: str, conversation_id: UUID, limit: int = 50
    ) -> list[ChatMessage]:
        rows = await self.session.scalars(
            select(ChatMessage)
            .join(ChatConversation, ChatConversation.id == ChatMessage.conversation_id)
            .join(ChatOwnerStatus, ChatOwnerStatus.owner_id == ChatConversation.owner_id)
            .where(
                ChatMessage.conversation_id == conversation_id,
                ChatConversation.owner_id == owner_id,
                ChatConversation.deleted_at.is_(None),
                ChatOwnerStatus.status == "ACTIVE",
            )
            .order_by(ChatMessage.sequence)
            .limit(limit)
        )
        return list(rows)

    async def recent_messages(self, owner_id: str, conversation_id: UUID) -> list[ChatMessage]:
        rows = await self.session.scalars(
            select(ChatMessage)
            .join(ChatConversation, ChatConversation.id == ChatMessage.conversation_id)
            .join(ChatOwnerStatus, ChatOwnerStatus.owner_id == ChatConversation.owner_id)
            .join(
                ChatTurn,
                and_(
                    ChatTurn.owner_id == ChatConversation.owner_id,
                    ChatTurn.conversation_id == ChatMessage.conversation_id,
                    ChatTurn.request_id == ChatMessage.request_id,
                    ChatTurn.status == "COMMITTED",
                ),
            )
            .where(
                ChatMessage.conversation_id == conversation_id,
                ChatConversation.owner_id == owner_id,
                ChatConversation.deleted_at.is_(None),
                ChatOwnerStatus.status == "ACTIVE",
            )
            .order_by(ChatMessage.sequence.desc())
            .limit(8)
        )
        return list(reversed(list(rows)))

    async def message_page(
        self, owner_id: str, conversation_id: UUID, limit: int, before: int | None = None
    ) -> list[ChatMessage]:
        stmt = (
            select(ChatMessage)
            .join(ChatConversation, ChatConversation.id == ChatMessage.conversation_id)
            .join(ChatOwnerStatus, ChatOwnerStatus.owner_id == ChatConversation.owner_id)
            .where(
                ChatMessage.conversation_id == conversation_id,
                ChatConversation.owner_id == owner_id,
                ChatConversation.deleted_at.is_(None),
                ChatOwnerStatus.status == "ACTIVE",
            )
        )
        if before is not None:
            stmt = stmt.where(ChatMessage.sequence < before)
        rows = await self.session.scalars(stmt.order_by(ChatMessage.sequence.desc()).limit(limit))
        return list(rows)

    async def last_sequence(self, conversation_id: UUID) -> int:
        return int(
            (
                await self.session.scalar(
                    select(func.max(ChatMessage.sequence)).where(
                        ChatMessage.conversation_id == conversation_id
                    )
                )
            )
            or 0
        )

    async def response_message(
        self, owner_id: str, conversation_id: UUID, message_id: UUID
    ) -> ChatMessage | None:
        return await self.session.scalar(
            select(ChatMessage)
            .join(ChatConversation, ChatConversation.id == ChatMessage.conversation_id)
            .join(ChatOwnerStatus, ChatOwnerStatus.owner_id == ChatConversation.owner_id)
            .where(
                ChatMessage.id == message_id,
                ChatMessage.conversation_id == conversation_id,
                ChatConversation.owner_id == owner_id,
                ChatConversation.deleted_at.is_(None),
                ChatOwnerStatus.status == "ACTIVE",
            )
        )

    async def reserve_turn(
        self,
        owner_id: str,
        conversation_id: UUID,
        request_id: UUID,
        fingerprint: str,
        base_version: int,
        lease_until: datetime,
        operation: Literal["chat", "state_update"] = "chat",
    ) -> bool:
        if not await self.ensure_active_owner(owner_id):
            return False
        room = await self.get(owner_id, conversation_id)
        if room is None or room.conversation_version != base_version:
            return False
        stmt = (
            insert(ChatTurn)
            .values(
                owner_id=owner_id,
                request_id=request_id,
                conversation_id=conversation_id,
                operation=operation,
                fingerprint=fingerprint,
                fingerprint_schema=2,
                status="IN_PROGRESS",
                base_version=base_version,
                lease_until=lease_until,
            )
            .on_conflict_do_nothing()
            .returning(ChatTurn.request_id)
        )
        return (await self.session.scalar(stmt)) is not None

    async def get_turn(self, owner_id: str, request_id: UUID) -> ChatTurn | None:
        turn = await self.session.scalar(
            select(ChatTurn)
            .join(ChatOwnerStatus, ChatOwnerStatus.owner_id == ChatTurn.owner_id)
            .where(
                ChatTurn.owner_id == owner_id,
                ChatTurn.request_id == request_id,
                ChatOwnerStatus.status == "ACTIVE",
            )
        )
        if turn and turn.conversation_id and not await self.get(owner_id, turn.conversation_id):
            return None
        return turn

    async def expire_turn(self, owner_id: str, request_id: UUID) -> bool:
        result = await self.session.execute(
            update(ChatTurn)
            .where(
                ChatTurn.owner_id == owner_id,
                ChatTurn.request_id == request_id,
                ChatTurn.status == "IN_PROGRESS",
                ChatTurn.lease_until <= func.clock_timestamp(),
            )
            .values(status="INTERRUPTED", updated_at=func.now(), error_code="lease_expired")
            .returning(ChatTurn.request_id)
        )
        return result.scalar_one_or_none() is not None

    async def expire_room_turns(self, owner_id: str, conversation_id: UUID) -> None:
        await self.session.execute(
            update(ChatTurn)
            .where(
                ChatTurn.owner_id == owner_id,
                ChatTurn.conversation_id == conversation_id,
                ChatTurn.status == "IN_PROGRESS",
                ChatTurn.lease_until <= func.clock_timestamp(),
            )
            .values(status="INTERRUPTED", updated_at=func.now(), error_code="lease_expired")
        )

    async def interrupt_turn(self, owner_id: str, request_id: UUID, attempt: int) -> None:
        await self.session.execute(
            update(ChatTurn)
            .where(
                ChatTurn.owner_id == owner_id,
                ChatTurn.request_id == request_id,
                ChatTurn.status == "IN_PROGRESS",
                ChatTurn.attempt_count == attempt,
            )
            .values(status="INTERRUPTED", updated_at=func.now(), error_code="execution_uncertain")
        )

    async def fail_turn(
        self, owner_id: str, request_id: UUID, attempt: int, error_code: str
    ) -> None:
        await self.session.execute(
            update(ChatTurn)
            .where(
                ChatTurn.owner_id == owner_id,
                ChatTurn.request_id == request_id,
                ChatTurn.status == "IN_PROGRESS",
                ChatTurn.attempt_count == attempt,
                ChatTurn.lease_until > func.clock_timestamp(),
            )
            .values(status="FAILED", updated_at=func.now(), error_code=error_code[:64])
        )

    async def renew_turn(
        self,
        owner_id: str,
        conversation_id: UUID,
        request_id: UUID,
        attempt: int,
        lease_until: datetime,
    ) -> bool:
        active = (
            select(ChatConversation.id)
            .join(ChatOwnerStatus, ChatOwnerStatus.owner_id == ChatConversation.owner_id)
            .where(
                ChatConversation.id == conversation_id,
                ChatConversation.owner_id == owner_id,
                ChatConversation.deleted_at.is_(None),
                ChatOwnerStatus.status == "ACTIVE",
            )
            .exists()
        )
        result = await self.session.execute(
            update(ChatTurn)
            .where(
                ChatTurn.owner_id == owner_id,
                ChatTurn.request_id == request_id,
                ChatTurn.conversation_id == conversation_id,
                ChatTurn.status == "IN_PROGRESS",
                ChatTurn.attempt_count == attempt,
                ChatTurn.lease_until > func.clock_timestamp(),
                active,
            )
            .values(lease_until=lease_until, updated_at=func.now())
            .returning(ChatTurn.request_id)
        )
        return result.scalar_one_or_none() is not None

    async def finish_turn(
        self,
        owner_id: str,
        conversation_id: UUID,
        request_id: UUID,
        turn_id: UUID,
        attempt: int,
        base_version: int,
        context: dict,
        messages: list[ChatMessage],
        checkpoint_id: str | None = None,
        memory_epoch: int | None = None,
        memory_refs: list[dict] | None = None,
        memory_generation: str | None = None,
        memory_enabled: bool = False,
    ) -> bool:
        if set(context) - _CONTEXT_KEYS:
            raise ValueError("Unknown conversation context field")
        _check_safe(context)
        if len(messages) != 2 or [item.role for item in messages] != ["user", "assistant"]:
            raise ValueError("A completed turn requires a user and an assistant message")
        for message in messages:
            _check_display(message.display_payload or {})
            if message.conversation_id != conversation_id:
                raise ValueError("Message conversation mismatch")
            if message.request_id not in (None, request_id):
                raise ValueError("Message request mismatch")
        if not await self.ensure_active_owner(owner_id):
            return False
        if memory_epoch is not None:
            current_epoch = await self.session.scalar(
                select(ChatOwnerStatus.revocation_epoch).where(ChatOwnerStatus.owner_id == owner_id)
            )
            if current_epoch != memory_epoch:
                return False
        if memory_generation is not None and (
            await MemoryRepository(self.session).generation(owner_id, memory_enabled)
            != memory_generation
        ):
            return False
        room = await self.session.scalar(
            select(ChatConversation)
            .where(
                ChatConversation.id == conversation_id,
                ChatConversation.owner_id == owner_id,
                ChatConversation.deleted_at.is_(None),
                ChatConversation.conversation_version == base_version,
            )
            .with_for_update()
        )
        if room is None:
            return False
        turn = await self.session.scalar(
            select(ChatTurn)
            .where(
                ChatTurn.owner_id == owner_id,
                ChatTurn.request_id == request_id,
                ChatTurn.conversation_id == conversation_id,
                ChatTurn.operation == "chat",
                ChatTurn.status == "IN_PROGRESS",
                ChatTurn.base_version == base_version,
                ChatTurn.attempt_count == attempt,
                ChatTurn.lease_until > func.clock_timestamp(),
            )
            .with_for_update()
        )
        if turn is None:
            return False
        room.context_json = context
        room.conversation_version += 1
        room.accepted_checkpoint_id = checkpoint_id
        room.accepted_checkpoint_version = room.conversation_version if checkpoint_id else None
        room.updated_at = func.now()
        turn.status = "COMMITTED"
        turn.committed_version = room.conversation_version
        turn.turn_id = turn_id
        turn.response_message_id = messages[1].id
        turn.updated_at = func.now()
        for message in messages:
            message.request_id = request_id
            message.memory_refs = memory_refs or []
        self.session.add_all(messages)
        await self.session.flush()
        return True

    async def finish_state_update(
        self,
        owner_id: str,
        conversation_id: UUID,
        request_id: UUID,
        attempt: int,
        base_version: int,
        context: dict,
        memory_epoch: int | None = None,
        memory_generation: str | None = None,
        memory_enabled: bool = False,
    ) -> dict | None:
        if set(context) - _CONTEXT_KEYS:
            raise ValueError("Unknown conversation context field")
        _check_safe(context)
        if not await self.ensure_active_owner(owner_id):
            return None
        if memory_epoch is not None:
            current_epoch = await self.session.scalar(
                select(ChatOwnerStatus.revocation_epoch).where(ChatOwnerStatus.owner_id == owner_id)
            )
            if current_epoch != memory_epoch:
                return None
        if memory_generation is not None and (
            await MemoryRepository(self.session).generation(owner_id, memory_enabled)
            != memory_generation
        ):
            return None
        room = await self.session.scalar(
            select(ChatConversation)
            .where(
                ChatConversation.id == conversation_id,
                ChatConversation.owner_id == owner_id,
                ChatConversation.deleted_at.is_(None),
                ChatConversation.conversation_version == base_version,
            )
            .with_for_update()
        )
        if room is None:
            return None
        turn = await self.session.scalar(
            select(ChatTurn)
            .where(
                ChatTurn.owner_id == owner_id,
                ChatTurn.request_id == request_id,
                ChatTurn.conversation_id == conversation_id,
                ChatTurn.operation == "state_update",
                ChatTurn.status == "IN_PROGRESS",
                ChatTurn.base_version == base_version,
                ChatTurn.attempt_count == attempt,
                ChatTurn.lease_until > func.clock_timestamp(),
            )
            .with_for_update()
        )
        if turn is None:
            return None
        snapshot = {
            "conversationId": str(conversation_id),
            "conversationVersion": base_version + 1,
            "context": context,
        }
        _check_safe(snapshot)
        room.context_json = context
        room.conversation_version = base_version + 1
        room.updated_at = func.now()
        turn.status = "COMMITTED"
        turn.committed_version = base_version + 1
        turn.result_version = base_version + 1
        turn.result_resource_id = conversation_id
        turn.result_payload = snapshot
        turn.updated_at = func.now()
        await self.session.flush()
        return snapshot

    async def finish_reply(
        self,
        owner_id: str,
        conversation_id: UUID,
        request_id: UUID,
        turn_id: UUID,
        attempt: int,
        base_version: int,
        context: dict,
        question: str,
        answer: str,
        display: dict,
        checkpoint_id: str | None = None,
        memory_epoch: int | None = None,
        memory_refs: list[dict] | None = None,
        memory_generation: str | None = None,
        memory_enabled: bool = False,
    ) -> bool:
        sequence = await self.last_sequence(conversation_id)
        return await self.finish_turn(
            owner_id,
            conversation_id,
            request_id,
            turn_id,
            attempt,
            base_version,
            context,
            [
                ChatMessage(
                    id=uuid4(),
                    conversation_id=conversation_id,
                    sequence=sequence + 1,
                    role="user",
                    text=question,
                    display_payload={},
                ),
                ChatMessage(
                    id=uuid4(),
                    conversation_id=conversation_id,
                    sequence=sequence + 2,
                    role="assistant",
                    text=answer,
                    display_payload=display,
                ),
            ],
            checkpoint_id,
            memory_epoch,
            memory_refs,
            memory_generation,
            memory_enabled,
        )

    async def mark_deleted(self, owner_id: str, conversation_id: UUID) -> bool:
        if not await self.ensure_active_owner(owner_id):
            return False
        result = await self.session.execute(
            update(ChatConversation)
            .where(
                ChatConversation.id == conversation_id,
                ChatConversation.owner_id == owner_id,
                ChatConversation.deleted_at.is_(None),
            )
            .values(deleted_at=func.now(), updated_at=func.now())
            .returning(ChatConversation.id)
        )
        return result.scalar_one_or_none() is not None

    async def deleting_thread(self, owner_id: str, conversation_id: UUID) -> UUID | None:
        return await self.session.scalar(
            select(ChatConversation.thread_id)
            .join(ChatOwnerStatus, ChatOwnerStatus.owner_id == ChatConversation.owner_id)
            .where(
                ChatConversation.id == conversation_id,
                ChatConversation.owner_id == owner_id,
                ChatOwnerStatus.status == "ACTIVE",
                ChatConversation.deleted_at.is_not(None),
            )
        )

    async def purge_deleted(self, owner_id: str, conversation_id: UUID) -> bool:
        if not await self.ensure_active_owner(owner_id):
            return False
        result = await self.session.execute(
            delete(ChatConversation)
            .where(
                ChatConversation.id == conversation_id,
                ChatConversation.owner_id == owner_id,
                ChatConversation.deleted_at.is_not(None),
            )
            .returning(ChatConversation.id)
        )
        if result.scalar_one_or_none() is None:
            return False
        creation = await self._creation_for_room(owner_id, conversation_id)
        if creation is not None:
            creation.result_payload = {"roomDeletionComplete": True}
        return True

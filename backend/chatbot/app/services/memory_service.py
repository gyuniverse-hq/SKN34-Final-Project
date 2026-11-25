"""Confirmed, owner-scoped memories and their server-issued proposals."""

import json
import re
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError, SQLAlchemyError

from app.core.config import get_settings
from app.core.db import get_chat_sessionmaker
from app.core.errors import ApiError
from app.models.conversation import ChatMemoryProposal, ChatMessage, ChatTurn
from app.repositories.conversation_repository import ConversationRepository
from app.repositories.memory_repository import MemoryRepository
from app.schemas.memory import CreateMemoryRequest, MemoryItem, MemoryProposal, UpdateMemoryRequest

_REMEMBER = re.compile(r"기억해\s*줘|기억해|\bremember\b|覚えて|记住", re.I)
_NEGATE = re.compile(
    r"기억하지\s*마|기억하지\s*말|기억하지\s*않|(?:do\s+not|don.t|never)\s+remember|\b(?:i|we)\s+remember\b|覚えない|不要记住|别记住",
    re.I,
)

_CONFIRM_PROMPT = {
    "ko": "이 내용을 다음 상담을 위해 기억할지 확인해 주세요.",
    "en": "Please confirm whether I should remember this for future consultations.",
    "ja": "この内容を今後の相談のために記憶するか確認してください。",
    "zh": "请确认是否为今后的咨询记住这些内容。",
}
_MISSING_PROMPT = {
    "ko": "기억할 내용을 구체적으로 알려 주세요.",
    "en": "Please say specifically what you would like me to remember.",
    "ja": "記憶する内容を具体的に教えてください。",
    "zh": "请具体说明希望记住的内容。",
}


def memory_request_prompt(text: str, locale: str) -> str | None:
    if not get_settings().g7_memory_enabled or not _REMEMBER.search(text) or _NEGATE.search(text):
        return None
    return candidate_prompt(text, locale) or _MISSING_PROMPT[locale]


def candidate_prompt(text: str, locale: str) -> str | None:
    if not get_settings().g7_memory_enabled or len(text) > 500:
        return None
    if not _REMEMBER.search(text) or _NEGATE.search(text):
        return None
    remainder = re.sub(r"[^\w]+", "", _REMEMBER.sub("", text), flags=re.UNICODE)
    return _CONFIRM_PROMPT[locale] if len(remainder) >= 2 else None


def require_memory() -> None:
    settings = get_settings()
    if (
        not settings.g7_memory_enabled
        or not settings.g7_persistence_enabled
        or settings.env not in {"local", "test"}
        or not settings.chat_database_url
    ):
        raise ApiError(503, "Memory is unavailable", "memory_unavailable")


def _fingerprint(owner: str, operation: str, value: dict) -> str:
    encoded = json.dumps(
        {"ownerId": owner, "operation": operation, "value": value},
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )
    return sha256(encoded.encode()).hexdigest()


def _item(row) -> MemoryItem:
    value = row.value_json
    if not isinstance(value, dict) or set(value) != {"text"} or not isinstance(value["text"], str):
        raise ApiError(503, "Memory is unavailable", "memory_unavailable")
    return MemoryItem(
        id=row.id,
        kind=row.kind,
        value=value["text"],
        version=row.version,
        consent_scope=row.consent_scope,
    )


def _proposal(row, text: str) -> MemoryProposal:
    return MemoryProposal(
        proposal_id=row.id,
        version=row.version,
        kind=row.kind,
        value=text,
        expires_at=row.expires_at,
    )


async def create_candidate(
    session, owner: str, room_id: UUID, request_id: UUID, epoch: int, text: str
) -> MemoryProposal | None:
    if candidate_prompt(text, "en") is None:
        return None
    source = await session.scalar(
        select(ChatMessage.id).where(
            ChatMessage.conversation_id == room_id,
            ChatMessage.request_id == request_id,
            ChatMessage.role == "user",
        )
    )
    if source is None:
        raise ValueError("Missing proposal source")
    kind = (
        "owned_product"
        if re.search(r"보유|가지고\s*있|\bi\s+own\b|持っている|我有", text, re.I)
        else "profile"
        if re.search(r"내\s*피부|피부\s*타입|my\s+skin|肌質|我的肤质", text, re.I)
        else "preference"
    )
    generation = await MemoryRepository(session).generation(owner, True)
    issued_at = datetime.now(UTC)
    row = ChatMemoryProposal(
        id=uuid4(),
        owner_id=owner,
        conversation_id=room_id,
        source_message_id=source,
        kind=kind,
        memory_key=f"source:{source}",
        revocation_epoch=epoch,
        memory_generation=generation,
        created_at=issued_at,
        expires_at=issued_at + timedelta(minutes=15),
    )
    session.add(row)
    await session.flush()
    return _proposal(row, text)


async def replay_candidate(
    session, owner: str, room_id: UUID, request_id: UUID
) -> MemoryProposal | None:
    repo = MemoryRepository(session)
    if not get_settings().g7_memory_enabled or not await repo.personalization_enabled(owner):
        return None
    result = await session.execute(
        select(ChatMemoryProposal, ChatMessage.text)
        .join(ChatMessage, ChatMessage.id == ChatMemoryProposal.source_message_id)
        .where(
            ChatMemoryProposal.owner_id == owner,
            ChatMemoryProposal.conversation_id == room_id,
            ChatMessage.request_id == request_id,
            ChatMemoryProposal.consumed_at.is_(None),
            ChatMemoryProposal.expires_at > datetime.now(UTC),
        )
    )
    item = result.one_or_none()
    epoch = await repo.owner_epoch(owner)
    generation = await repo.generation(owner, True)
    return (
        _proposal(item[0], item[1])
        if item and item[0].revocation_epoch == epoch and item[0].memory_generation == generation
        else None
    )


class MemoryService:
    @staticmethod
    def _sessions():
        require_memory()
        return get_chat_sessionmaker()

    @staticmethod
    async def _previous(session, owner, request_id, operation, fingerprint):
        row = await session.get(ChatTurn, (owner, request_id))
        if row and (row.operation != operation or row.fingerprint != fingerprint):
            raise ApiError(409, "Request ID conflicts", "request_conflict")
        return row

    @staticmethod
    def _record(session, owner, request_id, operation, fingerprint, memory_id, version):
        session.add(
            ChatTurn(
                owner_id=owner,
                request_id=request_id,
                operation=operation,
                fingerprint=fingerprint,
                status="COMMITTED",
                result_resource_id=memory_id,
                result_version=version,
            )
        )

    async def list(self, owner: str) -> dict:
        try:
            async with self._sessions().begin() as session:
                if not await ConversationRepository(session).ensure_active_owner(owner):
                    raise ApiError(403, "Account is unavailable", "account_unavailable")
                rows = await MemoryRepository(session).list(owner)
                return {
                    "memories": [_item(row).model_dump(mode="json", by_alias=True) for row in rows]
                }
        except (SQLAlchemyError, OSError) as exc:
            raise ApiError(503, "Memory is unavailable", "memory_unavailable") from exc

    async def create(self, owner: str, body: CreateMemoryRequest) -> dict:
        require_memory()
        try:
            proposal_id = UUID(body.proposal_id)
        except ValueError as exc:
            raise ApiError(404, "Proposal not found", "not_found") from exc
        fingerprint = _fingerprint(
            owner,
            "memory_create",
            {
                "proposalId": str(proposal_id),
                "expectedProposalVersion": body.expected_proposal_version,
                "confirmed": True,
            },
        )
        try:
            async with self._sessions().begin() as session:
                if not await ConversationRepository(session).ensure_active_owner(owner):
                    raise ApiError(403, "Account is unavailable", "account_unavailable")
                previous = await self._previous(
                    session, owner, body.request_id, "memory_create", fingerprint
                )
                repo = MemoryRepository(session)
                if previous:
                    if not await repo.get(owner, previous.result_resource_id):
                        raise ApiError(410, "Memory was deleted", "memory_deleted")
                    return {
                        "memoryId": str(previous.result_resource_id),
                        "memoryVersion": previous.result_version,
                    }
                if not await repo.personalization_enabled(owner):
                    raise ApiError(409, "Memory is turned off", "memory_disabled")
                proposal = await repo.proposal(owner, proposal_id)
                epoch = await repo.owner_epoch(owner)
                generation = await repo.generation(owner, True)
                if not proposal:
                    raise ApiError(404, "Proposal not found", "not_found")
                if (
                    proposal.consumed_at is not None
                    or proposal.expires_at <= datetime.now(UTC)
                    or proposal.revocation_epoch != epoch
                    or proposal.memory_generation != generation
                    or proposal.version != body.expected_proposal_version
                ):
                    raise ApiError(409, "Proposal is no longer valid", "proposal_expired")
                text = await session.scalar(
                    select(ChatMessage.text).where(
                        ChatMessage.id == proposal.source_message_id,
                        ChatMessage.conversation_id == proposal.conversation_id,
                        ChatMessage.role == "user",
                    )
                )
                if text is None or not 1 <= len(text) <= 500:
                    raise ApiError(409, "Proposal is no longer valid", "proposal_expired")
                memory_id = uuid4()
                row = await repo.create(
                    owner,
                    memory_id,
                    proposal.kind,
                    proposal.memory_key,
                    {"text": text},
                    "future_consultations",
                    datetime.now(UTC),
                    proposal.source_message_id,
                )
                if not row:
                    raise ApiError(404, "Proposal not found", "not_found")
                proposal.consumed_at = datetime.now(UTC)
                self._record(
                    session, owner, body.request_id, "memory_create", fingerprint, memory_id, 1
                )
                return {"memoryId": str(memory_id), "memoryVersion": 1}
        except IntegrityError as exc:
            raise ApiError(409, "Memory already exists", "memory_conflict") from exc
        except (SQLAlchemyError, OSError) as exc:
            raise ApiError(503, "Memory is unavailable", "memory_unavailable") from exc

    async def update(self, owner: str, memory_id: UUID, body: UpdateMemoryRequest) -> dict:
        require_memory()
        if body.expected_version >= 2**53 - 1:
            raise ApiError(409, "Memory version exhausted", "memory_conflict")
        value = body.value
        if isinstance(value, dict) and set(value) == {"text"}:
            value = value["text"]
        if not isinstance(value, str) or not value.strip() or len(value) > 500:
            raise ApiError(400, "Invalid memory", "invalid_request")
        value = value.strip()
        fingerprint = _fingerprint(
            owner,
            "memory_update",
            {
                "memoryId": str(memory_id),
                "expectedVersion": body.expected_version,
                "value": value,
                "confirmed": True,
            },
        )
        try:
            async with self._sessions().begin() as session:
                if not await ConversationRepository(session).ensure_active_owner(owner):
                    raise ApiError(403, "Account is unavailable", "account_unavailable")
                previous = await self._previous(
                    session, owner, body.request_id, "memory_update", fingerprint
                )
                repo = MemoryRepository(session)
                row = await repo.get(owner, memory_id)
                if not row:
                    raise ApiError(404, "Memory not found", "not_found")
                if previous:
                    return {"memoryId": str(memory_id), "memoryVersion": previous.result_version}
                version = await repo.update(
                    owner, memory_id, body.expected_version, {"text": value}
                )
                if version is None:
                    raise ApiError(409, "Memory version changed", "memory_conflict")
                self._record(
                    session,
                    owner,
                    body.request_id,
                    "memory_update",
                    fingerprint,
                    memory_id,
                    version,
                )
                return {"memoryId": str(memory_id), "memoryVersion": version}
        except (SQLAlchemyError, OSError) as exc:
            raise ApiError(503, "Memory is unavailable", "memory_unavailable") from exc

    async def delete(
        self, owner: str, memory_id: UUID, request_id: UUID, schema_version: int = 1
    ) -> None:
        identity = {"memoryId": str(memory_id)}
        if schema_version != 1:
            identity["schemaVersion"] = schema_version
        fingerprint = _fingerprint(owner, "memory_delete", identity)
        try:
            async with self._sessions().begin() as session:
                if not await ConversationRepository(session).ensure_active_owner(owner):
                    raise ApiError(403, "Account is unavailable", "account_unavailable")
                previous = await self._previous(
                    session, owner, request_id, "memory_delete", fingerprint
                )
                if previous:
                    return
                if not await MemoryRepository(session).revoke(owner, memory_id, schema_version):
                    raise ApiError(404, "Memory not found", "not_found")
                self._record(
                    session, owner, request_id, "memory_delete", fingerprint, memory_id, None
                )
        except (SQLAlchemyError, OSError) as exc:
            raise ApiError(503, "Memory is unavailable", "memory_unavailable") from exc

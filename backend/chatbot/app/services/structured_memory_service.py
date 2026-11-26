"""Issue, edit, and resolve owner-scoped structured memory proposals."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.errors import ApiError
from app.models.conversation import (
    ChatConversation,
    ChatMemory,
    ChatMemoryProposalGroup,
    ChatMemoryProposalItem,
    ChatMemorySource,
    ChatMessage,
    ChatTurn,
)
from app.repositories.conversation_repository import ConversationRepository
from app.repositories.memory_repository import MemoryRepository
from app.schemas.memory import (
    DecideStructuredProposals,
    EditStructuredProposal,
    StructuredMemoryValue,
    StructuredProposalGroup,
    StructuredProposalItem,
    UpdateStructuredMemory,
)
from app.services.memory_registry import (
    REGISTRY_VERSION,
    build_value,
    editable,
    edited_value,
    extract_values,
    normalize,
)
from app.services.memory_service import MemoryService, _fingerprint, _item

_PENDING = ("pending", "deferred")
_SCOPE = "future_consultations"


def enabled() -> bool:
    settings = get_settings()
    return settings.g7_memory_enabled and settings.g7_structured_memory_enabled


def _conflict() -> ApiError:
    return ApiError(409, "Review the current memory proposal", "memory_proposal_changed")


def _not_found() -> ApiError:
    return ApiError(404, "Memory proposal not found", "not_found")


def _stored_value(row: ChatMemory, locale: str) -> StructuredMemoryValue:
    return build_value(
        row.semantic_key, row.value_json, locale, row.applicability_json.get("context")
    )


def _stored_item(row: ChatMemory, locale: str) -> dict:
    current, choices = editable(_stored_value(row, locale), locale)
    return {
        "id": str(row.id),
        "schemaVersion": 2,
        "key": row.semantic_key,
        "kind": row.kind,
        "value": row.display_value,
        "version": row.version,
        "consentScope": row.consent_scope,
        "editableValue": current,
        "choices": choices,
    }


def _same_value(key: str, left: dict, right: dict) -> bool:
    if key != "inventory.product":
        return left == right
    if left.get("productId") and right.get("productId"):
        return (left["productId"], left.get("shadeId")) == (
            right["productId"],
            right.get("shadeId"),
        )
    return normalize(left["productName"]) == normalize(right["productName"])


def _applicability(draft: StructuredMemoryValue) -> dict:
    return {"context": draft.context} if draft.context else {}


async def _match(
    session: AsyncSession, owner: str, draft: StructuredMemoryValue, exclude_id: UUID | None = None
) -> tuple[bool, ChatMemory | None]:
    rows = await session.scalars(
        select(ChatMemory).where(
            ChatMemory.owner_id == owner,
            ChatMemory.schema_version == 2,
            ChatMemory.semantic_key == draft.key,
            ChatMemory.revoked_at.is_(None),
        )
    )
    target = None
    for row in rows:
        if row.id == exclude_id:
            continue
        if row.applicability_json != _applicability(draft):
            continue
        if _same_value(draft.key, row.value_json, draft.value):
            return True, None
        if draft.key == "skin.type":
            target = row
    return False, target


async def issue_group(
    session: AsyncSession,
    owner: str,
    room_id: UUID,
    request_id: UUID,
    locale: str,
    drafts: list[StructuredMemoryValue],
    prior: bool,
) -> None:
    current = await session.scalar(
        select(ChatMessage).where(
            ChatMessage.conversation_id == room_id,
            ChatMessage.request_id == request_id,
            ChatMessage.role == "user",
        )
    )
    if current is None:
        raise ValueError("Missing source for structured memory")
    source_ids = [current.id]
    if prior and not drafts:
        previous = await session.scalar(
            select(ChatMessage)
            .where(
                ChatMessage.conversation_id == room_id,
                ChatMessage.role == "user",
                ChatMessage.sequence < current.sequence,
            )
            .order_by(ChatMessage.sequence.desc())
            .limit(1)
        )
        if previous is not None:
            drafts = extract_values(previous.text, locale)
            legacy_blocked = await session.scalar(
                select(ChatMemory.id)
                .where(
                    ChatMemory.owner_id == owner,
                    ChatMemory.source_message_id == previous.id,
                    (ChatMemory.revoked_at.is_not(None)) | (ChatMemory.version > 1),
                )
                .limit(1)
            )
            if legacy_blocked is not None:
                return
            rejected = (
                select(ChatMemoryProposalItem.semantic_key)
                .join(ChatMemorySource, ChatMemorySource.item_id == ChatMemoryProposalItem.id)
                .where(
                    ChatMemorySource.message_id == previous.id,
                    ChatMemoryProposalItem.status == "rejected",
                )
            )
            revoked = (
                select(ChatMemory.semantic_key)
                .join(ChatMemorySource, ChatMemorySource.memory_id == ChatMemory.id)
                .where(
                    ChatMemorySource.message_id == previous.id,
                    ChatMemory.owner_id == owner,
                    (ChatMemory.revoked_at.is_not(None)) | (ChatMemory.version > 1),
                )
            )
            excluded = set(await session.scalars(rejected.union(revoked)))
            drafts = [draft for draft in drafts if draft.key not in excluded]
            source_ids.append(previous.id)
    choices = []
    skin_types: dict[str | None, set[str]] = {}
    for draft in drafts:
        if draft.key == "skin.type":
            skin_types.setdefault(draft.context, set()).add(draft.value["type"])
    for draft in drafts:
        if draft.key == "skin.type" and len(skin_types[draft.context]) != 1:
            continue
        if any(
            draft.key == choice.key
            and draft.context == choice.context
            and (draft.key == "skin.type" or _same_value(draft.key, draft.value, choice.value))
            for choice, _ in choices
        ):
            continue
        duplicate, target = await _match(session, owner, draft)
        if not duplicate:
            choices.append((draft, target))
    if not choices:
        return

    repo = MemoryRepository(session)
    epoch = await repo.owner_epoch(owner)
    generation = await repo.generation(owner, True)
    issued_at = datetime.now(UTC)
    group = ChatMemoryProposalGroup(
        id=uuid4(),
        owner_id=owner,
        conversation_id=room_id,
        origin_request_id=request_id,
        locale=locale,
        revocation_epoch=epoch,
        memory_generation=generation,
        created_at=issued_at,
        expires_at=issued_at + timedelta(minutes=15),
    )
    session.add(group)
    await session.flush()
    items = []
    for position, (draft, target) in enumerate(choices):
        item = ChatMemoryProposalItem(
            id=uuid4(),
            group_id=group.id,
            position=position,
            semantic_key=draft.key,
            payload=draft.model_dump(mode="json"),
            source_count=len(source_ids),
            target_id=target.id if target else None,
            target_version=target.version if target else None,
        )
        items.append(item)
    session.add_all(items)
    await session.flush()
    session.add_all(
        ChatMemorySource(id=uuid4(), item_id=item.id, message_id=source)
        for item in items
        for source in source_ids
    )
    await session.flush()


def _record(
    session: AsyncSession, owner: str, request: UUID, operation: str, fingerprint: str, result: dict
) -> None:
    session.add(
        ChatTurn(
            owner_id=owner,
            request_id=request,
            operation=operation,
            fingerprint=fingerprint,
            status="COMMITTED",
            result_payload=result,
        )
    )


async def _sources(session: AsyncSession, item: ChatMemoryProposalItem, group) -> list:
    links = (
        await session.scalars(select(ChatMemorySource).where(ChatMemorySource.item_id == item.id))
    ).all()
    ids = {link.message_id for link in links if link.message_id is not None}
    verified = set(
        await session.scalars(
            select(ChatMessage.id)
            .join(ChatConversation, ChatMessage.conversation_id == ChatConversation.id)
            .where(
                ChatMessage.id.in_(ids),
                ChatMessage.role == "user",
                ChatConversation.id == group.conversation_id,
                ChatConversation.owner_id == group.owner_id,
                ChatConversation.deleted_at.is_(None),
            )
        )
    )
    if len(verified) != item.source_count or verified != ids:
        raise _conflict()
    return links


async def _item_dto(session: AsyncSession, item, group) -> StructuredProposalItem:
    draft = StructuredMemoryValue.model_validate(item.payload)
    current, options = editable(draft, group.locale)
    previous = None
    if item.target_id:
        target = await session.get(ChatMemory, item.target_id)
        if (
            target is None
            or target.owner_id != group.owner_id
            or target.revoked_at is not None
            or target.version != item.target_version
            or target.schema_version != 2
        ):
            raise _conflict()
        previous = target.display_value
    return StructuredProposalItem(
        **draft.model_dump(),
        item_id=item.id,
        version=item.version,
        status=item.status,
        previous_display_value=previous,
        editable_value=current,
        choices=options,
    )


class StructuredMemoryService:
    @staticmethod
    @asynccontextmanager
    async def _session(owner: str) -> AsyncIterator[AsyncSession]:
        try:
            async with MemoryService._sessions().begin() as session:
                if not await ConversationRepository(session).ensure_active_owner(owner):
                    raise ApiError(403, "Account is unavailable", "account_unavailable")
                yield session
        except IntegrityError as exc:
            raise _conflict() from exc
        except (SQLAlchemyError, OSError) as exc:
            raise ApiError(503, "Memory is unavailable", "memory_unavailable") from exc

    @staticmethod
    async def _group(session, owner: str, group_id: UUID) -> ChatMemoryProposalGroup:
        group = await session.scalar(
            select(ChatMemoryProposalGroup)
            .join(ChatConversation, ChatConversation.id == ChatMemoryProposalGroup.conversation_id)
            .where(
                ChatMemoryProposalGroup.id == group_id,
                ChatMemoryProposalGroup.owner_id == owner,
                ChatConversation.owner_id == owner,
                ChatConversation.deleted_at.is_(None),
            )
        )
        if group is None:
            raise _not_found()
        return group

    @staticmethod
    async def _check_group(session, group: ChatMemoryProposalGroup) -> None:
        if not enabled():
            raise ApiError(503, "Structured memory is unavailable", "memory_unavailable")
        repo = MemoryRepository(session)
        if not await repo.personalization_enabled(group.owner_id):
            raise ApiError(409, "Memory is turned off", "memory_disabled")
        if datetime.now(UTC) >= group.expires_at:
            raise ApiError(410, "Memory proposal expired", "proposal_expired")
        if group.revocation_epoch != await repo.owner_epoch(
            group.owner_id
        ) or group.memory_generation != await repo.generation(group.owner_id, True):
            raise _conflict()

    async def list_groups(self, owner: str, conversation_id: UUID) -> list[StructuredProposalGroup]:
        if not enabled():
            return []
        async with self._session(owner) as session:
            if not await ConversationRepository(session).get(owner, conversation_id):
                raise _not_found()
            repo = MemoryRepository(session)
            if not await repo.personalization_enabled(owner):
                return []
            groups = (
                await session.scalars(
                    select(ChatMemoryProposalGroup)
                    .where(
                        ChatMemoryProposalGroup.owner_id == owner,
                        ChatMemoryProposalGroup.conversation_id == conversation_id,
                        ChatMemoryProposalGroup.expires_at > datetime.now(UTC),
                        ChatMemoryProposalGroup.revocation_epoch == await repo.owner_epoch(owner),
                        ChatMemoryProposalGroup.memory_generation
                        == await repo.generation(owner, True),
                    )
                    .order_by(ChatMemoryProposalGroup.created_at, ChatMemoryProposalGroup.id)
                )
            ).all()
            if not groups:
                return []
            by_group = {group.id: group for group in groups}
            items = await session.scalars(
                select(ChatMemoryProposalItem)
                .where(
                    ChatMemoryProposalItem.group_id.in_(by_group),
                    ChatMemoryProposalItem.status.in_(_PENDING),
                )
                .order_by(ChatMemoryProposalItem.position)
            )
            visible = {group.id: [] for group in groups}
            for item in items:
                group = by_group[item.group_id]
                try:
                    await _sources(session, item, group)
                    visible[group.id].append(await _item_dto(session, item, group))
                except ApiError as error:
                    if error.code != "memory_proposal_changed":
                        raise
            return [
                StructuredProposalGroup(
                    group_id=group.id,
                    conversation_id=group.conversation_id,
                    expires_at=group.expires_at,
                    items=visible[group.id],
                )
                for group in groups
                if visible[group.id]
            ]

    async def edit(
        self, owner: str, group_id: UUID, item_id: UUID, body: EditStructuredProposal
    ) -> StructuredProposalItem:
        operation = "memory_proposal_edit"
        fingerprint = _fingerprint(
            owner,
            operation,
            {
                "groupId": str(group_id),
                "itemId": str(item_id),
                **body.model_dump(mode="json"),
            },
        )
        async with self._session(owner) as session:
            group = await self._group(session, owner, group_id)
            await self._check_group(session, group)
            item = await session.get(ChatMemoryProposalItem, item_id)
            if item is None or item.group_id != group.id:
                raise _not_found()
            if item.status not in _PENDING:
                raise _conflict()
            await _sources(session, item, group)
            previous = await MemoryService._previous(
                session, owner, body.request_id, operation, fingerprint
            )
            if previous:
                if item.version != previous.result_payload["itemVersion"]:
                    raise _conflict()
                return await _item_dto(session, item, group)
            if item.version != body.expected_version or item.version >= 2**53 - 1:
                raise _conflict()
            try:
                draft = edited_value(
                    StructuredMemoryValue.model_validate(item.payload), body.value, group.locale
                )
            except ValueError as exc:
                raise ApiError(422, "Invalid memory value", "memory_value_invalid") from exc
            duplicate, target = await _match(session, owner, draft)
            if duplicate:
                raise _conflict()
            item.version += 1
            item.payload = draft.model_dump(mode="json")
            item.target_id = target.id if target else None
            item.target_version = target.version if target else None
            session.add(
                ChatMemorySource(id=uuid4(), item_id=item.id, edit_request_id=body.request_id)
            )
            _record(
                session,
                owner,
                body.request_id,
                operation,
                fingerprint,
                {
                    "itemId": str(item.id),
                    "itemVersion": item.version,
                },
            )
            return await _item_dto(session, item, group)

    async def decide(self, owner: str, group_id: UUID, body: DecideStructuredProposals) -> dict:
        operation = "memory_proposal_decide"
        fingerprint = _fingerprint(
            owner,
            operation,
            {
                "groupId": str(group_id),
                "decisions": [
                    item.model_dump(mode="json")
                    for item in sorted(body.decisions, key=lambda item: item.item_id)
                ],
            },
        )
        async with self._session(owner) as session:
            previous = await MemoryService._previous(
                session, owner, body.request_id, operation, fingerprint
            )
            if previous:
                return previous.result_payload
            group = await self._group(session, owner, group_id)
            await self._check_group(session, group)
            items = {
                item.id: item
                for item in await session.scalars(
                    select(ChatMemoryProposalItem).where(
                        ChatMemoryProposalItem.group_id == group.id,
                        ChatMemoryProposalItem.id.in_(
                            [decision.item_id for decision in body.decisions]
                        ),
                    )
                )
            }
            responses = []
            for decision in body.decisions:
                item = items.get(decision.item_id)
                if item is None:
                    raise _not_found()
                if item.status not in _PENDING or item.version != decision.expected_version:
                    raise _conflict()
                links = await _sources(session, item, group)
                result = {"itemId": str(item.id)}
                if decision.action == "approve":
                    memory = await self._approve(session, group, item, links)
                    item.status = "approved"
                    result.update(memoryId=str(memory.id), memoryVersion=memory.version)
                elif decision.action == "reject":
                    item.status = "rejected"
                else:
                    item.status = "deferred"
                if item.status not in _PENDING:
                    item.payload = None
                responses.append({**result, "status": item.status})
            await session.flush()
            group.memory_generation = await MemoryRepository(session).generation(owner, True)
            receipt = {"items": responses}
            _record(session, owner, body.request_id, operation, fingerprint, receipt)
            return receipt

    @staticmethod
    async def _approve(session, group, item, links) -> ChatMemory:
        try:
            draft = StructuredMemoryValue.model_validate(item.payload)
            canonical = build_value(draft.key, draft.value, group.locale, draft.context)
        except ValueError as exc:
            raise _conflict() from exc
        if canonical != draft:
            raise _conflict()
        duplicate, target = await _match(session, group.owner_id, draft)
        if (
            duplicate
            or item.target_id != (target.id if target else None)
            or item.target_version != (target.version if target else None)
        ):
            raise _conflict()
        now = datetime.now(UTC)
        if now >= group.expires_at:
            raise ApiError(410, "Memory proposal expired", "proposal_expired")
        if target is None:
            memory_id = uuid4()
            target = ChatMemory(
                id=memory_id,
                owner_id=group.owner_id,
                kind=draft.kind,
                memory_key=f"structured:{memory_id}",
                schema_version=2,
                registry_version=REGISTRY_VERSION,
                semantic_key=draft.key,
                consent_scope=_SCOPE,
                version=1,
            )
            session.add(target)
        else:
            if target.version >= 2**53 - 1:
                raise _conflict()
            target.version += 1
        target.value_json = draft.value
        target.applicability_json = _applicability(draft)
        target.display_value = draft.display_value
        target.confirmed_at = now
        target.updated_at = now
        await session.flush()
        existing = set(
            (
                await session.execute(
                    select(ChatMemorySource.message_id, ChatMemorySource.edit_request_id).where(
                        ChatMemorySource.memory_id == target.id
                    )
                )
            ).all()
        )
        session.add_all(
            ChatMemorySource(
                id=uuid4(),
                memory_id=target.id,
                message_id=link.message_id,
                edit_request_id=link.edit_request_id,
            )
            for link in links
            if (link.message_id, link.edit_request_id) not in existing
        )
        return target

    async def update_memory(
        self, owner: str, memory_id: UUID, body: UpdateStructuredMemory
    ) -> dict:
        operation = "memory_structured_update"
        fingerprint = _fingerprint(
            owner, operation, {"memoryId": str(memory_id), **body.model_dump(mode="json")}
        )
        async with self._session(owner) as session:
            repo = MemoryRepository(session)
            row = await repo.get(owner, memory_id, schema_version=2)
            if row is None:
                raise ApiError(404, "Memory not found", "not_found")
            if await MemoryService._previous(
                session, owner, body.request_id, operation, fingerprint
            ):
                return _stored_item(row, body.locale)
            if row.version != body.expected_version or row.version >= 2**53 - 1:
                raise ApiError(409, "Memory version changed", "memory_conflict")
            try:
                current = _stored_value(row, body.locale)
                if current.key == "inventory.product" and "productId" in current.value:
                    if normalize(body.value) != normalize(current.value["productName"]):
                        raise ApiError(
                            409,
                            "Confirm a new proposal for a different product",
                            "memory_requires_confirmation",
                        )
                    new = build_value(
                        current.key,
                        {**current.value, "productName": body.value},
                        body.locale,
                        current.context,
                    )
                else:
                    new = edited_value(current, body.value, body.locale)
            except ValueError as exc:
                raise ApiError(422, "Invalid memory value", "memory_value_invalid") from exc
            if new.value != current.value:
                duplicate, _ = await _match(session, owner, new, exclude_id=row.id)
                if duplicate:
                    raise ApiError(409, "Memory already exists", "memory_conflict")
                row.version += 1
                row.value_json = new.value
                row.display_value = new.display_value
                row.updated_at = datetime.now(UTC)
                session.add(
                    ChatMemorySource(id=uuid4(), memory_id=row.id, edit_request_id=body.request_id)
                )
            MemoryService._record(
                session, owner, body.request_id, operation, fingerprint, row.id, row.version
            )
            return _stored_item(row, body.locale)

    async def list_memories(self, owner: str, locale: str = "en") -> dict:
        async with self._session(owner) as session:
            repo = MemoryRepository(session)
            memories = [
                _item(row).model_dump(mode="json", by_alias=True) for row in await repo.list(owner)
            ]
            memories.extend(_stored_item(row, locale) for row in await repo.list(owner, 2))
            return {"memories": memories}

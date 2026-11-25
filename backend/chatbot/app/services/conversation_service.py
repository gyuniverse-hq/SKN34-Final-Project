"""Coordinate authenticated conversations without holding database locks during chat."""

import asyncio
import base64
import json
import logging
import re
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from types import SimpleNamespace
from uuid import UUID, uuid4

from sqlalchemy.exc import SQLAlchemyError

from app.clients.catalog_client import UpstreamError
from app.core.config import get_settings
from app.core.db import get_chat_sessionmaker
from app.core.errors import ApiError
from app.repositories.chat_session_repository import get_chat_sessions
from app.repositories.checkpoint_repository import CheckpointRepository
from app.repositories.conversation_repository import ConversationRepository
from app.repositories.memory_repository import MemoryRepository
from app.schemas.chat import BeautyContext, BeautyFilters, ChatRequest, ChatResponse
from app.schemas.conversation import (
    ConversationMetadata,
    CreateConversationRequest,
    UpdateConversationStateRequest,
)
from app.services.chat_service import ChatService
from app.services.consultation_memory import (
    CONSULTATION_MEMORY_LIMIT,
    capture_prompt_dependencies,
    ignores_memory,
    select_consultation_memories,
    visible_memory_evidence,
)
from app.services.conversation_context import (
    apply_state_update,
    display_payload,
    prepare_request,
    read_context,
    restore_response,
    revalidate_request,
    updated_context,
)
from app.services.memory_registry import (
    extract_values,
    is_explicit_request,
    refers_to_prior,
    with_verified_product,
)
from app.services.memory_service import (
    _item,
    create_candidate,
    memory_request_prompt,
    replay_candidate,
)
from app.services.structured_memory_service import enabled as structured_memory_enabled
from app.services.structured_memory_service import issue_group

logger = logging.getLogger(__name__)
_STRUCTURED_MEMORY_REPLY = {
    "ko": (
        "제안에서 선택하고 저장을 확인한 항목만 기억해요. "
        "제안이 보이지 않으면 기억할 내용을 구체적으로 알려주세요."
    ),
    "en": (
        "Only items you select and confirm will be saved. "
        "If no proposal appears, tell me what to remember more specifically."
    ),
    "ja": (
        "提案から選び、保存を確認した項目だけを記憶します。"
        "提案が表示されない場合は、内容を具体的に教えてください。"
    ),
    "zh": "只有选择并确认保存的项目才会被记住。若没有显示提议，请具体说明要记住的内容。",
}

_LIST_TITLE_RULES = (
    ("look", re.compile(r"룩|화장법|メイク方法|妆容|妝容|\bmakeup (?:look|tutorial)\b", re.I)),
    ("ingredient", re.compile(r"성분|향료|成分|香料|\b(?:ingredients?|fragrance)\b", re.I)),
    (
        "product",
        re.compile(
            r"제품|상품|립스틱|립틴트|製品|商品|口红|口紅|\b(?:products?|lipsticks?|lip tint)\b",
            re.I,
        ),
    ),
)
_LIST_PREVIEW_RULES = (
    ("hydration", re.compile(r"보습|촉촉|保湿|保濕|\b(?:moisturi[sz]\w*|hydrati\w*)\b", re.I)),
    (
        "price",
        re.compile(r"가격|예산|만원|価格|予算|价格|價格|预算|\b(?:price|budget|cost)\b", re.I),
    ),
)


def _list_summary(text: str) -> dict[str, str | list[str]]:
    title = next((topic for topic, pattern in _LIST_TITLE_RULES if pattern.search(text)), None)
    topics = [topic for topic, pattern in _LIST_PREVIEW_RULES if pattern.search(text)]
    summary: dict[str, str | list[str]] = {"previewTopics": topics} if title or topics else {}
    if title:
        summary["titleTopic"] = title
    return summary


def _unavailable() -> ApiError:
    return ApiError(503, "Persistent chat is unavailable", "persistence_unavailable")


def _safe_context(raw: dict, epoch: int, versions: dict[str, int]) -> dict:
    context = read_context(raw)
    if context.memory_revocation_epoch != epoch or any(
        versions.get(str(ref.memory_id)) != ref.version for ref in context.memory_refs
    ):
        return {"schemaVersion": 1, "memoryRevocationEpoch": epoch}
    return raw


def require_persistence() -> None:
    settings = get_settings()
    if not settings.g7_persistence_enabled:
        raise ApiError(503, "Persistent chat is disabled", "persistence_disabled")
    # Until coordinated account deletion is implemented, production and shared envs stay closed.
    if settings.env not in {"local", "test"} or not settings.chat_database_url:
        raise _unavailable()


def _fingerprint(owner_id: str, operation: str, value: dict) -> str:
    encoded = json.dumps(
        {"ownerId": owner_id, "operation": operation, "value": value},
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )
    return sha256(encoded.encode("utf-8")).hexdigest()


def _cursor(value: dict) -> str:
    return (
        base64.urlsafe_b64encode(json.dumps(value, separators=(",", ":")).encode())
        .decode()
        .rstrip("=")
    )


def _decode_cursor(value: str) -> dict:
    try:
        if len(value) > 1024:
            raise ValueError("cursor too large")
        data = json.loads(base64.urlsafe_b64decode(value + "=" * (-len(value) % 4)))
        if not isinstance(data, dict):
            raise ValueError("invalid cursor")
        return data
    except (ValueError, TypeError, UnicodeDecodeError) as exc:
        raise ApiError(400, "Invalid cursor", "invalid_request") from exc


class ConversationService:
    def __init__(self, chat: ChatService) -> None:
        self.chat = chat

    @staticmethod
    def _sessions():
        require_persistence()
        return get_chat_sessionmaker()

    async def create(self, owner_id: str, body: CreateConversationRequest) -> dict:
        fingerprint = _fingerprint(
            owner_id,
            "conversation_create",
            body.entry.model_dump(mode="json", by_alias=True, exclude_none=True),
        )
        try:
            async with self._sessions().begin() as session:
                repo = ConversationRepository(session)
                if not await repo.ensure_active_owner(owner_id):
                    raise ApiError(403, "Account is unavailable", "account_unavailable")
                previous = await repo.get_creation(owner_id, body.request_id)
                if previous:
                    if (
                        previous.operation != "conversation_create"
                        or previous.fingerprint != fingerprint
                    ):
                        raise ApiError(409, "Request ID conflicts", "request_conflict")
                    room = await repo.get(owner_id, previous.result_resource_id)
                    if room is None:
                        raise ApiError(410, "Conversation was deleted", "conversation_deleted")
                else:
                    room = await repo.create(
                        owner_id,
                        uuid4(),
                        uuid4(),
                        body.entry.model_dump(mode="json", by_alias=True, exclude_none=True),
                    )
                    if room is None:
                        raise ApiError(403, "Account is unavailable", "account_unavailable")
                    await repo.record_creation(owner_id, body.request_id, fingerprint, room.id)
                return {
                    "conversationId": str(room.id),
                    "conversationVersion": 0,
                    "subject": room.subject_json,
                    "createdAt": room.created_at,
                }
        except (SQLAlchemyError, OSError) as exc:
            raise _unavailable() from exc

    async def list(self, owner_id: str, limit: int, cursor: str | None) -> dict:
        before = None
        if cursor:
            data = _decode_cursor(cursor)
            try:
                before = (datetime.fromisoformat(data["updatedAt"]), UUID(data["id"]))
                if before[0].tzinfo is None:
                    raise ValueError("missing timezone")
            except (KeyError, TypeError, ValueError) as exc:
                raise ApiError(400, "Invalid cursor", "invalid_request") from exc
        try:
            async with self._sessions()() as session:
                repo = ConversationRepository(session)
                rows = await repo.list_page(owner_id, limit + 1, before)
                more = len(rows) > limit
                rows = rows[:limit]
                first_messages = await repo.first_user_messages(
                    owner_id, [row.id for row in rows if row.subject_json.get("type") == "general"]
                )
                next_cursor = (
                    _cursor({"updatedAt": rows[-1].updated_at.isoformat(), "id": str(rows[-1].id)})
                    if more
                    else None
                )
                conversations = []
                for row in rows:
                    item = {
                        "conversationId": str(row.id),
                        "conversationVersion": row.conversation_version,
                        "subject": row.subject_json,
                        "createdAt": row.created_at,
                        "updatedAt": row.updated_at,
                    }
                    summary = _list_summary(first_messages.get(row.id, ""))
                    if summary:
                        item["listSummary"] = summary
                    conversations.append(item)
                return {"conversations": conversations, "nextCursor": next_cursor}
        except (SQLAlchemyError, OSError) as exc:
            raise _unavailable() from exc

    async def detail(
        self, owner_id: str, conversation_id: UUID, limit: int = 50, before: int | None = None
    ) -> dict:
        try:
            async with self._sessions().begin() as session:
                repo = ConversationRepository(session)
                if not await repo.ensure_active_owner(owner_id):
                    raise ApiError(403, "Account is unavailable", "account_unavailable")
                room = await repo.get(owner_id, conversation_id)
                if room is None:
                    raise ApiError(404, "Conversation not found", "not_found")
                rows = await repo.message_page(owner_id, conversation_id, limit + 1, before)
                memory_repo = MemoryRepository(session)
                epoch = await memory_repo.owner_epoch(owner_id)
                versions, _, _ = await memory_repo.memory_fence(owner_id)
                if (
                    not get_settings().g7_memory_enabled
                    or not await memory_repo.personalization_enabled(owner_id)
                ):
                    versions = {}
                safe_context = _safe_context(dict(room.context_json), epoch, versions)
                more = len(rows) > limit
                rows = rows[:limit]
                next_cursor = rows[-1].sequence if more else None
                return {
                    "conversationId": str(room.id),
                    "conversationVersion": room.conversation_version,
                    "subject": room.subject_json,
                    "context": safe_context,
                    "messages": [
                        {
                            "id": str(row.id),
                            "role": row.role,
                            "text": row.text,
                            "displayPayload": visible_memory_evidence(
                                row.display_payload, versions
                            ),
                            "createdAt": row.created_at,
                        }
                        for row in reversed(rows)
                    ],
                    "nextMessageCursor": next_cursor,
                    "restoreStatus": "needs_revalidation" if safe_context else "ready",
                }
        except (SQLAlchemyError, OSError) as exc:
            raise _unavailable() from exc

    @staticmethod
    def _request_fingerprint(
        owner_id: str,
        request: ChatRequest,
        *,
        legacy: bool = False,
        legacy_without_clarification: bool = False,
    ) -> str:
        fields = {
            "conversationId": str(request.conversation_id),
            "message": request.message,
            "locale": request.locale,
            "requestType": request.request_type,
            "expectedConversationVersion": request.expected_conversation_version,
            "skin": request.skin.model_dump(mode="json", by_alias=True) if request.skin else None,
            "styleSearch": request.style_search,
            "generalMakeup": request.general_makeup,
        }
        if request.clarification_id is not None and not legacy_without_clarification:
            fields["clarificationId"] = str(request.clarification_id)
        if request.style_search and not legacy:
            if request.excluded_style:
                fields["excludedStyle"] = request.excluded_style.model_dump(
                    mode="json", by_alias=True
                )
            if request.previous_style_candidates:
                fields["hasPreviousStyleCandidates"] = True
            if request.previous_style_selection:
                fields["hasPreviousStyleSelection"] = True
            if request.style_compare:
                fields["styleCompare"] = True
        return _fingerprint(owner_id, "chat", fields)

    @staticmethod
    async def _result(
        repo: ConversationRepository, owner_id: str, conversation_id: UUID, turn
    ) -> ChatResponse:
        if not turn.response_message_id or turn.committed_version is None or not turn.turn_id:
            raise _unavailable()
        row = await repo.response_message(owner_id, conversation_id, turn.response_message_id)
        if row is None:
            raise _unavailable()
        payload = row.display_payload
        if "appliedMemories" in payload:
            memory_repo = MemoryRepository(repo.session)
            versions = {}
            if get_settings().g7_memory_enabled and await memory_repo.personalization_enabled(
                owner_id
            ):
                versions, _, _ = await memory_repo.memory_fence(owner_id)
            payload = visible_memory_evidence(payload, versions)
        try:
            response = restore_response(row.text, payload)
        except ValueError as exc:
            raise _unavailable() from exc
        response.conversation = ConversationMetadata(
            id=conversation_id,
            version=turn.committed_version,
            turn_id=turn.turn_id,
            persistence_status="stored",
        )
        response.memory_proposal = await replay_candidate(
            repo.session, owner_id, conversation_id, turn.request_id
        )
        return response

    async def answer(self, owner_id: str, principal_key: str, request: ChatRequest) -> ChatResponse:
        room_id, request_id, version = (
            request.conversation_id,
            request.request_id,
            request.expected_conversation_version,
        )
        if room_id is None or request_id is None or version is None:
            raise ApiError(400, "Invalid request", "invalid_request")
        fingerprint = self._request_fingerprint(owner_id, request)
        settings = get_settings()
        lease_seconds = max(20.0, settings.llm_timeout_seconds * 2)
        try:
            async with self._sessions().begin() as session:
                repo = ConversationRepository(session)
                if not await repo.ensure_active_owner(owner_id):
                    raise ApiError(403, "Account is unavailable", "account_unavailable")
                room = await repo.get(owner_id, room_id)
                if room is None:
                    raise ApiError(404, "Conversation not found", "not_found")
                await repo.expire_room_turns(owner_id, room_id)
                previous = await repo.get_creation(owner_id, request_id)
                if previous:
                    accepted_fingerprints = {fingerprint}
                    if previous.fingerprint_schema == 1:
                        accepted_fingerprints = {
                            self._request_fingerprint(owner_id, request, legacy=True),
                            self._request_fingerprint(
                                owner_id, request, legacy=True, legacy_without_clarification=True
                            ),
                        }
                    if (
                        previous.operation != "chat"
                        or previous.conversation_id != room_id
                        or previous.fingerprint not in accepted_fingerprints
                    ):
                        raise ApiError(409, "Request ID conflicts", "request_conflict")
                    if previous.status == "COMMITTED":
                        return await self._result(repo, owner_id, room_id, previous)
                    if previous.status == "IN_PROGRESS" and await repo.expire_turn(
                        owner_id, request_id
                    ):
                        # Commit interruption before asking for an explicit retry.
                        previous.status = "INTERRUPTED"
                    status = previous.status
                else:
                    status = None
                if status is None:
                    if room.conversation_version != version:
                        raise ApiError(409, "Conversation version changed", "conversation_conflict")
                    lease = datetime.now(UTC) + timedelta(seconds=lease_seconds)
                    if not await repo.reserve_turn(
                        owner_id, room_id, request_id, fingerprint, version, lease
                    ):
                        raise ApiError(409, "Conversation is busy", "conversation_busy")
                    messages = await repo.recent_messages(owner_id, room_id)
                    memory_repo = MemoryRepository(session)
                    memory_epoch = await memory_repo.owner_epoch(owner_id)
                    global_memory_enabled = settings.g7_memory_enabled
                    memory_enabled = (
                        global_memory_enabled
                        and await memory_repo.personalization_enabled(owner_id)
                    )
                    structured = (
                        memory_enabled
                        and request.structured_memory
                        and structured_memory_enabled()
                        and room.subject_json.get("type") == "general"
                        and request.request_type in {"chat", "beauty_consultation"}
                    )
                    memory_generation = await memory_repo.generation(owner_id, memory_enabled)
                    versions, removed_sources, cutoffs = await memory_repo.memory_fence(owner_id)
                    memory_opt_out = structured and ignores_memory(request.message)
                    if not memory_enabled or memory_opt_out:
                        versions = {}
                    raw_context = _safe_context(dict(room.context_json), memory_epoch, versions)
                    prepared = prepare_request(
                        request,
                        raw_context,
                        messages,
                        versions,
                        removed_sources,
                        cutoffs.get(str(room_id)),
                    )
                    memories = []
                    if structured:
                        prepared._consultation_memories = ()
                        if not memory_opt_out and not is_explicit_request(request.message):
                            try:
                                async with session.begin_nested():
                                    prepared._consultation_memories = select_consultation_memories(
                                        prepared, await memory_repo.consultation_rows(owner_id)
                                    )
                            except (SQLAlchemyError, OSError):
                                logger.warning("Consultation memory candidates are unavailable")
                    elif memory_enabled:
                        memories = (await memory_repo.list(owner_id))[:CONSULTATION_MEMORY_LIMIT]
                    prepared._consented_memories = [_item(item).value for item in memories]
                    prepared._memory_epoch = memory_epoch
                    prepared._memory_generation = memory_generation
                    memory_refs = [
                        {"memoryId": str(item.id), "version": item.version} for item in memories
                    ]
                    incoming_session = (
                        request.chat_context.session if request.chat_context else None
                    )
                    if (
                        incoming_session
                        and not memory_opt_out
                        and request.locale == "ko"
                        and request.request_type in {"chat", "beauty_consultation"}
                        and settings.g1_supervisor_enabled
                        and getattr(self.chat, "_sessions", None) is not None
                        and prepared.style_context is None
                    ):
                        if prepared.chat_context is None:
                            prepared.chat_context = BeautyContext(
                                issued_at=0, filters=BeautyFilters()
                            )
                        prepared.chat_context.session = incoming_session
                        prepared.clarification_id = request.clarification_id
                    execution = SimpleNamespace(
                        thread_id=room.thread_id,
                        conversation_id=room_id,
                        owner_id=owner_id,
                        request_id=request_id,
                        checkpoint_id=None,
                    )
                    prepared._g7_execution = execution
            if status is not None:
                raise ApiError(
                    409,
                    "Request is not available for automatic replay",
                    "request_in_progress" if status == "IN_PROGRESS" else "request_interrupted",
                )
        except (SQLAlchemyError, OSError, ValueError) as exc:
            raise _unavailable() from exc

        stop = asyncio.Event()
        heartbeat = asyncio.create_task(
            self._heartbeat(owner_id, room_id, request_id, 1, lease_seconds, stop)
        )
        try:
            await revalidate_request(self.chat, prepared)
            with capture_prompt_dependencies() as model_dependencies:
                response = await self.chat.answer(prepared, principal_key)
            if structured:
                selected_versions = {
                    entry.id: entry.version for entry in prepared._consultation_memories or ()
                }
                response.applied_memories = [
                    item
                    for item in response.applied_memories
                    if selected_versions.get(item.memory_id) == item.version
                ]
                dependencies = dict(model_dependencies)
                dependencies.update(
                    {str(item.memory_id): item.version for item in response.applied_memories}
                )
                memory_refs = [
                    {"memoryId": memory_id, "version": stamp}
                    for memory_id, stamp in dependencies.items()
                ]
            explicit_memory = structured and is_explicit_request(request.message)
            drafts = extract_values(request.message, request.locale) if explicit_memory else []
            previous_source = explicit_memory and refers_to_prior(request.message)
            catalog = getattr(self.chat, "_catalog", None)
            selected = prepared.chat_context.selected_product_id if prepared.chat_context else None
            if catalog and selected and any(draft.key == "inventory.product" for draft in drafts):
                try:
                    product = await catalog.get_product(selected)
                except UpstreamError:
                    product = None
                if product and product.id == selected:
                    drafts = [
                        with_verified_product(draft, product, request.locale)
                        if draft.key == "inventory.product"
                        else draft
                        for draft in drafts
                    ]
            if structured:
                if explicit_memory:
                    response.answer = _STRUCTURED_MEMORY_REPLY[request.locale]
            elif memory_enabled and (
                prompt := memory_request_prompt(request.message, request.locale)
            ):
                response.answer = prompt
            context = updated_context(raw_context, response)
            prior_refs = context.get("memoryRefs", [])
            combined = {
                (ref["memoryId"], ref["version"]): ref for ref in [*prior_refs, *memory_refs]
            }
            if len(combined) > 100:
                context = {"schemaVersion": 1, "memoryRevocationEpoch": memory_epoch}
                combined = {(ref["memoryId"], ref["version"]): ref for ref in memory_refs}
            context["memoryRevocationEpoch"] = memory_epoch
            context["memoryRefs"] = list(combined.values())
            display = display_payload(response)
            # Ensure the stored, token-free reply can be replayed before committing it.
            restore_response(response.answer, display)
            turn_id = uuid4()
            async with self._sessions().begin() as session:
                repo = ConversationRepository(session)
                if get_settings().g7_memory_enabled != global_memory_enabled:
                    raise ApiError(409, "Memory context changed", "request_interrupted")
                written = await repo.finish_reply(
                    owner_id,
                    room_id,
                    request_id,
                    turn_id,
                    1,
                    version,
                    context,
                    request.message,
                    response.answer,
                    display,
                    execution.checkpoint_id,
                    memory_epoch,
                    memory_refs,
                    memory_generation,
                    memory_enabled,
                )
                if not written:
                    raise ApiError(409, "Request was interrupted", "request_interrupted")
                if structured:
                    if structured_memory_enabled() and (drafts or previous_source):
                        try:
                            async with session.begin_nested():
                                await issue_group(
                                    session,
                                    owner_id,
                                    room_id,
                                    request_id,
                                    request.locale,
                                    drafts,
                                    previous_source,
                                )
                        except (SQLAlchemyError, ValueError):
                            # A proposal failure leaves the completed consultation intact.
                            logger.warning("Structured memory proposal could not be issued")
                elif memory_enabled:
                    response.memory_proposal = await create_candidate(
                        session, owner_id, room_id, request_id, memory_epoch, request.message
                    )
            response.conversation = ConversationMetadata(
                id=room_id, version=version + 1, turn_id=turn_id, persistence_status="stored"
            )
            return response
        except asyncio.CancelledError:
            await asyncio.shield(self._interrupt(owner_id, request_id, 1))
            raise
        except Exception as exc:
            await self._interrupt(owner_id, request_id, 1)
            if isinstance(exc, ApiError):
                raise
            raise _unavailable() from exc
        finally:
            stop.set()
            await heartbeat

    async def _interrupt(self, owner_id: str, request_id: UUID, attempt: int) -> None:
        try:
            async with self._sessions().begin() as session:
                await ConversationRepository(session).interrupt_turn(owner_id, request_id, attempt)
        except (SQLAlchemyError, OSError, ApiError):
            # Lease expiry still makes an unconfirmed execution non-replayable.
            pass

    async def _heartbeat(
        self,
        owner_id: str,
        room_id: UUID,
        request_id: UUID,
        attempt: int,
        lease_seconds: float,
        stop: asyncio.Event,
    ) -> None:
        while not stop.is_set():
            try:
                await asyncio.wait_for(stop.wait(), timeout=lease_seconds / 3)
                return
            except TimeoutError:
                pass
            try:
                async with self._sessions().begin() as session:
                    ok = await ConversationRepository(session).renew_turn(
                        owner_id,
                        room_id,
                        request_id,
                        attempt,
                        datetime.now(UTC) + timedelta(seconds=lease_seconds),
                    )
                if not ok:
                    return
            except (SQLAlchemyError, OSError, ApiError):
                return

    async def request_status(self, owner_id: str, conversation_id: UUID, request_id: UUID) -> dict:
        try:
            async with self._sessions().begin() as session:
                repo = ConversationRepository(session)
                if not await repo.ensure_active_owner(owner_id):
                    raise ApiError(403, "Account is unavailable", "account_unavailable")
                if not await repo.get(owner_id, conversation_id):
                    raise ApiError(404, "Conversation not found", "not_found")
                turn = await repo.get_turn(owner_id, request_id)
                if not turn or turn.conversation_id != conversation_id:
                    raise ApiError(404, "Request not found", "not_found")
                if turn.status == "IN_PROGRESS" and await repo.expire_turn(owner_id, request_id):
                    turn.status = "INTERRUPTED"
                result = {"requestId": str(request_id), "status": turn.status}
                if turn.status == "COMMITTED":
                    if turn.operation == "state_update":
                        result["response"] = await self._checked_state_result(
                            session, owner_id, conversation_id, turn
                        )
                    else:
                        response = await self._result(repo, owner_id, conversation_id, turn)
                        result["response"] = response.model_dump(
                            mode="json", by_alias=True, exclude_none=True
                        )
                return result
        except (SQLAlchemyError, OSError) as exc:
            raise _unavailable() from exc

    @staticmethod
    def _state_result(conversation_id: UUID, turn) -> dict:
        payload = turn.result_payload
        if (
            not isinstance(payload, dict)
            or set(payload) != {"conversationId", "conversationVersion", "context"}
            or payload["conversationId"] != str(conversation_id)
            or type(payload["conversationVersion"]) is not int
            or payload["conversationVersion"] != turn.committed_version
            or turn.result_resource_id != conversation_id
            or turn.result_version != turn.committed_version
        ):
            raise _unavailable()
        try:
            read_context(payload["context"])
        except (ValueError, TypeError) as exc:
            raise _unavailable() from exc
        return payload

    async def _checked_state_result(self, session, owner_id, conversation_id, turn) -> dict:
        payload = self._state_result(conversation_id, turn)
        repo = MemoryRepository(session)
        epoch = await repo.owner_epoch(owner_id)
        versions, _, _ = await repo.memory_fence(owner_id)
        if not get_settings().g7_memory_enabled or not await repo.personalization_enabled(owner_id):
            versions = {}
        if _safe_context(payload["context"], epoch, versions) != payload["context"]:
            raise ApiError(409, "Memory context changed", "memory_context_changed")
        return payload

    async def update_state(
        self, owner_id: str, conversation_id: UUID, body: UpdateConversationStateRequest
    ) -> dict:
        fingerprint = _fingerprint(
            owner_id,
            "state_update",
            {
                "conversationId": str(conversation_id),
                "expectedConversationVersion": body.expected_conversation_version,
                "operation": body.operation,
                "payload": body.payload,
            },
        )
        lease_seconds = max(20.0, get_settings().llm_timeout_seconds * 2)
        try:
            async with self._sessions().begin() as session:
                repo = ConversationRepository(session)
                if not await repo.ensure_active_owner(owner_id):
                    raise ApiError(403, "Account is unavailable", "account_unavailable")
                room = await repo.get(owner_id, conversation_id)
                if room is None:
                    raise ApiError(404, "Conversation not found", "not_found")
                await repo.expire_room_turns(owner_id, conversation_id)
                previous = await repo.get_creation(owner_id, body.request_id)
                if previous:
                    if (
                        previous.operation != "state_update"
                        or previous.conversation_id != conversation_id
                        or previous.fingerprint != fingerprint
                    ):
                        raise ApiError(409, "Request ID conflicts", "request_conflict")
                    if previous.status == "COMMITTED":
                        return await self._checked_state_result(
                            session, owner_id, conversation_id, previous
                        )
                    status = previous.status
                else:
                    status = None
                if status is None:
                    if room.conversation_version != body.expected_conversation_version:
                        raise ApiError(409, "Conversation version changed", "conversation_conflict")
                    if body.expected_conversation_version >= 2**53 - 1:
                        raise ApiError(
                            409, "Conversation version exhausted", "conversation_conflict"
                        )
                    lease = datetime.now(UTC) + timedelta(seconds=lease_seconds)
                    reserved = await repo.reserve_turn(
                        owner_id,
                        conversation_id,
                        body.request_id,
                        fingerprint,
                        body.expected_conversation_version,
                        lease,
                        operation="state_update",
                    )
                    if not reserved:
                        raise ApiError(409, "Conversation is busy", "conversation_busy")
                    memory_repo = MemoryRepository(session)
                    memory_epoch = await memory_repo.owner_epoch(owner_id)
                    global_memory_enabled = get_settings().g7_memory_enabled
                    memory_enabled = (
                        global_memory_enabled
                        and await memory_repo.personalization_enabled(owner_id)
                    )
                    memory_generation = await memory_repo.generation(owner_id, memory_enabled)
                    versions, _, _ = await memory_repo.memory_fence(owner_id)
                    if not memory_enabled:
                        versions = {}
                    raw_context = _safe_context(dict(room.context_json), memory_epoch, versions)
                    subject = dict(room.subject_json)
            if status is not None:
                code = {"IN_PROGRESS": "request_in_progress", "FAILED": "request_failed"}.get(
                    status, "request_interrupted"
                )
                raise ApiError(409, "Request is not available for automatic replay", code)
        except (SQLAlchemyError, OSError, ValueError) as exc:
            raise _unavailable() from exc

        stop = asyncio.Event()
        heartbeat = asyncio.create_task(
            self._heartbeat(owner_id, conversation_id, body.request_id, 1, lease_seconds, stop)
        )
        try:
            context = await apply_state_update(raw_context, subject, body, self.chat)
            async with self._sessions().begin() as session:
                if get_settings().g7_memory_enabled != global_memory_enabled:
                    raise ApiError(409, "Memory context changed", "request_interrupted")
                snapshot = await ConversationRepository(session).finish_state_update(
                    owner_id,
                    conversation_id,
                    body.request_id,
                    1,
                    body.expected_conversation_version,
                    context,
                    memory_epoch,
                    memory_generation,
                    memory_enabled,
                )
                if snapshot is None:
                    raise ApiError(409, "Request was interrupted", "request_interrupted")
            return snapshot
        except asyncio.CancelledError:
            await asyncio.shield(self._interrupt(owner_id, body.request_id, 1))
            raise
        except ApiError as exc:
            if exc.code == "request_interrupted":
                await self._interrupt(owner_id, body.request_id, 1)
            else:
                await self._fail(owner_id, body.request_id, 1, exc.code or "state_update_failed")
            raise
        except Exception as exc:
            await self._interrupt(owner_id, body.request_id, 1)
            raise _unavailable() from exc
        finally:
            stop.set()
            await heartbeat

    async def _fail(self, owner_id: str, request_id: UUID, attempt: int, code: str) -> None:
        try:
            async with self._sessions().begin() as session:
                await ConversationRepository(session).fail_turn(owner_id, request_id, attempt, code)
        except (SQLAlchemyError, OSError, ApiError):
            pass

    async def delete(self, owner_id: str, conversation_id: UUID) -> None:
        try:
            async with self._sessions().begin() as session:
                repo = ConversationRepository(session)
                if not await repo.ensure_active_owner(owner_id):
                    raise ApiError(403, "Account is unavailable", "account_unavailable")
                room = await repo.get(owner_id, conversation_id)
                if room:
                    thread_id = room.thread_id
                    await repo.mark_deleted(owner_id, conversation_id)
                else:
                    thread_id = await repo.deleting_thread(owner_id, conversation_id)
                if thread_id is None:
                    if await repo.room_deletion_completed(owner_id, conversation_id):
                        return
                    raise ApiError(404, "Conversation not found", "not_found")
                request_ids = await repo.room_chat_request_ids(owner_id, conversation_id)
            try:
                await CheckpointRepository(get_settings().chat_database_url).delete_thread(
                    thread_id
                )
                if request_ids:
                    sessions = getattr(self.chat, "_sessions", None) or get_chat_sessions()
                    await sessions.delete_room(owner_id, conversation_id, request_ids)
            except Exception as exc:
                raise ApiError(
                    503, "Conversation deletion is incomplete", "deletion_incomplete"
                ) from exc
            async with self._sessions().begin() as session:
                repo = ConversationRepository(session)
                if not await repo.purge_deleted(
                    owner_id, conversation_id
                ) and not await repo.room_deletion_completed(owner_id, conversation_id):
                    raise ApiError(
                        503, "Conversation deletion is incomplete", "deletion_incomplete"
                    )
        except (SQLAlchemyError, OSError) as exc:
            raise _unavailable() from exc

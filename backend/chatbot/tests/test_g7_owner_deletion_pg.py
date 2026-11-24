import asyncio
import os
from datetime import UTC, datetime, timedelta
from typing import TypedDict
from urllib.parse import urlparse
from uuid import UUID, uuid4

import httpx
import psycopg
import pytest
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from langgraph.graph import END, START, StateGraph
from redis.asyncio import Redis as AsyncRedis
from redis.exceptions import RedisError
from sqlalchemy import delete, func, select, update
from sqlalchemy.engine import make_url

from app.core import auth
from app.core.config import get_settings
from app.core.db import dispose_chat_engine, get_chat_engine, get_chat_sessionmaker
from app.core.errors import ApiError
from app.core.ratelimit import MemoryRateLimiter, get_rate_limiter
from app.main import create_app
from app.models.conversation import (
    ChatConversation,
    ChatMemory,
    ChatMemoryProposal,
    ChatMessage,
    ChatOwnerStatus,
    ChatTurn,
)
from app.repositories.chat_session_repository import ChatSessionRepository
from app.repositories.checkpoint_repository import CheckpointRepository
from app.repositories.conversation_repository import ConversationRepository
from app.repositories.memory_repository import MemoryRepository
from app.repositories.owner_deletion_repository import OwnerDeletionRepository, legacy_owner_access
from app.schemas.chat import ChatResponse
from app.services.chat_service import ChatService, get_chat_service
from app.services.owner_deletion_service import OwnerDeletionService
from tests.conftest import FakeVerifier
from tests.test_beauty_consultation import PlanLlm
from tests.test_chat_sessions import SessionCatalog

URL = os.environ.get("TEST_CHAT_DATABASE_URL")
REDIS_URL = os.environ.get("TEST_CHAT_REDIS_URL")
pytestmark = [
    pytest.mark.integration,
    pytest.mark.anyio,
    pytest.mark.skipif(not URL, reason="TEST_CHAT_DATABASE_URL not set"),
]


@pytest.fixture
def anyio_backend():
    if os.name == "nt":
        return "asyncio", {"loop_factory": asyncio.SelectorEventLoop}
    return "asyncio"


@pytest.fixture
async def setup(monkeypatch):
    url = make_url(URL)
    if (
        url.database != "vishue_chat_test"
        or url.host not in {"127.0.0.1", "localhost", "::1"}
        or os.environ.get("G7_ALLOW_DESTRUCTIVE_TESTS") != "1"
    ):
        raise RuntimeError("G7 deletion tests require an authorized disposable local database")
    settings = get_settings()
    monkeypatch.setattr(settings, "env", "local")
    monkeypatch.setattr(settings, "g7_persistence_enabled", True)
    monkeypatch.setattr(settings, "g7_memory_enabled", True)
    monkeypatch.setattr(settings, "g7_owner_deletion_guard_enabled", False)
    monkeypatch.setattr(settings, "chat_database_url", URL)
    monkeypatch.setattr(auth, "get_verifier", lambda: FakeVerifier())
    if REDIS_URL:
        if urlparse(REDIS_URL).hostname not in {"127.0.0.1", "localhost", "::1"}:
            raise RuntimeError("G7 deletion tests require a disposable local Redis")
        redis = AsyncRedis.from_url(REDIS_URL, decode_responses=True)
    else:

        class EmptyRedis:
            async def scan_iter(self, **kwargs):
                for key in ():
                    yield key

        redis = EmptyRedis()
    monkeypatch.setattr(
        "app.services.owner_deletion_service.get_chat_sessions",
        lambda: ChatSessionRepository(redis),
    )
    await dispose_chat_engine()
    get_chat_engine.cache_clear()
    try:
        yield
    finally:
        await dispose_chat_engine()
        if REDIS_URL:
            await redis.aclose()


class CheckpointState(TypedDict):
    result_ref: str


async def write_checkpoint(thread_id):
    dsn = make_url(URL).set(drivername="postgresql").render_as_string(hide_password=False)
    async with AsyncPostgresSaver.from_conn_string(dsn) as saver:
        await saver.setup()
        graph = StateGraph(CheckpointState)
        graph.add_node("finish", lambda state: {"result_ref": state["result_ref"]})
        graph.add_edge(START, "finish")
        graph.add_edge("finish", END)
        await graph.compile(checkpointer=saver).ainvoke(
            {"result_ref": "private-test-value"},
            {"configurable": {"thread_id": str(thread_id)}},
        )


async def checkpoint_exists(thread_id):
    dsn = make_url(URL).set(drivername="postgresql").render_as_string(hide_password=False)
    async with AsyncPostgresSaver.from_conn_string(dsn) as saver:
        return await saver.aget_tuple({"configurable": {"thread_id": str(thread_id)}}) is not None


async def seed_owner(owner, *, deleted_room=False):
    room_id, thread_id, message_id, memory_id = uuid4(), uuid4(), uuid4(), uuid4()
    async with get_chat_sessionmaker().begin() as session:
        repo = ConversationRepository(session)
        room = await repo.create(owner, room_id, thread_id, {"type": "general"})
        assert room is not None
        assert await repo.add_message(
            owner,
            room_id,
            ChatMessage(
                id=message_id,
                conversation_id=room_id,
                sequence=1,
                role="user",
                text="private-test-message",
                display_payload={},
            ),
        )
        assert await MemoryRepository(session).create(
            owner,
            memory_id,
            "preference",
            f"lip-{room_id}",
            {"text": "private-test-memory"},
            "future_consultations",
            datetime.now(UTC),
            message_id,
        )
        session.add(
            ChatMemoryProposal(
                id=uuid4(),
                owner_id=owner,
                conversation_id=room_id,
                source_message_id=message_id,
                kind="preference",
                memory_key=f"lip-{room_id}",
                revocation_epoch=0,
                memory_generation="test-generation",
                expires_at=datetime.now(UTC) + timedelta(minutes=15),
            )
        )
        session.add(
            ChatTurn(
                owner_id=owner,
                request_id=uuid4(),
                operation="memory_create",
                fingerprint="0" * 64,
                status="COMMITTED",
                result_resource_id=memory_id,
            )
        )
        if deleted_room:
            await session.execute(
                update(ChatConversation)
                .where(ChatConversation.id == room_id)
                .values(deleted_at=datetime.now(UTC))
            )
    await write_checkpoint(thread_id)
    return room_id, thread_id, message_id, memory_id


async def count_owner(session, model, owner):
    return await session.scalar(
        select(func.count()).select_from(model).where(model.owner_id == owner)
    )


async def test_deletes_all_owner_data_and_checkpoints_without_touching_other_owner(setup):
    owner, other = str(uuid4()), str(uuid4())
    room, thread, message, memory = await seed_owner(owner)
    deleted_room, deleted_thread, _, _ = await seed_owner(owner, deleted_room=True)
    other_room, other_thread, other_message, other_memory = await seed_owner(other)
    assert await checkpoint_exists(thread) and await checkpoint_exists(deleted_thread)

    service = OwnerDeletionService()
    await service.delete(owner)
    await service.delete(owner)

    async with get_chat_sessionmaker()() as session:
        tombstone = await session.get(ChatOwnerStatus, owner)
        assert tombstone.status == "DELETED" and tombstone.revocation_epoch == 1
        for model in (ChatConversation, ChatTurn, ChatMemory, ChatMemoryProposal):
            assert await count_owner(session, model, owner) == 0
        assert await session.get(ChatMessage, message) is None
        assert await session.get(ChatMemory, memory) is None
        assert await session.get(ChatConversation, room) is None
        assert await session.get(ChatConversation, deleted_room) is None
        assert await session.get(ChatConversation, other_room) is not None
        assert await session.get(ChatMessage, other_message) is not None
        assert await session.get(ChatMemory, other_memory) is not None
        assert await count_owner(session, ChatTurn, other) == 1
        assert await count_owner(session, ChatMemoryProposal, other) == 1
    assert not await checkpoint_exists(thread)
    assert not await checkpoint_exists(deleted_thread)
    assert await checkpoint_exists(other_thread)

    async with get_chat_sessionmaker().begin() as session:
        repo = ConversationRepository(session)
        assert not await repo.ensure_active_owner(owner)
        assert await repo.create(owner, uuid4(), uuid4(), {"type": "general"}) is None


async def test_checkpoint_failure_keeps_owner_blocked_and_retries_safely(setup, monkeypatch):
    token = "ok-" + uuid4().hex
    owner = "user-" + token
    room, thread, _, _ = await seed_owner(owner)
    _, another_thread, _, _ = await seed_owner(owner)
    original = CheckpointRepository.delete_thread
    calls = 0

    async def fail_second(self, thread_id):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise OSError("synthetic checkpoint failure")
        await original(self, thread_id)

    monkeypatch.setattr(CheckpointRepository, "delete_thread", fail_second)
    with pytest.raises(ApiError) as error:
        await OwnerDeletionService().delete(owner)
    assert (error.value.status, error.value.code) == (503, "account_deletion_incomplete")
    async with get_chat_sessionmaker()() as session:
        assert (await session.get(ChatOwnerStatus, owner)).status == "DELETING"
        assert await count_owner(session, ChatConversation, owner) == 2
        assert await count_owner(session, ChatMemory, owner) == 2
    assert sum([await checkpoint_exists(thread), await checkpoint_exists(another_thread)]) == 1

    app = create_app()
    app.dependency_overrides[get_rate_limiter] = lambda: MemoryRateLimiter(limit=100)
    app.dependency_overrides[get_chat_service] = lambda: FakeLegacyChat()
    headers = {"Authorization": f"Bearer {token}"}
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.post(
            "/api/chat/conversations",
            headers=headers,
            json={"requestId": str(uuid4()), "entry": {"type": "general"}},
        )
        assert (response.status_code, response.json()["code"]) == (403, "account_unavailable")
        response = await client.get("/api/chat/memories", headers=headers)
        assert (response.status_code, response.json()["code"]) == (403, "account_unavailable")
        response = await client.post("/api/chat", headers=headers, json={"message": "test"})
        assert (response.status_code, response.json()["code"]) == (403, "account_unavailable")
        response = await client.post("/api/chat/acks", headers=headers, json=ack_body())
        assert (response.status_code, response.json()["code"]) == (403, "account_unavailable")
        response = await client.post(
            "/api/chat",
            headers=headers,
            json={
                "message": "test",
                "conversationId": str(room),
                "requestId": str(uuid4()),
                "expectedConversationVersion": 0,
            },
        )
        assert (response.status_code, response.json()["code"]) == (403, "account_unavailable")

    monkeypatch.setattr(CheckpointRepository, "delete_thread", original)
    await OwnerDeletionService().delete(owner)
    assert not await checkpoint_exists(thread) and not await checkpoint_exists(another_thread)
    async with get_chat_sessionmaker()() as session:
        assert (await session.get(ChatOwnerStatus, owner)).status == "DELETED"
        assert await count_owner(session, ChatConversation, owner) == 0
        assert await count_owner(session, ChatMemory, owner) == 0
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.post(
            "/api/chat/conversations",
            headers=headers,
            json={"requestId": str(uuid4()), "entry": {"type": "general"}},
        )
        assert (response.status_code, response.json()["code"]) == (403, "account_unavailable")
        response = await client.get("/api/chat/memories", headers=headers)
        assert (response.status_code, response.json()["code"]) == (403, "account_unavailable")


async def test_inflight_turn_cannot_commit_after_owner_is_blocked(setup, monkeypatch):
    owner = str(uuid4())
    room, thread, _, _ = await seed_owner(owner)
    request_id = uuid4()
    async with get_chat_sessionmaker().begin() as session:
        assert await ConversationRepository(session).reserve_turn(
            owner,
            room,
            request_id,
            "1" * 64,
            0,
            datetime.now(UTC) + timedelta(minutes=2),
        )
    started, release = asyncio.Event(), asyncio.Event()
    original = CheckpointRepository.delete_thread

    async def wait_before_checkpoint_delete(self, thread_id):
        started.set()
        await release.wait()
        await original(self, thread_id)

    monkeypatch.setattr(CheckpointRepository, "delete_thread", wait_before_checkpoint_delete)
    task = asyncio.create_task(OwnerDeletionService().delete(owner))
    try:
        await asyncio.wait_for(started.wait(), timeout=10)
        async with get_chat_sessionmaker().begin() as session:
            assert (await session.get(ChatOwnerStatus, owner)).status == "DELETING"
            committed = await ConversationRepository(session).finish_reply(
                owner, room, request_id, uuid4(), 1, 0, {}, "late question", "late answer", {}
            )
            assert not committed
    finally:
        release.set()
        await task
    assert not await checkpoint_exists(thread)
    async with get_chat_sessionmaker()() as session:
        assert (await session.get(ChatOwnerStatus, owner)).status == "DELETED"
        assert await count_owner(session, ChatConversation, owner) == 0


async def test_unknown_owner_is_blocked_idempotently(setup):
    owner = str(uuid4())
    service = OwnerDeletionService()
    await service.delete(owner)
    await service.delete(owner)
    async with get_chat_sessionmaker().begin() as session:
        assert (await session.get(ChatOwnerStatus, owner)).status == "DELETED"
        assert not await ConversationRepository(session).ensure_active_owner(owner)


async def test_service_remains_closed_when_feature_or_environment_is_disabled(setup, monkeypatch):
    owner = str(uuid4())
    settings = get_settings()
    service = OwnerDeletionService()
    monkeypatch.setattr(settings, "g7_persistence_enabled", False)
    with pytest.raises(ApiError) as disabled:
        await service.delete(owner)
    assert (disabled.value.status, disabled.value.code) == (503, "persistence_disabled")
    monkeypatch.setattr(settings, "g7_persistence_enabled", True)
    monkeypatch.setattr(settings, "env", "production")
    with pytest.raises(ApiError) as production:
        await service.delete(owner)
    assert (production.value.status, production.value.code) == (503, "persistence_unavailable")
    async with get_chat_sessionmaker()() as session:
        assert await session.get(ChatOwnerStatus, owner) is None


async def test_checkpoint_failure_can_resume_with_persistence_off(setup, monkeypatch):
    owner, other = str(uuid4()), str(uuid4())
    room, thread, message, memory = await seed_owner(owner)
    other_room, other_thread, _, _ = await seed_owner(other)
    original = CheckpointRepository.delete_thread

    async def unavailable(self, thread_id):
        raise OSError("synthetic checkpoint failure")

    monkeypatch.setattr(CheckpointRepository, "delete_thread", unavailable)
    with pytest.raises(ApiError) as error:
        await OwnerDeletionService().delete(owner)
    assert (error.value.status, error.value.code) == (503, "account_deletion_incomplete")
    async with get_chat_sessionmaker()() as session:
        assert (await session.get(ChatOwnerStatus, owner)).status == "DELETING"
        assert await session.get(ChatConversation, room) is not None
    assert await checkpoint_exists(thread)

    monkeypatch.setattr(CheckpointRepository, "delete_thread", original)
    monkeypatch.setattr(get_settings(), "g7_owner_deletion_guard_enabled", True)
    monkeypatch.setattr(get_settings(), "g7_persistence_enabled", False)
    await OwnerDeletionService().delete(owner)
    await OwnerDeletionService().delete(owner)
    async with get_chat_sessionmaker()() as session:
        assert (await session.get(ChatOwnerStatus, owner)).status == "DELETED"
        assert await session.get(ChatConversation, room) is None
        assert await session.get(ChatMessage, message) is None
        assert await session.get(ChatMemory, memory) is None
        assert await session.get(ChatConversation, other_room) is not None
    assert not await checkpoint_exists(thread)
    assert await checkpoint_exists(other_thread)


async def test_persistence_off_cannot_start_new_deletions(setup, monkeypatch):
    active, unknown = str(uuid4()), str(uuid4())
    room, thread, _, _ = await seed_owner(active)
    monkeypatch.setattr(get_settings(), "g7_owner_deletion_guard_enabled", True)
    monkeypatch.setattr(get_settings(), "g7_persistence_enabled", False)
    for owner in (active, unknown):
        with pytest.raises(ApiError) as error:
            await OwnerDeletionService().delete(owner)
        assert (error.value.status, error.value.code) == (503, "persistence_disabled")
    async with get_chat_sessionmaker()() as session:
        assert (await session.get(ChatOwnerStatus, active)).status == "ACTIVE"
        assert await session.get(ChatOwnerStatus, unknown) is None
        assert await session.get(ChatConversation, room) is not None
    assert await checkpoint_exists(thread)


async def test_persistence_off_retry_requires_guard_and_available_local_database(
    setup, monkeypatch
):
    owner = str(uuid4())
    async with get_chat_sessionmaker().begin() as session:
        assert await OwnerDeletionRepository(session).block(owner)
    settings = get_settings()
    monkeypatch.setattr(settings, "g7_persistence_enabled", False)
    with pytest.raises(ApiError) as disabled:
        await OwnerDeletionService().delete(owner)
    assert (disabled.value.status, disabled.value.code) == (503, "persistence_disabled")

    monkeypatch.setattr(settings, "g7_owner_deletion_guard_enabled", True)
    monkeypatch.setattr(settings, "env", "production")
    with pytest.raises(ApiError) as production:
        await OwnerDeletionService().delete(owner)
    assert (production.value.status, production.value.code) == (503, "persistence_unavailable")
    monkeypatch.setattr(settings, "env", "local")
    monkeypatch.setattr(settings, "chat_database_url", None)
    with pytest.raises(ApiError) as missing:
        await OwnerDeletionService().delete(owner)
    assert (missing.value.status, missing.value.code) == (503, "persistence_unavailable")

    monkeypatch.setattr(settings, "chat_database_url", URL)

    def unavailable():
        raise OSError("synthetic database outage")

    with monkeypatch.context() as context:
        context.setattr("app.services.owner_deletion_service.get_chat_sessionmaker", unavailable)
        with pytest.raises(ApiError) as outage:
            await OwnerDeletionService().delete(owner)
    assert (outage.value.status, outage.value.code) == (503, "account_deletion_incomplete")
    async with get_chat_sessionmaker()() as session:
        assert (await session.get(ChatOwnerStatus, owner)).status == "DELETING"


async def test_concurrent_retries_of_blocked_owner_are_idempotent(setup, monkeypatch):
    owner = str(uuid4())
    async with get_chat_sessionmaker().begin() as session:
        assert await OwnerDeletionRepository(session).block(owner)
    monkeypatch.setattr(get_settings(), "g7_owner_deletion_guard_enabled", True)
    monkeypatch.setattr(get_settings(), "g7_persistence_enabled", False)
    await asyncio.gather(OwnerDeletionService().delete(owner), OwnerDeletionService().delete(owner))
    async with get_chat_sessionmaker()() as session:
        assert (await session.get(ChatOwnerStatus, owner)).status == "DELETED"


async def test_busy_checkpoint_lock_blocks_completion_until_retry(setup):
    owner = str(uuid4())
    room, thread, _, _ = await seed_owner(owner)
    dsn = make_url(URL).set(drivername="postgresql").render_as_string(hide_password=False)
    async with await psycopg.AsyncConnection.connect(dsn, autocommit=True) as conn:
        await conn.execute(
            "SELECT pg_advisory_lock(hashtextextended(%s, 0))", (f"g7:checkpoint:{thread}",)
        )
        with pytest.raises(ApiError) as error:
            await OwnerDeletionService().delete(owner)
        assert (error.value.status, error.value.code) == (503, "account_deletion_incomplete")
        async with get_chat_sessionmaker()() as session:
            assert (await session.get(ChatOwnerStatus, owner)).status == "DELETING"
            assert await session.get(ChatConversation, room) is not None
        assert await checkpoint_exists(thread)
        await conn.execute(
            "SELECT pg_advisory_unlock(hashtextextended(%s, 0))", (f"g7:checkpoint:{thread}",)
        )
    await OwnerDeletionService().delete(owner)
    assert not await checkpoint_exists(thread)
    async with get_chat_sessionmaker()() as session:
        assert (await session.get(ChatOwnerStatus, owner)).status == "DELETED"
        assert await session.get(ChatConversation, room) is None


async def test_database_failure_rolls_back_purge_and_remains_retryable(setup, monkeypatch):
    owner = str(uuid4())
    room, thread, _, memory_id = await seed_owner(owner)
    original = OwnerDeletionRepository.purge

    async def fail_mid_purge(self, owner_id):
        await self.session.execute(delete(ChatMemory).where(ChatMemory.owner_id == owner_id))
        raise OSError("synthetic database failure")

    monkeypatch.setattr(OwnerDeletionRepository, "purge", fail_mid_purge)
    with pytest.raises(ApiError) as error:
        await OwnerDeletionService().delete(owner)
    assert (error.value.status, error.value.code) == (503, "account_deletion_incomplete")
    assert not await checkpoint_exists(thread)
    async with get_chat_sessionmaker()() as session:
        assert (await session.get(ChatOwnerStatus, owner)).status == "DELETING"
        assert await session.get(ChatConversation, room) is not None
        assert await session.get(ChatMemory, memory_id) is not None
    monkeypatch.setattr(OwnerDeletionRepository, "purge", original)
    await OwnerDeletionService().delete(owner)
    async with get_chat_sessionmaker()() as session:
        assert (await session.get(ChatOwnerStatus, owner)).status == "DELETED"
        assert await session.get(ChatConversation, room) is None
        assert await session.get(ChatMemory, memory_id) is None


class FakeLegacyChat:
    def __init__(self):
        self.calls = 0
        self.acks = 0

    async def answer(self, request, principal_key):
        self.calls += 1
        return ChatResponse(answer="synthetic", products=[])

    def acknowledge_ar(self, principal_key, body):
        self.acks += 1


def legacy_app(chat):
    app = create_app()
    app.dependency_overrides[get_chat_service] = lambda: chat
    app.dependency_overrides[get_rate_limiter] = lambda: MemoryRateLimiter(limit=100)
    return app


def ack_body():
    return {
        "requestId": str(uuid4()),
        "commandId": str(uuid4()),
        "sessionId": str(uuid4()),
        "status": "APPLIED",
    }


@pytest.mark.parametrize("persistence_enabled", [True, False])
async def test_deleted_legacy_user_and_ack_are_blocked_but_guest_and_other_user_work(
    setup, monkeypatch, persistence_enabled
):
    token = "ok-" + uuid4().hex
    owner = "user-" + token
    await OwnerDeletionService().delete(owner)
    monkeypatch.setattr(get_settings(), "g7_owner_deletion_guard_enabled", not persistence_enabled)
    monkeypatch.setattr(get_settings(), "g7_persistence_enabled", persistence_enabled)
    other_token = "ok-" + uuid4().hex
    other_owner = "user-" + other_token
    chat = FakeLegacyChat()
    app = legacy_app(chat)

    class CountingLimiter(MemoryRateLimiter):
        def __init__(self):
            super().__init__(limit=100)
            self.keys = []

        async def allow(self, key):
            self.keys.append(key)
            return await super().allow(key)

    limiter = CountingLimiter()
    app.dependency_overrides[get_rate_limiter] = lambda: limiter
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        old = {"Authorization": f"Bearer {token}"}
        legacy = await client.post("/api/chat", headers=old, json={"message": "synthetic"})
        assert (legacy.status_code, legacy.json()["code"]) == (403, "account_unavailable")
        ack = await client.post("/api/chat/acks", headers=old, json=ack_body())
        assert (ack.status_code, ack.json()["code"]) == (403, "account_unavailable")
        other = await client.post(
            "/api/chat",
            headers={"Authorization": f"Bearer {other_token}"},
            json={"message": "synthetic"},
        )
        guest_headers = {"X-Vishue-Anonymous-Id": uuid4().hex}
        guest = await client.post("/api/chat", headers=guest_headers, json={"message": "synthetic"})
        assert other.status_code == 200 and guest.status_code == 200
        assert chat.calls == 2 and chat.acks == 0
        other_ack = await client.post(
            "/api/chat/acks", headers={"Authorization": f"Bearer {other_token}"}, json=ack_body()
        )
        guest_ack = await client.post("/api/chat/acks", headers=guest_headers, json=ack_body())
        assert other_ack.status_code == guest_ack.status_code == 200 and chat.acks == 2
        assert "user:" + owner not in limiter.keys
    async with get_chat_sessionmaker()() as session:
        assert await session.get(ChatOwnerStatus, other_owner) is None


async def test_disabled_flag_keeps_legacy_and_guest_paths_database_independent(setup, monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "g7_persistence_enabled", False)

    def unavailable():
        raise AssertionError("G7 database should not be queried")

    monkeypatch.setattr(
        "app.repositories.owner_deletion_repository.get_chat_sessionmaker", unavailable
    )
    app = legacy_app(FakeLegacyChat())
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        user = await client.post(
            "/api/chat",
            headers={"Authorization": "Bearer ok-normal"},
            json={"message": "synthetic"},
        )
        guest = await client.post(
            "/api/chat",
            headers={"X-Vishue-Anonymous-Id": uuid4().hex},
            json={"message": "synthetic"},
        )
        ack = await client.post(
            "/api/chat/acks", headers={"Authorization": "Bearer ok-normal"}, json=ack_body()
        )
        assert user.status_code == guest.status_code == ack.status_code == 200


async def test_enabled_guard_fails_closed_when_database_is_unavailable(setup, monkeypatch):
    monkeypatch.setattr(get_settings(), "chat_database_url", None)
    chat = FakeLegacyChat()
    app = legacy_app(chat)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        user = await client.post(
            "/api/chat",
            headers={"Authorization": "Bearer ok-normal"},
            json={"message": "synthetic"},
        )
        guest = await client.post(
            "/api/chat",
            headers={"X-Vishue-Anonymous-Id": uuid4().hex},
            json={"message": "synthetic"},
        )
        assert (user.status_code, user.json()["code"]) == (503, "persistence_unavailable")
        assert guest.status_code == 200 and chat.calls == 1


@pytest.mark.parametrize("database_failure", ["missing", "unreachable"])
async def test_separate_guard_fails_closed_with_persistence_off(
    setup, monkeypatch, database_failure
):
    settings = get_settings()
    monkeypatch.setattr(settings, "g7_persistence_enabled", False)
    monkeypatch.setattr(settings, "g7_owner_deletion_guard_enabled", True)
    if database_failure == "missing":
        monkeypatch.setattr(settings, "chat_database_url", None)
    else:

        def unavailable():
            raise OSError("synthetic database outage")

        monkeypatch.setattr(
            "app.repositories.owner_deletion_repository.get_chat_sessionmaker", unavailable
        )

    chat = FakeLegacyChat()
    app = legacy_app(chat)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        headers = {"Authorization": "Bearer ok-normal"}
        user = await client.post("/api/chat", headers=headers, json={"message": "synthetic"})
        ack = await client.post("/api/chat/acks", headers=headers, json=ack_body())
        guest = await client.post(
            "/api/chat",
            headers={"X-Vishue-Anonymous-Id": uuid4().hex},
            json={"message": "synthetic"},
        )
        assert (user.status_code, user.json()["code"]) == (503, "persistence_unavailable")
        assert (ack.status_code, ack.json()["code"]) == (503, "persistence_unavailable")
        assert guest.status_code == 200 and chat.calls == 1 and chat.acks == 0


@pytest.mark.parametrize("disable_persistence", [False, True])
async def test_legacy_response_started_before_deletion_is_not_delivered(
    setup, monkeypatch, disable_persistence
):
    token = "ok-" + uuid4().hex
    owner = "user-" + token
    started, release = asyncio.Event(), asyncio.Event()

    class WaitingChat(FakeLegacyChat):
        async def answer(self, request, principal_key):
            started.set()
            await release.wait()
            return ChatResponse(answer="private-late-response", products=[])

    app = legacy_app(WaitingChat())
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        task = asyncio.create_task(
            client.post(
                "/api/chat",
                headers={"Authorization": f"Bearer {token}"},
                json={"message": "synthetic"},
            )
        )
        try:
            await asyncio.wait_for(started.wait(), timeout=10)
            async with get_chat_sessionmaker()() as session:
                assert await session.get(ChatOwnerStatus, owner) is None
            await OwnerDeletionService().delete(owner)
            if disable_persistence:
                monkeypatch.setattr(get_settings(), "g7_owner_deletion_guard_enabled", True)
                monkeypatch.setattr(get_settings(), "g7_persistence_enabled", False)
        finally:
            release.set()
        response = await task
        assert (response.status_code, response.json()["code"]) == (403, "account_unavailable")
        assert "private-late-response" not in response.text


async def test_owner_lock_serializes_first_legacy_write_with_deletion(setup, monkeypatch):
    owner = str(uuid4())
    attempted = asyncio.Event()
    original = OwnerDeletionRepository.block

    async def signal_before_block(self, owner_id):
        attempted.set()
        return await original(self, owner_id)

    monkeypatch.setattr(OwnerDeletionRepository, "block", signal_before_block)
    async with legacy_owner_access(owner):
        task = asyncio.create_task(OwnerDeletionService().delete(owner))
        await asyncio.wait_for(attempted.wait(), timeout=10)
        await asyncio.sleep(0.1)
        assert not task.done()
        async with get_chat_sessionmaker()() as session:
            assert await session.get(ChatOwnerStatus, owner) is None
    await asyncio.wait_for(task, timeout=10)
    async with get_chat_sessionmaker()() as session:
        assert (await session.get(ChatOwnerStatus, owner)).status == "DELETED"


@pytest.mark.skipif(not REDIS_URL, reason="disposable Redis required")
@pytest.mark.parametrize("disable_persistence", [False, True])
async def test_legacy_inflight_cannot_create_redis_state_after_deletion(
    setup, monkeypatch, disable_persistence
):
    token = "ok-" + uuid4().hex
    owner = "user-" + token
    request_id = uuid4()
    started, release = asyncio.Event(), asyncio.Event()
    client_redis = AsyncRedis.from_url(REDIS_URL, decode_responses=True)
    repo = ChatSessionRepository(client_redis)
    chat = ChatService(
        None, PlanLlm(intent="search", category="lip"), SessionCatalog(), sessions=repo
    )
    original = chat._interpret_beauty

    async def wait_for_deletion(request, *, pending=None):
        started.set()
        await release.wait()
        return await original(request, pending=pending)

    monkeypatch.setattr(chat, "_interpret_beauty", wait_for_deletion)
    app = legacy_app(chat)
    try:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            task = asyncio.create_task(
                client.post(
                    "/api/chat",
                    headers={"Authorization": f"Bearer {token}"},
                    json={
                        "message": "립 추천",
                        "locale": "ko",
                        "requestType": "beauty_consultation",
                        "requestId": str(request_id),
                    },
                )
            )
            try:
                await asyncio.wait_for(started.wait(), timeout=10)
                await OwnerDeletionService().delete(owner)
                if disable_persistence:
                    monkeypatch.setattr(get_settings(), "g7_owner_deletion_guard_enabled", True)
                    monkeypatch.setattr(get_settings(), "g7_persistence_enabled", False)
            finally:
                release.set()
            response = await task
            assert (response.status_code, response.json()["code"]) == (403, "account_unavailable")
            assert not await client_redis.exists(repo.request_key("user:" + owner, request_id))
    finally:
        await client_redis.aclose()


@pytest.mark.skipif(not REDIS_URL, reason="disposable Redis required")
async def test_existing_legacy_redis_session_cannot_be_read_after_deletion(setup):
    token = "ok-" + uuid4().hex
    owner = "user-" + token
    client_redis = AsyncRedis.from_url(REDIS_URL, decode_responses=True)
    repo = ChatSessionRepository(client_redis)
    chat = ChatService(
        None, PlanLlm(intent="search", category="lip"), SessionCatalog(), sessions=repo
    )
    app = legacy_app(chat)
    headers = {"Authorization": f"Bearer {token}"}
    try:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            body = {
                "message": "립 추천",
                "locale": "ko",
                "requestType": "beauty_consultation",
                "requestId": str(uuid4()),
            }
            first = await client.post("/api/chat", headers=headers, json=body)
            assert first.status_code == 200
            context = first.json()["chatContext"]
            session_key = repo.key(UUID(context["session"]["sessionId"]))
            assert await client_redis.exists(session_key)
            await OwnerDeletionService().delete(owner)
            assert not await client_redis.exists(session_key)
            retry = await client.post(
                "/api/chat",
                headers=headers,
                json={**body, "requestId": str(uuid4()), "chatContext": context},
            )
            assert (retry.status_code, retry.json()["code"]) == (403, "account_unavailable")
    finally:
        await client_redis.aclose()


@pytest.mark.skipif(not REDIS_URL, reason="disposable Redis required")
@pytest.mark.parametrize("persistence_enabled", [True, False])
async def test_redis_deletion_removes_only_target_owner_data_including_old_deleted(
    setup, monkeypatch, persistence_enabled
):
    owner = "ok-*-[" + uuid4().hex
    other = "ok-" + uuid4().hex
    client_redis = AsyncRedis.from_url(REDIS_URL, decode_responses=True)
    repo = ChatSessionRepository(client_redis)
    chat = ChatService(
        None, PlanLlm(intent="search", category="lip"), SessionCatalog(), sessions=repo
    )
    app = legacy_app(chat)
    tokens = [owner, owner, other, None]
    keys = []
    request_keys = []
    try:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            for token in tokens:
                request_id = uuid4()
                headers = (
                    {"Authorization": f"Bearer {token}"}
                    if token
                    else {"X-Vishue-Anonymous-Id": uuid4().hex}
                )
                response = await client.post(
                    "/api/chat",
                    headers=headers,
                    json={
                        "message": "립 추천",
                        "locale": "ko",
                        "requestType": "beauty_consultation",
                        "requestId": str(request_id),
                    },
                )
                assert response.status_code == 200, response.text
                keys.append(repo.key(UUID(response.json()["chatContext"]["session"]["sessionId"])))
                if token:
                    request_keys.append(repo.request_key("user:user-" + token, request_id))

        target_owner = "user-" + owner
        target_rate = f"vishue:chat:rl:user:{target_owner}:123"
        other_rate = f"vishue:chat:rl:user:{target_owner}:other:123"
        await client_redis.set(target_rate, "1", ex=60)
        await client_redis.set(other_rate, "1", ex=60)

        # Simulate an old tombstone whose Redis cleanup was never performed.
        async with get_chat_sessionmaker().begin() as session:
            assert await OwnerDeletionRepository(session).block(target_owner)
            await session.execute(
                update(ChatOwnerStatus)
                .where(ChatOwnerStatus.owner_id == target_owner)
                .values(status="DELETED")
            )
        monkeypatch.setattr(get_settings(), "g7_owner_deletion_guard_enabled", True)
        monkeypatch.setattr(get_settings(), "g7_persistence_enabled", persistence_enabled)
        await OwnerDeletionService().delete(target_owner)
        assert [await client_redis.exists(key) for key in keys] == [0, 0, 1, 1]
        assert [await client_redis.exists(key) for key in request_keys] == [0, 0, 1]
        assert not await client_redis.exists(target_rate)
        assert await client_redis.exists(other_rate)
    finally:
        await client_redis.aclose()


@pytest.mark.parametrize("failure", ["missing", "unreachable"])
@pytest.mark.parametrize("previously_deleted", [False, True])
async def test_missing_or_unreachable_redis_does_not_complete_deletion(
    setup, monkeypatch, failure, previously_deleted
):
    owner = str(uuid4())
    if previously_deleted:
        async with get_chat_sessionmaker().begin() as session:
            assert await OwnerDeletionRepository(session).block(owner)
            await session.execute(
                update(ChatOwnerStatus)
                .where(ChatOwnerStatus.owner_id == owner)
                .values(status="DELETED")
            )

    class UnreachableRedis:
        async def scan_iter(self, **kwargs):
            raise RedisError("synthetic Redis outage")
            yield  # pragma: no cover

    client = None if failure == "missing" else UnreachableRedis()
    monkeypatch.setattr(
        "app.services.owner_deletion_service.get_chat_sessions",
        lambda: ChatSessionRepository(client),
    )
    with pytest.raises(ApiError) as error:
        await OwnerDeletionService().delete(owner)
    assert (error.value.status, error.value.code) == (503, "account_deletion_incomplete")
    async with get_chat_sessionmaker()() as session:
        expected = "DELETED" if previously_deleted else "DELETING"
        assert (await session.get(ChatOwnerStatus, owner)).status == expected


@pytest.mark.skipif(not REDIS_URL, reason="disposable Redis required")
async def test_redis_cleanup_failure_keeps_owner_blocked_and_allows_retry(setup, monkeypatch):
    owner = str(uuid4())
    room, thread, _, memory = await seed_owner(owner)
    redis = AsyncRedis.from_url(REDIS_URL, decode_responses=True)
    repo = ChatSessionRepository(redis)
    request_key = repo.request_key("user:" + owner, uuid4())
    await redis.set(request_key, str(uuid4()), ex=600)
    original = repo.delete_owner

    async def fail_after_cleanup(owner_id):
        await original(owner_id)
        raise ApiError(503, "synthetic Redis acknowledgement loss", "chat_session_unavailable")

    monkeypatch.setattr(repo, "delete_owner", fail_after_cleanup)
    monkeypatch.setattr("app.services.owner_deletion_service.get_chat_sessions", lambda: repo)
    try:
        with pytest.raises(ApiError) as error:
            await OwnerDeletionService().delete(owner)
        assert (error.value.status, error.value.code) == (503, "account_deletion_incomplete")
        async with get_chat_sessionmaker()() as session:
            assert (await session.get(ChatOwnerStatus, owner)).status == "DELETING"
            assert await session.get(ChatConversation, room) is not None
            assert await session.get(ChatMemory, memory) is not None
        assert await checkpoint_exists(thread)
        assert not await redis.exists(request_key)
        monkeypatch.setattr(repo, "delete_owner", original)
        await OwnerDeletionService().delete(owner)
        async with get_chat_sessionmaker()() as session:
            assert (await session.get(ChatOwnerStatus, owner)).status == "DELETED"
            assert await session.get(ChatConversation, room) is None
        assert not await checkpoint_exists(thread)
    finally:
        await redis.aclose()


@pytest.mark.skipif(not REDIS_URL, reason="disposable Redis required")
async def test_malformed_session_prevents_false_deletion_completion(setup):
    owner = str(uuid4())
    redis = AsyncRedis.from_url(REDIS_URL, decode_responses=True)
    malformed_key = ChatSessionRepository.key(uuid4())
    await redis.set(malformed_key, "not-json", ex=600)
    try:
        with pytest.raises(ApiError) as error:
            await OwnerDeletionService().delete(owner)
        assert (error.value.status, error.value.code) == (503, "account_deletion_incomplete")
        async with get_chat_sessionmaker()() as session:
            assert (await session.get(ChatOwnerStatus, owner)).status == "DELETING"
        assert await redis.exists(malformed_key)
        await redis.delete(malformed_key)
        await OwnerDeletionService().delete(owner)
        async with get_chat_sessionmaker()() as session:
            assert (await session.get(ChatOwnerStatus, owner)).status == "DELETED"
    finally:
        await redis.delete(malformed_key)
        await redis.aclose()


@pytest.mark.skipif(not REDIS_URL, reason="disposable Redis required")
async def test_redis_commit_finishes_before_owner_can_be_blocked(setup, monkeypatch):
    token = "ok-" + uuid4().hex
    owner = "user-" + token
    request_id = uuid4()
    started, release, deletion_attempted = asyncio.Event(), asyncio.Event(), asyncio.Event()
    client_redis = AsyncRedis.from_url(REDIS_URL, decode_responses=True)
    repo = ChatSessionRepository(client_redis)
    original_commit = repo.commit
    original_block = OwnerDeletionRepository.block

    async def wait_before_commit(state, expected_version):
        started.set()
        await release.wait()
        await original_commit(state, expected_version)

    async def signal_before_block(self, owner_id):
        deletion_attempted.set()
        return await original_block(self, owner_id)

    monkeypatch.setattr(repo, "commit", wait_before_commit)
    monkeypatch.setattr(OwnerDeletionRepository, "block", signal_before_block)
    chat = ChatService(
        None, PlanLlm(intent="search", category="lip"), SessionCatalog(), sessions=repo
    )
    app = legacy_app(chat)
    headers = {"Authorization": f"Bearer {token}"}
    body = {
        "message": "립 추천",
        "locale": "ko",
        "requestType": "beauty_consultation",
        "requestId": str(request_id),
    }
    request_key = repo.request_key("user:" + owner, request_id)
    try:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            request = asyncio.create_task(client.post("/api/chat", headers=headers, json=body))
            deletion = None
            try:
                await asyncio.wait_for(started.wait(), timeout=10)
                deletion = asyncio.create_task(OwnerDeletionService().delete(owner))
                await asyncio.wait_for(deletion_attempted.wait(), timeout=10)
                await asyncio.sleep(0.1)
                assert not deletion.done() and not await client_redis.exists(request_key)
                async with get_chat_sessionmaker()() as session:
                    assert await session.get(ChatOwnerStatus, owner) is None
            finally:
                release.set()
            response = await asyncio.wait_for(request, timeout=10)
            await asyncio.wait_for(deletion, timeout=10)
            assert response.status_code in {200, 403}
            assert not await client_redis.exists(request_key)
            async with get_chat_sessionmaker()() as session:
                assert (await session.get(ChatOwnerStatus, owner)).status == "DELETED"
            retry = await client.post(
                "/api/chat", headers=headers, json={**body, "requestId": str(uuid4())}
            )
            assert (retry.status_code, retry.json()["code"]) == (403, "account_unavailable")
    finally:
        await client_redis.aclose()

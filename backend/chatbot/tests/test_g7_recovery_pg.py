import asyncio
import os
import socket
import subprocess
import sys
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from urllib.parse import urlsplit
from uuid import UUID, uuid4

import httpx
import pytest
from redis.asyncio import Redis
from sqlalchemy import select, text, update
from sqlalchemy.engine import make_url

from app.core import auth
from app.core.config import get_settings
from app.core.db import dispose_chat_engine, get_chat_engine, get_chat_sessionmaker
from app.core.errors import ApiError
from app.core.ratelimit import get_rate_limiter
from app.main import create_app
from app.models.conversation import ChatConversation, ChatTurn
from app.repositories.chat_session_repository import ChatSessionRepository
from app.repositories.checkpoint_repository import CheckpointRepository
from app.repositories.conversation_repository import ConversationRepository
from app.schemas.chat import ChatRequest, ChatResponse
from app.services.chat_service import ChatService, get_chat_service
from tests.conftest import FakeGraph, FakeLlm, FakeVerifier
from tests.test_beauty_consultation import PlanLlm
from tests.test_chat_sessions import RedisDouble, SessionCatalog

URL = os.environ.get("TEST_CHAT_DATABASE_URL")
pytestmark = [
    pytest.mark.integration,
    pytest.mark.anyio,
    pytest.mark.skipif(not URL, reason="TEST_CHAT_DATABASE_URL not set"),
]
AUTH = {"Authorization": "Bearer ok-1"}


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.fixture
async def setup(monkeypatch):
    if make_url(URL).database != "vishue_chat_test":
        raise RuntimeError("G7 recovery tests require disposable vishue_chat_test database")
    settings = get_settings()
    monkeypatch.setattr(settings, "env", "local")
    monkeypatch.setattr(settings, "g7_persistence_enabled", True)
    monkeypatch.setattr(settings, "chat_database_url", URL)
    monkeypatch.setattr(auth, "get_verifier", lambda: FakeVerifier())
    redis = RedisDouble()
    monkeypatch.setattr(
        "app.services.conversation_service.get_chat_sessions",
        lambda: ChatSessionRepository(redis),
    )
    get_chat_engine.cache_clear()
    get_rate_limiter.cache_clear()
    try:
        yield
    finally:
        await dispose_chat_engine()
        get_rate_limiter.cache_clear()


class BlockingChat:
    def __init__(self):
        self.started = asyncio.Event()
        self.release = asyncio.Event()
        self.calls = 0

    async def answer(self, request, principal_key):
        self.calls += 1
        self.started.set()
        await self.release.wait()
        return ChatResponse(answer="done", products=[])


async def create(client):
    res = await client.post(
        "/api/chat/conversations",
        headers=AUTH,
        json={"requestId": str(uuid4()), "entry": {"type": "general"}},
    )
    assert res.status_code == 201, res.text
    return res.json()["conversationId"]


class BlockingCatalog:
    def __init__(self):
        self.started = asyncio.Event()
        self.release = asyncio.Event()
        self.calls = 0

    async def get_product(self, product_id):
        self.calls += 1
        self.started.set()
        await self.release.wait()
        return SimpleNamespace(id=product_id, shades=[])


async def test_state_update_serializes_concurrent_requests_and_replays(setup):
    app = create_app()
    fake = BlockingChat()
    fake._catalog = BlockingCatalog()
    app.dependency_overrides[get_chat_service] = lambda: fake
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        room = await create(client)
        body = {
            "requestId": str(uuid4()),
            "expectedConversationVersion": 0,
            "operation": "select_product",
            "payload": {"productId": "product-1"},
        }
        url = f"/api/chat/conversations/{room}/state"
        task = asyncio.create_task(client.patch(url, headers=AUTH, json=body))
        await asyncio.wait_for(fake._catalog.started.wait(), timeout=10)
        duplicate = await client.patch(url, headers=AUTH, json=body)
        assert (duplicate.status_code, duplicate.json()["code"]) == (409, "request_in_progress")
        other = await client.post(
            "/api/chat",
            headers=AUTH,
            json={
                "conversationId": room,
                "requestId": str(uuid4()),
                "expectedConversationVersion": 0,
                "message": "hello",
            },
        )
        assert (other.status_code, other.json()["code"]) == (409, "conversation_busy")
        fake._catalog.release.set()
        completed = await task
        assert completed.status_code == 200, completed.text
        replay = await client.patch(url, headers=AUTH, json=body)
        assert replay.json() == completed.json()
        assert fake._catalog.calls == 1 and fake.calls == 0


async def test_state_update_failure_after_flush_rolls_back(setup, monkeypatch):
    app = create_app()
    app.dependency_overrides[get_chat_service] = BlockingChat
    original = ConversationRepository.finish_state_update

    async def fail_after_flush(self, *args, **kwargs):
        assert await original(self, *args, **kwargs)
        raise OSError("synthetic failure after state update flush")

    monkeypatch.setattr(ConversationRepository, "finish_state_update", fail_after_flush)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        room = await create(client)
        body = {
            "requestId": str(uuid4()),
            "expectedConversationVersion": 0,
            "operation": "clear_selection",
            "payload": {},
        }
        url = f"/api/chat/conversations/{room}/state"
        response = await client.patch(url, headers=AUTH, json=body)
        assert (response.status_code, response.json()["code"]) == (503, "persistence_unavailable")
        detail = (await client.get(f"/api/chat/conversations/{room}", headers=AUTH)).json()
        assert detail["conversationVersion"] == 0 and detail["messages"] == []
        state = await client.get(
            f"/api/chat/conversations/{room}/requests/{body['requestId']}", headers=AUTH
        )
        assert state.json()["status"] == "INTERRUPTED"
        assert (await client.patch(url, headers=AUTH, json=body)).status_code == 409


async def test_delete_waits_for_active_graph_before_removing_checkpoints(setup, monkeypatch):
    monkeypatch.setattr(get_settings(), "g1_supervisor_enabled", True)

    class BlockingLlm(FakeLlm):
        def __init__(self):
            super().__init__()
            self.started, self.release = asyncio.Event(), asyncio.Event()

        async def complete(self, messages):
            self.started.set()
            await self.release.wait()
            return await super().complete(messages)

    app = create_app()
    llm = BlockingLlm()
    app.dependency_overrides[get_chat_service] = lambda: ChatService(FakeGraph(), llm)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        room = await create(client)
        async with get_chat_sessionmaker().begin() as session:
            thread = await session.scalar(
                select(ChatConversation.thread_id).where(ChatConversation.id == UUID(room))
            )
        task = asyncio.create_task(
            client.post(
                "/api/chat",
                headers=AUTH,
                json={
                    "conversationId": room,
                    "requestId": str(uuid4()),
                    "expectedConversationVersion": 0,
                    "locale": "en",
                    "message": "hello",
                },
            )
        )
        await asyncio.wait_for(llm.started.wait(), timeout=10)
        deleted = await client.delete(f"/api/chat/conversations/{room}", headers=AUTH)
        assert (deleted.status_code, deleted.json()["code"]) == (503, "deletion_incomplete")
        assert (
            await client.get(f"/api/chat/conversations/{room}", headers=AUTH)
        ).status_code == 404
        llm.release.set()
        response = await task
        assert (response.status_code, response.json()["code"]) == (409, "request_interrupted")
        assert (
            await client.delete(f"/api/chat/conversations/{room}", headers=AUTH)
        ).status_code == 204
        async with get_chat_sessionmaker().begin() as session:
            count = await session.scalar(
                text("SELECT count(*) FROM checkpoints WHERE thread_id = :id"), {"id": str(thread)}
            )
        assert count == 0


async def test_graph_cannot_start_after_room_was_deleted(setup, monkeypatch):
    from app.services import conversation_service

    monkeypatch.setattr(get_settings(), "g1_supervisor_enabled", True)
    started, release = asyncio.Event(), asyncio.Event()

    async def pause_before_graph(*args):
        started.set()
        await release.wait()

    monkeypatch.setattr(conversation_service, "revalidate_request", pause_before_graph)
    app = create_app()
    app.dependency_overrides[get_chat_service] = lambda: ChatService(FakeGraph(), FakeLlm())
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        room = await create(client)
        async with get_chat_sessionmaker().begin() as session:
            thread = await session.scalar(
                select(ChatConversation.thread_id).where(ChatConversation.id == UUID(room))
            )
        task = asyncio.create_task(
            client.post(
                "/api/chat",
                headers=AUTH,
                json={
                    "conversationId": room,
                    "requestId": str(uuid4()),
                    "expectedConversationVersion": 0,
                    "locale": "en",
                    "message": "hello",
                },
            )
        )
        await asyncio.wait_for(started.wait(), timeout=10)
        assert (
            await client.delete(f"/api/chat/conversations/{room}", headers=AUTH)
        ).status_code == 204
        release.set()
        response = await task
        assert response.status_code in {409, 503}
        async with get_chat_sessionmaker().begin() as session:
            count = await session.scalar(
                text("SELECT count(*) FROM checkpoints WHERE thread_id = :id"), {"id": str(thread)}
            )
        assert count == 0


async def test_deleted_room_rejects_a_late_redis_write(setup, monkeypatch):
    monkeypatch.setattr(get_settings(), "g1_supervisor_enabled", True)
    redis = RedisDouble()
    sessions = ChatSessionRepository(redis)
    service = ChatService(
        FakeGraph(), PlanLlm(intent="search", category="lip"), SessionCatalog(), sessions=sessions
    )
    before_write, release = asyncio.Event(), asyncio.Event()
    validate = service._validate_session_context

    async def pause_before_save(context, incoming, screen, **kwargs):
        result = await validate(context, incoming, screen, **kwargs)
        if incoming is None and screen is None and not before_write.is_set():
            before_write.set()
            await release.wait()
        return result

    async def unavailable_checkpoint(self, thread_id):
        raise OSError("Checkpoint temporarily unavailable")

    monkeypatch.setattr(service, "_validate_session_context", pause_before_save)
    app = create_app()
    app.dependency_overrides[get_chat_service] = lambda: service
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        room, other_room = await create(client), await create(client)
        request_id = uuid4()
        body = {
            "conversationId": room,
            "expectedConversationVersion": 0,
            "requestId": str(request_id),
            "locale": "ko",
            "message": "립 추천해줘",
        }
        pending = asyncio.create_task(client.post("/api/chat", headers=AUTH, json=body))
        delete_url = f"/api/chat/conversations/{room}"
        try:
            await asyncio.wait_for(before_write.wait(), timeout=10)
            with monkeypatch.context() as cleanup:
                cleanup.setattr(CheckpointRepository, "delete_thread", unavailable_checkpoint)
                deleted = await client.delete(delete_url, headers=AUTH)
            assert (deleted.status_code, deleted.json()["code"]) == (503, "deletion_incomplete")
            async with get_chat_sessionmaker().begin() as session:
                deleted_at = await session.scalar(
                    select(ChatConversation.deleted_at).where(ChatConversation.id == UUID(room))
                )
            assert deleted_at is not None
        finally:
            release.set()
            late = await asyncio.wait_for(pending, timeout=10)
        assert (late.status_code, late.json()["code"]) == (409, "request_interrupted")
        assert redis.writes == 0
        assert await redis.get(sessions.request_key("user:user-ok-1", request_id)) is None
        assert (await client.delete(delete_url, headers=AUTH)).status_code == 204

        other = await client.post(
            "/api/chat",
            headers=AUTH,
            json={**body, "conversationId": other_room, "requestId": str(uuid4())},
        )
        assert other.status_code == 200, other.text
        assert other.json()["chatContext"]["session"] and redis.writes == 1


@pytest.mark.skipif(
    not os.environ.get("TEST_CHAT_REDIS_URL"), reason="disposable Redis not configured"
)
async def test_room_redis_cleanup_is_retryable_and_preserves_other_sessions(setup, monkeypatch):
    monkeypatch.setattr(get_settings(), "g1_supervisor_enabled", True)
    redis_url = os.environ["TEST_CHAT_REDIS_URL"]
    if urlsplit(redis_url).hostname not in {"127.0.0.1", "localhost", "::1"}:
        raise RuntimeError("Room cleanup tests require a disposable local Redis")
    async with Redis.from_url(redis_url, decode_responses=True) as redis:
        sessions = ChatSessionRepository(redis)
        service = ChatService(
            FakeGraph(),
            PlanLlm(intent="search", category="lip"),
            SessionCatalog(),
            sessions=sessions,
        )
        app = create_app()
        app.dependency_overrides[get_chat_service] = lambda: service
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            room, other_room = await create(client), await create(client)

            async def store(room_id, version=0):
                request_id = uuid4()
                response = await client.post(
                    "/api/chat",
                    headers=AUTH,
                    json={
                        "conversationId": room_id,
                        "expectedConversationVersion": version,
                        "requestId": str(request_id),
                        "locale": "ko",
                        "message": "립 추천해줘",
                    },
                )
                assert response.status_code == 200, response.text
                session_id = UUID(response.json()["chatContext"]["session"]["sessionId"])
                return sessions.key(session_id), sessions.request_key("user:user-ok-1", request_id)

            orphan_session, evicted_request = await store(room)
            room_session, room_request = await store(room, 1)
            other_session, other_request = await store(other_room)
            guest_id = f"guest:{uuid4()}"
            guest_request_id = uuid4()
            guest = await service.answer(
                ChatRequest(
                    message="립 추천해줘",
                    locale="ko",
                    request_type="beauty_consultation",
                    request_id=guest_request_id,
                ),
                guest_id,
            )
            guest_session = sessions.key(guest.chat_context.session.session_id)
            guest_request = sessions.request_key(guest_id, guest_request_id)
            # Simulate eviction of only the disposable room's request key.
            assert await redis.delete(evicted_request) == 1

            async def unavailable(*args):
                raise ApiError(503, "Redis unavailable", "chat_session_unavailable")

            path = f"/api/chat/conversations/{room}"
            with monkeypatch.context() as outage:
                outage.setattr(sessions, "delete_room", unavailable)
                incomplete = await client.delete(path, headers=AUTH)
            assert (incomplete.status_code, incomplete.json()["code"]) == (
                503,
                "deletion_incomplete",
            )
            assert (await client.get(path, headers=AUTH)).status_code == 404
            assert await redis.exists(orphan_session, room_session, room_request) == 3

            assert (await client.delete(path, headers=AUTH)).status_code == 204
            assert (await client.delete(path, headers=AUTH)).status_code == 204
            assert await redis.exists(orphan_session, room_session, room_request) == 0
            assert (
                await redis.exists(other_session, other_request, guest_session, guest_request) == 4
            )


@pytest.mark.parametrize("change", ["delete", "update"])
async def test_memory_change_during_chat_prevents_stale_response_commit(setup, monkeypatch, change):
    monkeypatch.setattr(get_settings(), "g7_memory_enabled", True)

    class MemoryChat:
        def __init__(self):
            self.started, self.release = asyncio.Event(), asyncio.Event()

        async def answer(self, request, principal_key):
            if request.message == "blocking":
                assert request._consented_memories
                self.started.set()
                await self.release.wait()
            return ChatResponse(answer="answer", products=[])

    app = create_app()
    fake = MemoryChat()
    app.dependency_overrides[get_chat_service] = lambda: fake
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        source_room = await create(client)
        source = await client.post(
            "/api/chat",
            headers=AUTH,
            json={
                "conversationId": source_room,
                "requestId": str(uuid4()),
                "expectedConversationVersion": 0,
                "message": "코랄 립 기억해줘",
            },
        )
        assert source.status_code == 200, source.text
        proposal = source.json()["memoryProposal"]
        memory = await client.post(
            "/api/chat/memories",
            headers=AUTH,
            json={
                "requestId": str(uuid4()),
                "proposalId": proposal["proposalId"],
                "expectedProposalVersion": proposal["version"],
                "confirmed": True,
            },
        )
        assert memory.status_code == 200, memory.text
        room = await create(client)
        task = asyncio.create_task(
            client.post(
                "/api/chat",
                headers=AUTH,
                json={
                    "conversationId": room,
                    "requestId": str(uuid4()),
                    "expectedConversationVersion": 0,
                    "message": "blocking",
                },
            )
        )
        await asyncio.wait_for(fake.started.wait(), timeout=10)
        if change == "delete":
            changed = await client.delete(
                f"/api/chat/memories/{memory.json()['memoryId']}",
                headers={**AUTH, "Idempotency-Key": str(uuid4())},
            )
            assert changed.status_code == 204
        else:
            changed = await client.patch(
                f"/api/chat/memories/{memory.json()['memoryId']}",
                headers=AUTH,
                json={
                    "requestId": str(uuid4()),
                    "expectedVersion": 1,
                    "confirmed": True,
                    "value": "새로운 취향",
                },
            )
            assert changed.status_code == 200
        fake.release.set()
        response = await task
        assert (response.status_code, response.json()["code"]) == (409, "request_interrupted")
        detail = (await client.get(f"/api/chat/conversations/{room}", headers=AUTH)).json()
        assert detail["conversationVersion"] == 0 and detail["messages"] == []


async def test_concurrent_requests_do_not_execute_twice(setup):
    app = create_app()
    fake = BlockingChat()
    app.dependency_overrides[get_chat_service] = lambda: fake
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        room = await create(client)
        body = {
            "conversationId": room,
            "requestId": str(uuid4()),
            "expectedConversationVersion": 0,
            "message": "hello",
        }
        task = asyncio.create_task(client.post("/api/chat", headers=AUTH, json=body))
        await asyncio.wait_for(fake.started.wait(), timeout=10)
        duplicate = await client.post("/api/chat", headers=AUTH, json=body)
        assert (duplicate.status_code, duplicate.json()["code"]) == (409, "request_in_progress")
        other = await client.post(
            "/api/chat", headers=AUTH, json={**body, "requestId": str(uuid4())}
        )
        assert (other.status_code, other.json()["code"]) == (409, "conversation_busy")
        fake.release.set()
        completed = await task
        assert completed.status_code == 200
        replay = await client.post("/api/chat", headers=AUTH, json=body)
        assert replay.status_code == 200 and fake.calls == 1


async def test_failure_after_database_flush_rolls_back_and_never_replays(setup, monkeypatch):
    app = create_app()
    fake = BlockingChat()
    fake.release.set()
    app.dependency_overrides[get_chat_service] = lambda: fake
    original = ConversationRepository.finish_reply

    async def fail_after_flush(self, *args, **kwargs):
        assert await original(self, *args, **kwargs)
        raise OSError("synthetic failure after flush")

    monkeypatch.setattr(ConversationRepository, "finish_reply", fail_after_flush)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        room = await create(client)
        body = {
            "conversationId": room,
            "requestId": str(uuid4()),
            "expectedConversationVersion": 0,
            "message": "hello",
        }
        res = await client.post("/api/chat", headers=AUTH, json=body)
        assert (res.status_code, res.json()["code"]) == (503, "persistence_unavailable")
        detail = (await client.get(f"/api/chat/conversations/{room}", headers=AUTH)).json()
        assert detail["conversationVersion"] == 0 and detail["messages"] == []
        state = await client.get(
            f"/api/chat/conversations/{room}/requests/{body['requestId']}", headers=AUTH
        )
        assert state.json()["status"] == "INTERRUPTED"
        assert (await client.post("/api/chat", headers=AUTH, json=body)).status_code == 409
        assert fake.calls == 1


async def test_new_request_interrupts_expired_reservation_in_same_room(setup):
    app = create_app()
    fake = BlockingChat()
    fake.release.set()
    app.dependency_overrides[get_chat_service] = lambda: fake
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        room = await create(client)
        old_request = uuid4()
        async with get_chat_sessionmaker().begin() as session:
            assert await ConversationRepository(session).reserve_turn(
                "user-ok-1",
                UUID(room),
                old_request,
                "a" * 64,
                0,
                datetime.now(UTC) - timedelta(seconds=1),
            )
        body = {
            "conversationId": room,
            "requestId": str(uuid4()),
            "expectedConversationVersion": 0,
            "message": "new request",
        }
        response = await client.post("/api/chat", headers=AUTH, json=body)
        assert response.status_code == 200, response.text
        old = await client.get(
            f"/api/chat/conversations/{room}/requests/{old_request}", headers=AUTH
        )
        assert old.json()["status"] == "INTERRUPTED" and fake.calls == 1


_CHILD_SERVER = r"""
import asyncio, os
import uvicorn
from app.core import auth
from app.main import create_app
from app.schemas.chat import ChatResponse
from app.services.chat_service import get_chat_service
class Verifier:
    async def verify(self, token):
        return {"sub": "user-ok-1", "role": "authenticated"} if token == "ok-1" else None
class WaitingChat:
    async def answer(self, request, principal_key):
        await asyncio.sleep(300)
        return ChatResponse(answer="unexpected", products=[])
auth.get_verifier = lambda: Verifier()
app = create_app()
app.dependency_overrides[get_chat_service] = lambda: WaitingChat()
uvicorn.run(app, host="127.0.0.1", port=int(os.environ["G73_CRASH_PORT"]), log_level="error")
"""


async def test_killed_server_request_becomes_interrupted_after_lease_expiry(setup):
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    env = {
        **os.environ,
        "CHAT_DATABASE_URL": URL,
        "ENV": "local",
        "G7_PERSISTENCE_ENABLED": "true",
        "G73_CRASH_PORT": str(port),
        "PYTHONDONTWRITEBYTECODE": "1",
    }
    flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
    process = await asyncio.to_thread(
        subprocess.Popen,
        [sys.executable, "-u", "-c", _CHILD_SERVER],
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        creationflags=flags,
    )
    task = None
    try:
        async with httpx.AsyncClient(base_url=f"http://127.0.0.1:{port}", timeout=10) as child:
            for _ in range(150):
                try:
                    if (await child.get("/healthz")).status_code == 200:
                        break
                except httpx.HTTPError:
                    pass
                await asyncio.sleep(0.1)
            else:
                pytest.fail("child server did not start")
            room = await create(child)
            request_id = str(uuid4())
            body = {
                "conversationId": room,
                "requestId": request_id,
                "expectedConversationVersion": 0,
                "message": "waiting",
            }
            task = asyncio.create_task(child.post("/api/chat", headers=AUTH, json=body))
            for _ in range(150):
                async with get_chat_sessionmaker()() as session:
                    status = await session.scalar(
                        select(ChatTurn.status).where(
                            ChatTurn.owner_id == "user-ok-1",
                            ChatTurn.request_id == UUID(request_id),
                        )
                    )
                if status == "IN_PROGRESS":
                    break
                await asyncio.sleep(0.1)
            else:
                pytest.fail("request was not reserved")
            process.kill()
            await asyncio.to_thread(process.wait, 10)
            with pytest.raises(httpx.HTTPError):
                await task
            task = None
        # Advance the test lease without waiting for the production heartbeat interval.
        async with get_chat_sessionmaker().begin() as session:
            await session.execute(
                update(ChatTurn)
                .where(ChatTurn.owner_id == "user-ok-1", ChatTurn.request_id == UUID(request_id))
                .values(lease_until=datetime.now(UTC) - timedelta(seconds=1))
            )
        app = create_app()
        fake = BlockingChat()
        app.dependency_overrides[get_chat_service] = lambda: fake
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            state = await client.get(
                f"/api/chat/conversations/{room}/requests/{request_id}", headers=AUTH
            )
            assert state.json()["status"] == "INTERRUPTED"
            replay = await client.post("/api/chat", headers=AUTH, json=body)
            assert (replay.status_code, replay.json()["code"]) == (409, "request_interrupted")
            assert fake.calls == 0
    finally:
        if process.poll() is None:
            process.kill()
            await asyncio.to_thread(process.wait, 10)
        if task is not None:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)

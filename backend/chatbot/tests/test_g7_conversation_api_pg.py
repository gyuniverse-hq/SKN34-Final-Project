import json
import os
from types import SimpleNamespace
from typing import TypedDict
from uuid import uuid4

import httpx
import psycopg
import pytest
from langgraph.checkpoint.postgres import PostgresSaver
from langgraph.graph import END, START, StateGraph
from redis import Redis
from redis.asyncio import Redis as AsyncRedis
from sqlalchemy.engine import make_url

from app.clients.catalog_client import CatalogClient
from app.core.config import get_settings
from app.core.db import get_chat_engine
from app.core.ratelimit import MemoryRateLimiter, get_rate_limiter
from app.repositories.chat_session_repository import ChatSessionRepository
from app.repositories.checkpoint_repository import CheckpointRepository
from app.repositories.conversation_repository import ConversationRepository
from app.schemas.chat import BeautyContext, BeautyFilters, ChatResponse, ChatSessionRef
from app.services.chat_service import ChatService, get_chat_service
from tests.conftest import FakeGraph, FakeLlm
from tests.test_beauty_consultation import PlanLlm
from tests.test_chat_sessions import SessionCatalog
from tests.test_g2_multiturn import G2Llm
from tests.test_g4_option_search import OptionCatalog, OptionLlm

URL = os.environ.get("TEST_CHAT_DATABASE_URL")
pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(not URL, reason="TEST_CHAT_DATABASE_URL not set"),
]
AUTH = {"Authorization": "Bearer ok-1"}
OTHER = {"Authorization": "Bearer ok-2"}


class RecordingChat:
    def __init__(self):
        self.requests = []

    async def answer(self, request, principal_key):
        self.requests.append((request, principal_key))
        return ChatResponse(answer=f"answer-{len(self.requests)}", products=[])


@pytest.fixture
def api(client, monkeypatch):
    if make_url(URL).database != "vishue_chat_test":
        raise RuntimeError("G7 API tests require disposable vishue_chat_test database")
    settings = get_settings()
    monkeypatch.setattr(settings, "env", "local")
    monkeypatch.setattr(settings, "g7_persistence_enabled", True)
    monkeypatch.setattr(settings, "chat_database_url", URL)
    get_chat_engine.cache_clear()
    fake = RecordingChat()
    client.app.dependency_overrides[get_chat_service] = lambda: fake
    client.app.dependency_overrides[get_rate_limiter] = lambda: MemoryRateLimiter(limit=1000)
    with client:
        yield client, fake


def create(client, request_id=None):
    request_id = request_id or str(uuid4())
    body = {"requestId": request_id, "entry": {"type": "general"}}
    result = client.post("/api/chat/conversations", headers=AUTH, json=body)
    assert result.status_code == 201, result.text
    return result.json(), body


def test_two_turns_replay_server_history_and_owner_isolation(api):
    client, fake = api
    created, create_body = create(client)
    same = client.post("/api/chat/conversations", headers=AUTH, json=create_body)
    assert same.json()["conversationId"] == created["conversationId"]
    room = created["conversationId"]
    first = {
        "conversationId": room,
        "expectedConversationVersion": 0,
        "requestId": str(uuid4()),
        "message": "first question",
        "locale": "en",
    }
    first_reply = client.post("/api/chat", json=first, headers=AUTH)
    assert first_reply.status_code == 200, first_reply.text
    assert first_reply.json()["conversation"]["version"] == 1
    second = {
        "conversationId": room,
        "expectedConversationVersion": 1,
        "requestId": str(uuid4()),
        "message": "what next?",
        "locale": "en",
        "styleContext": {"kind": "video", "lookId": "untrusted"},
        "recentMessages": [{"id": "fake", "role": "user", "text": "untrusted"}],
    }
    reply = client.post("/api/chat", json=second, headers=AUTH)
    assert reply.status_code == 200, reply.text
    assert reply.json()["conversation"]["version"] == 2
    prepared, principal = fake.requests[-1]
    assert principal == "user:user-ok-1"
    assert [entry.text for entry in prepared.recent_messages] == ["first question", "answer-1"]
    assert prepared.style_context is None
    replay = client.post("/api/chat", json=first, headers=AUTH)
    assert replay.status_code == 200 and replay.json()["answer"] == "answer-1"
    assert replay.json()["conversation"]["version"] == 1
    assert len(fake.requests) == 2
    conflict = client.post("/api/chat", json={**first, "message": "different"}, headers=AUTH)
    assert (conflict.status_code, conflict.json()["code"]) == (409, "request_conflict")
    for path in (
        f"/api/chat/conversations/{room}",
        f"/api/chat/conversations/{room}/requests/{first['requestId']}",
    ):
        assert client.get(path, headers=OTHER).status_code == 404
    history = client.get(f"/api/chat/conversations/{room}", headers=AUTH).json()
    assert [m["text"] for m in history["messages"]] == [
        "first question",
        "answer-1",
        "what next?",
        "answer-2",
    ]
    status = client.get(
        f"/api/chat/conversations/{room}/requests/{first['requestId']}", headers=AUTH
    )
    assert (
        status.json()["status"] == "COMMITTED" and status.json()["response"]["answer"] == "answer-1"
    )


def test_room_deletion_is_retryable_and_does_not_resurrect_on_create_replay(api, monkeypatch):
    client, _ = api
    created, body = create(client)
    room = created["conversationId"]
    real = CheckpointRepository.delete_thread

    async def fail(self, thread_id):
        raise OSError("temporary failure")

    monkeypatch.setattr(CheckpointRepository, "delete_thread", fail)
    failed = client.delete(f"/api/chat/conversations/{room}", headers=AUTH)
    assert (failed.status_code, failed.json()["code"]) == (503, "deletion_incomplete")
    assert client.get(f"/api/chat/conversations/{room}", headers=AUTH).status_code == 404
    monkeypatch.setattr(CheckpointRepository, "delete_thread", real)
    assert client.delete(f"/api/chat/conversations/{room}", headers=AUTH).status_code == 204
    assert client.delete(f"/api/chat/conversations/{room}", headers=AUTH).status_code == 204
    replay = client.post("/api/chat/conversations", headers=AUTH, json=body)
    assert (replay.status_code, replay.json()["code"]) == (410, "conversation_deleted")


def test_room_delete_removes_existing_checkpoint(api):
    client, _ = api
    room = create(client)[0]["conversationId"]
    dsn = make_url(URL).set(drivername="postgresql").render_as_string(hide_password=False)
    with psycopg.connect(dsn) as conn:
        thread = str(
            conn.execute(
                "SELECT thread_id FROM chat_conversations WHERE id = %s", (room,)
            ).fetchone()[0]
        )

    class State(TypedDict):
        result: str

    with PostgresSaver.from_conn_string(dsn) as saver:
        graph = StateGraph(State)
        graph.add_node("step", lambda state: {"result": "stored"})
        graph.add_edge(START, "step")
        graph.add_edge("step", END)
        config = {"configurable": {"thread_id": thread}}
        graph.compile(checkpointer=saver).invoke({"result": "start"}, config)
        assert saver.get_tuple(config) is not None
        assert client.delete(f"/api/chat/conversations/{room}", headers=AUTH).status_code == 204
        assert saver.get_tuple(config) is None


def test_pagination_returns_latest_rooms_and_message_pages(api):
    client, _ = api
    owner = {"Authorization": f"Bearer ok-page-{uuid4()}"}
    for _ in range(3):
        result = client.post(
            "/api/chat/conversations",
            headers=owner,
            json={"requestId": str(uuid4()), "entry": {"type": "general"}},
        )
        assert result.status_code == 201
    page = client.get("/api/chat/conversations?limit=2", headers=owner).json()
    assert len(page["conversations"]) == 2 and page["nextCursor"]
    next_page = client.get(
        "/api/chat/conversations", headers=owner, params={"limit": 2, "cursor": page["nextCursor"]}
    ).json()
    assert len(next_page["conversations"]) == 1 and next_page["nextCursor"] is None
    assert (
        len({r["conversationId"] for r in page["conversations"] + next_page["conversations"]}) == 3
    )


def test_real_chat_service_receives_persisted_history_with_g1_off(api, monkeypatch):
    client, _ = api
    monkeypatch.setattr(get_settings(), "g1_supervisor_enabled", False)
    llm = FakeLlm()
    service = ChatService(FakeGraph(), llm)
    client.app.dependency_overrides[get_chat_service] = lambda: service
    owner = {"Authorization": f"Bearer ok-history-{uuid4()}"}
    room = client.post(
        "/api/chat/conversations",
        headers=owner,
        json={"requestId": str(uuid4()), "entry": {"type": "general"}},
    ).json()["conversationId"]
    first = client.post(
        "/api/chat",
        headers=owner,
        json={
            "conversationId": room,
            "requestId": str(uuid4()),
            "expectedConversationVersion": 0,
            "locale": "en",
            "message": "tell me about coral lipstick",
        },
    )
    assert first.status_code == 200, first.text
    second = client.post(
        "/api/chat",
        headers=owner,
        json={
            "conversationId": room,
            "requestId": str(uuid4()),
            "expectedConversationVersion": 1,
            "locale": "en",
            "message": "what did I just ask?",
        },
    )
    assert second.status_code == 200, second.text
    assert any(m["content"] == "tell me about coral lipstick" for m in llm.messages)
    assert llm.messages[-1]["content"] == "what did I just ask?"


def test_actual_graph_uses_safe_checkpoints_and_never_restores_unapproved_latest(api, monkeypatch):
    client, _ = api
    monkeypatch.setattr(get_settings(), "g1_supervisor_enabled", True)
    llm = FakeLlm()
    service = ChatService(FakeGraph(), llm)
    token = "secret-redis-token-must-not-enter-checkpoint"
    original_execute = service._execute_turn

    async def execute_with_token(*args, **kwargs):
        result = await original_execute(*args, **kwargs)
        result.chat_context = BeautyContext(
            issued_at=1,
            filters=BeautyFilters(),
            session=ChatSessionRef(
                session_id=uuid4(),
                session_token=token,
                result_set_id=uuid4(),
                state_version=1,
                expires_at=9999999999,
            ),
        )
        return result

    monkeypatch.setattr(service, "_execute_turn", execute_with_token)
    client.app.dependency_overrides[get_chat_service] = lambda: service
    room = create(client)[0]["conversationId"]
    secret = "private-message-should-not-be-checkpointed"
    first_id = str(uuid4())
    first = client.post(
        "/api/chat",
        headers=AUTH,
        json={
            "conversationId": room,
            "requestId": first_id,
            "expectedConversationVersion": 0,
            "locale": "en",
            "message": secret,
        },
    )
    assert first.status_code == 200, first.text
    dsn = make_url(URL).set(drivername="postgresql").render_as_string(hide_password=False)
    with psycopg.connect(dsn) as conn:
        thread, accepted, version = conn.execute(
            "SELECT thread_id, accepted_checkpoint_id, accepted_checkpoint_version "
            "FROM chat_conversations WHERE id = %s",
            (room,),
        ).fetchone()
    assert accepted and version == 1
    config = {"configurable": {"thread_id": str(thread), "checkpoint_id": accepted}}
    with PostgresSaver.from_conn_string(dsn) as saver:
        saved = saver.get_tuple(config)
        values = saved.checkpoint["channel_values"]
        assert values["request_id"] == first_id and values["execution_status"] == "done"
        assert secret not in str(saved) and "ChatResponse" not in str(saved)

        class RogueState(TypedDict):
            unapproved: str

        graph = StateGraph(RogueState)
        graph.add_node("done", lambda state: {"unapproved": "must-never-restore"})
        graph.add_edge(START, "done")
        graph.add_edge("done", END)
        graph.compile(checkpointer=saver).invoke(
            {"unapproved": "must-never-restore"}, {"configurable": {"thread_id": str(thread)}}
        )
    second_id = str(uuid4())
    second = client.post(
        "/api/chat",
        headers=AUTH,
        json={
            "conversationId": room,
            "requestId": second_id,
            "expectedConversationVersion": 1,
            "locale": "en",
            "message": "what did I ask?",
        },
    )
    assert second.status_code == 200, second.text
    assert any(message["content"] == secret for message in llm.messages)
    with psycopg.connect(dsn) as conn:
        accepted2, version2 = conn.execute(
            "SELECT accepted_checkpoint_id, accepted_checkpoint_version "
            "FROM chat_conversations WHERE id = %s",
            (room,),
        ).fetchone()
        blobs = conn.execute(
            "SELECT blob FROM checkpoint_blobs WHERE thread_id = %s", (str(thread),)
        ).fetchall()
        writes = conn.execute(
            "SELECT blob FROM checkpoint_writes WHERE thread_id = %s", (str(thread),)
        ).fetchall()
    assert accepted2 != accepted and version2 == 2
    assert all(
        sensitive.encode() not in bytes(row[0])
        for row in blobs + writes
        if row[0]
        for sensitive in (secret, token, "Try Rom&nd Juicy Tint.")
    )
    with PostgresSaver.from_conn_string(dsn) as saver:
        saved2 = saver.get_tuple(
            {"configurable": {"thread_id": str(thread), "checkpoint_id": accepted2}}
        )
        assert saved2.checkpoint["channel_values"]["request_id"] == second_id
        assert "unapproved" not in saved2.checkpoint["channel_values"]
    assert client.delete(f"/api/chat/conversations/{room}", headers=AUTH).status_code == 204


def test_checkpoint_is_not_accepted_if_completed_reply_rolls_back(api, monkeypatch):
    client, _ = api
    monkeypatch.setattr(get_settings(), "g1_supervisor_enabled", True)
    client.app.dependency_overrides[get_chat_service] = lambda: ChatService(FakeGraph(), FakeLlm())
    room = create(client)[0]["conversationId"]
    body = {
        "conversationId": room,
        "requestId": str(uuid4()),
        "expectedConversationVersion": 0,
        "locale": "en",
        "message": "hello",
    }
    original = ConversationRepository.finish_reply

    async def fail_after_flush(self, *args, **kwargs):
        assert await original(self, *args, **kwargs)
        raise OSError("simulated failure after flush")

    monkeypatch.setattr(ConversationRepository, "finish_reply", fail_after_flush)
    failed = client.post("/api/chat", headers=AUTH, json=body)
    assert (failed.status_code, failed.json()["code"]) == (503, "persistence_unavailable")
    dsn = make_url(URL).set(drivername="postgresql").render_as_string(hide_password=False)
    with psycopg.connect(dsn) as conn:
        thread, accepted, version = conn.execute(
            "SELECT thread_id, accepted_checkpoint_id, conversation_version "
            "FROM chat_conversations WHERE id = %s",
            (room,),
        ).fetchone()
        assert accepted is None and version == 0
        assert (
            conn.execute(
                "SELECT count(*) FROM checkpoints WHERE thread_id = %s", (str(thread),)
            ).fetchone()[0]
            > 0
        )
    monkeypatch.setattr(ConversationRepository, "finish_reply", original)
    retried = client.post("/api/chat", headers=AUTH, json={**body, "requestId": str(uuid4())})
    assert retried.status_code == 200, retried.text
    with psycopg.connect(dsn) as conn:
        accepted, version = conn.execute(
            "SELECT accepted_checkpoint_id, accepted_checkpoint_version "
            "FROM chat_conversations WHERE id = %s",
            (room,),
        ).fetchone()
    assert accepted and version == 1


def test_checkpoint_failure_does_not_commit_reply(api, monkeypatch):
    client, _ = api
    monkeypatch.setattr(get_settings(), "g1_supervisor_enabled", True)
    client.app.dependency_overrides[get_chat_service] = lambda: ChatService(FakeGraph(), FakeLlm())

    def unavailable(self, *args):
        raise OSError("checkpoint unavailable")

    monkeypatch.setattr(CheckpointRepository, "fresh_writer", unavailable)
    room = create(client)[0]["conversationId"]
    response = client.post(
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
    assert (response.status_code, response.json()["code"]) == (503, "persistence_unavailable")
    detail = client.get(f"/api/chat/conversations/{room}", headers=AUTH).json()
    assert detail["conversationVersion"] == 0 and detail["messages"] == []


@pytest.mark.skipif(
    not os.environ.get("TEST_CATALOG_API_URL") or not os.environ.get("TEST_CHAT_REDIS_URL"),
    reason="real Catalog and disposable Redis are not configured",
)
def test_real_catalog_and_redis_session_expiry_in_persisted_conversation(api, monkeypatch):
    client, _ = api
    monkeypatch.setattr(get_settings(), "g1_supervisor_enabled", True)
    redis_url = os.environ["TEST_CHAT_REDIS_URL"]
    llm = PlanLlm(intent="search", category="lip")
    service = ChatService(
        None,
        llm,
        CatalogClient(os.environ["TEST_CATALOG_API_URL"]),
        sessions=ChatSessionRepository(AsyncRedis.from_url(redis_url, decode_responses=True)),
    )
    client.app.dependency_overrides[get_chat_service] = lambda: service
    room = create(client)[0]["conversationId"]
    first_body = {
        "conversationId": room,
        "requestId": str(uuid4()),
        "expectedConversationVersion": 0,
        "locale": "ko",
        "message": "립 추천해줘",
    }
    first = client.post("/api/chat", headers=AUTH, json=first_body)
    assert first.status_code == 200, first.text
    context = first.json()["chatContext"]
    assert first.json()["products"] and context["session"]
    session = context["session"]
    key = ChatSessionRepository.key(session["sessionId"])
    with Redis.from_url(redis_url, decode_responses=True) as redis:
        assert 0 < redis.ttl(key) <= 600
    dsn = make_url(URL).set(drivername="postgresql").render_as_string(hide_password=False)
    with psycopg.connect(dsn) as conn:
        checkpoint, version = conn.execute(
            "SELECT accepted_checkpoint_id, accepted_checkpoint_version "
            "FROM chat_conversations WHERE id = %s",
            (room,),
        ).fetchone()
    assert checkpoint and version == 1

    forged_context = json.loads(json.dumps(context))
    forged_context["session"]["sessionToken"] = "forged-token-with-no-valid-owner"
    forbidden = client.post(
        "/api/chat",
        headers=AUTH,
        json={
            **first_body,
            "requestId": str(uuid4()),
            "expectedConversationVersion": 1,
            "message": "첫 번째 자세히 알려줘",
            "chatContext": forged_context,
        },
    )
    assert (forbidden.status_code, forbidden.json()["code"]) == (403, "chat_session_forbidden")

    llm.plan = {"intent": "detail", "ordinal": 1}
    active = client.post(
        "/api/chat",
        headers=AUTH,
        json={
            **first_body,
            "requestId": str(uuid4()),
            "expectedConversationVersion": 1,
            "message": "첫 번째 자세히 알려줘",
            "chatContext": context,
        },
    )
    assert active.status_code == 200, active.text
    active_context = active.json()["chatContext"]
    active_key = ChatSessionRepository.key(active_context["session"]["sessionId"])
    with Redis.from_url(redis_url, decode_responses=True) as redis:
        redis.delete(active_key)  # Simulate the 600-second expiry in an isolated Redis.

    expired = client.post(
        "/api/chat",
        headers=AUTH,
        json={
            **first_body,
            "requestId": str(uuid4()),
            "expectedConversationVersion": 2,
            "message": "첫 번째 자세히 알려줘",
            "chatContext": active_context,
        },
    )
    assert expired.status_code == 410, expired.text
    assert expired.json()["code"] == "chat_session_expired"
    llm.plan = {"intent": "search", "category": "lip"}
    fresh = client.post(
        "/api/chat",
        headers=AUTH,
        json={
            **first_body,
            "requestId": str(uuid4()),
            "expectedConversationVersion": 2,
            "message": "립 다시 추천해줘",
            "chatContext": active_context,
        },
    )
    assert fresh.status_code == 200, fresh.text
    assert fresh.json()["chatContext"]["session"]["sessionId"] != session["sessionId"]

    product_id = fresh.json()["products"][0]["id"]
    selection = client.patch(
        f"/api/chat/conversations/{room}/state",
        headers=AUTH,
        json={
            "requestId": str(uuid4()),
            "expectedConversationVersion": 3,
            "operation": "select_product",
            "payload": {"productId": product_id},
        },
    )
    assert selection.status_code == 200, selection.text
    llm.plan = {"intent": "price", "scope": "catalog"}
    detail = client.post(
        "/api/chat",
        headers=AUTH,
        json={
            **first_body,
            "requestId": str(uuid4()),
            "expectedConversationVersion": 4,
            "message": "이 상품 가격 알려줘",
        },
    )
    assert detail.status_code == 200, detail.text
    assert detail.json()["products"][0]["id"] == product_id


@pytest.mark.skipif(
    not os.environ.get("TEST_CATALOG_API_URL"), reason="real Catalog not configured"
)
def test_real_catalog_look_recipe_step_resumes(api, monkeypatch):
    client, _ = api
    monkeypatch.setattr(get_settings(), "g1_supervisor_enabled", True)
    catalog_url = os.environ["TEST_CATALOG_API_URL"]
    looks = httpx.get(f"{catalog_url}/api/style-looks", timeout=15).json()["looks"]
    assert looks
    look_id = looks[0]["id"]
    service = ChatService(None, FakeLlm(), CatalogClient(catalog_url))
    client.app.dependency_overrides[get_chat_service] = lambda: service
    room = create(client)[0]["conversationId"]
    state_path = f"/api/chat/conversations/{room}/state"
    select = client.patch(
        state_path,
        headers=AUTH,
        json={
            "requestId": str(uuid4()),
            "expectedConversationVersion": 0,
            "operation": "select_look",
            "payload": {"kind": "video", "lookId": look_id},
        },
    )
    assert select.status_code == 200, select.text
    body = {
        "conversationId": room,
        "requestId": str(uuid4()),
        "expectedConversationVersion": 1,
        "locale": "ko",
        "message": "단계 알려줘",
    }
    first = client.post("/api/chat", headers=AUTH, json=body)
    assert first.status_code == 200, first.text
    recipe = first.json()["styleRecipe"]
    assert len(recipe["steps"]) > 1
    changed = client.patch(
        state_path,
        headers=AUTH,
        json={
            "requestId": str(uuid4()),
            "expectedConversationVersion": 2,
            "operation": "set_recipe_step",
            "payload": {
                "kind": "video",
                "lookId": look_id,
                "recipeVersion": recipe["recipeVersion"],
                "currentStep": 1,
            },
        },
    )
    assert changed.status_code == 200, changed.text
    followup = client.post(
        "/api/chat",
        headers=AUTH,
        json={
            **body,
            "requestId": str(uuid4()),
            "expectedConversationVersion": 3,
            "message": "현재 단계 알려줘",
        },
    )
    assert followup.status_code == 200, followup.text
    assert followup.json()["styleRecipe"]["currentStep"] == 1


@pytest.mark.skipif(
    not os.environ.get("TEST_CHAT_REDIS_URL"), reason="disposable Redis not configured"
)
def test_persisted_conversation_resumes_g3_pending_ingredient_question(api, monkeypatch):
    client, _ = api
    monkeypatch.setattr(get_settings(), "g1_supervisor_enabled", True)
    llm = G2Llm()
    catalog = SessionCatalog()
    service = ChatService(
        None,
        llm,
        catalog,
        sessions=ChatSessionRepository(
            AsyncRedis.from_url(os.environ["TEST_CHAT_REDIS_URL"], decode_responses=True)
        ),
    )
    client.app.dependency_overrides[get_chat_service] = lambda: service
    room = create(client)[0]["conversationId"]
    body = {
        "conversationId": room,
        "requestId": str(uuid4()),
        "expectedConversationVersion": 0,
        "locale": "ko",
        "message": "3만원 이하 립 추천해줘",
    }
    first = client.post("/api/chat", headers=AUTH, json=body)
    assert first.status_code == 200, first.text
    llm.plan = {
        "intent": "detail",
        "scope": "previous",
        "ordinal": 1,
        "ingredientName": "향료",
        "ingredientLookup": True,
    }
    pending = client.post(
        "/api/chat",
        headers=AUTH,
        json={
            **body,
            "requestId": str(uuid4()),
            "expectedConversationVersion": 1,
            "message": "첫 번째 제품에 향료 있어?",
            "chatContext": first.json()["chatContext"],
        },
    )
    assert pending.status_code == 200, pending.text
    question = pending.json()["pendingClarification"]
    assert question["missingSlot"] == "shade" and question["productId"] == "a"
    llm.plan = {"intent": "detail", "scope": "previous", "shadeName": "03"}
    other_room = create(client)[0]["conversationId"]
    wrong_room = client.post(
        "/api/chat",
        headers=AUTH,
        json={
            **body,
            "conversationId": other_room,
            "requestId": str(uuid4()),
            "message": "03호",
            "chatContext": pending.json()["chatContext"],
            "clarificationId": question["id"],
        },
    )
    assert (wrong_room.status_code, wrong_room.json()["code"]) == (410, "chat_session_expired")
    forged = client.post(
        "/api/chat",
        headers=AUTH,
        json={
            **body,
            "requestId": str(uuid4()),
            "expectedConversationVersion": 2,
            "message": "03호",
            "chatContext": pending.json()["chatContext"],
            "clarificationId": str(uuid4()),
        },
    )
    assert (forged.status_code, forged.json()["code"]) == (409, "chat_clarification_conflict")
    resolved_request_id = str(uuid4())
    resolved = client.post(
        "/api/chat",
        headers=AUTH,
        json={
            **body,
            "requestId": resolved_request_id,
            "expectedConversationVersion": 2,
            "message": "03호",
            "chatContext": pending.json()["chatContext"],
            "clarificationId": question["id"],
        },
    )
    assert resolved.status_code == 200, resolved.text
    result = resolved.json()["ingredientResults"][0]
    assert result["productId"] == "a" and result["shadeId"] == "a-03"
    assert result["conditions"][0]["ingredientName"] == "향료"
    conflict = client.post(
        "/api/chat",
        headers=AUTH,
        json={
            **body,
            "requestId": resolved_request_id,
            "expectedConversationVersion": 2,
            "message": "03호",
            "chatContext": pending.json()["chatContext"],
            "clarificationId": str(uuid4()),
        },
    )
    assert (conflict.status_code, conflict.json()["code"]) == (409, "request_conflict")
    with Redis.from_url(os.environ["TEST_CHAT_REDIS_URL"], decode_responses=True) as redis:
        redis.delete(
            ChatSessionRepository.key(pending.json()["chatContext"]["session"]["sessionId"])
        )
    expired = client.post(
        "/api/chat",
        headers=AUTH,
        json={
            **body,
            "requestId": str(uuid4()),
            "expectedConversationVersion": 3,
            "message": "03호",
            "chatContext": pending.json()["chatContext"],
            "clarificationId": question["id"],
        },
    )
    assert expired.status_code == 410, expired.text


@pytest.mark.skipif(
    not os.environ.get("TEST_CHAT_REDIS_URL"), reason="disposable Redis not configured"
)
def test_persisted_conversation_resumes_g4_verified_option_scope(api, monkeypatch):
    client, _ = api
    monkeypatch.setattr(get_settings(), "g1_supervisor_enabled", True)
    llm = OptionLlm()
    catalog = OptionCatalog()
    service = ChatService(
        None,
        llm,
        catalog,
        sessions=ChatSessionRepository(
            AsyncRedis.from_url(os.environ["TEST_CHAT_REDIS_URL"], decode_responses=True)
        ),
    )
    client.app.dependency_overrides[get_chat_service] = lambda: service
    room = create(client)[0]["conversationId"]
    body = {
        "conversationId": room,
        "requestId": str(uuid4()),
        "expectedConversationVersion": 0,
        "locale": "ko",
        "message": "현재 만원 이하 립 옵션 찾아줘",
    }
    first = client.post("/api/chat", headers=AUTH, json=body)
    assert first.status_code == 200, first.text
    assert first.json()["optionSearch"]["status"] == "PARTIAL"
    context = first.json()["chatContext"]
    context["optionScope"][0]["optionId"] = "forged-option"
    llm.plan = {"intent": "refine", "scope": "previous", "maxPriceKRW": 9000}
    followup = client.post(
        "/api/chat",
        headers=AUTH,
        json={
            **body,
            "requestId": str(uuid4()),
            "expectedConversationVersion": 1,
            "message": "그중 9천원 이하로",
            "chatContext": context,
        },
    )
    assert followup.status_code == 200, followup.text
    assert catalog.calls[-1].option_scope[0].option_id == "synthetic-option"
    assert followup.json()["chatContext"]["session"]["stateVersion"] == 2


def test_redis_session_capability_is_not_persisted_or_replayed(api):
    client, _ = api
    secret, session_id = "s" * 40, uuid4()

    class SessionReply:
        async def answer(self, request, principal_key):
            context = BeautyContext(
                issued_at=1,
                filters=BeautyFilters(),
                session=ChatSessionRef(
                    session_id=session_id,
                    session_token=secret,
                    result_set_id=uuid4(),
                    state_version=1,
                    expires_at=9999999999,
                ),
            )
            return ChatResponse(answer="saved", products=[], chat_context=context)

    client.app.dependency_overrides[get_chat_service] = lambda: SessionReply()
    room = create(client)[0]["conversationId"]
    request_id = str(uuid4())
    body = {
        "conversationId": room,
        "requestId": request_id,
        "expectedConversationVersion": 0,
        "message": "hello",
    }
    initial = client.post("/api/chat", headers=AUTH, json=body)
    assert initial.status_code == 200
    assert secret in initial.text
    detail = client.get(f"/api/chat/conversations/{room}", headers=AUTH)
    assert secret not in detail.text and str(session_id) not in detail.text
    replay = client.post("/api/chat", headers=AUTH, json=body)
    assert replay.status_code == 200
    assert secret not in replay.text and str(session_id) not in replay.text
    assert json.loads(replay.text)["answer"] == "saved"


class ProductCatalog:
    def __init__(self):
        self.calls = 0

    async def get_product(self, product_id):
        self.calls += 1
        if product_id != "lip-1":
            return None
        return SimpleNamespace(id="lip-1", shades=[SimpleNamespace(id="shade-1")])


def test_state_patch_replays_original_snapshot_after_later_changes(api):
    client, fake = api
    fake._catalog = ProductCatalog()
    room = create(client)[0]["conversationId"]
    path = f"/api/chat/conversations/{room}/state"
    first = {
        "requestId": str(uuid4()),
        "expectedConversationVersion": 0,
        "operation": "select_product",
        "payload": {"productId": "lip-1"},
    }
    response = client.patch(path, headers=AUTH, json=first)
    assert response.status_code == 200, response.text
    first_result = response.json()
    assert first_result["conversationVersion"] == 1
    assert first_result["context"]["product"]["selectedProductId"] == "lip-1"
    second = {
        "requestId": str(uuid4()),
        "expectedConversationVersion": 1,
        "operation": "select_shade",
        "payload": {"productId": "lip-1", "shadeId": "shade-1"},
    }
    response2 = client.patch(path, headers=AUTH, json=second)
    assert response2.status_code == 200, response2.text
    assert response2.json()["conversationVersion"] == 2
    assert response2.json()["context"]["product"]["selectedShadeId"] == "shade-1"
    assert client.patch(path, headers=AUTH, json=first).json() == first_result
    assert fake._catalog.calls == 2
    conflict = client.patch(path, headers=AUTH, json={**first, "payload": {"productId": "other"}})
    assert (conflict.status_code, conflict.json()["code"]) == (409, "request_conflict")
    status = client.get(
        f"/api/chat/conversations/{room}/requests/{first['requestId']}", headers=AUTH
    )
    assert status.json()["status"] == "COMMITTED" and status.json()["response"] == first_result
    assert client.patch(path, headers=OTHER, json=first).status_code == 404
    detail = client.get(f"/api/chat/conversations/{room}", headers=AUTH).json()
    assert detail["conversationVersion"] == 2 and detail["messages"] == []


def test_state_patch_rejects_unverified_or_unexpected_input(api):
    client, fake = api
    fake._catalog = ProductCatalog()
    room = create(client)[0]["conversationId"]
    path = f"/api/chat/conversations/{room}/state"
    body = {
        "requestId": str(uuid4()),
        "expectedConversationVersion": 0,
        "operation": "select_shade",
        "payload": {"productId": "lip-1", "shadeId": "wrong"},
    }
    bad_shade = client.patch(path, headers=AUTH, json=body)
    assert (bad_shade.status_code, bad_shade.json()["code"]) == (404, "shade_not_found")
    state = client.get(f"/api/chat/conversations/{room}/requests/{body['requestId']}", headers=AUTH)
    assert state.json()["status"] == "FAILED"
    assert client.patch(path, headers=AUTH, json=body).json()["code"] == "request_failed"
    malformed = client.patch(
        path,
        headers=AUTH,
        json={
            **body,
            "requestId": str(uuid4()),
            "payload": {"productId": "lip-1", "shadeId": "shade-1", "ownerId": "someone"},
        },
    )
    assert malformed.status_code == 400
    detail = client.get(f"/api/chat/conversations/{room}", headers=AUTH).json()
    assert detail["conversationVersion"] == 0 and detail["messages"] == []


def test_clearing_selection_removes_selected_product_and_shade(api):
    client, fake = api
    fake._catalog = ProductCatalog()
    room = create(client)[0]["conversationId"]
    path = f"/api/chat/conversations/{room}/state"
    first = {
        "requestId": str(uuid4()),
        "expectedConversationVersion": 0,
        "operation": "select_shade",
        "payload": {"productId": "lip-1", "shadeId": "shade-1"},
    }
    assert client.patch(path, headers=AUTH, json=first).status_code == 200
    clear = {
        "requestId": str(uuid4()),
        "expectedConversationVersion": 1,
        "operation": "clear_selection",
        "payload": {},
    }
    response = client.patch(path, headers=AUTH, json=clear)
    assert response.status_code == 200
    product = response.json()["context"]["product"]
    assert "selectedProductId" not in product and "selectedShadeId" not in product


def test_deleting_room_removes_state_result_snapshot(api):
    client, _ = api
    room = create(client)[0]["conversationId"]
    request_id = str(uuid4())
    body = {
        "requestId": request_id,
        "expectedConversationVersion": 0,
        "operation": "clear_selection",
        "payload": {},
    }
    assert (
        client.patch(f"/api/chat/conversations/{room}/state", headers=AUTH, json=body).status_code
        == 200
    )
    dsn = make_url(URL).set(drivername="postgresql").render_as_string(hide_password=False)
    with psycopg.connect(dsn) as conn:
        assert (
            conn.execute(
                "SELECT result_payload FROM chat_turns WHERE owner_id = %s AND request_id = %s",
                ("user-ok-1", request_id),
            ).fetchone()[0]
            is not None
        )
    assert client.delete(f"/api/chat/conversations/{room}", headers=AUTH).status_code == 204
    with psycopg.connect(dsn) as conn:
        assert (
            conn.execute(
                "SELECT result_payload FROM chat_turns WHERE owner_id = %s AND request_id = %s",
                ("user-ok-1", request_id),
            ).fetchone()
            is None
        )

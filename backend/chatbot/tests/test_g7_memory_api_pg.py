import os
from uuid import uuid4

import psycopg
import pytest
from redis.asyncio import Redis as AsyncRedis
from sqlalchemy.engine import make_url

from app.core.config import get_settings
from app.core.db import get_chat_engine
from app.core.ratelimit import MemoryRateLimiter, get_rate_limiter
from app.repositories.chat_session_repository import ChatSessionRepository
from app.schemas.chat import ChatRequest, ChatResponse
from app.services.chat_service import ChatService, get_chat_service
from app.services.conversation_service import ConversationService
from tests.test_chat_sessions import SessionCatalog
from tests.test_g2_multiturn import G2Llm

URL = os.environ.get("TEST_CHAT_DATABASE_URL")
pytestmark = [pytest.mark.integration, pytest.mark.skipif(not URL, reason="test database required")]
AUTH = {"Authorization": "Bearer ok-memory"}
OTHER = {"Authorization": "Bearer ok-other"}


class RecordingChat:
    def __init__(self):
        self.calls = []

    async def answer(self, request, principal_key):
        self.calls.append(
            {
                "memories": list(request._consented_memories),
                "history": [item.text for item in request.recent_messages],
            }
        )
        return ChatResponse(answer="answer", products=[])


@pytest.fixture
def memory_api(client, monkeypatch):
    if make_url(URL).database != "vishue_chat_test":
        raise RuntimeError("G7 tests require disposable vishue_chat_test")
    settings = get_settings()
    monkeypatch.setitem(AUTH, "Authorization", f"Bearer ok-memory-{uuid4()}")
    monkeypatch.setattr(settings, "env", "local")
    monkeypatch.setattr(settings, "g7_persistence_enabled", True)
    monkeypatch.setattr(settings, "g7_memory_enabled", True)
    monkeypatch.setattr(settings, "chat_database_url", URL)
    get_chat_engine.cache_clear()
    chat = RecordingChat()
    client.app.dependency_overrides[get_chat_service] = lambda: chat
    client.app.dependency_overrides[get_rate_limiter] = lambda: MemoryRateLimiter(limit=1000)
    with client:
        yield client, chat


def new_room(client):
    result = client.post(
        "/api/chat/conversations",
        headers=AUTH,
        json={
            "requestId": str(uuid4()),
            "entry": {"type": "general"},
        },
    )
    assert result.status_code == 201, result.text
    return result.json()["conversationId"]


def ask(client, room, version, message, request_id=None):
    response = client.post(
        "/api/chat",
        headers=AUTH,
        json={
            "conversationId": room,
            "requestId": request_id or str(uuid4()),
            "expectedConversationVersion": version,
            "locale": "ko",
            "message": message,
        },
    )
    assert response.status_code == 200, response.text
    return response.json()


def test_previous_fingerprint_schema_replays_and_new_schema_checks_style(memory_api):
    client, chat = memory_api
    room = new_room(client)
    body = {
        "conversationId": room,
        "requestId": str(uuid4()),
        "expectedConversationVersion": 0,
        "locale": "ko",
        "message": "추천 룩 비교해줘",
        "styleSearch": True,
    }
    first = client.post("/api/chat", headers=AUTH, json=body)
    assert first.status_code == 200, first.text
    changed = {
        **body,
        "styleCompare": True,
        "previousStyleCandidates": [{"kind": "video", "lookId": "ST-A"}],
    }
    conflict = client.post("/api/chat", headers=AUTH, json=changed)
    assert (conflict.status_code, conflict.json()["code"]) == (409, "request_conflict")

    owner_id = "user-" + AUTH["Authorization"].removeprefix("Bearer ")
    legacy_hash = ConversationService._request_fingerprint(
        owner_id, ChatRequest.model_validate(changed), legacy=True
    )
    dsn = make_url(URL).set(drivername="postgresql").render_as_string(hide_password=False)
    with psycopg.connect(dsn) as conn:
        conn.execute(
            "UPDATE chat_turns SET fingerprint = %s, fingerprint_schema = 1 "
            "WHERE owner_id = %s AND request_id = %s",
            (legacy_hash, owner_id, body["requestId"]),
        )
    before = len(chat.calls)
    replay = client.post("/api/chat", headers=AUTH, json=changed)
    assert replay.status_code == 200, replay.text
    assert replay.json() == first.json() and len(chat.calls) == before


def test_consent_ownership_idempotency_and_redaction(memory_api):
    client, chat = memory_api
    room = new_room(client)
    ordinary = ask(client, room, 0, "코랄 립이 좋아요")
    assert ordinary.get("memoryProposal") is None
    assert client.get("/api/chat/memories", headers=AUTH).json() == {"memories": []}
    proposal_request_id = str(uuid4())
    proposed = ask(client, room, 1, "코랄 립을 다음에도 기억해줘", proposal_request_id)
    assert "확인" in proposed["answer"] and "기억했" not in proposed["answer"]
    proposal = proposed["memoryProposal"]
    replay = ask(client, room, 1, "코랄 립을 다음에도 기억해줘", proposal_request_id)
    assert replay["memoryProposal"] == proposal
    assert client.get("/api/chat/memories", headers=AUTH).json() == {"memories": []}
    body = {
        "requestId": str(uuid4()),
        "proposalId": proposal["proposalId"],
        "expectedProposalVersion": proposal["version"],
        "confirmed": True,
    }
    assert client.post("/api/chat/memories", headers=OTHER, json=body).status_code == 404
    assert (
        client.post(
            "/api/chat/memories", headers=AUTH, json={**body, "confirmed": False}
        ).status_code
        == 400
    )
    created = client.post("/api/chat/memories", headers=AUTH, json=body)
    assert created.status_code == 200, created.text
    assert client.post("/api/chat/memories", headers=AUTH, json=body).json() == created.json()
    memory_id = created.json()["memoryId"]
    assert len(client.get("/api/chat/memories", headers=AUTH).json()["memories"]) == 1
    another = new_room(client)
    ask(client, another, 0, "어떤 색이 좋아요?")
    assert "코랄 립을 다음에도 기억해줘" in chat.calls[-1]["memories"]
    state_body = {
        "requestId": str(uuid4()),
        "expectedConversationVersion": 1,
        "operation": "clear_selection",
        "payload": {},
    }
    state_path = f"/api/chat/conversations/{another}/state"
    assert client.patch(state_path, headers=AUTH, json=state_body).status_code == 200
    delete_key = str(uuid4())
    assert (
        client.delete(
            f"/api/chat/memories/{memory_id}", headers={**AUTH, "Idempotency-Key": delete_key}
        ).status_code
        == 204
    )
    assert (
        client.delete(
            f"/api/chat/memories/{memory_id}", headers={**AUTH, "Idempotency-Key": delete_key}
        ).status_code
        == 204
    )
    assert client.get("/api/chat/memories", headers=AUTH).json() == {"memories": []}
    replay_deleted = client.post("/api/chat/memories", headers=AUTH, json=body)
    assert (replay_deleted.status_code, replay_deleted.json()["code"]) == (410, "memory_deleted")
    cannot_reuse = client.post(
        "/api/chat/memories", headers=AUTH, json={**body, "requestId": str(uuid4())}
    )
    assert (cannot_reuse.status_code, cannot_reuse.json()["code"]) == (409, "proposal_expired")
    dsn = make_url(URL).set(drivername="postgresql").render_as_string(hide_password=False)
    with psycopg.connect(dsn) as conn:
        value, revoked_at = conn.execute(
            "SELECT value_json, revoked_at FROM chat_memories WHERE id = %s", (memory_id,)
        ).fetchone()
        assert value is None and revoked_at is not None
        columns = conn.execute(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_name = 'chat_memory_proposals'"
        ).fetchall()
        assert "value_json" not in {column[0] for column in columns}
    assert (
        client.patch(state_path, headers=AUTH, json=state_body).json()["code"]
        == "memory_context_changed"
    )
    status = client.get(
        f"/api/chat/conversations/{another}/requests/{state_body['requestId']}", headers=AUTH
    )
    assert status.status_code == 409 and status.json()["code"] == "memory_context_changed"
    ask(client, room, 2, "다른 조언을 해줘")
    assert chat.calls[-1]["memories"] == []
    assert "코랄 립을 다음에도 기억해줘" not in chat.calls[-1]["history"]
    assert "코랄 립이 좋아요" not in chat.calls[-1]["history"]
    ask(client, another, 2, "다시 설명해줘")
    assert chat.calls[-1]["memories"] == [] and chat.calls[-1]["history"] == []


def test_memory_edit_compare_and_swap_and_proposal_invalidation(memory_api):
    client, chat = memory_api
    room = new_room(client)
    proposal = ask(client, room, 0, "매트 립을 기억해줘")["memoryProposal"]
    body = {
        "requestId": str(uuid4()),
        "proposalId": proposal["proposalId"],
        "expectedProposalVersion": 1,
        "confirmed": True,
    }
    created = client.post("/api/chat/memories", headers=AUTH, json=body).json()
    memory_id = created["memoryId"]
    pending = ask(client, room, 1, "새틴도 기억해줘")["memoryProposal"]
    another = new_room(client)
    ask(client, another, 0, "기존 취향으로 상담해줘")
    assert "매트 립을 기억해줘" in chat.calls[-1]["memories"]
    edit = {"requestId": str(uuid4()), "expectedVersion": 1, "confirmed": True, "value": "새틴 립"}
    updated = client.patch(f"/api/chat/memories/{memory_id}", headers=AUTH, json=edit)
    assert updated.status_code == 200 and updated.json()["memoryVersion"] == 2
    ask(client, another, 1, "다시 추천해줘")
    assert chat.calls[-1]["memories"] == ["새틴 립"]
    assert chat.calls[-1]["history"] == []
    assert (
        client.patch(f"/api/chat/memories/{memory_id}", headers=AUTH, json=edit).json()
        == updated.json()
    )
    stale = client.patch(
        f"/api/chat/memories/{memory_id}", headers=AUTH, json={**edit, "requestId": str(uuid4())}
    )
    assert (stale.status_code, stale.json()["code"]) == (409, "memory_conflict")
    invalid = client.post(
        "/api/chat/memories",
        headers=AUTH,
        json={
            "requestId": str(uuid4()),
            "proposalId": pending["proposalId"],
            "expectedProposalVersion": 1,
            "confirmed": True,
        },
    )
    assert (invalid.status_code, invalid.json()["code"]) == (409, "proposal_expired")


@pytest.mark.parametrize(
    ("text", "kind"),
    [
        ("내 피부 타입은 건성이라고 기억해줘", "profile"),
        ("클리오 립을 가지고 있다고 기억해줘", "owned_product"),
    ],
)
def test_proposal_kind_and_exact_content_are_visible_before_confirmation(memory_api, text, kind):
    client, _ = memory_api
    proposal = ask(client, new_room(client), 0, text)["memoryProposal"]
    assert proposal["kind"] == kind and proposal["value"] == text
    assert proposal["consentScope"] == "future_consultations"
    assert client.get("/api/chat/memories", headers=AUTH).json() == {"memories": []}


def test_expired_proposal_cannot_be_confirmed(memory_api):
    client, _ = memory_api
    proposal = ask(client, new_room(client), 0, "코랄 립을 기억해줘")["memoryProposal"]
    dsn = make_url(URL).set(drivername="postgresql").render_as_string(hide_password=False)
    with psycopg.connect(dsn) as conn:
        conn.execute(
            "UPDATE chat_memory_proposals SET expires_at = now() - interval '1 second' "
            "WHERE id = %s",
            (proposal["proposalId"],),
        )
    response = client.post(
        "/api/chat/memories",
        headers=AUTH,
        json={
            "requestId": str(uuid4()),
            "proposalId": proposal["proposalId"],
            "expectedProposalVersion": 1,
            "confirmed": True,
        },
    )
    assert (response.status_code, response.json()["code"]) == (409, "proposal_expired")
    assert client.get("/api/chat/memories", headers=AUTH).json() == {"memories": []}


@pytest.mark.skipif(not os.environ.get("TEST_CHAT_REDIS_URL"), reason="disposable Redis required")
def test_memory_edit_invalidates_old_redis_candidates(memory_api, monkeypatch):
    client, _ = memory_api
    source = new_room(client)
    proposal = ask(client, source, 0, "코랄 립 기억해줘")["memoryProposal"]
    created = client.post(
        "/api/chat/memories",
        headers=AUTH,
        json={
            "requestId": str(uuid4()),
            "proposalId": proposal["proposalId"],
            "expectedProposalVersion": 1,
            "confirmed": True,
        },
    ).json()
    monkeypatch.setattr(get_settings(), "g1_supervisor_enabled", True)
    llm = G2Llm()
    chat = ChatService(
        None,
        llm,
        SessionCatalog(),
        sessions=ChatSessionRepository(
            AsyncRedis.from_url(os.environ["TEST_CHAT_REDIS_URL"], decode_responses=True)
        ),
    )
    client.app.dependency_overrides[get_chat_service] = lambda: chat
    room = new_room(client)
    initial = ask(client, room, 0, "3만원 이하 립 추천해줘")
    old_context = initial["chatContext"]
    changed = client.patch(
        f"/api/chat/memories/{created['memoryId']}",
        headers=AUTH,
        json={
            "requestId": str(uuid4()),
            "expectedVersion": 1,
            "confirmed": True,
            "value": "매트 립",
        },
    )
    assert changed.status_code == 200
    llm.plan = {"intent": "detail", "scope": "previous", "ordinal": 1}
    stale = client.post(
        "/api/chat",
        headers=AUTH,
        json={
            "conversationId": room,
            "requestId": str(uuid4()),
            "expectedConversationVersion": 1,
            "locale": "ko",
            "message": "첫 번째 가격",
            "chatContext": old_context,
        },
    )
    assert (stale.status_code, stale.json()["code"]) == (410, "chat_session_expired")
    llm.plan = {"intent": "search", "scope": "catalog", "category": "lip"}
    fresh = client.post(
        "/api/chat",
        headers=AUTH,
        json={
            "conversationId": room,
            "requestId": str(uuid4()),
            "expectedConversationVersion": 1,
            "locale": "ko",
            "message": "립 다시 추천해줘",
            "chatContext": old_context,
        },
    )
    assert fresh.status_code == 200, fresh.text
    assert (
        fresh.json()["chatContext"]["session"]["sessionId"] != old_context["session"]["sessionId"]
    )

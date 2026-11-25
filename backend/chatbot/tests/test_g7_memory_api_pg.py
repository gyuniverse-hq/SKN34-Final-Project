import json
import os
from datetime import UTC, datetime, timedelta
from typing import get_args
from unittest.mock import Mock
from uuid import uuid4

import httpx
import psycopg
import pytest
from redis.asyncio import Redis as AsyncRedis
from sqlalchemy.engine import make_url

from app.clients.catalog_client import CatalogClient
from app.clients.skincare_recommendation_client import SkincareRecommendationClient
from app.core.config import get_settings
from app.core.db import get_chat_engine
from app.core.ratelimit import MemoryRateLimiter, get_rate_limiter
from app.repositories.chat_session_repository import ChatSessionRepository
from app.schemas.catalog import CatalogShade
from app.schemas.chat import ChatRequest, ChatResponse
from app.schemas.skincare_recommendation import SkinGoal
from app.services import memory_service
from app.services.chat_service import ChatService, build_messages, get_chat_service
from app.services.conversation_service import ConversationService
from app.services.skincare_recommendation_tool import SkincareRecommendationTool
from tests.conftest import FakeGraph
from tests.test_beauty_consultation import Catalog, PlanLlm, product
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


def ask(client, room, version, message, request_id=None, *, structured=False, request_type="chat"):
    response = client.post(
        "/api/chat",
        headers=AUTH,
        json={
            "conversationId": room,
            "requestId": request_id or str(uuid4()),
            "expectedConversationVersion": version,
            "locale": "ko",
            "message": message,
            "requestType": request_type,
            **({"structuredMemory": True} if structured else {}),
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
        ("  코랄 립을\n기억해줘.  ", "preference"),
    ],
)
def test_proposal_and_saved_memory_preserve_original_text(memory_api, text, kind):
    client, _ = memory_api
    proposal = ask(client, new_room(client), 0, text)["memoryProposal"]
    assert proposal["kind"] == kind and proposal["value"] == text
    assert proposal["consentScope"] == "future_consultations"
    assert client.get("/api/chat/memories", headers=AUTH).json() == {"memories": []}
    created = client.post(
        "/api/chat/memories",
        headers=AUTH,
        json={
            "requestId": str(uuid4()),
            "proposalId": proposal["proposalId"],
            "expectedProposalVersion": proposal["version"],
            "confirmed": True,
        },
    )
    assert created.status_code == 200, created.text
    memory_id = created.json()["memoryId"]
    assert client.get("/api/chat/memories", headers=AUTH).json() == {
        "memories": [
            {
                "id": memory_id,
                "kind": kind,
                "value": text,
                "version": 1,
                "consentScope": "future_consultations",
            }
        ]
    }
    dsn = make_url(URL).set(drivername="postgresql").render_as_string(hide_password=False)
    with psycopg.connect(dsn) as conn:
        stored = conn.execute(
            "SELECT value_json FROM chat_memories WHERE id = %s", (memory_id,)
        ).fetchone()
    assert stored == ({"text": text},)


def test_proposal_has_exactly_fifteen_minutes_and_expires_at_boundary(memory_api, monkeypatch):
    client, _ = memory_api
    room = new_room(client)
    request_id = str(uuid4())
    text = "코랄 립을 기억해줘"
    proposal = ask(client, room, 0, text, request_id)["memoryProposal"]
    dsn = make_url(URL).set(drivername="postgresql").render_as_string(hide_password=False)
    with psycopg.connect(dsn) as conn:
        issued_at, expires_at = conn.execute(
            "SELECT created_at, expires_at FROM chat_memory_proposals WHERE id = %s",
            (proposal["proposalId"],),
        ).fetchone()
    assert expires_at - issued_at == timedelta(minutes=15)

    clock = Mock()
    monkeypatch.setattr(memory_service, "datetime", clock)
    clock.now.return_value = expires_at - timedelta(microseconds=1)
    assert ask(client, room, 0, text, request_id)["memoryProposal"] == proposal

    clock.now.return_value = expires_at
    assert ask(client, room, 0, text, request_id).get("memoryProposal") is None
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


def test_structured_memory_partial_approval_preserves_versions_and_sources(memory_api, monkeypatch):
    client, chat = memory_api
    monkeypatch.setattr(get_settings(), "g7_structured_memory_enabled", True)
    room = new_room(client)
    source = (
        "나는 건성이야, 출근할 때 코랄 립을 좋아하고, "
        "매트 베이스를 선호하고, A 파운데이션을 갖고 있어, 기억해줘"
    )
    asked = ask(client, room, 0, source, structured=True)
    assert asked.get("memoryProposal") is None
    assert len(chat.calls) == 1
    path = "/api/chat/v2/memory-proposals"
    params = {"conversationId": room}
    assert client.get(path, headers=OTHER, params=params).status_code == 404
    (group,) = client.get(path, headers=AUTH, params=params).json()
    items = {item["key"]: item for item in group["items"]}
    assert set(items) == {"skin.type", "makeup.color", "makeup.finish", "inventory.product"}
    assert items["makeup.color"]["value"] == {"area": "lip", "family": "coral"}
    assert items["makeup.color"]["context"] == "work"
    assert items["inventory.product"]["value"] == {"productName": "A 파운데이션"}
    group_path = f"{path}/{group['groupId']}"
    color = items["makeup.color"]
    edit = {"requestId": str(uuid4()), "expectedVersion": color["version"], "value": "pink"}
    edited = client.patch(f"{group_path}/{color['itemId']}", headers=AUTH, json=edit)
    assert edited.status_code == 200, edited.text
    assert edited.json()["value"] == {"area": "lip", "family": "pink"}
    assert (
        client.patch(f"{group_path}/{color['itemId']}", headers=AUTH, json=edit).json()
        == edited.json()
    )

    def decision(item, action="approve"):
        return {
            "itemId": item["itemId"],
            "expectedVersion": item["version"],
            "action": action,
            **({"confirmed": True} if action == "approve" else {}),
        }

    decisions_path = f"{group_path}/decisions"
    stale = {
        "requestId": str(uuid4()),
        "decisions": [decision(items["skin.type"]), decision(color)],
    }
    assert client.post(decisions_path, headers=AUTH, json=stale).status_code == 409
    assert client.get("/api/chat/v2/memories", headers=AUTH).json() == {"memories": []}
    body = {
        "requestId": str(uuid4()),
        "decisions": [
            decision(items["skin.type"]),
            decision(edited.json()),
            decision(items["makeup.finish"], "reject"),
            decision(items["inventory.product"], "defer"),
        ],
    }
    assert client.post(decisions_path, headers=OTHER, json=body).status_code == 404
    approved = client.post(decisions_path, headers=AUTH, json=body)
    assert approved.status_code == 200, approved.text
    assert client.post(decisions_path, headers=AUTH, json=body).json() == approved.json()
    (open_group,) = client.get(path, headers=AUTH, params=params).json()
    assert open_group["expiresAt"] == group["expiresAt"]
    assert [(item["key"], item["status"]) for item in open_group["items"]] == [
        ("inventory.product", "deferred")
    ]

    assert client.get("/api/chat/memories", headers=AUTH).json() == {"memories": []}
    listed = client.get("/api/chat/v2/memories", headers=AUTH).json()["memories"]
    assert {item["key"] for item in listed} == {"skin.type", "makeup.color"}
    color_id = next(item["id"] for item in listed if item["key"] == "makeup.color")
    dsn = make_url(URL).set(drivername="postgresql").render_as_string(hide_password=False)
    with psycopg.connect(dsn) as conn:
        assert conn.execute(
            "SELECT count(message_id), count(edit_request_id) FROM chat_memory_sources "
            "WHERE memory_id = %s",
            (color_id,),
        ).fetchone() == (1, 1)
        assert conn.execute(
            "SELECT expires_at - created_at FROM chat_memory_proposal_groups WHERE id = %s",
            (group["groupId"],),
        ).fetchone() == (timedelta(minutes=15),)
        conn.execute("DELETE FROM chat_messages WHERE conversation_id = %s", (room,))
    assert client.get(path, headers=AUTH, params=params).json() == []
    assert client.get("/api/chat/v2/memories", headers=AUTH).json()["memories"] == listed
    with psycopg.connect(dsn) as conn:
        assert conn.execute(
            "SELECT count(message_id) FROM chat_memory_sources WHERE memory_id = %s",
            (color_id,),
        ).fetchone() == (0,)
    delete_headers = {**AUTH, "Idempotency-Key": str(uuid4())}
    assert (
        client.delete(f"/api/chat/memories/{color_id}", headers=delete_headers).status_code == 404
    )
    assert (
        client.delete(f"/api/chat/v2/memories/{color_id}", headers=delete_headers).status_code
        == 204
    )


def test_structured_proposal_uses_prior_user_source_and_expires(memory_api, monkeypatch):
    client, _ = memory_api
    monkeypatch.setattr(get_settings(), "g7_structured_memory_enabled", True)
    room = new_room(client)
    ask(client, room, 0, "나는 복합성이야", structured=True)
    ask(client, room, 1, "방금 말한 내용을 기억해줘", structured=True)
    path = "/api/chat/v2/memory-proposals"
    params = {"conversationId": room}
    (group,) = client.get(path, headers=AUTH, params=params).json()
    (item,) = group["items"]
    assert item["value"] == {"type": "combination"}
    dsn = make_url(URL).set(drivername="postgresql").render_as_string(hide_password=False)
    with psycopg.connect(dsn) as conn:
        assert conn.execute(
            "SELECT count(message_id) FROM chat_memory_sources WHERE item_id = %s",
            (item["itemId"],),
        ).fetchone() == (2,)
        conn.execute(
            "UPDATE chat_memory_proposal_groups SET expires_at = now() WHERE id = %s",
            (group["groupId"],),
        )
    assert client.get(path, headers=AUTH, params=params).json() == []
    outcome = client.post(
        f"{path}/{group['groupId']}/decisions",
        headers=AUTH,
        json={
            "requestId": str(uuid4()),
            "decisions": [
                {
                    "itemId": item["itemId"],
                    "expectedVersion": item["version"],
                    "action": "approve",
                    "confirmed": True,
                }
            ],
        },
    )
    assert (outcome.status_code, outcome.json()["code"]) == (410, "proposal_expired")


def test_structured_skin_replacement_and_second_decision_use_latest_versions(
    memory_api, monkeypatch
):
    client, _ = memory_api
    monkeypatch.setattr(get_settings(), "g7_structured_memory_enabled", True)
    room = new_room(client)
    path = "/api/chat/v2/memory-proposals"
    params = {"conversationId": room}

    def current_group():
        (group,) = client.get(path, headers=AUTH, params=params).json()
        return group

    def approve(group, key):
        item = next(item for item in group["items"] if item["key"] == key)
        response = client.post(
            f"{path}/{group['groupId']}/decisions",
            headers=AUTH,
            json={
                "requestId": str(uuid4()),
                "decisions": [
                    {
                        "itemId": item["itemId"],
                        "expectedVersion": item["version"],
                        "action": "approve",
                        "confirmed": True,
                    }
                ],
            },
        )
        assert response.status_code == 200, response.text
        return response.json()["items"][0]

    ask(client, room, 0, "내 피부 타입은 건성이야, 기억해줘", structured=True)
    first = approve(current_group(), "skin.type")
    ask(
        client,
        room,
        1,
        "내 피부 타입은 지성이야, 매트 베이스를 선호해, B 파운데이션을 갖고 있어, 기억해줘",
        structured=True,
    )
    group = current_group()
    changed_skin = next(item for item in group["items"] if item["key"] == "skin.type")
    assert changed_skin["previousDisplayValue"] == "건성"
    saved = approve(group, "skin.type")
    assert saved["memoryId"] == first["memoryId"] and saved["memoryVersion"] == 2
    approve(current_group(), "makeup.finish")
    approve(current_group(), "inventory.product")
    assert client.get(path, headers=AUTH, params=params).json() == []
    memories = client.get("/api/chat/v2/memories", headers=AUTH).json()["memories"]
    assert {memory["key"]: memory["value"] for memory in memories} == {
        "skin.type": "지성",
        "makeup.finish": "베이스 · 매트",
        "inventory.product": "B 파운데이션 (상품 미확인)",
    }


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
    legacy = client.post(
        "/api/chat",
        headers=AUTH,
        json={"locale": "ko", "message": "첫 번째 가격", "chatContext": old_context},
    )
    assert (legacy.status_code, legacy.json()["code"]) == (410, "chat_session_expired")
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
    fresh_context = fresh.json()["chatContext"]
    assert fresh_context["session"]["sessionId"] != old_context["session"]["sessionId"]
    assert client.delete(f"/api/chat/conversations/{room}", headers=AUTH).status_code == 204
    llm.plan = {"intent": "detail", "scope": "previous", "ordinal": 1}
    after_deletion = client.post(
        "/api/chat",
        headers=AUTH,
        json={"locale": "ko", "message": "첫 번째 가격", "chatContext": fresh_context},
    )
    assert (after_deletion.status_code, after_deletion.json()["code"]) == (
        410,
        "chat_session_expired",
    )


def test_memory_policy_and_catalog_application_end_to_end(memory_api, monkeypatch):
    client, chat = memory_api
    config = get_settings()
    monkeypatch.setattr(config, "g7_structured_memory_enabled", True)
    monkeypatch.setattr(config, "g1_supervisor_enabled", False)
    room = new_room(client)
    settings_path = "/api/chat/v2/memory-settings"
    memories_path = "/api/chat/v2/memories"
    groups_path = "/api/chat/v2/memory-proposals"
    params = {"conversationId": room}

    def settings():
        response = client.get(settings_path, headers=AUTH)
        assert response.status_code == 200, response.text
        return response.json()

    def mode(enabled):
        response = client.patch(
            settings_path,
            headers=AUTH,
            json={
                "requestId": str(uuid4()),
                "expectedVersion": settings()["version"],
                "enabled": enabled,
                "acknowledgeNotice": True,
            },
        )
        assert response.status_code == 200, response.text
        return response.json()

    def approve(group):
        return client.post(
            f"{groups_path}/{group['groupId']}/decisions",
            headers=AUTH,
            json={
                "requestId": str(uuid4()),
                "decisions": [
                    {
                        "itemId": item["itemId"],
                        "expectedVersion": item["version"],
                        "action": "approve",
                        "confirmed": True,
                    }
                    for item in group["items"]
                ],
            },
        )

    initial = settings()
    assert initial["enabled"] and not initial["noticeAcknowledged"]
    ask(client, room, 0, "나는 매트 립을 선호해, 기억해줘", structured=True)
    (group,) = client.get(groups_path, headers=AUTH, params=params).json()
    approved = approve(group)
    assert approved.status_code == 200, approved.text
    memory_id = approved.json()["items"][0]["memoryId"]
    original = "  코랄 립을 기억해줘  "
    legacy = ask(client, room, 1, original)["memoryProposal"]
    created = client.post(
        "/api/chat/memories",
        headers=AUTH,
        json={
            "requestId": str(uuid4()),
            "proposalId": legacy["proposalId"],
            "expectedProposalVersion": legacy["version"],
            "confirmed": True,
        },
    )
    assert created.status_code == 200, created.text
    original_id = created.json()["memoryId"]
    ask(client, room, 2, "나는 건성이야, 기억해줘", structured=True)
    (pending,) = client.get(groups_path, headers=AUTH, params=params).json()

    class PromptChat:
        async def answer(self, request, principal_key):
            prompt = build_messages(request, [])[0]["content"]
            assert original in prompt
            assert "makeup.finish" in prompt
            assert "건성이야" not in prompt
            return ChatResponse(answer="관련 상담 답변", products=[])

    client.app.dependency_overrides[get_chat_service] = PromptChat
    prompt_room = new_room(client)
    answer = ask(client, prompt_room, 0, "립 마무리 방법이 궁금해", structured=True)
    assert "appliedMemories" not in answer
    dsn = make_url(URL).set(drivername="postgresql").render_as_string(hide_password=False)
    with psycopg.connect(dsn) as conn:
        (refs,) = conn.execute(
            "SELECT memory_refs FROM chat_messages "
            "WHERE conversation_id = %s AND role = 'assistant'",
            (prompt_room,),
        ).fetchone()
        assert {item["memoryId"] for item in refs} == {original_id, memory_id}

    catalog = Catalog()
    catalog.products[0].texture = "glossy"
    llm = PlanLlm(intent="search", category="lip", maxPriceKRW=20000)
    service = ChatService(None, llm, catalog)
    client.app.dependency_overrides[get_chat_service] = lambda: service
    target = new_room(client)
    query = "2만원 이하 립 추천해줘"
    rid = str(uuid4())
    first = ask(client, target, 0, query, rid, structured=True, request_type="beauty_consultation")
    assert [p["id"] for p in first["products"]] == ["b", "a"]
    assert first["appliedMemories"] == [
        {
            "memoryId": memory_id,
            "version": 1,
            "key": "makeup.finish",
            "tool": "catalog.search_products",
            "field": "texture",
            "applicationKind": "ranking",
        }
    ]
    assert original not in str(llm.messages)
    ignored = ask(
        client,
        target,
        1,
        "기억 반영하지 말고 2만원 이하 립 추천해줘",
        structured=True,
        request_type="beauty_consultation",
    )
    assert [p["id"] for p in ignored["products"]] == ["a", "b"]
    assert "appliedMemories" not in ignored
    explicit = ask(
        client,
        target,
        2,
        "글로시한 2만원 이하 립 추천해줘",
        structured=True,
        request_type="beauty_consultation",
    )
    assert "appliedMemories" not in explicit

    disabled = mode(False)
    assert not disabled["enabled"] and disabled["noticeAcknowledged"]
    assert len(client.get(memories_path, headers=AUTH).json()["memories"]) == 2
    patch = client.patch(
        f"{memories_path}/{memory_id}",
        headers=AUTH,
        json={
            "requestId": str(uuid4()),
            "expectedVersion": 1,
            "confirmed": True,
            "value": "satin",
            "locale": "ko",
        },
    )
    assert patch.status_code == 200 and patch.json()["version"] == 2
    off = ask(client, target, 3, query, structured=True, request_type="beauty_consultation")
    assert [p["id"] for p in off["products"]] == ["a", "b"] and "appliedMemories" not in off
    replay = ask(client, target, 0, query, rid, structured=True, request_type="beauty_consultation")
    assert "appliedMemories" not in replay
    blocked = approve(pending)
    assert blocked.status_code == 409 and blocked.json()["code"] == "memory_disabled"
    assert mode(True)["enabled"]
    assert client.get(groups_path, headers=AUTH, params=params).json() == []
    client.app.dependency_overrides[get_chat_service] = lambda: chat
    ask(client, room, 3, "치크는 코랄을 좋아해, 기억해줘", structured=True)
    (to_clear,) = client.get(groups_path, headers=AUTH, params=params).json()
    before = settings()
    clear = {
        "requestId": str(uuid4()),
        "expectedVersion": before["version"],
        "expectedMemorySetRevision": before["memorySetRevision"],
        "confirmed": True,
    }
    deleted = client.post(f"{memories_path}/delete-all", headers=AUTH, json=clear)
    assert deleted.status_code == 200 and deleted.json()["enabled"]
    assert (
        client.post(f"{memories_path}/delete-all", headers=AUTH, json=clear).json()
        == deleted.json()
    )
    assert client.get(memories_path, headers=AUTH).json() == {"memories": []}
    blocked = approve(to_clear)
    assert blocked.status_code == 409 and blocked.json()["code"] == "memory_proposal_changed"
    detail = client.get(f"/api/chat/conversations/{target}", headers=AUTH).json()
    assert len(detail["messages"]) == 8
    assert all("appliedMemories" not in item["displayPayload"] for item in detail["messages"])


class SkincareHttpFixture:
    def __init__(self):
        self.products = {}
        for name, price in (("profile-match", 15000), ("over-budget", 25000), ("fragrance", 10000)):
            item = product(name, price, category="skincare")
            item.shades = []
            self.products[name] = item.model_dump(mode="json", by_alias=True) | {
                "volume": "50 ml",
                "imageUrl": "",
                "searchKeyword": name,
            }
        self.v4_calls = []
        self.option_calls = []
        self.unavailable = False
        self.unmatched_option = False

    def __call__(self, request):
        if request.url.path == "/api/products":
            return httpx.Response(200, json={"products": list(self.products.values())})
        body = json.loads(request.content)
        if request.url.path == "/api/recommendations/skincare/v4":
            self.v4_calls.append(body)
            if self.unavailable:
                return httpx.Response(503, json={})
            goal = body["detectedConcerns"][0]["goal"]
            matches = [
                {
                    "product": item,
                    "optionId": "option-" + name,
                    "optionName": name,
                    "priceKRW": item["priceKRW"],
                    "reasons": [
                        {
                            "goal": goal,
                            "sources": ["conversation", "skinProfile"],
                            "ingredientCodes": ["fixture-humectant"],
                            "evidenceLevel": "ingredient_presence",
                            "evidenceSources": ["cosing_function"],
                        }
                    ],
                }
                for name, item in self.products.items()
            ]
            groups = {key: matches if key == goal else [] for key in get_args(SkinGoal)}
            return httpx.Response(
                200,
                json={
                    "strategyVersion": "skincare-v4",
                    "dataVersion": "fixture-v1",
                    "overallTop5": matches,
                    "overallTop10": matches,
                    "byConcern": groups,
                    "coverage": [
                        {"goal": goal, "status": "ok" if rows else "no_matches"}
                        for goal, rows in groups.items()
                    ],
                },
            )
        assert request.url.path == "/api/catalog/options/search"
        self.option_calls.append(body)
        stamp = datetime.now(UTC).isoformat()
        items = []
        for scope in body["optionScope"]:
            name = scope["productId"]
            assert scope["optionId"] == "option-" + name and scope["shadeId"] is None
            amount = self.products[name]["priceKRW"]
            source = {"sourceVersion": "fixture-v1", "sourceRef": "https://example.test/option"}
            checks = [{"condition": "identity", "verdict": "MATCH", "reason": "exact", **source}]
            price = None
            if body["maxPriceKRW"] is not None:
                checks.append(
                    {
                        "condition": "price",
                        "verdict": "MATCH" if amount <= body["maxPriceKRW"] else "NOT_MATCH",
                        "reason": "reference_price",
                        **source,
                    }
                )
                price = {
                    "requestedBasis": body["priceBasis"],
                    "observedBasis": "catalog_reference",
                    "amountKRW": amount,
                    "checkedAt": stamp,
                    **source,
                }
            for condition in body["ingredientConditions"]:
                present = name == "fragrance"
                checks.append(
                    {
                        "condition": "ingredient",
                        **condition,
                        "verdict": "NOT_MATCH" if present else "MATCH",
                        "reason": "ingredient_present" if present else "ingredient_absent",
                        "evidenceId": name + "-ingredients",
                        "reviewStatus": "verified",
                        "observedAt": stamp,
                        "ingredientCoverage": "full",
                        "normalizationStatus": "verified",
                        **source,
                    }
                )
            items.append(
                {
                    **scope,
                    **({"optionId": "unmatched"} if self.unmatched_option else {}),
                    "sourceVersion": "fixture-v1",
                    "checks": checks,
                    "price": price,
                    "group": "EXCLUDED"
                    if any(c["verdict"] == "NOT_MATCH" for c in checks)
                    else "ELIGIBLE",
                }
            )
        visible = [self.products[i["productId"]] for i in items if i["group"] == "ELIGIBLE"]
        return httpx.Response(
            200,
            json={
                "effectiveRequest": body,
                "checkedAt": stamp,
                "status": "SUCCESS",
                "items": items,
                "products": visible,
                "excludedCount": len(items) - len(visible),
                "omittedCount": 0,
                "checkedScope": {
                    "candidateProducts": len(items),
                    "candidateOptions": len(items),
                    "checkedOptions": len(items),
                    "unidentifiedOptions": 0,
                    "exhaustive": True,
                    "stoppedReason": "COMPLETE",
                    "errors": 0,
                },
            },
        )


def test_consented_skin_type_selects_only_verified_options(memory_api, monkeypatch):
    client, _ = memory_api
    config = get_settings()
    monkeypatch.setattr(config, "g7_structured_memory_enabled", True)
    monkeypatch.setattr(config, "g1_supervisor_enabled", False)
    room = new_room(client)
    proposals = "/api/chat/v2/memory-proposals"
    ask(client, room, 0, "나는 건성이야. 기억해줘", structured=True)
    (group,) = client.get(proposals, headers=AUTH, params={"conversationId": room}).json()
    (item,) = group["items"]
    assert item["key"] == "skin.type"

    fixture = SkincareHttpFixture()
    transport = httpx.MockTransport(fixture)
    async_client = httpx.AsyncClient
    monkeypatch.setattr(
        httpx, "AsyncClient", lambda **kwargs: async_client(transport=transport, **kwargs)
    )
    url = "http://catalog.example.test"
    llm = PlanLlm(intent="search", category="skincare")
    service = ChatService(
        None,
        llm,
        CatalogClient(url),
        skincare=SkincareRecommendationTool(SkincareRecommendationClient(url)),
    )
    client.app.dependency_overrides[get_chat_service] = lambda: service

    def recommend(message="보습 스킨케어 추천해줘", *, request_type="beauty_consultation"):
        return ask(
            client,
            new_room(client),
            0,
            message,
            structured=True,
            request_type=request_type,
        )

    assert "appliedMemories" not in recommend()
    assert not fixture.v4_calls
    approved = client.post(
        f"{proposals}/{group['groupId']}/decisions",
        headers=AUTH,
        json={
            "requestId": str(uuid4()),
            "decisions": [
                {
                    "itemId": item["itemId"],
                    "expectedVersion": item["version"],
                    "action": "approve",
                    "confirmed": True,
                }
            ],
        },
    )
    assert approved.status_code == 200, approved.text
    memory_id = approved.json()["items"][0]["memoryId"]

    llm.plan.update(
        maxPriceKRW=20000,
        moisturizing=True,
        ingredientConditions=[{"ingredientName": "향료", "operator": "excludes"}],
    )
    selected = recommend("2만원 이하로 향료 제외하고 보습 스킨케어 추천해줘", request_type="chat")
    assert [p["id"] for p in selected["products"]] == ["profile-match"]
    assert selected["appliedMemories"] == [
        {
            "memoryId": memory_id,
            "version": 1,
            "key": "skin.type",
            "tool": "skincare.recommend",
            "field": "skinType",
            "applicationKind": "candidate_selection",
        }
    ]
    assert fixture.v4_calls == [
        {
            "detectedConcerns": [{"goal": "dryness", "sources": ["conversation"]}],
            "skinType": "dry",
        }
    ]
    assert fixture.option_calls[0]["maxPriceKRW"] == 20000
    assert fixture.option_calls[0]["ingredientConditions"] == [
        {"ingredientName": "향료", "operator": "excludes"},
    ]
    assert fixture.option_calls[0]["moisturizing"] is False
    assert "confirmedUserPreferences" not in llm.messages[-1]["content"]
    selected_room = selected["conversation"]["id"]
    detail_path = f"/api/chat/conversations/{selected_room}"
    detail = client.get(detail_path, headers=AUTH).json()
    assert (
        detail["messages"][-1]["displayPayload"]["appliedMemories"] == selected["appliedMemories"]
    )

    llm.plan = {"intent": "search", "category": "skincare"}
    for message in (
        "지성용 보습 스킨케어 추천해줘",
        "Recommend hydrating skincare. My skin is oily now.",
        "친구에게 줄 보습 스킨케어 추천해줘",
        "기억 반영하지 말고 보습 스킨케어 추천해줘",
        "보습 말고 스킨케어 추천해줘",
    ):
        assert "appliedMemories" not in recommend(message)
    assert len(fixture.v4_calls) == 1
    fixture.unavailable = True
    assert recommend()["products"] and len(fixture.v4_calls) == 2
    fixture.unavailable = False
    fixture.unmatched_option = True
    fallback = recommend()
    assert fallback["products"] and "appliedMemories" not in fallback
    fixture.unmatched_option = False
    path = "/api/chat/v2/memory-settings"
    settings = client.get(path, headers=AUTH).json()
    disabled = client.patch(
        path,
        headers=AUTH,
        json={
            "requestId": str(uuid4()),
            "expectedVersion": settings["version"],
            "enabled": False,
        },
    )
    assert disabled.status_code == 200, disabled.text
    assert "appliedMemories" not in recommend()
    assert len(fixture.v4_calls) == 3
    detail = client.get(detail_path, headers=AUTH).json()
    assert "appliedMemories" not in detail["messages"][-1]["displayPayload"]

    edit = client.patch(
        f"/api/chat/v2/memories/{memory_id}",
        headers=AUTH,
        json={
            "requestId": str(uuid4()),
            "expectedVersion": 1,
            "confirmed": True,
            "value": "oily",
            "locale": "ko",
        },
    )
    assert edit.status_code == 200, edit.text
    enabled = client.patch(
        path,
        headers=AUTH,
        json={
            "requestId": str(uuid4()),
            "expectedVersion": disabled.json()["version"],
            "enabled": True,
        },
    )
    assert enabled.status_code == 200, enabled.text
    assert recommend("유분 관리 스킨케어 추천해줘")["appliedMemories"][0]["version"] == 2
    assert fixture.v4_calls[-1] == {
        "detectedConcerns": [{"goal": "oiliness", "sources": ["conversation"]}],
        "skinType": "oily",
    }


class ColorCatalog(Catalog):
    def __init__(self):
        super().__init__()
        self.products = [
            product("a-glossy", 11000),
            product("b-matte", 12000),
            product("c-matte-coral", 15000),
            product("d-over-budget", 25000),
            product("a-blush", 10000, category="cheek"),
            product("b-blush-pink", 13000, category="cheek"),
            product("c-contour", 11000, category="cheek"),
        ]
        self.products[0].texture = "glossy"
        self.products[4].makeup_zone = self.products[5].makeup_zone = "blush"
        self.products[6].makeup_zone = "contour"
        coral = CatalogShade(
            id="coral-option",
            name="Sunset",
            hex="#F37F63",
            measure_method="estimated",
            color_source="option_chip",
            color_family="coral",
        )
        self.products[2].shades = [
            self.products[2].shades[0],
            coral,
        ]
        self.products[3].shades = [coral]
        self.products[1].shades = [
            CatalogShade(
                id="placeholder",
                name="Coral",
                hex="#F37F63",
                measure_method="placeholder",
            )
        ]
        self.products[5].shades = [CatalogShade(id="pink-option", name="Soft Pink", hex="#E9A7BB")]
        self.products[6].shades = [CatalogShade(id="contour", name="Pink", hex="#E9A7BB")]


def test_consented_lip_and_cheek_color_rank_without_selecting_shades(memory_api, monkeypatch):
    client, _ = memory_api
    config = get_settings()
    monkeypatch.setattr(config, "g7_structured_memory_enabled", True)
    monkeypatch.setattr(config, "g1_supervisor_enabled", False)
    origin = new_room(client)
    path = "/api/chat/v2/memory-proposals"
    ask(
        client,
        origin,
        0,
        "Please remember that I prefer coral lip, I prefer pink blush, I prefer matte lip",
        structured=True,
    )
    (group,) = client.get(path, headers=AUTH, params={"conversationId": origin}).json()
    assert {item["key"] for item in group["items"]} == {"makeup.color", "makeup.finish"}
    assert len(group["items"]) == 3

    llm = PlanLlm(intent="search", category="lip", maxPriceKRW=20000)
    service = ChatService(None, llm, ColorCatalog())
    client.app.dependency_overrides[get_chat_service] = lambda: service
    question = "2만원 이하 립 제품 추천해줘"

    def recommend(text=question, request_type="beauty_consultation"):
        return ask(
            client,
            new_room(client),
            0,
            text,
            structured=True,
            request_type=request_type,
        )

    initial = recommend()
    assert [p["id"] for p in initial["products"]] == ["a-glossy", "b-matte", "c-matte-coral"]
    assert "appliedMemories" not in initial
    saved = client.post(
        f"{path}/{group['groupId']}/decisions",
        headers=AUTH,
        json={
            "requestId": str(uuid4()),
            "decisions": [
                {
                    "itemId": item["itemId"],
                    "expectedVersion": item["version"],
                    "action": "approve",
                    "confirmed": True,
                }
                for item in group["items"]
            ],
        },
    )
    assert saved.status_code == 200, saved.text
    ids = {item["itemId"]: item["memoryId"] for item in saved.json()["items"]}
    lip_id = next(
        ids[item["itemId"]] for item in group["items"] if item["value"].get("family") == "coral"
    )
    cheek_id = next(
        ids[item["itemId"]] for item in group["items"] if item["value"].get("family") == "pink"
    )
    applied = recommend(request_type="chat")
    assert [p["id"] for p in applied["products"]] == ["c-matte-coral", "b-matte", "a-glossy"]
    matte, color = applied["appliedMemories"]
    assert matte["key"] == "makeup.finish"
    assert color == {
        "memoryId": lip_id,
        "version": 1,
        "key": "makeup.color",
        "tool": "catalog.search_products",
        "field": "shadeColorFamily",
        "applicationKind": "ranking",
        "matches": [
            {
                "productId": "c-matte-coral",
                "shadeId": "coral-option",
                "basis": "estimated",
            }
        ],
    }
    assert not applied["chatContext"].get("shadeSelections")
    assert applied["chatContext"].get("selectedProductId") is None
    assert "confirmedUserPreferences" not in llm.messages[-1]["content"]
    for explicit in ("빨간 립 제품 추천해줘", "립 2호 제품 추천해줘"):
        assert [item["key"] for item in recommend(explicit)["appliedMemories"]] == ["makeup.finish"]

    llm.plan["category"] = "cheek"
    cheek = recommend("치크 제품 추천해줘")
    assert [p["id"] for p in cheek["products"]] == ["b-blush-pink", "a-blush", "c-contour"]
    (evidence,) = cheek["appliedMemories"]
    assert evidence["memoryId"] == cheek_id and evidence["matches"] == [
        {"productId": "b-blush-pink", "shadeId": "pink-option", "basis": "catalog_name"}
    ]
    assert "appliedMemories" not in recommend("친구에게 선물할 치크 추천해줘")
    assert "appliedMemories" not in recommend("기억 쓰지 말고 치크 추천해줘")
    detail = f"/api/chat/conversations/{cheek['conversation']['id']}"
    stored = client.get(detail, headers=AUTH).json()["messages"][-1]["displayPayload"]
    assert stored["appliedMemories"] == cheek["appliedMemories"]
    settings_path = "/api/chat/v2/memory-settings"
    settings = client.get(settings_path, headers=AUTH).json()
    off = client.patch(
        settings_path,
        headers=AUTH,
        json={
            "requestId": str(uuid4()),
            "expectedVersion": settings["version"],
            "enabled": False,
        },
    )
    assert off.status_code == 200, off.text
    assert "appliedMemories" not in recommend("치크 제품 추천해줘")
    stored = client.get(detail, headers=AUTH).json()["messages"][-1]["displayPayload"]
    assert "appliedMemories" not in stored


class OwnedCatalog(Catalog):
    def __init__(self):
        super().__init__()
        self.products = [
            product("a-owned", 12000),
            product("b-new", 14000),
            product("c-ambiguous", 11000),
            product("d-ambiguous", 13000),
            product("e-unqualified", 16000),
            product("f-expensive", 25000),
            product("g-stale", 17000),
        ]
        names = (
            "Owned Lip",
            "Fresh Lip",
            "Choice",
            "Choice",
            "Unqualified Lip",
            "Expensive Lip",
            "Old Lip",
        )
        for item, name in zip(self.products, names, strict=True):
            item.brand = "Fixture Brand"
            item.name = item.name_ko = name
        self.products[0].shades = [CatalogShade(id="rose-option", name="Rose", hex="#C86871")]
        self.products[6].shades = [CatalogShade(id="retired-option", name="Retired", hex="#BC6581")]


def test_use_only_or_exclude_verified_owned_products_without_changing_memory(
    memory_api, monkeypatch
):
    client, _ = memory_api
    monkeypatch.setattr(get_settings(), "g7_structured_memory_enabled", True)
    monkeypatch.setattr(get_settings(), "g1_supervisor_enabled", False)
    catalog = OwnedCatalog()
    llm = PlanLlm(intent="search", category="lip", maxPriceKRW=20000)
    service = ChatService(FakeGraph(), llm, catalog)
    client.app.dependency_overrides[get_chat_service] = lambda: service
    path = "/api/chat/v2/memory-proposals"
    memories_path = "/api/chat/v2/memories"
    include = "제가 가진 립 중 2만원 이하 제품 추천해줘"
    exclude = "이미 가진 제품은 빼고 2만원 이하 립 추천해줘"

    def recommend(question):
        return ask(client, new_room(client), 0, question, structured=True)

    def approve(room):
        (group,) = client.get(path, headers=AUTH, params={"conversationId": room}).json()
        result = client.post(
            f"{path}/{group['groupId']}/decisions",
            headers=AUTH,
            json={
                "requestId": str(uuid4()),
                "decisions": [
                    {
                        "itemId": item["itemId"],
                        "expectedVersion": item["version"],
                        "action": "approve",
                        "confirmed": True,
                    }
                    for item in group["items"]
                ],
            },
        )
        assert result.status_code == 200, result.text
        return {item["itemId"]: item["memoryId"] for item in result.json()["items"]}, group

    before = recommend(include)
    assert not before["products"] and "appliedMemories" not in before
    origin = new_room(client)
    ask(
        client,
        origin,
        0,
        "Please remember that I own Fixture Brand Owned Lip Rose, I own Fixture Brand Choice, "
        "I own Unqualified Lip, I own Fixture Brand Expensive Lip",
        structured=True,
    )
    ids, group = approve(origin)
    assert len(group["items"]) == 4 and all(
        set(item["value"]) == {"productName"} for item in group["items"]
    )
    owned_id = next(
        ids[item["itemId"]]
        for item in group["items"]
        if item["value"]["productName"] == "Fixture Brand Owned Lip Rose"
    )
    linked = new_room(client)
    chosen = client.patch(
        f"/api/chat/conversations/{linked}/state",
        headers=AUTH,
        json={
            "requestId": str(uuid4()),
            "expectedConversationVersion": 0,
            "operation": "select_shade",
            "payload": {"productId": "g-stale", "shadeId": "retired-option"},
        },
    )
    assert chosen.status_code == 200, chosen.text
    ask(
        client,
        linked,
        chosen.json()["conversationVersion"],
        "Please remember that I own Fixture Brand Old Lip Retired",
        structured=True,
    )
    _, linked_group = approve(linked)
    assert linked_group["items"][0]["value"]["shadeId"] == "retired-option"
    catalog.products[-1].shades = []
    owned = recommend(include)
    assert [item["id"] for item in owned["products"]] == ["a-owned"]
    (evidence,) = owned["appliedMemories"]
    assert evidence == {
        "memoryId": owned_id,
        "version": 1,
        "key": "inventory.product",
        "tool": "catalog.search_products",
        "field": "productId",
        "applicationKind": "candidate_filter",
        "action": "include",
        "productId": "a-owned",
        "shadeId": "rose-option",
    }
    assert not owned["chatContext"].get("shadeSelections")
    assert owned["chatContext"].get("selectedProductId") is None
    assert "confirmedUserPreferences" not in llm.messages[-1]["content"]
    assert "대조하지 못했어요" in owned["answer"]
    excluded = recommend(exclude)
    assert [item["id"] for item in excluded["products"]] == [
        "b-new",
        "c-ambiguous",
        "d-ambiguous",
        "e-unqualified",
        "g-stale",
    ]
    assert excluded["appliedMemories"] == [evidence | {"action": "exclude"}]
    detail = f"/api/chat/conversations/{owned['conversation']['id']}"
    stored = client.get(detail, headers=AUTH).json()["messages"][-1]["displayPayload"]
    assert stored["appliedMemories"] == [evidence]
    saved = client.get(memories_path, headers=AUTH).json()["memories"]
    name_only = next(item for item in saved if item["id"] == owned_id)
    assert "상품 미확인" in name_only["value"] and name_only["version"] == 1
    assert len(saved) == 5
    ordinary = ask(
        client,
        new_room(client),
        0,
        "2만원 이하 립 추천해줘",
        structured=True,
        request_type="beauty_consultation",
    )
    assert ordinary["products"][0]["id"] == "a-owned" and "appliedMemories" not in ordinary
    llm.plan["optionSearch"] = True
    assert recommend(include)["resultType"] == "clarification"
    llm.plan.pop("optionSearch")
    settings_path = "/api/chat/v2/memory-settings"
    settings = client.get(settings_path, headers=AUTH).json()
    off = client.patch(
        settings_path,
        headers=AUTH,
        json={
            "requestId": str(uuid4()),
            "expectedVersion": settings["version"],
            "enabled": False,
        },
    )
    assert off.status_code == 200, off.text
    ignored = recommend(include)
    assert not ignored["products"] and "appliedMemories" not in ignored
    stored = client.get(detail, headers=AUTH).json()["messages"][-1]["displayPayload"]
    assert "appliedMemories" not in stored

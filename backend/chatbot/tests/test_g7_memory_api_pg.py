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
from tests.conftest import FakeGraph, FakeLlm
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


def new_room(client, entry=None):
    result = client.post(
        "/api/chat/conversations",
        headers=AUTH,
        json={
            "requestId": str(uuid4()),
            "entry": entry or {"type": "general"},
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
            item.texture = None
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
            profile_goal = {"dry": "dryness", "oily": "oiliness"}[body["skinType"]]
            matches = [
                {
                    "product": item,
                    "optionId": "option-" + name,
                    "optionName": name,
                    "priceKRW": item["priceKRW"],
                    "reasons": [
                        {
                            "goal": reason_goal,
                            "sources": (["conversation"] if reason_goal == goal else [])
                            + (["skinProfile"] if reason_goal == profile_goal else []),
                            "ingredientCodes": ["fixture-humectant"],
                            "evidenceLevel": "ingredient_presence",
                            "evidenceSources": ["cosing_function"],
                        }
                        for reason_goal in dict.fromkeys((goal, profile_goal))
                    ],
                }
                for name, item in self.products.items()
            ]
            groups = {
                key: matches if key in {goal, profile_goal} else [] for key in get_args(SkinGoal)
            }
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

    def recommend(
        message="보습 스킨케어 추천해줘", *, request_type="beauty_consultation", request_id=None
    ):
        return ask(
            client,
            new_room(client),
            0,
            message,
            request_id,
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
    selected_request_id = str(uuid4())
    selected = recommend(
        "2만원 이하로 향료 제외하고 얼굴이 당길 때 쓸 보습 크림 추천해줘",
        request_type="chat",
        request_id=selected_request_id,
    )
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
    display = detail["messages"][-1]["displayPayload"]
    assert display["appliedMemories"] == selected["appliedMemories"]
    assert display["optionSearch"]["products"][0]["texture"] is None
    recovered = client.get(f"{detail_path}/requests/{selected_request_id}", headers=AUTH)
    assert recovered.status_code == 200, recovered.text
    recovery = recovered.json()
    assert recovery["status"] == "COMMITTED"
    assert recovery["response"]["appliedMemories"] == selected["appliedMemories"]
    explicit = recommend("오늘은 피부가 지성이에요. 2만원 이하 보습 크림 추천해줘")
    assert [p["id"] for p in explicit["products"]] == ["profile-match"]
    assert "appliedMemories" not in explicit
    assert fixture.v4_calls[-1]["skinType"] == "oily"

    llm.plan = {"intent": "search", "category": "skincare"}
    for message in (
        "지성용 보습 스킨케어 추천해줘",
        "Recommend hydrating skincare. My skin is oily now.",
        "친구에게 줄 보습 스킨케어 추천해줘",
        "기억 반영하지 말고 보습 스킨케어 추천해줘",
        "보습 말고 스킨케어 추천해줘",
    ):
        assert "appliedMemories" not in recommend(message)
    assert len(fixture.v4_calls) == 2
    fixture.unavailable = True
    assert recommend()["products"] and len(fixture.v4_calls) == 3
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
    assert len(fixture.v4_calls) == 4
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


def test_n02_consented_inventory_selected_look_persistence_and_replay(
    memory_api, monkeypatch, record_property
):
    from app.services import owned_look_consultation_service as owned_service
    from tests.test_g8_owned_look import FilteredCatalog as LookCatalog

    client, _ = memory_api
    settings = get_settings()
    for name in ("g7_structured_memory_enabled", "g8_enabled"):
        monkeypatch.setattr(settings, name, True)
    monkeypatch.setattr(settings, "g1_supervisor_enabled", False)
    catalog = LookCatalog()

    class NoModel(FakeLlm):
        async def complete(self, *args, **kwargs):
            raise AssertionError("N02 exact-match path must not call a model")

    service = ChatService(FakeGraph(), FakeLlm(), catalog)
    client.app.dependency_overrides[get_chat_service] = lambda: service
    tasks = []
    original = owned_service.execute_owned_look

    async def observed(req, catalog, *, trace=None):
        local = []
        response = await original(req, catalog, trace=local)
        tasks.extend(local)
        if trace is not None:
            trace.extend(local)
        return response

    monkeypatch.setattr(owned_service, "execute_owned_look", observed)

    def select(room, version, operation, payload):
        response = client.patch(
            f"/api/chat/conversations/{room}/state",
            headers=AUTH,
            json={
                "requestId": str(uuid4()),
                "expectedConversationVersion": version,
                "operation": operation,
                "payload": payload,
            },
        )
        assert response.status_code == 200, response.text
        return response.json()["conversationVersion"]

    origin = new_room(client)
    version = select(origin, 0, "select_shade", {"productId": "lip-a", "shadeId": "lip-a-shade"})
    ask(
        client,
        origin,
        version,
        "Please remember that I own Fixture lip-a Fixture shade",
        structured=True,
    )
    path = "/api/chat/v2/memory-proposals"
    (group,) = client.get(path, headers=AUTH, params={"conversationId": origin}).json()
    (item,) = group["items"]
    assert item["value"]["productId"] == "lip-a"
    assert item["value"]["shadeId"] == "lip-a-shade"
    approved = client.post(
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
    assert approved.status_code == 200, approved.text
    service = ChatService(FakeGraph(), NoModel(), catalog)
    # Shared-parent conversational resume, using real PostgreSQL and synthetic Catalog/G5.
    from app.schemas.knowledge import KnowledgeReply
    from app.services import consultation_parent_graph as parent_graph
    from app.services.knowledge_service import Consultation

    knowledge_inputs = []

    async def mock_knowledge(question, *, prior_user_context):
        knowledge_inputs.append(json.loads(prior_user_context))
        return Consultation(
            KnowledgeReply(status="insufficient_evidence", limitations="합성 근거 부족"), {}
        )

    monkeypatch.setattr(parent_graph.knowledge_service, "consult_knowledge", mock_knowledge)
    parent_room = new_room(client)
    parent_version = select(
        parent_room, 0, "select_look", {"kind": "catalog", "lookId": "fixture-look"}
    )
    parent_first = ask(
        client,
        parent_room,
        parent_version,
        "내가 가진 립으로 이 룩에 필요한 제품만 추가 추천해줘. 순서의 이유도 설명해줘.",
        structured=True,
    )
    assert not parent_first["products"]
    assert "Fixture blush-b (blush-b-shade) 제품을 가지고 있나요" in parent_first["answer"]
    assert knowledge_inputs[0]["styleRecipe"]["lookId"] == "fixture-look"
    parent_second = ask(
        client, parent_room, parent_first["conversation"]["version"], "없어", structured=True
    )
    assert [p["id"] for p in parent_second["products"]] == ["blush-b"]
    assert len(knowledge_inputs) == 1  # No repeat G5 call for a resolved ownership question.
    parent_third = ask(
        client,
        parent_room,
        parent_second["conversation"]["version"],
        "상품은 됐고 사용 순서만 알려줘",
        structured=True,
    )
    assert not parent_third["products"] and parent_third["styleRecipe"]
    restored_parent = client.get(f"/api/chat/conversations/{parent_room}", headers=AUTH).json()
    assert restored_parent["messages"][-1]["displayPayload"]["products"] == []
    record_property(
        "parent_pg_evidence",
        json.dumps(
            {
                "postgresMode": "live",
                "catalogMode": "mock",
                "authenticationMode": "mock",
                "modelConfiguredMode": "mock",
                "externalModelCalls": 0,
                "knowledgeInputs": knowledge_inputs,
                "turns": [
                    {"modelMode": "mock", "externalModelCalls": 0, "response": value}
                    for value in (parent_first, parent_second, parent_third)
                ],
            },
            ensure_ascii=False,
        ),
    )
    room = new_room(client)
    version = select(room, 0, "select_look", {"kind": "catalog", "lookId": "fixture-look"})
    body = {
        "conversationId": room,
        "expectedConversationVersion": version,
        "requestId": str(uuid4()),
        "locale": "ko",
        "structuredMemory": True,
        "message": "내가 가진 립으로 이 룩을 따라 해보고 필요한 것만 추가 추천해줘. 블러셔는 없어.",
        "styleContext": {"kind": "catalog", "lookId": "client-forged-look"},
    }
    catalog.searches.clear()
    first = client.post("/api/chat", headers=AUTH, json=body)
    assert first.status_code == 200, first.text
    reply = first.json()
    assert [p["id"] for p in reply["products"]] == ["blush-b"]
    assert reply["appliedMemories"][0]["productId"] == "lip-a"
    assert reply["appliedMemories"][0]["shadeId"] == "lip-a-shade"
    assert catalog.searches == [{"ids": ["lip-a"]}, {"ids": ["blush-b"]}]
    assert all(look_id == "fixture-look" for _, look_id in catalog.look_calls)
    before = (len(catalog.searches), len(catalog.look_calls), len(tasks))
    replay = client.post("/api/chat", headers=AUTH, json=body)
    assert replay.json() == reply
    assert before == (len(catalog.searches), len(catalog.look_calls), len(tasks))
    detail = f"/api/chat/conversations/{room}"
    stored = client.get(detail, headers=AUTH).json()["messages"][-1]["displayPayload"]
    assert stored["products"] == reply["products"]
    assert stored["appliedMemories"] == reply["appliedMemories"]
    assert client.get(detail, headers=OTHER).status_code == 404
    denied = client.post("/api/chat", headers=OTHER, json={**body, "requestId": str(uuid4())})
    assert denied.status_code == 404
    assert before == (len(catalog.searches), len(catalog.look_calls), len(tasks))
    following = ask(
        client,
        room,
        reply["conversation"]["version"],
        "내가 가진 립으로 이 룩에 필요한 제품만 추가 추천해줘.",
        structured=True,
    )
    assert following["appliedMemories"][0]["productId"] == "lip-a"
    assert [p["id"] for p in following["products"]] == ["blush-b"]
    assert "블러셔 제품도 가지고 있나요" not in following["answer"]
    assert "Fixture blush-b (blush-b-shade) 제품을 가지고 있나요" not in following["answer"]
    priced_request_id = str(uuid4())
    priced = ask(
        client,
        room,
        following["conversation"]["version"],
        "2만원 이하, 향료 제외",
        request_id=priced_request_id,
        structured=True,
    )
    assert [p["id"] for p in priced["products"]] == ["blush-b"]
    display = priced["ownedLookOptions"]
    assert display["selections"][0]["optionId"] == "blush-b-sale"
    assert display["batches"][0]["items"][0]["price"]["amountKRW"] == 15000
    restored = client.get(detail, headers=AUTH).json()["messages"][-1]["displayPayload"]
    assert restored["ownedLookOptions"] == display
    calls_before_replay = (len(catalog.option_calls), len(tasks))
    replay_priced = ask(
        client,
        room,
        following["conversation"]["version"],
        "2만원 이하, 향료 제외",
        request_id=priced_request_id,
        structured=True,
    )
    assert replay_priced == priced
    assert calls_before_replay == (len(catalog.option_calls), len(tasks))

    lowered = ask(
        client, room, priced["conversation"]["version"], "예산은 1만원 이하", structured=True
    )
    assert not lowered["products"]
    assert catalog.option_calls[-1].max_price_krw == 10000
    assert catalog.option_calls[-1].ingredient_conditions[0].ingredient_name == "향료"
    reversed_release = ask(
        client,
        room,
        lowered["conversation"]["version"],
        "향료 제외. 성분 조건 전체 해제해줘.",
        structured=True,
    )
    assert not catalog.option_calls[-1].ingredient_conditions
    assert catalog.option_calls[-1].max_price_krw == 10000
    filter_clear = ask(
        client,
        room,
        reversed_release["conversation"]["version"],
        "상품 조건 전체 해제해줘. 예산은 2만원 이하. 판테놀 제외.",
        structured=True,
    )
    assert [p["id"] for p in filter_clear["products"]] == ["blush-b"]
    assert catalog.option_calls[-1].max_price_krw == 20000
    assert [c.ingredient_name for c in catalog.option_calls[-1].ingredient_conditions] == ["판테놀"]
    restored = client.get(detail, headers=AUTH).json()["messages"][-1]["displayPayload"]
    assert restored["ownedLookOptions"] == filter_clear["ownedLookOptions"]

    changed = ask(
        client,
        room,
        filter_clear["conversation"]["version"],
        "블러셔는 이제 있어.",
        structured=True,
    )
    assert not changed["products"]
    assert "확인할 정보가 부족해요" in changed["answer"]
    released = ask(
        client,
        room,
        changed["conversation"]["version"],
        "블러셔 미보유 조건 해제해줘",
        structured=True,
    )
    assert not released["products"]
    assert "Fixture blush-b (blush-b-shade) 제품을 가지고 있나요" in released["answer"]
    reset_missing = ask(
        client, room, released["conversation"]["version"], "블러셔는 없어.", structured=True
    )
    assert [p["id"] for p in reset_missing["products"]] == ["blush-b"]
    clear_all = ask(
        client,
        room,
        reset_missing["conversation"]["version"],
        "미보유 조건 전부 해제해줘",
        structured=True,
    )
    assert not clear_all["products"]
    task_count = len(tasks)
    search_count = len(catalog.searches)
    opted_out = ask(
        client,
        room,
        clear_all["conversation"]["version"],
        "내가 가진 립으로 이 룩에 필요한 제품 추천해줘. 기억은 쓰지 마.",
        structured=True,
    )
    assert not opted_out["products"] and not opted_out.get("appliedMemories")
    assert (len(tasks), len(catalog.searches)) == (task_count, search_count)
    look_room = client.post(
        "/api/chat/conversations",
        headers=AUTH,
        json={
            "requestId": str(uuid4()),
            "entry": {"type": "look", "kind": "catalog", "lookId": "fixture-look"},
        },
    )
    assert look_room.status_code == 201, look_room.text
    look_reply = ask(
        client, look_room.json()["conversationId"], 0, body["message"], structured=True
    )
    assert not look_reply["products"] and not look_reply.get("appliedMemories")
    assert (len(tasks), len(catalog.searches)) == (task_count, search_count)
    record_property(
        "n02_pg_evidence",
        json.dumps(
            {
                "catalogMode": "mock",
                "postgresMode": "live",
                "modelMode": "mock-forbidden",
                "actualModelCalls": 0,
                "tasks": tasks,
                "answer": reply["answer"],
                "products": reply["products"],
                "replayAdditionalCalls": 0,
                "optionDisplayStoredAndReplayed": display,
                "orderedConditionTurns": [lowered, reversed_release, filter_clear],
                "serverLookRestored": True,
                "ownerIsolation": True,
                "followup": following["answer"],
                "absenceDecisionPersistence": "passed: keep/change/release/restore/clear-all",
                "memoryOptout": "passed",
                "directLookEntryMemoryBoundary": "passed: no inventory consumption",
            },
            ensure_ascii=False,
        ),
    )


@pytest.mark.skipif(
    not os.environ.get("G8_N02_LIVE_CATALOG"), reason="live Catalog opt-in required"
)
def test_n02_live_catalog_pg_evidence_boundary(memory_api, monkeypatch, record_property):
    import asyncio
    import hashlib

    from app.services import owned_look_consultation_service as owned_service

    client, _ = memory_api
    settings = get_settings()
    monkeypatch.setattr(settings, "g7_structured_memory_enabled", True)
    monkeypatch.setattr(settings, "g8_enabled", True)
    monkeypatch.setattr(settings, "g1_supervisor_enabled", False)
    queries, tasks = [], []

    class ObservedCatalog(CatalogClient):
        async def search_products(self, **query):
            rows = await super().search_products(**query)
            queries.append({"request": query, "resultIds": [p.id for p in rows]})
            return rows

    catalog = ObservedCatalog(os.environ["G8_N02_LIVE_CATALOG"])

    async def select_data():
        looks = await catalog.fetch_style_looks()
        products = await catalog.search_products(category="lip")
        for product in products:
            for shade in product.shades:
                label = f"{product.brand} {product.name} {shade.name}"
                if product.makeup_zone == "lip" and not any(
                    c in label for c in ",;.!?。！？；，\n"
                ):
                    return looks[0], product, shade
        pytest.skip("Live Catalog has no lip/shade suitable for an exact memory label")

    look, product, shade = asyncio.run(select_data())
    # General consultation does not require a reviewed recipe. Availability of
    # exact sale options and actual usage evidence are evaluated separately.
    service = ChatService(FakeGraph(), FakeLlm(), catalog)
    client.app.dependency_overrides[get_chat_service] = lambda: service
    original = owned_service.execute_owned_look

    async def observed(req, catalog, *, trace=None):
        local = []
        response = await original(req, catalog, trace=local)
        tasks.extend(local)
        if trace is not None:
            trace.extend(local)
        return response

    monkeypatch.setattr(owned_service, "execute_owned_look", observed)
    room = new_room(client)
    selected = client.patch(
        f"/api/chat/conversations/{room}/state",
        headers=AUTH,
        json={
            "requestId": str(uuid4()),
            "expectedConversationVersion": 0,
            "operation": "select_shade",
            "payload": {"productId": product.id, "shadeId": shade.id},
        },
    )
    assert selected.status_code == 200, selected.text
    ask(
        client,
        room,
        selected.json()["conversationVersion"],
        f"Please remember that I own {product.brand} {product.name} {shade.name}",
        structured=True,
    )
    path = "/api/chat/v2/memory-proposals"
    (group,) = client.get(path, headers=AUTH, params={"conversationId": room}).json()
    item = next(i for i in group["items"] if i["key"] == "inventory.product")
    assert item["value"]["productId"] == product.id
    assert item["value"]["shadeId"] == shade.id
    consent = client.post(
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
    assert consent.status_code == 200, consent.text
    room = new_room(client)
    selected = client.patch(
        f"/api/chat/conversations/{room}/state",
        headers=AUTH,
        json={
            "requestId": str(uuid4()),
            "expectedConversationVersion": 0,
            "operation": "select_look",
            "payload": {"kind": "video", "lookId": look.id},
        },
    )
    assert selected.status_code == 200, selected.text
    replies = []
    version = selected.json()["conversationVersion"]
    for text in [
        "내가 가진 립으로 이 룩에 필요한 제품만 추가 추천해줘. 블러셔는 없어.",
        "블러셔는 이제 있어.",
        "블러셔 미보유 조건 해제해줘",
    ]:
        reply = ask(client, room, version, text, structured=True)
        assert reply["styleRecipe"]
        restored = client.get(f"/api/chat/conversations/{room}", headers=AUTH).json()
        display = restored["messages"][-1]["displayPayload"]
        from app.schemas.style_recipe import StyleRecipe

        assert StyleRecipe.model_validate(display["styleRecipe"]) == StyleRecipe.model_validate(
            reply["styleRecipe"]
        )
        assert display.get("ownedLookOptions") == reply.get("ownedLookOptions")
        replies.append(
            {
                "text": text,
                "answer": reply["answer"],
                "products": reply["products"],
                "modelSettingsMode": "mock",
                "actualExternalModelCalls": 0,
            }
        )
        version = reply["conversation"]["version"]
    assert any(q["request"].get("ids") == [product.id] for q in queries)
    assert any(t["task"]["taskId"] == "N1" for t in tasks)
    record_property(
        "n02_live_catalog_evidence",
        json.dumps(
            {
                "catalogMode": "live HTTP",
                "postgresMode": "live isolated",
                "lookId": look.id,
                "productId": product.id,
                "shadeId": shade.id,
                "lookSnapshotSha256": hashlib.sha256(look.model_dump_json().encode()).hexdigest(),
                "productSnapshotSha256": hashlib.sha256(
                    product.model_dump_json().encode()
                ).hexdigest(),
                "dataVersion": "API does not expose snapshot version; response digests recorded",
                "recipe": "present" if look.recipe else "absent",
                "ownedProductRelationToLook": "not established; no substitution claim",
                "positiveRecommendation": any(t["products"] for t in replies),
                "queries": queries,
                "tasks": tasks,
                "turns": replies,
            },
            ensure_ascii=False,
        ),
    )


@pytest.mark.skipif(not os.environ.get("G8_SALE_CATALOG_URL"), reason="current Catalog required")
def test_live_sale_without_ar_persists_and_restores(memory_api, monkeypatch, record_property):
    client, _ = memory_api
    settings = get_settings()
    monkeypatch.setattr(settings, "g7_structured_memory_enabled", True)
    monkeypatch.setattr(settings, "g8_enabled", True)
    monkeypatch.setattr(settings, "g1_supervisor_enabled", False)
    catalog = CatalogClient(os.environ["G8_SALE_CATALOG_URL"])

    class NoModel(FakeLlm):
        async def complete(self, *args, **kwargs):
            raise AssertionError("No model call expected")

    service = ChatService(FakeGraph(), NoModel(configured=False), catalog)
    client.app.dependency_overrides[get_chat_service] = lambda: service
    room = new_room(client)
    selected = client.patch(
        f"/api/chat/conversations/{room}/state",
        headers=AUTH,
        json={
            "requestId": str(uuid4()),
            "expectedConversationVersion": 0,
            "operation": "select_look",
            "payload": {"kind": "video", "lookId": "AG03mUj4vnY"},
        },
    )
    assert selected.status_code == 200
    version = selected.json()["conversationVersion"]
    turns = []
    for message, expected in [
        ("내가 가진 립으로 이 룩에 필요한 제품만 추가 추천해줘. 아이섀도는 없어.", True),
        ("향료 제외 조건 추가해줘", False),
        ("향료 제외 조건 해제해줘", True),
    ]:
        reply = ask(client, room, version, message, structured=True)
        assert ("oy-a000000162667" in [p["id"] for p in reply["products"]]) is expected
        restored = client.get(f"/api/chat/conversations/{room}", headers=AUTH).json()
        display = restored["messages"][-1]["displayPayload"]
        assert display["ownedLookOptions"] == reply["ownedLookOptions"]
        from app.schemas.style_recipe import StyleRecipe

        assert StyleRecipe.model_validate(display["styleRecipe"]) == StyleRecipe.model_validate(
            reply["styleRecipe"]
        )
        assert not reply.get("arResult")
        if expected:
            option = next(
                o
                for o in display["ownedLookOptions"]["selections"]
                if o["productId"] == "oy-a000000162667"
            )
            assert option["optionId"] == "A000000162667-012" and option.get("shadeId") is None
        turns.append(
            {
                "message": message,
                "response": reply,
                "restoredDisplay": display,
                "catalogMode": "live_http_current_source",
                "postgresMode": "live_disposable",
                "authenticationMode": "mock",
                "modelConfiguredMode": "disabled",
                "actualRemoteModelCalls": 0,
            }
        )
        version = reply["conversation"]["version"]
    record_property("live_sale_pg_roundtrip", json.dumps(turns, ensure_ascii=False))


@pytest.mark.skipif(not os.environ.get("G8_N02_LIVE_CATALOG"), reason="live Catalog required")
def test_sale_option_normal_proposal_pg_restore_and_n02(memory_api, monkeypatch, record_property):
    from app.services import owned_look_consultation_service as owned_service

    client, _ = memory_api
    settings = get_settings()
    monkeypatch.setattr(settings, "g7_structured_memory_enabled", True)
    monkeypatch.setattr(settings, "g8_enabled", True)
    monkeypatch.setattr(settings, "g1_supervisor_enabled", False)
    calls, tasks = [], []

    class ObservedCatalog(CatalogClient):
        async def get_product_option(self, pid, oid):
            result = await super().get_product_option(pid, oid)
            calls.append(
                {
                    "productId": pid,
                    "optionId": oid,
                    "found": result is not None,
                    "arShadeId": result.ar_shade_id if result else None,
                }
            )
            return result

    catalog = ObservedCatalog(os.environ["G8_N02_LIVE_CATALOG"])

    class RecordingLlm(FakeLlm):
        call_count = 0

        async def complete(self, messages):
            self.call_count += 1
            return await super().complete(messages)

    llm = RecordingLlm()
    service = ChatService(FakeGraph(), llm, catalog)
    client.app.dependency_overrides[get_chat_service] = lambda: service
    original = owned_service.execute_owned_look

    async def observed(req, catalog, *, trace=None):
        local = []
        response = await original(req, catalog, trace=local)
        tasks.extend(local)
        if trace is not None:
            trace.extend(local)
        return response

    monkeypatch.setattr(owned_service, "execute_owned_look", observed)
    pid = "oy-a000000162667"
    oid = "A000000162667-012"
    created = client.post(
        "/api/chat/conversations",
        headers=AUTH,
        json={
            "requestId": str(uuid4()),
            "entry": {"type": "product", "productId": pid, "optionId": oid},
        },
    )
    assert created.status_code == 201, created.text
    room = created.json()["conversationId"]
    reply = ask(client, room, 0, "이 옵션을 가지고 있다고 기억해줘", structured=True)
    first_calls = llm.call_count
    path = "/api/chat/v2/memory-proposals"
    (group,) = client.get(path, headers=AUTH, params={"conversationId": room}).json()
    (item,) = [i for i in group["items"] if i["key"] == "inventory.product"]
    assert item["value"]["optionId"] == oid
    assert "shadeId" not in item["value"]
    # A proposal is not consent. Only this explicit decision writes a memory.
    consent = client.post(
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
    assert consent.status_code == 200, consent.text
    restored = client.get(f"/api/chat/conversations/{room}", headers=AUTH)
    assert restored.status_code == 200, restored.text
    assert restored.json()["context"]["product"]["selectedOptionId"] == oid
    # Same product, different sale option, both without AR: independent consented memories.
    changed = client.patch(
        f"/api/chat/conversations/{room}/state",
        headers=AUTH,
        json={
            "requestId": str(uuid4()),
            "expectedConversationVersion": reply["conversation"]["version"],
            "operation": "select_product",
            "payload": {"productId": pid, "optionId": "A000000162667-001"},
        },
    )
    assert changed.status_code == 200, changed.text
    ask(
        client,
        room,
        changed.json()["conversationVersion"],
        "이 옵션을 가지고 있다고 기억해줘",
        structured=True,
    )
    second_calls = llm.call_count - first_calls
    groups = client.get(path, headers=AUTH, params={"conversationId": room}).json()
    group_b = next(
        g
        for g in groups
        if any(i["value"].get("optionId") == "A000000162667-001" for i in g["items"])
    )
    item_b = next(i for i in group_b["items"] if i["value"].get("optionId") == "A000000162667-001")
    saved_b = client.post(
        f"{path}/{group_b['groupId']}/decisions",
        headers=AUTH,
        json={
            "requestId": str(uuid4()),
            "decisions": [
                {
                    "itemId": item_b["itemId"],
                    "expectedVersion": item_b["version"],
                    "action": "approve",
                    "confirmed": True,
                }
            ],
        },
    )
    assert saved_b.status_code == 200, saved_b.text
    look_room = new_room(client)
    selected = client.patch(
        f"/api/chat/conversations/{look_room}/state",
        headers=AUTH,
        json={
            "requestId": str(uuid4()),
            "expectedConversationVersion": 0,
            "operation": "select_look",
            "payload": {"kind": "video", "lookId": "L8RvSmdkR2g"},
        },
    )
    assert selected.status_code == 200, selected.text
    response = ask(
        client,
        look_room,
        selected.json()["conversationVersion"],
        "내가 보유한 제품으로 이 룩을 구성하고 없는 제품만 추천해줘",
        structured=True,
    )
    owned_tasks = [t for t in tasks if t.get("task", {}).get("taskId") == "O1"]
    assert owned_tasks and oid in json.dumps(owned_tasks, ensure_ascii=False)
    assert "A000000162667-001" in json.dumps(owned_tasks, ensure_ascii=False)
    assert response.get("arResult") is None
    record_property(
        "option_memory_evidence",
        json.dumps(
            {
                "catalogMode": "live",
                "storageMode": "PostgreSQL",
                "modelConfiguredMode": "mock-configured",
                "actualExternalModelCalls": 0,
                "optionCalls": calls,
                "ownedTasks": owned_tasks,
                "proposalValue": item["value"],
                "restoredOptionId": oid,
                "turns": [
                    {
                        "modelMode": "mock",
                        "externalModelCalls": 0,
                        "mockCompleteCalls": first_calls,
                        "purpose": "memory-proposal-A",
                    },
                    {
                        "modelMode": "mock",
                        "externalModelCalls": 0,
                        "mockCompleteCalls": second_calls,
                        "purpose": "memory-proposal-B",
                    },
                    {
                        "modelMode": "mock",
                        "externalModelCalls": 0,
                        "mockCompleteCalls": llm.call_count - first_calls - second_calls,
                        "purpose": "N02-memory-use",
                    },
                ],
                "memoryReply": reply["answer"],
                "n02Answer": response["answer"],
            },
            ensure_ascii=False,
        ),
    )


def test_same_zone_item_question_pg_restore_and_final_status(
    memory_api, monkeypatch, record_property
):
    from tests.test_g8_owned_look import MultiLipCatalog

    client, _ = memory_api
    settings = get_settings()
    monkeypatch.setattr(settings, "g7_structured_memory_enabled", True)
    monkeypatch.setattr(settings, "g8_enabled", True)
    monkeypatch.setattr(settings, "g1_supervisor_enabled", False)
    catalog = MultiLipCatalog()
    service = ChatService(FakeGraph(), FakeLlm(configured=False), catalog)
    client.app.dependency_overrides[get_chat_service] = lambda: service
    room = new_room(client)
    selected = client.patch(
        f"/api/chat/conversations/{room}/state",
        headers=AUTH,
        json={
            "requestId": str(uuid4()),
            "expectedConversationVersion": 0,
            "operation": "select_look",
            "payload": {"kind": "catalog", "lookId": "fixture-look"},
        },
    )
    assert selected.status_code == 200, selected.text
    version = selected.json()["conversationVersion"]
    turns = []
    # First answer resolves blush, second lip-a, third lip-b; all are independent.
    for message in [
        "내가 보유한 제품으로 이 룩을 구성하고 필요한 것만 추천해줘. 2만원 이하로 추천해줘.",
        "있어",
        "있어",
        "없어",
        "예산 1만원 이하로 바꿔줘.",
        "lip-b 미보유 조건 해제해줘.",
    ]:
        response = ask(client, room, version, message, structured=True)
        restored = client.get(f"/api/chat/conversations/{room}", headers=AUTH).json()
        display = restored["messages"][-1]["displayPayload"]
        assert display.get("ownedLookOptions") == response.get("ownedLookOptions")
        turns.append(
            {
                "message": message,
                "response": response,
                "restoredDisplay": display,
                "catalogMode": "mock",
                "postgresMode": "live_disposable",
                "authenticationMode": "mock",
                "modelConfiguredMode": "disabled",
                "actualModelCalls": 0,
            }
        )
        version = response["conversation"]["version"]
    assert [p["id"] for p in turns[3]["response"]["products"]] == ["lip-b"]
    assert not turns[4]["response"]["products"]
    assert "lip-b" in turns[5]["response"]["answer"]
    assert "가지고 있나요" in turns[5]["response"]["answer"]
    assert all(q.product_ids == ["lip-b"] for q in catalog.option_calls)
    record_property("item_question_pg_roundtrip", json.dumps(turns, ensure_ascii=False))


def test_scope_option_level_and_goal_only_followup_pg(memory_api, monkeypatch, record_property):
    from tests.test_g8_owned_look import KoreanScopeCatalog

    client, _ = memory_api
    settings = get_settings()
    monkeypatch.setattr(settings, "g7_structured_memory_enabled", True)
    monkeypatch.setattr(settings, "g8_enabled", True)
    monkeypatch.setattr(settings, "g1_supervisor_enabled", False)
    catalog = KoreanScopeCatalog()
    observed = []

    class NoModel(FakeLlm):
        async def complete(self, *args, **kwargs):
            raise AssertionError("No external or mock model invocation expected")

    class ObservedChat(ChatService):
        async def answer(self, req, principal_key=None):
            response = await super().answer(req, principal_key)
            observed.append(response)
            return response

    service = ObservedChat(FakeGraph(), NoModel(configured=False), catalog)
    client.app.dependency_overrides[get_chat_service] = lambda: service
    room = new_room(client)
    selected = client.patch(
        f"/api/chat/conversations/{room}/state",
        headers=AUTH,
        json={
            "requestId": str(uuid4()),
            "expectedConversationVersion": 0,
            "operation": "select_look",
            "payload": {"kind": "video", "lookId": "fixture-look"},
        },
    )
    assert selected.status_code == 200, selected.text
    version = selected.json()["conversationVersion"]
    turns = []
    for message in [
        "내가 보유한 제품으로 이 룩에 필요한 것만 추천해줘. 하트퍼센트 립펜슬 07호는 있어. "
        "롬앤 쥬시 래스팅 틴트는 있어. 2만원 이하 향료 제외해줘.",
        "있어",
        "롬앤 쥬시 래스팅 틴트 07호는 없어.",
        "설명은 빼고 상품만 찾아줘",
        "롬앤 쥬시 래스팅 틴트 미보유 조건 해제해줘.",
    ]:
        response = ask(client, room, version, message, structured=True)
        restored = client.get(f"/api/chat/conversations/{room}", headers=AUTH).json()
        display = restored["messages"][-1]["displayPayload"]
        assert display.get("ownedLookOptions") == response.get("ownedLookOptions")
        turns.append(
            {
                "message": message,
                "response": response,
                "restoredDisplay": display,
                "parent": observed[-1]._consultation_parent.model_dump(mode="json", by_alias=True),
                "trace": observed[-1]._parent_trace,
                "catalogMode": "mock",
                "postgresMode": "live_disposable",
                "authenticationMode": "mock",
                "modelConfiguredMode": "disabled",
                "actualModelCalls": 0,
            }
        )
        version = response["conversation"]["version"]
    assert observed[0]._owned_look_outcome.status == "waiting_user"
    assert "07호" in observed[0]._consultation_parent.question.text
    assert observed[1]._owned_look_outcome.status == "completed"
    assert [p.id for p in observed[2].products] == ["lip-b"]
    assert [p.id for p in observed[3].products] == ["lip-b"]
    assert observed[3]._owned_look_context.filters == observed[2]._owned_look_context.filters
    assert observed[4]._owned_look_outcome.status == "waiting_user"
    assert len(observed[4]._owned_look_context.item_declarations) == 1
    assert observed[4]._consultation_parent.question.ownership_scope == "option"
    assert all(q.product_ids == ["lip-b"] for q in catalog.option_calls)
    assert all(q.max_price_krw == 20000 for q in catalog.option_calls)
    record_property("scope_pg_roundtrip", json.dumps(turns, ensure_ascii=False))


@pytest.mark.parametrize(
    "request_type,look_room",
    [("chat", False), ("style_consultation", False), ("style_consultation", True)],
)
def test_reference_exception_pg_restore(
    memory_api, monkeypatch, record_property, request_type, look_room
):
    from tests.test_g8_owned_look import KoreanScopeCatalog
    from tests.test_g8_owned_look_interpreter import Model

    client, _ = memory_api
    monkeypatch.setattr(get_settings(), "g7_structured_memory_enabled", True)
    monkeypatch.setattr(get_settings(), "g8_enabled", True)
    monkeypatch.setattr(get_settings(), "g1_supervisor_enabled", False)

    class GeneralCapableModel(Model):
        general_messages = None

        async def complete(self, messages):
            self.general_messages = messages
            return "새 상담 목표를 알려주세요."

    catalog, model, observed = KoreanScopeCatalog(), GeneralCapableModel(), []

    class ObservedChat(ChatService):
        async def answer(self, req, principal_key=None):
            response = await super().answer(req, principal_key)
            observed.append(response)
            return response

    service = ObservedChat(FakeGraph(), model, catalog)
    client.app.dependency_overrides[get_chat_service] = lambda: service
    room = new_room(
        client,
        {"type": "look", "kind": "video", "lookId": "fixture-look"} if look_room else None,
    )
    selected = client.patch(
        f"/api/chat/conversations/{room}/state",
        headers=AUTH,
        json={
            "requestId": str(uuid4()),
            "expectedConversationVersion": 0,
            "operation": "select_look",
            "payload": {"kind": "video", "lookId": "fixture-look"},
        },
    )
    assert selected.status_code == 200
    version = selected.json()["conversationVersion"]
    turns = []
    for message in [
        "내가 보유한 제품으로 이 룩에 필요한 것만 추천해줘. "
        "립 제품은 전부 없어. 2만원 이하로 찾아줘.",
        "그 틴트만 미보유 조건에서 빼줘",
        "예산은 3만원 이하로 바꿔줘",
        "립 제품은 전부 없어.",
    ]:
        before = len(model.calls)
        response = ask(client, room, version, message, structured=True, request_type=request_type)
        restored = client.get(f"/api/chat/conversations/{room}", headers=AUTH).json()
        assert restored["messages"][-1]["text"] == response["answer"]
        display = restored["messages"][-1]["displayPayload"]
        assert display.get("ownedLookOptions") == response.get("ownedLookOptions")
        version = response["conversation"]["version"]
        turns.append(
            {
                "utterance": message,
                "response": response,
                "state": observed[-1]._owned_look_context.model_dump(mode="json", by_alias=True),
                "catalogMode": "mock",
                "modelMode": "mock",
                "modelConfigured": True,
                "mockCalls": len(model.calls) - before,
                "actualExternalCalls": 0,
                "storageMode": "live_disposable_postgresql",
                "authMode": "mock",
                "restoredAnswer": restored["messages"][-1]["text"],
                "answerModelCalls": 0,
            }
        )
    assert "‘없음’ 조건에서 뺐어요" in observed[1].answer
    assert observed[2].answer.startswith("예산을 30,000원 이하로 바꿨어요.")
    assert "가지고 있나요?" not in observed[2].answer
    assert observed[1]._owned_look_context.exceptions
    assert observed[2]._owned_look_context.exceptions == observed[1]._owned_look_context.exceptions
    assert {p.id for p in observed[2].products} == {"lip-a"}
    assert not observed[3]._owned_look_context.exceptions
    assert {p.id for p in observed[3].products} == {"lip-a", "lip-b"}
    assert len(model.calls) == 1
    record_property("reference_pg", json.dumps(turns, ensure_ascii=False))
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
    assert off.status_code == 200
    disabled = ask(
        client,
        room,
        version,
        "내가 보유한 제품으로 이 룩에 필요한 것만 추천해줘",
        structured=True,
        request_type=request_type,
    )
    assert not disabled["products"]
    assert observed[-1]._owned_look_context is None
    assert "동의" in disabled["answer"]
    if request_type == "chat":
        general = ask(
            client,
            room,
            disabled["conversation"]["version"],
            "다시 추천해줘",
            structured=True,
            request_type=request_type,
        )
        assert general["answer"] == "새 상담 목표를 알려주세요."
        assert model.general_messages is not None
        assert not general.get("appliedMemories")
        restored = client.get(f"/api/chat/conversations/{room}", headers=AUTH).json()
        assert restored["messages"][-1]["text"] == general["answer"]


def test_e01_partial_result_pg_restore_and_style_only_retry(
    memory_api, monkeypatch, record_property
):
    from tests.test_g8_partial_success import Catalog, CombinedModel

    client, _ = memory_api
    monkeypatch.setattr(get_settings(), "g8_enabled", True)
    monkeypatch.setattr(get_settings(), "g8_read_retries", 1)
    catalog, model, observed = Catalog(), CombinedModel(), []

    class ObservedChat(ChatService):
        async def answer(self, req, principal_key=None):
            result = await super().answer(req, principal_key)
            observed.append(result)
            return result

    service = ObservedChat(FakeGraph(), model, catalog)
    client.app.dependency_overrides[get_chat_service] = lambda: service
    room = new_room(client)
    version = 0
    for operation, payload in [
        ("select_product", {"productId": "product-a"}),
        ("select_look", {"kind": "catalog", "lookId": "daily"}),
    ]:
        changed = client.patch(
            f"/api/chat/conversations/{room}/state",
            headers=AUTH,
            json={
                "requestId": str(uuid4()),
                "expectedConversationVersion": version,
                "operation": operation,
                "payload": payload,
            },
        )
        assert changed.status_code == 200, changed.text
        version = changed.json()["conversationVersion"]
    catalog.product_calls.clear()
    first = ask(
        client,
        room,
        version,
        '"상품나"와 브랜드 비교하고 비슷한 룩도 찾아줘',
        request_type="beauty_consultation",
    )
    assert first["styleStatus"] == "error"
    product_calls = list(catalog.product_calls)
    restored = client.get(f"/api/chat/conversations/{room}", headers=AUTH)
    assert restored.status_code == 200
    assert restored.json()["messages"][-1]["text"] == first["answer"]
    second = ask(
        client,
        room,
        first["conversation"]["version"],
        "룩만 다시 찾아줘",
        request_type="beauty_consultation",
    )
    assert second["styleStatus"] == "ready"
    assert catalog.product_calls == product_calls and model.calls == 1
    assert observed[-1]._consultation_parent.tasks[0].attempts == 0
    assert observed[-1]._consultation_parent.tasks[0].input_refs
    restored = client.get(f"/api/chat/conversations/{room}", headers=AUTH).json()
    assert restored["messages"][-1]["text"] == second["answer"]
    record_property(
        "e01_pg",
        json.dumps(
            {
                "storageMode": "real PostgreSQL",
                "authMode": "mock",
                "catalogMode": "mock",
                "modelMode": "mock",
                "actualExternalModelCalls": 0,
                "firstAnswer": first["answer"],
                "secondAnswer": second["answer"],
                "firstTrace": observed[0]._parent_trace,
                "secondTrace": observed[1]._parent_trace,
            },
            ensure_ascii=False,
        ),
    )


def test_parent_cancel_resume_pg_preserves_results_and_stops_reads(memory_api, monkeypatch):
    from tests.test_g8_consultation_intent import IntentModel
    from tests.test_g8_partial_success import Catalog, CombinedModel

    client, _ = memory_api
    monkeypatch.setattr(get_settings(), "g8_enabled", True)
    catalog, model, observed = Catalog(failures=0), CombinedModel(), []

    class ObservedChat(ChatService):
        async def answer(self, req, principal_key=None):
            result = await super().answer(req, principal_key)
            observed.append(result)
            return result

    service = ObservedChat(FakeGraph(), model, catalog)
    client.app.dependency_overrides[get_chat_service] = lambda: service
    room, version = new_room(client), 0
    for operation, payload in [
        ("select_product", {"productId": "product-a"}),
        ("select_look", {"kind": "catalog", "lookId": "daily"}),
    ]:
        changed = client.patch(
            f"/api/chat/conversations/{room}/state",
            headers=AUTH,
            json={
                "requestId": str(uuid4()),
                "expectedConversationVersion": version,
                "operation": operation,
                "payload": payload,
            },
        )
        assert changed.status_code == 200
        version = changed.json()["conversationVersion"]
    first = ask(
        client,
        room,
        version,
        '"상품나"와 브랜드 비교하고 비슷한 룩도 찾아줘',
        request_type="beauty_consultation",
    )
    service._llm = IntentModel("cancel", ["product", "style"])
    stopped = ask(
        client,
        room,
        first["conversation"]["version"],
        "이 상담은 여기서 멈춰",
        request_type="beauty_consultation",
    )
    assert observed[-1]._consultation_parent.execution_state == "cancelled"
    style_calls = catalog.style_calls
    service._llm = IntentModel("continue", [])
    waiting = ask(
        client,
        room,
        stopped["conversation"]["version"],
        "그다음은?",
        request_type="beauty_consultation",
    )
    assert waiting["resultType"] == "clarification" and catalog.style_calls == style_calls
    assert observed[-1]._product_style_context.product_result is not None
    service._llm = IntentModel("resume", ["style"])
    resumed = ask(
        client,
        room,
        waiting["conversation"]["version"],
        "중단한 룩 찾기부터 이어 줘",
        request_type="beauty_consultation",
    )
    assert resumed["styleStatus"] == "ready" and catalog.style_calls == style_calls + 1
    assert observed[-1]._consultation_parent.execution_state == "active"
    assert (
        next(t for t in observed[-1]._consultation_parent.tasks if t.goal == "product").attempts
        == 0
    )
    restored = client.get(f"/api/chat/conversations/{room}", headers=AUTH).json()
    assert restored["messages"][-1]["text"] == resumed["answer"]


def test_live_new_search_after_comparison_pg(memory_api, monkeypatch, record_property):
    from app.clients.llm_client import LlmClient

    if os.environ.get("G8_GOAL_BINDING_LIVE") != "1":
        pytest.skip("Explicit synthetic live model/Catalog/PG verification only")
    client, _ = memory_api
    monkeypatch.setattr(get_settings(), "g8_enabled", True)
    events, turns, observed, restored = [], [], [], []
    original_send = httpx.AsyncClient.send

    async def send(http, request, *args, **kwargs):
        row = {
            "host": request.url.host,
            "path": request.url.path,
            "query": request.url.query.decode(),
        }
        events.append(row)
        response = await original_send(http, request, *args, **kwargs)
        row["status"] = response.status_code
        return response

    monkeypatch.setattr(httpx.AsyncClient, "send", send)

    class Service(ChatService):
        async def answer(self, req, principal_key=None):
            restored.append(req._consultation_parent)
            response = await super().answer(req, principal_key)
            observed.append(response)
            return response

    llm = LlmClient(
        os.environ["LLM_BASE_URL"], os.environ["LLM_API_KEY"], os.environ["LLM_MODEL"], 80
    )
    service = Service(None, llm, CatalogClient("http://127.0.0.1:19834"))
    client.app.dependency_overrides[get_chat_service] = lambda: service
    room = new_room(client, {"type": "product", "productId": "oy-a000000004434"})
    version = 0
    comparison = toner = cream = None
    try:
        for index, question in enumerate(
            [
                "이 제품과 토리든 립 에센스를 비교하고 데일리 룩도 찾아줘",
                "토너 찾아줘. 크림도 찾아줘",
                "크림만 15,000원 이하로 바꿔줘",
            ]
        ):
            start = len(events)
            result = ask(client, room, version, question, request_type="beauty_consultation")
            version = result["conversation"]["version"]
            parent = observed[-1]._consultation_parent
            turns.append(
                {
                    "question": question,
                    "answer": result["answer"],
                    "parent": parent.model_dump(mode="json", by_alias=True) if parent else None,
                    "events": events[start:],
                    "modelConfiguredMode": "live",
                    "actualModelCalls": sum(e["host"] == "api.openai.com" for e in events[start:]),
                }
            )
            assert parent is not None
            if index == 0:
                comparison = next(t for t in parent.tasks if t.product_operation == "compare")
            else:
                old = next(t for t in parent.tasks if t.task_id == comparison.task_id)
                assert old.objective == comparison.objective
                assert old.product_operation == "compare"
                searches = [t for t in parent.tasks if t.product_operation == "search"]
                assert len(searches) == 2
                current_toner = next(t for t in searches if t.product_requirement.kind == "toner")
                current_cream = next(t for t in searches if t.product_requirement.kind == "cream")
                assert all(
                    t.status == "completed" and t.product_assessment.matched > 0 for t in searches
                )
                queries = [e for e in events[start:] if e["path"] == "/api/products"]
                assert len(queries) == (2 if index == 1 else 1)
                if index == 1:
                    toner, cream = current_toner, current_cream
                else:
                    assert current_toner.task_id == toner.task_id
                    assert current_toner.display_result == toner.display_result
                    assert current_cream.task_id == cream.task_id
                    assert current_cream.product_context["filters"]["maxPriceKRW"] == 15000
                    assert (
                        next(
                            t for t in restored[-1].tasks if t.task_id == cream.task_id
                        ).product_operation
                        == "search"
                    )
            stored = client.get(f"/api/chat/conversations/{room}", headers=AUTH).json()
            assert stored["messages"][-1]["text"] == result["answer"]
    finally:
        record_property(
            "live_goal_binding",
            json.dumps(
                {
                    "turns": turns,
                    "auth": "mock",
                    "parentSeed": "normal ChatService",
                    "pg": "live",
                    "catalog": "live",
                    "loginApp": "NOT_RUN",
                    "model": os.environ["LLM_MODEL"],
                },
                ensure_ascii=False,
            ),
        )


def test_live_comparison_question_model_catalog_pg(memory_api, monkeypatch, record_property):
    from app.clients.llm_client import LlmClient

    if os.environ.get("G8_COMPARISON_FOLLOWUP_LIVE") != "1":
        pytest.skip("Explicit synthetic live model/Catalog/PG verification only")
    client, _ = memory_api
    monkeypatch.setattr(get_settings(), "g8_enabled", True)
    events, turns, observed, restored = [], [], [], []
    original_send = httpx.AsyncClient.send

    async def send(http, request, *args, **kwargs):
        row = {
            "host": request.url.host,
            "path": request.url.path,
            "query": request.url.query.decode(),
        }
        events.append(row)
        response = await original_send(http, request, *args, **kwargs)
        row["status"] = response.status_code
        return response

    monkeypatch.setattr(httpx.AsyncClient, "send", send)

    class Service(ChatService):
        async def answer(self, req, principal_key=None):
            restored.append(req._consultation_parent)
            response = await super().answer(req, principal_key)
            observed.append(response)
            return response

    llm = LlmClient(
        os.environ["LLM_BASE_URL"], os.environ["LLM_API_KEY"], os.environ["LLM_MODEL"], 80
    )
    service = Service(None, llm, CatalogClient("http://127.0.0.1:19834"))
    client.app.dependency_overrides[get_chat_service] = lambda: service
    room = new_room(client, {"type": "product", "productId": "oy-a000000004434"})
    selected = client.patch(
        f"/api/chat/conversations/{room}/state",
        headers=AUTH,
        json={
            "requestId": str(uuid4()),
            "expectedConversationVersion": 0,
            "operation": "select_product",
            "payload": {"productId": "oy-a000000004434"},
        },
    )
    assert selected.status_code == 200, selected.text
    version = selected.json()["conversationVersion"]
    old_style = None
    try:
        for index, question in enumerate(
            [
                "이 제품과 토리든 립 에센스를 비교하고 데일리 룩도 찾아줘",
                "비교 대상만 다른 크림으로 바꿔줘",
                "다슈 맨즈 아쿠아 리얼 모이스트 올인원크림",
            ]
        ):
            start = len(events)
            result = ask(client, room, version, question, request_type="beauty_consultation")
            version = result["conversation"]["version"]
            parent = observed[-1]._consultation_parent
            turns.append(
                {
                    "question": question,
                    "answer": result["answer"],
                    "parent": parent.model_dump(mode="json", by_alias=True) if parent else None,
                    "events": events[start:],
                    "modelConfiguredMode": "live",
                    "actualModelCalls": sum(e["host"] == "api.openai.com" for e in events[start:]),
                }
            )
            assert parent is not None
            task = next(t for t in parent.tasks if t.task_id == "product")
            assert task.product_operation == "compare"
            style = next(t for t in parent.tasks if t.task_id == "style")
            if index == 0:
                old_style = style.display_result
            else:
                assert style.display_result == old_style
                assert not any(
                    e["path"] in {"/api/looks", "/api/style-looks"} for e in events[start:]
                )
                if index == 1:
                    assert parent.question and parent.question.task_id == "product"
                    assert task.status == "waiting_user"
                else:
                    assert restored[-1].question.task_id == "product"
                    assert parent.question is None
                    assert any(
                        "oy-a000000122212" in e["path"] or "q=" in e["query"]
                        for e in events[start:]
                    )
                    assert {e["productId"] for e in task.product_assessment.evidence} == {
                        "oy-a000000004434",
                        "oy-a000000122212",
                    }
            stored = client.get(f"/api/chat/conversations/{room}", headers=AUTH).json()
            assert stored["messages"][-1]["text"] == result["answer"]
    finally:
        record_property(
            "live_comparison_followup",
            json.dumps(
                {
                    "turns": turns,
                    "auth": "mock",
                    "parentSeed": "normal ChatService",
                    "pg": "live",
                    "catalog": "live",
                    "loginApp": "NOT_RUN",
                    "model": os.environ["LLM_MODEL"],
                },
                ensure_ascii=False,
            ),
        )


def test_live_original_g8_integration_pg(memory_api, monkeypatch, record_property):
    from app.clients.llm_client import LlmClient
    from app.core.errors import UpstreamError

    scenario = os.environ.get("G8_INTEGRATION_SCENARIO")
    if scenario not in {"n01", "e01"}:
        pytest.skip("Explicit synthetic integration run only")
    client, _ = memory_api
    settings = get_settings()
    monkeypatch.setattr(settings, "g8_enabled", True)
    monkeypatch.setattr(settings, "g1_supervisor_enabled", True)
    if scenario == "n01":
        monkeypatch.setattr(settings, "g5_enabled", True)
        monkeypatch.setattr(settings, "catalog_api_url", "http://127.0.0.1:19838")
        monkeypatch.setattr(settings, "g5_openai_api_key", os.environ["G5_OPENAI_API_KEY"])
        monkeypatch.setattr(settings, "g5_internal_token", os.environ["G5_INTERNAL_TOKEN"])
    replay_path = os.environ.get("G8_N01_KNOWLEDGE_REPLAY")
    if replay_path:
        from pathlib import Path
        from unittest.mock import AsyncMock

        from app.schemas.knowledge import KnowledgeReply
        from app.services import compound_consultation_service as specialists
        from app.services.knowledge_service import Consultation

        stored = json.loads(Path(replay_path).read_text(encoding="utf-8"))
        knowledge = KnowledgeReply.model_validate(stored["turns"][1]["response"]["knowledge"])
        monkeypatch.setattr(
            specialists,
            "consult_knowledge",
            AsyncMock(return_value=Consultation(reply=knowledge, trace={})),
        )
    events, turns, observed = [], [], []
    original_send = httpx.AsyncClient.send

    async def send(http, request, *args, **kwargs):
        event = {"host": request.url.host, "path": request.url.path}
        events.append(event)
        response = await original_send(http, request, *args, **kwargs)
        event["status"] = response.status_code
        return response

    monkeypatch.setattr(httpx.AsyncClient, "send", send)

    class Catalog(CatalogClient):
        inject_failure = scenario == "e01"

        async def fetch_style_looks(self):
            if self.inject_failure:
                events.append({"host": "fault_injection", "path": "style", "status": 503})
                raise UpstreamError("Synthetic integration Style failure")
            return await super().fetch_style_looks()

    class Service(ChatService):
        async def answer(self, req, principal_key=None):
            response = await super().answer(req, principal_key)
            observed.append(response)
            return response

    llm = LlmClient(
        os.environ["LLM_BASE_URL"], os.environ["LLM_API_KEY"], os.environ["LLM_MODEL"], 80
    )
    catalog = Catalog("http://127.0.0.1:19834")
    service = Service(
        None,
        llm,
        catalog,
        skincare=SkincareRecommendationTool(SkincareRecommendationClient("http://127.0.0.1:19834")),
    )
    client.app.dependency_overrides[get_chat_service] = lambda: service
    room = new_room(client)
    version = 0
    if scenario == "e01":
        selected = client.patch(
            f"/api/chat/conversations/{room}/state",
            headers=AUTH,
            json={
                "requestId": str(uuid4()),
                "expectedConversationVersion": 0,
                "operation": "select_product",
                "payload": {"productId": "oy-a000000004434"},
            },
        )
        assert selected.status_code == 200
        version = selected.json()["conversationVersion"]
    questions = (
        [
            "오후에 화장이 뜨는데 원인 알려주고 나한테 맞는 제품도 찾아줘",
            "각질과 당김이 있어. 로션과 쿠션을 써. 예산은 2만 원이고 향료는 제외해 줘.",
        ]
        if scenario == "n01"
        else [
            "이 제품과 다슈 맨즈 아쿠아 리얼 모이스트 올인원크림 153ml를 비교하고 "
            "데일리 룩도 찾아줘",
            "룩만 다시 찾아줘",
        ]
    )
    if replay_path:
        questions.append("예산만 1만 8천 원으로 바꿔줘")
    try:
        for index, question in enumerate(questions):
            if index:
                catalog.inject_failure = False
            start = len(events)
            reply = ask(client, room, version, question, request_type="beauty_consultation")
            version = reply["conversation"]["version"]
            turns.append(
                {
                    "question": question,
                    "response": reply,
                    "events": events[start:],
                    "modelConfiguredMode": "live",
                    "actualModelCalls": sum(e["host"] == "api.openai.com" for e in events[start:]),
                    "parent": observed[-1]._consultation_parent.model_dump(
                        mode="json", by_alias=True
                    )
                    if observed[-1]._consultation_parent
                    else None,
                }
            )
            saved = client.get(f"/api/chat/conversations/{room}", headers=AUTH).json()
            assert saved["messages"][-1]["text"] == reply["answer"]
            if scenario == "n01":
                if index == 0:
                    assert reply["resultType"] == "clarification"
                elif index == 1:
                    assert reply.get("compound") and reply.get("knowledge")
                    assert reply["knowledge"]["status"] != "error"
                    if replay_path:
                        assert any(
                            b["attempt"] == "without_unresolved_knowledge"
                            for b in reply["compound"]["batches"]
                        )
                        assert all(
                            any(
                                c["ingredientName"] == "향료"
                                for c in b["request"]["ingredientConditions"]
                            )
                            for b in reply["compound"]["batches"]
                        )
                    else:
                        assert any("knowledge" in e["path"] for e in events[start:])
                else:
                    assert reply["compound"]["goal"]["maxPriceKRW"] == 18000
                    assert all(b["attempt"] == "primary" for b in reply["compound"]["batches"])
                    assert all(
                        all(
                            c["ingredientName"] != "세라마이드"
                            for c in b["request"]["ingredientConditions"]
                        )
                        for b in reply["compound"]["batches"]
                    )
            else:
                assert reply["styleStatus"] == ("ready" if index else "error")
                if not index:
                    task = next(
                        t for t in observed[-1]._consultation_parent.tasks if t.goal == "product"
                    )
                    assert task.product_assessment and task.product_assessment.status == "completed"
                if index:
                    assert not any("/products" in e["path"] for e in events[start:])
    finally:
        record_property(
            "live_g8_integration",
            json.dumps(
                {
                    "g5Mode": "replay" if replay_path else "live",
                    "scenario": scenario,
                    "turns": turns,
                    "auth": "mock",
                    "pg": "live",
                    "catalog": "live",
                    "model": os.environ["LLM_MODEL"],
                    "fault": "injected Style failure" if scenario == "e01" else None,
                    "embeddingCallsInsideApi": "not instrumented",
                },
                ensure_ascii=False,
            ),
        )


def test_live_duplicate_comparison_selection_pg(memory_api, monkeypatch, record_property):
    from app.clients.llm_client import LlmClient

    if os.environ.get("G8_COMPARISON_SELECTION_LIVE") != "1":
        pytest.skip("Explicit synthetic live model/Catalog/PG verification only")
    client, _ = memory_api
    monkeypatch.setattr(get_settings(), "g8_enabled", True)
    events, turns, observed, restored = [], [], [], []
    original_send = httpx.AsyncClient.send

    async def send(http, request, *args, **kwargs):
        row = {
            "host": request.url.host,
            "path": request.url.path,
            "query": request.url.query.decode(),
        }
        events.append(row)
        response = await original_send(http, request, *args, **kwargs)
        row["status"] = response.status_code
        return response

    monkeypatch.setattr(httpx.AsyncClient, "send", send)

    class Service(ChatService):
        async def answer(self, req, principal_key=None):
            restored.append(req._consultation_parent)
            response = await super().answer(req, principal_key)
            observed.append(response)
            return response

    llm = LlmClient(
        os.environ["LLM_BASE_URL"], os.environ["LLM_API_KEY"], os.environ["LLM_MODEL"], 80
    )
    service = Service(None, llm, CatalogClient("http://127.0.0.1:19834"))
    client.app.dependency_overrides[get_chat_service] = lambda: service
    room = new_room(client, {"type": "product", "productId": "oy-a000000122212"})
    selected = client.patch(
        f"/api/chat/conversations/{room}/state",
        headers=AUTH,
        json={
            "requestId": str(uuid4()),
            "expectedConversationVersion": 0,
            "operation": "select_product",
            "payload": {"productId": "oy-a000000122212"},
        },
    )
    assert selected.status_code == 200, selected.text
    version = selected.json()["conversationVersion"]
    current_price = os.environ.get("G8_CURRENT_PRICE_FOLLOWUP") == "1"
    old_style = None
    try:
        for index, question in enumerate(
            [
                "이 제품과 바이오더마 하이드라비오 토너 250ml를 비교하고 데일리 룩도 찾아줘"
                + (". 지금 판매 가격으로 비교해줘" if current_price else ""),
                "2번",
                "토너 찾아줘. 크림도 찾아줘",
            ]
        ):
            start = len(events)
            result = ask(client, room, version, question, request_type="beauty_consultation")
            version = result["conversation"]["version"]
            parent = observed[-1]._consultation_parent
            turns.append(
                {
                    "question": question,
                    "answer": result["answer"],
                    "parent": parent.model_dump(mode="json", by_alias=True) if parent else None,
                    "events": events[start:],
                    "modelConfiguredMode": "live",
                    "actualModelCalls": sum(e["host"] == "api.openai.com" for e in events[start:]),
                }
            )
            assert parent is not None
            if index == 0:
                assert parent.question and len(parent.question.comparison_choices) == 2
                if current_price:
                    assert parent.question.comparison_price_basis == "current_offer"
                selected_id = parent.question.comparison_choices[1].product_id
                old_style = next(t for t in parent.tasks if t.goal == "style").display_result
            elif index == 1:
                task = next(t for t in parent.tasks if t.task_id == "product")
                assert restored[-1].question.comparison_choices[1].product_id == selected_id
                assert parent.question is None
                assert {e["productId"] for e in task.product_assessment.evidence} == {
                    "oy-a000000122212",
                    selected_id,
                }
                assert any(e["path"].endswith(selected_id) for e in events[start:])
                if current_price:
                    assert restored[-1].question.comparison_price_basis == "current_offer"
                    assert "실제 판매가" in result["answer"] and "미확인" in result["answer"]
                else:
                    assert "앱 등록 가격" in result["answer"] and "Catalog" not in result["answer"]
                assert (
                    next(t for t in parent.tasks if t.goal == "style").display_result == old_style
                )
            else:
                assert "앞서 비교한 내용은 그대로 유지" in result["answer"]
                assert len([t for t in parent.tasks if t.product_operation == "search"]) == 2
            stored = client.get(f"/api/chat/conversations/{room}", headers=AUTH).json()
            assert stored["messages"][-1]["text"] == result["answer"]
    finally:
        record_property(
            "live_comparison_selection",
            json.dumps(
                {
                    "turns": turns,
                    "auth": "mock",
                    "parentSeed": "normal ChatService",
                    "pg": "live",
                    "catalog": "live",
                    "loginApp": "NOT_RUN",
                    "model": os.environ["LLM_MODEL"],
                },
                ensure_ascii=False,
            ),
        )


def test_live_product_kind_model_catalog_pg(memory_api, monkeypatch, record_property):
    import os

    from app.clients.catalog_client import CatalogClient
    from app.clients.llm_client import LlmClient
    from app.schemas.chat import ChatResponse
    from app.schemas.consultation_parent import ConsultationParent, ParentTask

    if os.environ.get("G8_PRODUCT_CONTRACT_LIVE") != "1":
        pytest.skip("Explicit live synthetic model/Catalog/PG run only")
    client, _ = memory_api
    monkeypatch.setattr(get_settings(), "g8_enabled", True)
    observed, restored, events, turns = [], [], [], []
    original_send = httpx.AsyncClient.send

    async def send(http, request, *args, **kwargs):
        row = {
            "host": request.url.host,
            "path": request.url.path,
            "query": request.url.query.decode(),
        }
        events.append(row)
        response = await original_send(http, request, *args, **kwargs)
        row["status"] = response.status_code
        return response

    monkeypatch.setattr(httpx.AsyncClient, "send", send)

    class Service(ChatService):
        async def answer(self, req, principal_key=None):
            restored.append(req._consultation_parent)
            if req.message == "합성 기존 상담":
                result = ChatResponse(answer="합성 준비 상태", products=[])
                result._consultation_parent = ConsultationParent(
                    tasks=[ParentTask(goal="knowledge", version=1, status="completed")]
                )
            else:
                result = await super().answer(req, principal_key)
            observed.append(result)
            return result

    llm = LlmClient(
        os.environ["LLM_BASE_URL"], os.environ["LLM_API_KEY"], os.environ["LLM_MODEL"], 80
    )
    service = Service(None, llm, CatalogClient("http://127.0.0.1:19834"))
    client.app.dependency_overrides[get_chat_service] = lambda: service
    room = new_room(client)
    result = ask(client, room, 0, "합성 기존 상담", request_type="beauty_consultation")
    target = None
    preserved_id, preserved_products = None, None
    try:
        for question, expected, budget in [
            ("토너 찾아줘. 크림도 찾아줘", "cream", None),
            ("토너 쪽은 놔두고 크림만 촉촉한 걸로", "cream", None),
            ("토너 쪽은 놔두고 크림만 15,000원 이하로", "cream", 15000),
            ("크림 종류 제한만 풀고 그 예산은 유지해줘", None, 15000),
        ]:
            start = len(events)
            result = ask(
                client,
                room,
                result["conversation"]["version"],
                question,
                request_type="beauty_consultation",
            )
            parent = observed[-1]._consultation_parent
            assert "현재 변경 요청:" not in result["answer"]
            assert "공통 조건:" not in result["answer"]
            assert all(task.task_id not in result["answer"] for task in parent.tasks)
            turns.append(
                {
                    "question": question,
                    "answer": result["answer"],
                    "parent": parent.model_dump(mode="json", by_alias=True),
                    "events": events[start:],
                    "modelConfiguredMode": "live",
                    "actualRemoteHttpCalls": sum(
                        e["host"] == "api.openai.com" for e in events[start:]
                    ),
                }
            )
            products = [t for t in parent.tasks if t.goal == "product"]
            if target is None:
                assert len(products) == 2
                target = next(t.task_id for t in products if t.product_requirement.kind == "cream")
                toner = next(t for t in products if t.product_requirement.kind == "toner")
                preserved_id = toner.task_id
                preserved_products = toner.display_result["products"]
            toner = next(t for t in products if t.task_id == preserved_id)
            assert toner.status == "completed"
            assert toner.display_result["products"] == preserved_products
            task = next(t for t in products if t.task_id == target)
            assert task.product_requirement.kind == expected
            assert task.product_context["filters"]["maxPriceKRW"] == budget
            assert task.status == "completed" and task.product_assessment.matched > 0
            if budget is not None:
                assert restored[-1] is not None
                assert sum(e["path"] == "/api/products" for e in events[start:]) == 1
            stored = client.get(f"/api/chat/conversations/{room}", headers=AUTH).json()
            assert stored["messages"][-1]["text"] == result["answer"]
    finally:
        record_property(
            "live_product_contract",
            json.dumps(
                {
                    "turns": turns,
                    "auth": "mock",
                    "parentSeed": "synthetic",
                    "pg": "live",
                    "catalog": "live",
                    "loginApp": "NOT_RUN",
                    "model": os.environ["LLM_MODEL"],
                },
                ensure_ascii=False,
            ),
        )


def test_product_kind_pg_restore_budget_change_and_release(memory_api, monkeypatch):
    from app.schemas.chat import ChatResponse
    from app.schemas.consultation_parent import ConsultationParent, ParentTask
    from tests.test_beauty_consultation import Catalog
    from tests.test_g8_consultation_intent import AdditionModel
    from tests.test_product_search_contract import named

    client, _ = memory_api
    monkeypatch.setattr(get_settings(), "g8_enabled", True)
    catalog = Catalog()
    catalog.products = [
        named("수분 토너", 5000),
        named("보습 크림", 9000),
        named("보습 로션", 8000),
        named("클렌징크림", 7000),
    ]
    observed, restored = [], []

    class Model(AdditionModel):
        plans = []

        async def complete(self, messages):
            return json.dumps(self.plans.pop(0))

    class Service(ChatService):
        async def answer(self, req, principal_key=None):
            restored.append(req._consultation_parent)
            if req.message == "합성 기존 상담":
                result = ChatResponse(answer="합성 준비 상태", products=[])
                result._consultation_parent = ConsultationParent(
                    tasks=[ParentTask(goal="knowledge", version=1, status="completed")]
                )
            else:
                result = await super().answer(req, principal_key)
            observed.append(result)
            return result

    model = Model()
    service = Service(None, model, catalog)
    client.app.dependency_overrides[get_chat_service] = lambda: service
    room = new_room(client)
    seed = ask(client, room, 0, "합성 기존 상담", request_type="beauty_consultation")
    question = "토너 찾아줘. 크림도 찾아줘"
    model.additions = [
        {"capability": "product", "quote": q} for q in ["토너 찾아줘", "크림도 찾아줘"]
    ]
    model.plans = [
        {
            "intent": "search",
            "category": "skincare",
            "productRequirement": {"operation": "set", "kind": k, "quote": q},
        }
        for k, q in [("toner", "토너"), ("cream", "크림")]
    ]
    result = ask(
        client, room, seed["conversation"]["version"], question, request_type="beauty_consultation"
    )
    tasks = [t for t in observed[-1]._consultation_parent.tasks if t.goal == "product"]
    assert [t.product_requirement.kind for t in tasks] == ["toner", "cream"]
    target = tasks[1].task_id
    model.additions = []
    for question, operation, kind, expected in [
        ("예산은 1만원 이하", "keep", None, "cream"),
        ("로션으로 변경", "set", "lotion", "lotion"),
        ("종류 조건 해제", "clear", None, None),
    ]:
        model.changes = [{"taskId": target, "operation": "update", "quote": question}]
        plan = {
            "intent": "refine",
            "category": "skincare",
            "productRequirement": {"operation": operation, "kind": kind, "quote": question},
        }
        if operation == "keep":
            plan["maxPriceKRW"] = 10000
        model.plans = [plan]
        result = ask(
            client,
            room,
            result["conversation"]["version"],
            question,
            request_type="beauty_consultation",
        )
        task = next(t for t in observed[-1]._consultation_parent.tasks if t.task_id == target)
        assert task.product_requirement.kind == expected
        assert task.product_context["filters"]["maxPriceKRW"] == 10000
        assert task.status == "completed"
        assert next(t for t in restored[-1].tasks if t.task_id == target).product_requirement
        assert next(t for t in observed[-1]._task_results if t.task_id == tasks[0].task_id).reused
    stored = client.get(f"/api/chat/conversations/{room}", headers=AUTH).json()
    assert stored["messages"][-1]["text"] == result["answer"]


def test_added_same_role_task_ids_pg_restore_and_targeted_retry(memory_api, monkeypatch):
    from app.core.errors import UpstreamError
    from app.services import chat_service
    from tests.test_g8_consultation_intent import AdditionModel, knowledge_result
    from tests.test_g8_partial_success import Catalog, CombinedModel

    client, _ = memory_api
    monkeypatch.setattr(get_settings(), "g8_enabled", True)
    monkeypatch.setattr(get_settings(), "g8_read_retries", 0)
    catalog, observed, calls = Catalog(failures=0), [], []
    q1, q2 = "세안 후 보습 순서를 설명해줘", "자외선 차단제를 덧바르는 방법도 설명해줘"
    failing = True

    async def knowledge(question):
        calls.append(question)
        if question == q2 and failing:
            raise UpstreamError("synthetic knowledge failure")
        return knowledge_result(question, 1 if question == q1 else 2)

    monkeypatch.setattr(chat_service, "consult_knowledge", knowledge)

    class Observed(ChatService):
        async def answer(self, req, principal_key=None):
            result = await super().answer(req, principal_key)
            observed.append(result)
            return result

    service = Observed(FakeGraph(), CombinedModel(), catalog)
    client.app.dependency_overrides[get_chat_service] = lambda: service
    room, version = new_room(client), 0
    for operation, payload in [
        ("select_product", {"productId": "product-a"}),
        ("select_look", {"kind": "catalog", "lookId": "daily"}),
    ]:
        changed = client.patch(
            f"/api/chat/conversations/{room}/state",
            headers=AUTH,
            json={
                "requestId": str(uuid4()),
                "expectedConversationVersion": version,
                "operation": operation,
                "payload": payload,
            },
        )
        assert changed.status_code == 200
        version = changed.json()["conversationVersion"]
    first = ask(
        client,
        room,
        version,
        '"상품나"와 브랜드 비교하고 비슷한 룩도 찾아줘',
        request_type="beauty_consultation",
    )
    service._llm = AdditionModel([{"capability": "knowledge", "quote": q} for q in [q1, q2]])
    added = ask(
        client,
        room,
        first["conversation"]["version"],
        q1 + ". " + q2,
        request_type="beauty_consultation",
    )
    task_ids = [t.task_id for t in observed[-1]._consultation_parent.tasks if t.goal == "knowledge"]
    assert len(task_ids) == 2 and calls == [q1, q2]
    assert [t.status for t in observed[-1]._consultation_parent.tasks if t.goal == "knowledge"] == [
        "completed",
        "failed",
    ]
    failing = False
    service._llm = AdditionModel(action="retry", targets=[task_ids[1]])
    recovered = ask(
        client,
        room,
        added["conversation"]["version"],
        "덧바르는 방법만 다시 설명해줘",
        request_type="beauty_consultation",
    )
    assert calls == [q1, q2, q2]
    assert [
        t.task_id for t in observed[-1]._consultation_parent.tasks if t.goal == "knowledge"
    ] == task_ids
    records = {r.task_id: r for r in observed[-1]._task_results}
    assert records[task_ids[0]].reused and records[task_ids[0]].attempt == 0
    assert [e["documentId"] for e in recovered["knowledge"]["evidence"]] == [1, 2]
    restored = client.get(f"/api/chat/conversations/{room}", headers=AUTH).json()
    assert restored["messages"][-1]["text"] == recovered["answer"]


def test_live_common_entry_without_parent_seed_pg(memory_api, monkeypatch, record_property):
    from app.clients.catalog_client import CatalogClient
    from app.clients.llm_client import LlmClient

    if os.environ.get("G8_COMMON_ENTRY_LIVE") != "1":
        pytest.skip("Explicit synthetic live model/Catalog/PG run only")
    client, _ = memory_api
    monkeypatch.setattr(get_settings(), "g8_enabled", True)
    events, observed, turns = [], [], []
    original = httpx.AsyncClient.send

    async def send(http, request, *args, **kwargs):
        row = {"host": request.url.host, "path": request.url.path}
        events.append(row)
        result = await original(http, request, *args, **kwargs)
        row["status"] = result.status_code
        return result

    monkeypatch.setattr(httpx.AsyncClient, "send", send)

    class Service(ChatService):
        async def answer(self, req, principal_key=None):
            if not observed:
                assert req._consultation_parent is None
            result = await super().answer(req, principal_key)
            observed.append(result)
            return result

    llm = LlmClient(
        os.environ["LLM_BASE_URL"], os.environ["LLM_API_KEY"], os.environ["LLM_MODEL"], 80
    )
    client.app.dependency_overrides[get_chat_service] = lambda: Service(
        None, llm, CatalogClient("http://127.0.0.1:19834")
    )
    room = new_room(client)
    version = 0
    try:
        for question in ["토너 찾아줘. 크림도 찾아줘", "토너 쪽은 놔두고 크림만 15,000원 이하로"]:
            offset = len(events)
            result = ask(client, room, version, question, request_type="beauty_consultation")
            version = result["conversation"]["version"]
            parent = observed[-1]._consultation_parent
            turns.append(
                {
                    "question": question,
                    "answer": result["answer"],
                    "parent": parent.model_dump(mode="json", by_alias=True) if parent else None,
                    "events": events[offset:],
                    "modelConfiguredMode": "live",
                    "actualModelHttpCalls": sum(
                        e["host"] == "api.openai.com" for e in events[offset:]
                    ),
                }
            )
            assert parent and len(parent.tasks) == 2
            assert {t.product_requirement.kind for t in parent.tasks} == {"toner", "cream"}
            if len(turns) == 1:
                toner = next(t for t in parent.tasks if t.product_requirement.kind == "toner")
                saved_id, saved_products = toner.task_id, toner.display_result["products"]
            else:
                toner = next(t for t in parent.tasks if t.task_id == saved_id)
                assert toner.display_result["products"] == saved_products
                cream = next(t for t in parent.tasks if t.product_requirement.kind == "cream")
                assert cream.product_context["filters"]["maxPriceKRW"] == 15000
    finally:
        record_property(
            "common_entry_dialogue",
            json.dumps(
                {
                    "turns": turns,
                    "parentSeed": None,
                    "auth": "mock",
                    "pg": "live",
                    "catalog": "live",
                    "model": os.environ["LLM_MODEL"],
                },
                ensure_ascii=False,
            ),
        )


def test_live_common_result_cooperation_pg(memory_api, monkeypatch, record_property):
    from app.clients.knowledge_client import KnowledgeClient
    from app.clients.llm_client import LlmClient

    if os.environ.get("G8_COMMON_ENTRY_LIVE") != "1":
        pytest.skip("Explicit synthetic live cooperation only")
    client, _ = memory_api
    monkeypatch.setattr(get_settings(), "g8_enabled", True)
    monkeypatch.setattr(get_settings(), "g5_enabled", True)
    monkeypatch.setattr(get_settings(), "g7_structured_memory_enabled", True)
    original_init = KnowledgeClient.__init__

    def init(knowledge, *args, **kwargs):
        original_init(knowledge, *args, **kwargs)
        knowledge.http.base_url = httpx.URL("http://127.0.0.1:19838/internal/knowledge/")

    monkeypatch.setattr(KnowledgeClient, "__init__", init)
    observed, events, turns = [], [], []
    original_send = httpx.AsyncClient.send

    async def send(http, request, *args, **kwargs):
        item = {"host": request.url.host, "path": request.url.path}
        events.append(item)
        reply = await original_send(http, request, *args, **kwargs)
        item["status"] = reply.status_code
        return reply

    monkeypatch.setattr(httpx.AsyncClient, "send", send)

    class Service(ChatService):
        async def answer(self, req, principal_key=None):
            if not observed:
                assert req._consultation_parent is None
            result = await super().answer(req, principal_key)
            observed.append(result)
            return result

    llm = LlmClient(
        os.environ["LLM_BASE_URL"], os.environ["LLM_API_KEY"], os.environ["LLM_MODEL"], 80
    )
    client.app.dependency_overrides[get_chat_service] = lambda: Service(
        None, llm, CatalogClient("http://127.0.0.1:19834")
    )
    room = new_room(client)
    selected = client.patch(
        f"/api/chat/conversations/{room}/state",
        headers=AUTH,
        json={
            "requestId": str(uuid4()),
            "expectedConversationVersion": 0,
            "operation": "select_look",
            "payload": {"kind": "video", "lookId": "AG03mUj4vnY"},
        },
    )
    assert selected.status_code == 200
    question = (
        "내가 가진 립으로 이 룩에 필요한 제품만 추가 추천해줘. 아이섀도는 없어. "
        "이 룩 순서의 이유도 설명해줘."
    )
    try:
        result = ask(
            client, room, selected.json()["conversationVersion"], question, structured=True
        )
        parent = observed[-1]._consultation_parent
        assert any(e.get("continuation") == "accepted" for e in observed[-1]._parent_trace)
        assert [t.goal for t in parent.tasks] == ["owned_look", "knowledge"]
        assert observed[-1]._task_results[1].inputs["referenceContext"]["styleRecipe"]
        restored = client.get(f"/api/chat/conversations/{room}", headers=AUTH).json()
        from app.schemas.style_recipe import StyleRecipe

        assert StyleRecipe.model_validate(
            restored["messages"][-1]["displayPayload"]["styleRecipe"]
        ) == StyleRecipe.model_validate(result["styleRecipe"])
        turns.append(
            {
                "question": question,
                "answer": result["answer"],
                "modelConfiguredMode": "live",
                "actualModelHttpCalls": sum(e["host"] == "api.openai.com" for e in events),
            }
        )
        if os.environ.get("G8_COOPERATION_FOLLOWUP") == "1":
            task_ids = [t.task_id for t in parent.tasks]
            for message in ["설명만 다시 해줘", "설명은 빼고 추천만 2만원 이하로 다시 확인해줘"]:
                offset = len(events)
                result = ask(
                    client, room, result["conversation"]["version"], message, structured=True
                )
                current = observed[-1]._consultation_parent
                turns.append(
                    {
                        "question": message,
                        "answer": result["answer"],
                        "modelConfiguredMode": "live",
                        "actualModelHttpCalls": sum(
                            e["host"] == "api.openai.com" for e in events[offset:]
                        ),
                        "parent": current.model_dump(mode="json", by_alias=True),
                        "trace": observed[-1]._parent_trace,
                    }
                )
                assert [t.task_id for t in current.tasks] == task_ids
                if message == "설명만 다시 해줘" and parent.question:
                    assert current.question.model_dump(exclude={"version"}) == (
                        parent.question.model_dump(exclude={"version"})
                    )
                if message.startswith("설명은"):
                    assert current.tasks[1].status == "superseded"
                    assert not any(e["path"].endswith("/query") for e in events[offset:])
                restored = client.get(f"/api/chat/conversations/{room}", headers=AUTH).json()
                assert restored["messages"][-1]["text"] == result["answer"]
    finally:
        record_property(
            "common_cooperation_dialogue",
            json.dumps(
                {
                    "question": question,
                    "turns": turns,
                    "events": events,
                    "modelConfiguredMode": "live",
                    "actualModelHttpCalls": sum(e["host"] == "api.openai.com" for e in events),
                    "auth": "mock",
                    "pg": "live",
                    "catalog": "live",
                    "g5": "live",
                    "answer": observed[-1].answer if observed else None,
                    "trace": observed[-1]._parent_trace if observed else [],
                    "parent": observed[-1]._consultation_parent.model_dump(
                        mode="json", by_alias=True
                    )
                    if observed and observed[-1]._consultation_parent
                    else None,
                },
                ensure_ascii=False,
            ),
        )

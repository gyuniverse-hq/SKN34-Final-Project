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
from app.clients.skincare_recommendation_client import SkincareRecommendationClient
from app.core.config import get_settings
from app.core.db import get_chat_engine
from app.core.ratelimit import MemoryRateLimiter, get_rate_limiter
from app.repositories.chat_session_repository import ChatSessionRepository
from app.repositories.checkpoint_repository import CheckpointRepository
from app.repositories.conversation_repository import ConversationRepository
from app.schemas.chat import BeautyContext, BeautyFilters, ChatResponse, ChatSessionRef
from app.schemas.compound_consultation import (
    CompoundContext,
    CompoundDisplay,
    CompoundGoal,
    RankedOption,
    VerifiedOption,
)
from app.services import compound_consultation_graph as compound_graph
from app.services.chat_service import ChatService, get_chat_service
from app.services.skincare_recommendation_tool import SkincareRecommendationTool
from tests import test_g8_compound_consultation as skin_case
from tests.conftest import FakeGraph, FakeLlm
from tests.test_beauty_consultation import PlanLlm
from tests.test_chat_sessions import RedisDouble, SessionCatalog
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
    redis = RedisDouble()
    monkeypatch.setattr(
        "app.services.conversation_service.get_chat_sessions",
        lambda: ChatSessionRepository(redis),
    )
    fake = RecordingChat()
    client.app.dependency_overrides[get_chat_service] = lambda: fake
    client.app.dependency_overrides[get_rate_limiter] = lambda: MemoryRateLimiter(limit=1000)
    with client:
        yield client, fake


def create(client, request_id=None, *, headers=AUTH):
    request_id = request_id or str(uuid4())
    body = {"requestId": request_id, "entry": {"type": "general"}}
    result = client.post("/api/chat/conversations", headers=headers, json=body)
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


def test_compound_options_replay_and_restore_from_server_only(api, monkeypatch):
    client, service = api
    room = create(client)[0]["conversationId"]
    goal = CompoundGoal(goals=["dryness", "pores"], max_price_krw=20_000, fragrance_free=True)
    options = [
        RankedOption(
            rank=rank,
            product_id=f"p-{rank}",
            option_id=f"sale-{rank}",
            option_name=f"Option {rank}",
            product_name=f"Product {rank}",
            brand="example",
            has_shades=False,
            data_version="catalog-a",
        )
        for rank in range(1, 11)
    ]
    calls = []

    async def answer(prepared, _principal):
        calls.append(prepared._compound_context)
        if len(calls) == 1:
            display = CompoundDisplay(
                plan_version=1,
                goal=goal,
                options=[VerifiedOption(candidate=item, outcome="unknown") for item in options],
            )
            return ChatResponse(answer="Ten options checked", products=[], compound=display)
        next_goal = goal.model_copy(update={"wants_products": False})
        context = CompoundContext(plan_version=2, goal=next_goal, candidates=options)
        return ChatResponse(
            answer="Care follow-up",
            products=[],
            compound=CompoundDisplay(plan_version=2, goal=next_goal),
            chat_context=BeautyContext(issued_at=1, filters=BeautyFilters(), compound=context),
        )

    monkeypatch.setattr(service, "answer", answer)
    first = {
        "conversationId": room,
        "expectedConversationVersion": 0,
        "requestId": str(uuid4()),
        "message": "Care and recommendations",
    }
    response = client.post("/api/chat", headers=AUTH, json=first)
    assert response.status_code == 200, response.text
    replay = client.post("/api/chat", headers=AUTH, json=first)
    assert replay.json() == response.json()
    detail = client.get(f"/api/chat/conversations/{room}", headers=AUTH).json()
    assert detail["messages"][-1]["displayPayload"]["compound"] == response.json()["compound"]
    durable = detail["context"]["compound"]
    assert [item["optionId"] for item in durable["candidates"]] == [v.option_id for v in options]
    assert "options" not in durable
    forged = CompoundContext(plan_version=99, goal=goal, candidates=[])
    second = {
        **first,
        "expectedConversationVersion": 1,
        "requestId": str(uuid4()),
        "message": "Just explain the care this time",
        "chatContext": {"issuedAt": 1, "filters": {}, "compound": forged.model_dump(by_alias=True)},
    }
    followup = client.post("/api/chat", headers=AUTH, json=second)
    assert followup.status_code == 200, followup.text
    assert calls == [None, CompoundContext(plan_version=1, goal=goal, candidates=options)]
    restored = client.get(f"/api/chat/conversations/{room}", headers=AUTH).json()["context"]
    assert restored["compound"]["planVersion"] == 2
    assert restored["compound"]["candidates"][-1]["optionId"] == "sale-10"
    assert client.get(f"/api/chat/conversations/{room}", headers=OTHER).status_code == 404


def test_g8_graph_commits_replays_and_rechecks_the_saved_budget(api, monkeypatch, record_property):
    client, _ = api
    monkeypatch.setattr(get_settings(), "g8_enabled", True)
    consult = skin_case.install_knowledge(monkeypatch)
    downstream = skin_case.SkinApi()
    original_client = httpx.AsyncClient
    monkeypatch.setattr(
        httpx,
        "AsyncClient",
        lambda **kw: original_client(transport=httpx.MockTransport(downstream), **kw),
    )
    planner_inputs = []
    followup = "예산만 1만 5천 원 이하로 바꿔 줘."

    class Planner(skin_case.Planner):
        async def complete_with_tools(self, messages, tools, *, required_tool=None):
            if required_tool == "extract_knowledge_search_conditions":
                return await super().complete_with_tools(
                    messages, tools, required_tool=required_tool
                )
            inputs = json.loads(messages[-1]["content"])
            planner_inputs.append(inputs)
            reply, usage = await super().complete_with_tools(
                messages, tools, required_tool=required_tool
            )
            if inputs["utterance"] == followup:
                goal = skin_case.GOAL.model_copy(
                    update={"max_price_krw": 15000, "wants_knowledge": False}
                )
                call = reply["choices"][0]["message"]["tool_calls"][0]
                call["function"]["arguments"] = json.dumps(
                    {
                        "action": "refine",
                        "goal": goal.model_dump(by_alias=True),
                        "question": "",
                    }
                )
            return reply, usage

    traces = []
    execute = compound_graph.run_compound

    async def observe(*args, **kwargs):
        tasks = []
        traces.append(tasks)
        return await execute(*args, trace=tasks, **kwargs)

    monkeypatch.setattr(compound_graph, "run_compound", observe)
    chat = ChatService(
        None,
        Planner(),
        CatalogClient("https://api.test"),
        skincare=SkincareRecommendationTool(SkincareRecommendationClient("https://api.test")),
    )
    client.app.dependency_overrides[get_chat_service] = lambda: chat
    room = create(client)[0]["conversationId"]
    data = {"conversationId": room, "locale": "ko"}
    path = f"/api/chat/conversations/{room}"
    observations = []
    dsn = make_url(URL).set(drivername="postgresql").render_as_string(hide_password=False)
    for version, question in enumerate((skin_case.QUESTION, followup), 1):
        req_id = str(uuid4())
        request = {
            **data,
            "requestId": req_id,
            "expectedConversationVersion": version - 1,
            "message": question,
        }
        start_calls = len(downstream.calls)
        response = client.post("/api/chat", headers=AUTH, json=request)
        assert response.status_code == 200, response.text
        public = response.json()
        display = public["compound"]
        assert public["conversation"]["version"] == display["planVersion"] == version
        calls = downstream.calls[start_calls:]
        assert [route for route, _ in calls] == (
            (["/api/recommendations/skincare/v4"] if version == 1 else [])
            + ["/api/catalog/options/search"] * 2
        )
        assert [len(body["optionScope"]) for _, body in calls[-2:]] == [6, 4]
        assert all(
            body["maxPriceKRW"] == (20000 if version == 1 else 15000) for _, body in calls[-2:]
        )
        assert calls[-1][1]["optionScope"][2]["optionId"] == "sale-9"
        cards = [item for item in display["options"] if item["outcome"] == "eligible"]
        assert [item["candidate"]["optionId"] for item in cards] == (
            ["sale-9"] if version == 1 else []
        )
        if version == 1:
            assert display["options"][2]["outcome"] == "unknown"
            evidence_id = public["knowledge"]["evidence"][0]["id"]
            assert public["knowledge"]["claims"][0]["citations"] == [evidence_id]
            assert f"{skin_case.CARE_ADVICE} [1]" in public["answer"]
            assert evidence_id not in public["answer"]
        else:
            assert planner_inputs[-1]["previousGoal"]["maxPriceKRW"] == 20000
            assert display["options"][8]["outcome"] == "excluded"
        replay = client.post("/api/chat", headers=AUTH, json=request)
        assert replay.status_code == 200, replay.text
        assert replay.json()["answer"] == public["answer"] and replay.json()["compound"] == display
        assert len(traces) == len(planner_inputs) == version
        assert downstream.calls[start_calls:] == calls
        detail = client.get(path, headers=AUTH).json()
        assert len(detail["messages"]) == version * 2
        assert detail["messages"][-1]["displayPayload"]["compound"] == display
        assert detail["context"]["compound"]["candidates"][-1]["optionId"] == "sale-10"
        with psycopg.connect(dsn) as conn:
            thread, checkpoint, accepted = conn.execute(
                "SELECT thread_id, accepted_checkpoint_id, accepted_checkpoint_version "
                "FROM chat_conversations WHERE id = %s",
                (room,),
            ).fetchone()
            namespaces = conn.execute(
                "SELECT checkpoint_ns FROM checkpoints WHERE thread_id=%s "
                "UNION SELECT checkpoint_ns FROM checkpoint_blobs WHERE thread_id=%s "
                "UNION SELECT checkpoint_ns FROM checkpoint_writes WHERE thread_id=%s",
                (str(thread),) * 3,
            ).fetchall()
            checkpoint_bytes = conn.execute(
                "SELECT blob FROM checkpoint_blobs WHERE thread_id=%s "
                "UNION ALL SELECT blob FROM checkpoint_writes WHERE thread_id=%s "
                "UNION ALL SELECT convert_to(checkpoint::text, 'UTF8') "
                "FROM checkpoints WHERE thread_id=%s",
                (str(thread),) * 3,
            ).fetchall()
        assert namespaces == [("",)]
        forbidden = (b"sale-9", b"chunk8", b"fixture-rag", skin_case.QUESTION.encode())
        assert all(
            marker not in bytes(blob or b"") for (blob,) in checkpoint_bytes for marker in forbidden
        )
        with PostgresSaver.from_conn_string(dsn) as saver:
            saved = saver.get_tuple(
                {"configurable": {"thread_id": str(thread), "checkpoint_id": checkpoint}}
            )
        assert checkpoint and accepted == version
        channels = saved.checkpoint["channel_values"]
        assert channels["request_id"] == req_id and channels["execution_status"] == "done"
        assert "sale-9" not in str(channels) and skin_case.QUESTION not in str(channels)
        observations.append(
            {
                "version": version,
                "utterance": question,
                "plannerInput": planner_inputs[-1],
                "toolHttpRequests": calls,
                "tasks": traces[-1],
                "answer": public["answer"],
                "display": display,
                "knowledge": public.get("knowledge"),
                "httpStatus": response.status_code,
                "replayHttpStatus": replay.status_code,
                "replayAdditionalGraphCalls": 0,
                "replayAdditionalHttpCalls": len(downstream.calls) - start_calls - len(calls),
                "detailMessageCount": len(detail["messages"]),
                "acceptedCheckpointVersion": accepted,
                "checkpointExecutionStatus": channels["execution_status"],
                "checkpointNamespaces": [ns for (ns,) in namespaces],
                "rawCheckpointMarkersFound": 0,
                "durableCandidateScope": [
                    [v["rank"], v["productId"], v["optionId"]]
                    for v in detail["context"]["compound"]["candidates"]
                ],
            }
        )
    consult.assert_awaited_once_with(skin_case.CARE_QUESTION)
    record_property("g8_verified_turns", observations)


def test_room_deletion_is_retryable_and_does_not_resurrect_on_create_replay(api, monkeypatch):
    client, _ = api
    created, body = create(client)
    room = created["conversationId"]
    path = f"/api/chat/conversations/{room}"
    assert client.delete(path, headers=OTHER).status_code == 404
    real = CheckpointRepository.delete_thread

    async def fail(self, thread_id):
        raise OSError("temporary failure")

    monkeypatch.setattr(CheckpointRepository, "delete_thread", fail)
    failed = client.delete(f"/api/chat/conversations/{room}", headers=AUTH)
    assert (failed.status_code, failed.json()["code"]) == (503, "deletion_incomplete")
    assert client.get(f"/api/chat/conversations/{room}", headers=AUTH).status_code == 404
    monkeypatch.setattr(CheckpointRepository, "delete_thread", real)
    assert client.delete(path, headers=AUTH).status_code == 204
    assert client.delete(path, headers=AUTH).status_code == 204
    assert client.delete(path, headers=OTHER).status_code == 404
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


def test_room_delete_preserves_approved_memory_and_removes_pending_proposal(api, monkeypatch):
    client, _ = api
    monkeypatch.setattr(get_settings(), "g7_memory_enabled", True)
    headers = {"Authorization": f"Bearer ok-room-memory-{uuid4()}"}
    room = create(client, headers=headers)[0]["conversationId"]

    def propose(version, message):
        response = client.post(
            "/api/chat",
            headers=headers,
            json={
                "conversationId": room,
                "requestId": str(uuid4()),
                "expectedConversationVersion": version,
                "locale": "ko",
                "message": message,
            },
        )
        assert response.status_code == 200, response.text
        return response.json()["memoryProposal"]

    original = "코랄 립을 좋아하는 걸 기억해줘"
    proposal = propose(0, original)
    saved = client.post(
        "/api/chat/memories",
        headers=headers,
        json={
            "requestId": str(uuid4()),
            "proposalId": proposal["proposalId"],
            "expectedProposalVersion": proposal["version"],
            "confirmed": True,
        },
    )
    assert saved.status_code == 200, saved.text
    memory_id = saved.json()["memoryId"]
    pending = propose(1, "매트 립을 좋아하는 걸 기억해줘")
    assert pending["proposalId"] != proposal["proposalId"]

    assert client.delete(f"/api/chat/conversations/{room}", headers=headers).status_code == 204
    memories = client.get("/api/chat/memories", headers=headers).json()["memories"]
    assert [(item["id"], item["value"]) for item in memories] == [(memory_id, original)]
    dsn = make_url(URL).set(drivername="postgresql").render_as_string(hide_password=False)
    with psycopg.connect(dsn) as conn:
        assert conn.execute(
            "SELECT source_message_id FROM chat_memories WHERE id = %s", (memory_id,)
        ).fetchone() == (None,)
        assert conn.execute(
            "SELECT count(*) FROM chat_memory_proposals WHERE conversation_id = %s", (room,)
        ).fetchone() == (0,)


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


def test_list_summarizes_first_user_message_only_and_keeps_keyset_order(api):
    client, fake = api
    owner = {"Authorization": f"Bearer ok-summary-{uuid4()}"}
    other = {"Authorization": f"Bearer ok-summary-{uuid4()}"}
    product_room = create(client, headers=owner)[0]["conversationId"]
    ingredient_room = create(client, headers=owner)[0]["conversationId"]
    empty_room = create(client, headers=owner)[0]["conversationId"]
    other_room = create(client, headers=other)[0]["conversationId"]
    private_text = "synthetic-person@example.invalid"
    first = f"Suggest a moisturizing lip product in my price budget. My email is {private_text}."

    def send(room, headers, text, version=0):
        response = client.post(
            "/api/chat",
            headers=headers,
            json={
                "conversationId": room,
                "requestId": str(uuid4()),
                "expectedConversationVersion": version,
                "locale": "en",
                "message": text,
            },
        )
        assert response.status_code == 200, response.text

    send(product_room, owner, first)
    send(product_room, owner, "Can you show me a makeup look?", version=1)
    send(ingredient_room, owner, "Does this contain fragrance or other ingredients?")
    send(other_room, other, "Show me a makeup look")
    ids = [product_room, ingredient_room, empty_room]
    dsn = make_url(URL).set(drivername="postgresql").render_as_string(hide_password=False)
    with psycopg.connect(dsn) as conn:
        conn.execute(
            "UPDATE chat_conversations SET updated_at = TIMESTAMPTZ '2026-01-01 00:00:00+00' "
            "WHERE id = ANY(%s::uuid[])",
            (ids,),
        )

    first_page = client.get("/api/chat/conversations?limit=2", headers=owner)
    page = first_page.json()
    last_page = client.get(
        "/api/chat/conversations", headers=owner, params={"limit": 2, "cursor": page["nextCursor"]}
    )
    rows = page["conversations"] + last_page.json()["conversations"]
    assert [row["conversationId"] for row in rows] == sorted(ids, reverse=True)
    assert last_page.json()["nextCursor"] is None
    summaries = {row["conversationId"]: row.get("listSummary") for row in rows}
    assert summaries == {
        product_room: {"titleTopic": "product", "previewTopics": ["hydration", "price"]},
        ingredient_room: {"titleTopic": "ingredient", "previewTopics": []},
        empty_room: None,
    }
    assert private_text not in (first_page.text + last_page.text)
    assert first not in (first_page.text + last_page.text)
    assert len(fake.requests) == 4
    detail = client.get(f"/api/chat/conversations/{product_room}", headers=owner)
    assert detail.json()["messages"][0]["text"] == first


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


def test_restored_product_price_revalidates_the_server_candidates(api, monkeypatch):
    client, _ = api
    monkeypatch.setattr(get_settings(), "g1_supervisor_enabled", True)
    llm = PlanLlm(intent="search", category="lip")
    catalog = SessionCatalog()
    service = ChatService(None, llm, catalog, sessions=ChatSessionRepository(RedisDouble()))
    client.app.dependency_overrides[get_chat_service] = lambda: service
    room = create(client)[0]["conversationId"]
    body = {"conversationId": room, "locale": "ko"}
    first = client.post(
        "/api/chat",
        headers=AUTH,
        json={
            **body,
            "requestId": str(uuid4()),
            "expectedConversationVersion": 0,
            "message": "립 추천해줘",
        },
    )
    assert first.status_code == 200, first.text
    expected = first.json()["products"][1]
    refreshed_price = 9_777
    next(
        product for product in catalog.products if product.id == expected["id"]
    ).price_krw = refreshed_price
    detail = client.get(f"/api/chat/conversations/{room}", headers=AUTH)
    assert '"sessionToken"' not in detail.text

    llm.plan = {"intent": "detail", "scope": "previous", "ordinal": 2}
    followup = client.post(
        "/api/chat",
        headers=AUTH,
        json={
            **body,
            "requestId": str(uuid4()),
            "expectedConversationVersion": 1,
            "message": "두 번째 제품 가격을 자세히 알려 주세요.",
        },
    )
    assert followup.status_code == 200, followup.text
    assert [item["id"] for item in followup.json()["products"]] == [expected["id"]]
    assert f"{refreshed_price:,}" in followup.json()["answer"]
    assert not followup.json().get("chatContext")


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


def test_n01_condition_provenance_survives_pg_followups(api, monkeypatch, record_property):
    client, _ = api
    monkeypatch.setattr(get_settings(), "g8_enabled", True)
    reply = skin_case.resolved_ingredient_reply(monkeypatch)
    consult = skin_case.AsyncMock(return_value=skin_case.Consultation(reply=reply, trace={}))
    monkeypatch.setattr(skin_case.specialists, "consult_knowledge", consult)
    downstream = skin_case.SkinApi()
    original = httpx.AsyncClient
    monkeypatch.setattr(
        httpx, "AsyncClient", lambda **kw: original(transport=httpx.MockTransport(downstream), **kw)
    )
    extractor = skin_case.IngredientExtractor()

    class Planner(skin_case.Planner):
        calls = 0

        async def complete_with_tools(self, messages, tools, *, required_tool=None):
            if required_tool == "extract_knowledge_search_conditions":
                return await extractor.complete_with_tools(
                    messages, tools, required_tool=required_tool
                )
            self.calls += 1
            response, ms = await super().complete_with_tools(
                messages, tools, required_tool=required_tool
            )
            f = response["choices"][0]["message"]["tool_calls"][0]["function"]
            plan = json.loads(f["arguments"])
            turn = self.calls
            if turn > 1:
                plan["action"] = "refine"
                plan["goal"].update(maxPriceKRW=15000, wantsKnowledge=False)
                plan["question"] = ""
            if turn == 3:
                plan["removeKnowledgeIngredients"] = ["글리세린"]
            if turn >= 4:
                plan["goal"]["goals"] = ["sensitivity"]
            if turn in {5, 7}:
                plan["knowledgeAction"] = "clear"
            if turn == 6:
                plan["knowledgeAction"] = "reevaluate"
            f["arguments"] = json.dumps(plan)
            return response, ms

    planner = Planner()
    chat = ChatService(
        None,
        planner,
        CatalogClient("https://api.test"),
        skincare=SkincareRecommendationTool(SkincareRecommendationClient("https://api.test")),
    )
    client.app.dependency_overrides[get_chat_service] = lambda: chat
    room = create(client)[0]["conversationId"]
    observations = []
    for version, message in enumerate(
        [
            skin_case.QUESTION,
            "예산만 1만5천 원으로 바꿔 줘.",
            "글리세린 포함 조건은 삭제해 줘.",
            "모공 대신 민감함 목표로 제품을 추천해 줘.",
            "지식에서 제안한 조건은 모두 해제해 줘.",
            "지식 조건을 다시 적용해 줘. 제품도 추천해 줘.",
            "지식 조건을 삭제해 줘.",
        ],
        1,
    ):
        if version == 4:
            new_reply = skin_case.resolved_ingredient_reply(monkeypatch, "판테놀")
            consult.return_value = skin_case.Consultation(reply=new_reply, trace={})
            monkeypatch.setattr(skin_case.specialists, "consult_knowledge", consult)
        before = len(downstream.calls)
        payload = {
            "conversationId": room,
            "requestId": str(uuid4()),
            "expectedConversationVersion": version - 1,
            "message": message,
            "locale": "ko",
        }
        response = client.post("/api/chat", headers=AUTH, json=payload)
        assert response.status_code == 200, response.text
        detail = client.get(f"/api/chat/conversations/{room}", headers=AUTH).json()
        state = detail["context"]["compound"]
        assert state["goal"]["excludedIngredients"] == ["향료"]
        expected = {
            1: ["글리세린"],
            2: ["글리세린"],
            3: [],
            4: ["판테놀"],
            5: [],
            6: ["판테놀"],
            7: [],
        }[version]
        assert [c["ingredientName"] for c in state["knowledgeSearch"]["conditions"]] == expected
        assert state["knowledgeSearch"]["source"] == "knowledge"
        calls = downstream.calls[before:]
        assert len([p for p, b in calls if p.endswith("/v4")]) == (1 if version in {1, 4} else 0)
        count = len(downstream.calls)
        model_count = planner.calls + extractor.calls
        replay = client.post("/api/chat", headers=AUTH, json=payload)
        assert replay.status_code == 200
        for field in ("answer", "compound", "knowledge", "conversation"):
            assert replay.json().get(field) == response.json().get(field)
        assert len(downstream.calls) == count and planner.calls + extractor.calls == model_count
        observations.append(
            {
                "turn": version,
                "input": message,
                "httpStatus": response.status_code,
                "storedKnowledgeState": state["knowledgeSearch"],
                "toolHttpRequests": calls,
                "modelConfiguredMode": "mock",
                "actualRemoteModelCalls": 0,
                "mockPlannerCallsCumulative": planner.calls,
                "mockExtractorCallsCumulative": extractor.calls,
                "postgres": "live",
                "api": "mock_transport",
                "replayAdditionalCalls": 0,
            }
        )
    assert consult.await_count == extractor.calls == 3
    record_property("n01_followup_turns", observations)


@pytest.mark.parametrize("g1_enabled", [False, True])
def test_original_n01_pg_restores_clarification_without_client_history(
    api, monkeypatch, record_property, g1_enabled
):
    client, _ = api
    monkeypatch.setattr(get_settings(), "g8_enabled", True)
    monkeypatch.setattr(get_settings(), "g1_supervisor_enabled", g1_enabled)
    first = "오후에 화장이 뜨는데 원인 알려주고 나한테 맞는 제품도 찾아줘"
    question = "당김·각질이 있나요, 유분 때문에 뭉치나요? 기초와 베이스도 알려주세요."
    followup = "각질과 당김이 있어. 로션과 쿠션을 써. 예산은 2만 원이고 향료는 제외해 줘."
    consult = skin_case.install_knowledge(monkeypatch)
    downstream = skin_case.SkinApi()
    original = httpx.AsyncClient
    monkeypatch.setattr(
        httpx, "AsyncClient", lambda **kw: original(transport=httpx.MockTransport(downstream), **kw)
    )

    class Planner(skin_case.Planner):
        calls = 0
        restored = []

        async def complete_with_tools(self, messages, tools, *, required_tool=None):
            self.calls += 1
            response, ms = await super().complete_with_tools(
                messages, tools, required_tool=required_tool
            )
            if required_tool == "plan_skin_consultation":
                data = json.loads(messages[-1]["content"])
                f = response["choices"][0]["message"]["tool_calls"][0]["function"]
                if data["utterance"] == first:
                    plan = {"action": "clarify", "question": question}
                else:
                    assert data["utterance"] == followup
                    self.restored = [(m["role"], m["text"]) for m in data["recentMessages"]]
                    assert ("user", first) in self.restored
                    assert ("assistant", question) in self.restored
                    plan = json.loads(f["arguments"])
                    plan["goal"]["goals"] = ["dryness"]
                    plan["question"] = first + " / " + followup
                f["arguments"] = json.dumps(plan)
            return response, ms

    planner = Planner()
    chat = ChatService(
        None,
        planner,
        CatalogClient("https://api.test"),
        skincare=SkincareRecommendationTool(SkincareRecommendationClient("https://api.test")),
    )
    client.app.dependency_overrides[get_chat_service] = lambda: chat
    room = create(client)[0]["conversationId"]
    observations = []
    for version, message in enumerate([first, followup], 1):
        payload = {
            "conversationId": room,
            "requestId": str(uuid4()),
            "expectedConversationVersion": version - 1,
            "message": message,
            "locale": "ko",
        }
        assert "recentMessages" not in payload
        response = client.post("/api/chat", headers=AUTH, json=payload)
        assert response.status_code == 200, response.text
        body = response.json()
        if version == 1:
            assert body["resultType"] == "clarification" and body["answer"] == question
            assert body["products"] == [] and not body.get("compound")
            assert downstream.calls == [] and consult.await_count == 0
        else:
            consult.assert_awaited_once_with(first + " / " + followup)
            assert body["compound"]["goal"]["goals"] == ["dryness"]
            assert body["compound"]["options"][8]["outcome"] == "eligible"
        counts = (planner.calls, consult.await_count, len(downstream.calls))
        replay = client.post("/api/chat", headers=AUTH, json=payload)
        assert replay.status_code == 200
        assert replay.json()["answer"] == body["answer"]
        assert replay.json().get("compound") == body.get("compound")
        assert counts == (planner.calls, consult.await_count, len(downstream.calls))
        observations.append(
            {
                "turn": version,
                "input": message,
                "answer": body["answer"],
                "clientHistoryProvided": False,
                "modelConfiguredMode": "mock",
                "actualRemoteModelCalls": 0,
                "postgres": "live",
                "catalog": "mock_transport",
                "replayAdditionalCalls": 0,
                "mockCallsCumulative": counts,
            }
        )
    record_property(
        "original_n01_pg",
        {
            "g1Enabled": g1_enabled,
            "turns": observations,
            "serverRestoredHistory": planner.restored,
            "toolRequests": downstream.calls,
        },
    )

"""Supervisor contracts against real executors and fake providers, without network calls."""

from copy import deepcopy

import pytest
from pydantic import ValidationError

from app.core.errors import ApiError, UpstreamError
from app.repositories.ar_command_repository import MemoryArRequestRepository
from app.schemas.chat import ChatRequest, ChatResponse, ProductRef
from app.schemas.supervisor import ConditionCheck, ScreenContext, TaskPlan, ToolResult
from app.services.chat_service import (
    ChatService,
    build_plan,
    check_sufficiency,
    resolve_context,
    route_intent,
    verify_response,
)
from tests.conftest import FakeGraph, FakeLlm
from tests.test_ar_ack import Catalog as ArCatalog
from tests.test_ar_ack import JsonLlm, request_body
from tests.test_beauty_consultation import Catalog, PlanLlm, request


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    import httpx

    async def fail(*args, **kwargs):
        raise AssertionError("Supervisor tests must not call external APIs")

    monkeypatch.setattr(httpx.AsyncClient, "send", fail)


@pytest.mark.anyio
async def test_catalog_budget_and_followup_use_one_interpretation_each():
    llm = PlanLlm(intent="search", category="lip", maxPriceKRW=20000)
    catalog = Catalog()
    service = ChatService(FakeGraph(), llm, catalog)
    result = await service.answer(request())
    assert llm.calls == 1
    assert [p.id for p in result.products] == ["a", "b"]
    assert result.supervisor.plan.tasks == ["beauty"]
    assert result.supervisor.result.product_ids == ["a", "b"]
    assert all(e.source == "catalog_api" for e in result.supervisor.result.evidence)
    llm.plan = dict(intent="detail", scope="previous", ordinal=2)
    followup = await service.answer(request("두 번째 제품 가격은?", result.chat_context))
    assert llm.calls == 2
    assert followup.chat_context.candidate_ids == ["a", "b"]
    assert followup.chat_context.filters.max_price_krw == 20000
    assert [p.id for p in followup.products] == ["b"]
    assert "supervisor" not in followup.model_dump(mode="json")
    assert "toolResult" not in followup.model_dump(mode="json")
    assert ChatResponse.model_validate(followup.model_dump()).products == followup.products


@pytest.mark.anyio
async def test_missing_reference_and_unknown_ingredients_are_not_fabricated():
    service = ChatService(FakeGraph(), PlanLlm(intent="detail", scope="previous"), Catalog())
    result = await service.answer(request("이 제품 성분은?"))
    assert result.result_type == "clarification"
    assert result.supervisor.result.status == "clarification"
    service._llm = PlanLlm(intent="search", category="lip", fragranceFree=True)
    result = await service.answer(request("향료 없는 립 추천"))
    assert result.products  # Unverified candidates remain available for shade selection.
    assert result.result_type == "clarification"
    assert result.supervisor.result.status == "clarification"
    ingredient_checks = [
        c for c in result.supervisor.result.conditions if c.condition == "ingredient"
    ]
    assert ingredient_checks and all(c.verdict == "UNKNOWN" for c in ingredient_checks)


@pytest.mark.anyio
async def test_legacy_general_and_knowledge_keep_graph_path():
    for text, intent in [
        ("hello", "general"),
        ("성분 설명해줘", "ingredient"),
    ]:
        graph, llm = FakeGraph(), FakeLlm()
        result = await ChatService(graph, llm).answer(ChatRequest(message=text))
        assert result.answer == "Try Rom&nd Juicy Tint."
        assert graph.terms
        assert result.supervisor.intent.intent == intent
        assert result.supervisor.result.tool == "graph_chat"
        assert result.supervisor.result.status == "partial"
        assert result.supervisor.unavailable_tools == ["knowledge"]
        assert result.supervisor.result.application == "not_requested"


@pytest.mark.anyio
async def test_general_beauty_fallback_does_not_repeat_classification():
    class Llm(FakeLlm):
        calls = 0

        async def complete(self, messages):
            self.calls += 1
            return '{"intent":"general"}' if self.calls == 1 else "General advice"

    llm = Llm()
    result = await ChatService(FakeGraph(), llm, Catalog()).answer(request("사용법 알려줘"))
    assert result.answer == "General advice"
    assert llm.calls == 2  # one interpretation and one answer, never two interpretations


@pytest.mark.anyio
async def test_ar_proposes_but_never_reports_app_application(monkeypatch):
    monkeypatch.setenv("ENV", "local")
    from app.core.config import get_settings

    monkeypatch.setattr(get_settings(), "env", "local")
    service = ChatService(FakeGraph(), JsonLlm(), ArCatalog(), MemoryArRequestRepository())
    req = ChatRequest.model_validate(request_body())
    before = deepcopy(req.model_dump())
    result = await service.answer(req, "test-owner")
    assert result.ar_result.status == "proposed"
    assert result.supervisor.result.action_proposed
    assert result.supervisor.result.application == "awaiting_app_ack"
    assert req.model_dump() == before
    assert await service.answer(req, "test-owner") == result
    body = request_body()
    body["arContext"]["lip"] = None
    body["requestId"] = "0d8b4c3e-8c41-44d2-9b27-9a8e1471a421"
    result = await service.answer(ChatRequest.model_validate(body), "test-owner")
    assert result.supervisor.result.status == "clarification"
    assert not result.supervisor.result.action_proposed


@pytest.mark.anyio
async def test_compound_request_stops_without_llm_catalog_or_ar():
    llm = PlanLlm(intent="search", category="lip")
    result = await ChatService(FakeGraph(), llm, Catalog()).answer(request("립 추천하고 발라줘"))
    assert llm.calls == 0
    assert result.products == [] and result.ar_result is None
    assert result.supervisor.plan.tasks == []
    assert result.supervisor.result.status == "unsupported"


@pytest.mark.anyio
async def test_tool_error_is_not_an_empty_result():
    class Broken(Catalog):
        async def search_products(self, **kwargs):
            raise UpstreamError("offline")

    service = ChatService(FakeGraph(), PlanLlm(intent="search", category="lip"), Broken())
    with pytest.raises(ApiError) as error:
        await service.answer(request())
    assert error.value.code == "upstream_error"
    assert error.value.supervisor_result.status == "error"
    empty = Catalog()
    empty.products = []
    service._catalog = empty
    result = await service.answer(request())
    assert result.result_type == "empty"
    assert result.supervisor.result.status == "success"


def test_context_slots_and_contract_validation():
    req = request()
    req.screen_context = ScreenContext(screenId="P-02", productId="untrusted", lookId="look")
    ctx = resolve_context(req)
    assert ctx.screen.product_id == "untrusted" and ctx.trusted is False
    assert ctx.selected_product_id is None  # no automatic promotion of caller screen IDs
    decision = route_intent(ctx)
    assert build_plan(ctx, decision, check_sufficiency(ctx, decision)).tasks == ["graph_chat"]
    with pytest.raises(ValidationError):
        ConditionCheck(condition="price", verdict="probably")


def test_response_verifier_rejects_invented_refs_and_ar_on_read_paths():
    req = ChatRequest(message="hello")
    decision = route_intent(resolve_context(req))
    plan = TaskPlan(tasks=["graph_chat"])
    response = ChatResponse(
        answer="x", products=[ProductRef(id="invented", brand="x", name="x", category="lip")]
    )
    with pytest.raises(ApiError):
        verify_response(
            req,
            decision,
            plan,
            response,
            ToolResult(tool="graph_chat", status="success", product_ids=["real"]),
        )


@pytest.mark.anyio
@pytest.mark.parametrize("tool", ["knowledge"])
async def test_unimplemented_tools_return_unsupported_without_model_calls(tool):
    llm = PlanLlm(intent="general")
    service = ChatService(FakeGraph(), llm, Catalog())
    req = ChatRequest(message="hello")
    decision = route_intent(resolve_context(req))
    response, result = await service.execute_tool(req, decision, TaskPlan(tasks=[tool]))
    assert result.status == "unsupported" and result.reason == "tool_unavailable"
    assert response.products == [] and llm.calls == 0


@pytest.mark.anyio
async def test_beauty_request_cannot_smuggle_ar_context_or_invoke_ar(monkeypatch):
    service = ChatService(FakeGraph(), PlanLlm(intent="search", category="lip"), Catalog())
    body = request_body()
    body["requestType"] = "beauty_consultation"
    body["message"] = "립 추천해줘"
    req = ChatRequest.model_validate(body)
    before = deepcopy(req.model_dump())

    async def forbidden(*args):
        raise AssertionError("AR must not be called by a read-only tool")

    monkeypatch.setattr(service, "_propose_ar", forbidden)
    response = await service.answer(req)
    assert response.ar_result is None and req.model_dump() == before
    assert response.supervisor.result.application == "not_requested"


def test_verifier_rejects_execution_claims_and_filter_mismatch():
    req = ChatRequest(message="hello")
    decision = route_intent(resolve_context(req))
    response = ChatResponse(answer="x", products=[])
    with pytest.raises(ApiError):
        verify_response(
            req,
            decision,
            TaskPlan(tasks=["graph_chat"]),
            response,
            ToolResult(tool="graph_chat", status="success", action_proposed=True),
        )
    response.result_type = "recommendations"
    with pytest.raises(ApiError):
        verify_response(
            req,
            decision,
            TaskPlan(tasks=["graph_chat"]),
            response,
            ToolResult(
                tool="graph_chat",
                status="success",
                conditions=[ConditionCheck(condition="price", verdict="NOT_MATCH")],
            ),
        )


@pytest.mark.anyio
async def test_invalid_interpretation_remains_error_not_empty():
    service = ChatService(FakeGraph(), PlanLlm(intent="not-allowed"), Catalog())
    with pytest.raises(ApiError) as error:
        await service.answer(request())
    assert error.value.code == "invalid_chat_plan"
    assert error.value.supervisor_result.status == "error"


@pytest.mark.anyio
async def test_http_json_preserves_existing_fields(client, monkeypatch):
    from app.services.chat_service import get_chat_service

    service = ChatService(FakeGraph(), PlanLlm(intent="search", category="lip"), Catalog())
    client.app.dependency_overrides[get_chat_service] = lambda: service
    body = client.post(
        "/api/chat",
        json={"message": "립 추천", "requestType": "beauty_consultation"},
        headers={"Authorization": "Bearer ok-1"},
    ).json()
    assert body["answer"] and body["products"]
    assert [p["id"] for p in body["products"]] == body["chatContext"]["candidateIds"]
    assert "supervisor" not in body and "toolResult" not in body


@pytest.mark.anyio
async def test_catalog_price_conditions_are_from_facts_not_model_ids():
    llm = PlanLlm(intent="search", category="lip", maxPriceKRW=20000)
    result = await ChatService(FakeGraph(), llm, Catalog()).answer(request())
    checks = result.supervisor.result.conditions
    assert {c.condition for c in checks} == {"category", "maxPriceKRW"}
    assert all(c.verdict == "MATCH" for c in checks)
    assert {c.product_id for c in checks} == {p.id for p in result.products}


def test_read_path_rejects_even_valid_ar_payload_from_a_wrong_tool():
    from uuid import UUID

    from app.schemas.chat import ArResult

    req = ChatRequest(message="hello")
    response = ChatResponse(
        answer="x",
        products=[],
        arResult=ArResult(requestId=UUID("0d8b4c3e-8c41-44d2-9b27-9a8e1471a420"), status="noop"),
    )
    with pytest.raises(ApiError):
        verify_response(
            req,
            route_intent(resolve_context(req)),
            TaskPlan(tasks=["graph_chat"]),
            response,
            ToolResult(tool="graph_chat", status="success"),
        )

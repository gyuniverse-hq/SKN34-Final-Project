from unittest.mock import AsyncMock
from uuid import UUID

import pytest

from app.core.config import Settings, get_settings
from app.core.errors import ApiError, UpstreamError
from app.schemas.chat import ChatRequest
from app.services.chat_service import ChatService
from app.services.product_consultation_graph import product_supervisor
from tests.conftest import FakeGraph, FakeLlm
from tests.test_ar_ack import request_body
from tests.test_beauty_consultation import Catalog, PlanLlm, request


@pytest.fixture
def anyio_backend():
    return "asyncio"


def test_supervisor_flag_defaults_off(monkeypatch):
    monkeypatch.delenv("G1_SUPERVISOR_ENABLED", raising=False)
    assert Settings(_env_file=None).g1_supervisor_enabled is False


@pytest.mark.anyio
@pytest.mark.parametrize("request_type", ["chat", "beauty_consultation"])
async def test_enabled_graph_preserves_public_response(request_type, monkeypatch):
    if request_type == "chat":
        req = ChatRequest(message="화장 초보예요", locale="ko")
        llm = FakeLlm()
    else:
        req = request()
        llm = PlanLlm(intent="search", category="lip", maxPriceKRW=20000)
    service = ChatService(FakeGraph(), llm, Catalog())
    run_graph = AsyncMock(wraps=product_supervisor.ainvoke)
    monkeypatch.setattr(product_supervisor, "ainvoke", run_graph)
    settings = get_settings()
    monkeypatch.setattr(settings, "g1_supervisor_enabled", False)
    legacy = await service.answer(req)
    run_graph.assert_not_awaited()

    monkeypatch.setattr(settings, "g1_supervisor_enabled", True)
    result = await service.answer(req)
    run_graph.assert_awaited_once()
    state = run_graph.await_args.args[0]
    assert isinstance(state["turn_id"], UUID)
    assert state["locale"] == "ko"
    assert state["thread_id"] is None
    assert "request" not in state
    expected = legacy.model_dump(mode="json")
    actual = result.model_dump(mode="json")
    for payload in expected, actual:
        if payload.get("chatContext"):
            payload["chatContext"].pop("issuedAt", None)
    assert actual == expected
    assert result.supervisor == legacy.supervisor


@pytest.mark.anyio
async def test_enabled_graph_preserves_upstream_error(monkeypatch):
    monkeypatch.setattr(get_settings(), "g1_supervisor_enabled", True)
    service = ChatService(FakeGraph(), FakeLlm(error=UpstreamError("provider unavailable")))
    with pytest.raises(ApiError) as caught:
        await service.answer(ChatRequest(message="hello"))
    assert (caught.value.status, caught.value.code) == (502, "upstream_error")
    assert caught.value.supervisor_result.tool == "graph_chat"


@pytest.mark.anyio
async def test_production_ar_is_still_closed_before_graph(monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "env", "production")
    monkeypatch.setattr(settings, "g1_supervisor_enabled", True)
    run_graph = AsyncMock()
    monkeypatch.setattr(product_supervisor, "ainvoke", run_graph)
    service = ChatService(FakeGraph(), FakeLlm())
    with pytest.raises(ApiError) as caught:
        await service.answer(ChatRequest.model_validate(request_body()))
    assert (caught.value.status, caught.value.code) == (503, "ar_requests_unavailable")
    run_graph.assert_not_awaited()

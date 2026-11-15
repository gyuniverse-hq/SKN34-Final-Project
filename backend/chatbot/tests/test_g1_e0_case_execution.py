"""Opt-in per-case E0 execution; results are synthetic and never production evidence."""

import asyncio
import base64
import json
import os
from pathlib import Path

import httpx
import pytest

from app.clients.catalog_client import CatalogClient
from app.core.auth import ChatPrincipal, chat_principal
from app.core.config import get_settings
from app.core.ratelimit import MemoryRateLimiter, get_rate_limiter
from app.main import create_app
from app.services.chat_service import ChatService, get_chat_service
from tests.conftest import FakeGraph, FakeLlm
from tests.g1_e1_live_driver import FixtureModel
from tests.test_g1_catalog_tool import row


class GeneralFixtureModel:
    configured = True

    def __init__(self):
        self.calls = 0

    async def complete_with_tools(self, messages, tools, **kwargs):
        self.calls += 1
        return {
            "id": "e0-general-completion",
            "model": "e0-general-fixture",
            "choices": [
                {
                    "finish_reason": "stop",
                    "message": {"content": "피부 상태와 원하는 표현에 맞춰 가볍게 시작해 보세요."},
                }
            ],
        }, 0


class LegacyFixtureModel(FakeLlm):
    def __init__(self):
        super().__init__()
        self.calls = 0

    async def complete(self, messages):
        self.calls += 1
        return await super().complete(messages)


@pytest.mark.anyio
@pytest.mark.skipif(not os.environ.get("G1_E0_CASE"), reason="Only the E0 driver selects a case")
async def test_case_observation(monkeypatch):
    item = json.loads(base64.b64decode(os.environ["G1_E0_CASE"]).decode("utf-8"))
    case, variant, run_id = item["case"], item["variantId"], item["runId"]
    is_general = case["caseId"].startswith("G1-GEN-")
    is_legacy = case["caseId"] == "G1-REG-01"
    model = (
        LegacyFixtureModel()
        if is_legacy
        else GeneralFixtureModel()
        if is_general
        else FixtureModel(case)
    )
    monkeypatch.setattr(get_settings(), "g1_supervisor_enabled", not is_legacy)
    app = create_app()
    route = []
    original_choose = ChatService._choose_g1_turn

    async def observe_choose(service, request):
        turn = await original_choose(service, request)
        if turn:
            route.append(turn.plan.intent)
        return turn

    monkeypatch.setattr(ChatService, "_choose_g1_turn", observe_choose)
    app.dependency_overrides[get_chat_service] = lambda: ChatService(
        FakeGraph() if is_legacy else None, model, CatalogClient("http://g1-e0-catalog.invalid")
    )
    app.dependency_overrides[chat_principal] = lambda: ChatPrincipal(rate_limit_key="guest:g1-e0")
    app.dependency_overrides[get_rate_limiter] = lambda: MemoryRateLimiter(100)
    entry = next(
        (v for v in case["input"].get("requiredVariants", []) if v["variantId"] == variant), {}
    )
    body = {
        "message": case["input"]["message"],
        "locale": case["input"]["locale"],
        "requestType": entry.get("requestType", case["input"]["requestType"]),
    }
    products = [row("e0-product", brand="롬앤")]
    events = []
    original = httpx.AsyncClient.send

    async def send(client, request, *args, **kwargs):
        if request.url.host == "g1-e0-catalog.invalid":
            result = httpx.Response(200, json={"products": products}, request=request)
            events.append(
                {
                    "name": "catalog.search_products",
                    "method": request.method,
                    "path": request.url.path,
                    "status": 200,
                    "query": dict(request.url.params),
                    "category": request.url.params.get("category"),
                }
            )
            return result
        return await original(client, request, *args, **kwargs)

    monkeypatch.setattr(httpx.AsyncClient, "send", send)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://g1-e0"
    ) as client:
        response = await client.post("/api/chat", json=body, headers={"X-Request-ID": run_id})
    result = {
        "request": body,
        "httpStatus": response.status_code,
        "response": response.json(),
        "events": events,
        "fixtureProductIds": [p["id"] for p in products],
        "modelCalls": model.calls,
        "routeIntent": route[0] if len(route) == 1 else None,
    }
    await asyncio.to_thread(
        Path(os.environ["G1_E0_CAPTURE"]).write_text,
        json.dumps(result, ensure_ascii=False),
        encoding="utf-8",
    )
    assert response.status_code == 200


@pytest.fixture
def anyio_backend():
    return "asyncio"

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
from app.services import chat_service
from app.services.chat_service import ChatService, get_chat_service
from app.services.g1_catalog_tool import G1CatalogTool
from tests.conftest import FakeGraph, FakeLlm
from tests.g1_e1_live_driver import FixtureModel
from tests.run_g1_evaluation import grade
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
    router_decisions = []
    original_choose = ChatService._choose_g1_turn
    original_route = chat_service.route_intent

    def observe_route(context):
        decision = original_route(context)
        router_decisions.append(decision.intent)
        return decision

    async def observe_choose(service, request):
        turn = await original_choose(service, request)
        if turn:
            route.append(turn.plan.intent)
        return turn

    monkeypatch.setattr(ChatService, "_choose_g1_turn", observe_choose)
    monkeypatch.setattr(chat_service, "route_intent", observe_route)
    tool_calls, model_calls, service_entries = [], [], []
    original_answer = ChatService.answer

    async def observed_answer(self, *args, **kwargs):
        service_entries.append("answer")
        return await original_answer(self, *args, **kwargs)

    monkeypatch.setattr(ChatService, "answer", observed_answer)
    for name in ("search_products", "get_product_detail"):
        original_tool = getattr(G1CatalogTool, name)

        async def observed_tool(self, *args, _name=name, _original=original_tool, **kwargs):
            tool_calls.append({"name": _name})
            return await _original(self, *args, **kwargs)

        monkeypatch.setattr(G1CatalogTool, name, observed_tool)
    for name in ("complete", "complete_with_tools"):
        if not hasattr(model, name):
            continue
        original_model = getattr(model, name)

        async def observed_model(*args, _name=name, _original=original_model, **kwargs):
            model_calls.append({"name": _name})
            return await _original(*args, **kwargs)

        monkeypatch.setattr(model, name, observed_model)
    app.dependency_overrides[get_chat_service] = lambda: ChatService(
        FakeGraph() if is_legacy else None, model, CatalogClient("http://g1-e0-catalog.invalid")
    )
    app.dependency_overrides[chat_principal] = lambda: ChatPrincipal(rate_limit_key="guest:g1-e0")
    limiter = MemoryRateLimiter(1 if case["caseId"] == "G1-ERR-09" else 100)
    app.dependency_overrides[get_rate_limiter] = lambda: limiter
    entry = next(
        (v for v in case["input"].get("requiredVariants", []) if v["variantId"] == variant), {}
    )
    body = {
        "message": case["input"]["message"],
        "locale": case["input"]["locale"],
        "requestType": entry.get("requestType", case["input"]["requestType"]),
    }
    products = [] if case["caseId"] == "G1-CAT-07" else [row("e0-product", brand="롬앤")]
    events = []
    injected = {
        "G1-ERR-01": "timeout",
        "G1-ERR-02": "upstream_http_error",
        "G1-ERR-03": "invalid_json",
        "G1-ERR-06": "duplicate_ids",
    }.get(case["caseId"])
    original = httpx.AsyncClient.send

    async def send(client, request, *args, **kwargs):
        if request.url.host == "g1-e0-catalog.invalid":
            event = {
                "name": "catalog.search_products",
                "method": request.method,
                "path": request.url.path,
                "query": dict(request.url.params),
                "category": request.url.params.get("category"),
                "faultKind": injected,
            }
            if injected == "timeout":
                events.append(event | {"status": None})
                raise httpx.ReadTimeout("injected timeout", request=request)
            status = 503 if injected == "upstream_http_error" else 200
            if injected == "invalid_json":
                result = httpx.Response(status, content=b"not-json", request=request)
            else:
                rows = [products[0], products[0]] if injected == "duplicate_ids" else products
                result = httpx.Response(status, json={"products": rows}, request=request)
                event["productCount"] = len(rows)
                event["productIds"] = [product["id"] for product in rows]
            events.append(event | {"status": status})
            return result
        return await original(client, request, *args, **kwargs)

    monkeypatch.setattr(httpx.AsyncClient, "send", send)
    preflight = None
    if case["caseId"] == "G1-CAT-07":
        async with httpx.AsyncClient() as catalog:
            check = await catalog.get(
                "http://g1-e0-catalog.invalid/api/products",
                params={"q": case["expected"]["allowedArgs"]["q"]},
            )
        preflight = {
            "httpStatus": check.status_code,
            "productIds": [p["id"] for p in check.json()["products"]],
            "request": events[-1],
        }
        events.clear()
    rate_trace = None
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://g1-e0"
    ) as client:
        if case["caseId"] == "G1-ERR-09":
            first = await client.post("/api/chat", json=body, headers={"X-Request-ID": run_id})
            assert first.status_code == 200
            tool_before, model_before, service_before = (
                len(tool_calls),
                len(model_calls),
                len(service_entries),
            )
        response = await client.post("/api/chat", json=body, headers={"X-Request-ID": run_id})
        # If the service boundary was entered, the narrower probes cannot certify all tools.
        if case["caseId"] == "G1-ERR-09" and len(service_entries) == service_before:
            rate_trace = {
                "tools": tool_calls[tool_before:],
                "modelCalls": model_calls[model_before:],
                "serviceEntriesBefore": service_before,
                "serviceEntriesAfter": len(service_entries),
            }
    result = {
        "request": body,
        "httpStatus": response.status_code,
        "response": response.json(),
        "events": events,
        "fixtureProductIds": [p["id"] for p in products],
        "modelCalls": model.calls,
        "routeIntent": (
            router_decisions[0]
            if case["caseId"] == "G1-CAT-08" and router_decisions
            else route[0]
            if len(route) == 1
            else None
        ),
        "catalogPreflight": preflight,
        "catalogResultCount": (events[-1].get("productCount") if events else None),
        "faultKind": next((event["faultKind"] for event in events if event["faultKind"]), None),
        "rateLimitTrace": rate_trace,
    }
    await asyncio.to_thread(
        Path(os.environ["G1_E0_CAPTURE"]).write_text,
        json.dumps(result, ensure_ascii=False),
        encoding="utf-8",
    )
    if injected or case["caseId"] == "G1-ERR-09":
        assert response.status_code >= 400
    else:
        assert response.status_code == 200


@pytest.mark.parametrize(
    ("predicate", "fault"),
    [
        ("error.timeout_not_empty", "timeout"),
        ("error.upstream_not_empty", "upstream_http_error"),
        ("error.invalid_json_rejected", "invalid_json"),
    ],
)
def test_fault_predicates_require_injection_and_reject_success(predicate, fault):
    error = {"httpStatus": 502, "response": {"error": "fixture failure", "code": "upstream"}}
    assert grade(predicate, error) == "NOT_RUN"
    assert grade(predicate, error | {"fault": {"kind": fault}}) == "PASS"
    fake_success = error | {
        "fault": {"kind": fault},
        "httpStatus": 200,
        "response": {"answer": "fixture success", "products": []},
    }
    assert grade(predicate, fake_success) == "FAIL"


def test_empty_preflight_and_product_route_require_actual_observations():
    assert grade("catalog.preflight_empty", {"sourceSnapshotId": "fixture"}) == "NOT_RUN"
    assert (
        grade(
            "catalog.preflight_empty",
            {
                "sourceSnapshotId": "fixture",
                "catalogPreflight": {"httpStatus": 200, "productIds": ["p"]},
            },
        )
        == "FAIL"
    )
    assert grade("route.intent_product", {}) == "NOT_RUN"
    assert grade("route.intent_product", {"routeIntent": "general"}) == "FAIL"


def test_rate_limit_does_not_pass_missing_or_nonempty_call_trace():
    base = {
        "httpStatus": 429,
        "requestId": "r",
        "response": {"error": "limit", "code": "rate_limited"},
    }
    assert grade("trace.no_tool_after_rate_limit", base) == "NOT_RUN"
    trace = {
        "requestId": "r",
        "completeDomains": ["tools", "modelCalls"],
        "tools": [],
        "modelCalls": [],
    }
    assert grade("trace.no_tool_after_rate_limit", base | {"trace": trace}) == "PASS"
    assert (
        grade(
            "trace.no_tool_after_rate_limit",
            base | {"trace": trace | {"tools": [{"name": "catalog"}]}},
        )
        == "FAIL"
    )


def test_duplicate_product_response_is_not_accepted():
    observation = {
        "httpStatus": 200,
        "response": {
            "answer": "fixture",
            "products": [
                {"id": "same", "brand": "B", "name": "P", "category": "lip"},
                {"id": "same", "brand": "B", "name": "P", "category": "lip"},
            ],
        },
    }
    assert grade("catalog.duplicate_ids_not_exposed", observation) == "FAIL"
    assert grade("catalog.duplicate_ids_not_exposed", {"httpStatus": 200}) == "NOT_RUN"


@pytest.fixture
def anyio_backend():
    return "asyncio"

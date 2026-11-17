import httpx
import pytest
from langgraph.graph import END, START, StateGraph

from app.core.observability import catalog_tool_call_id
from app.schemas.supervisor import IntentDecision
from tests.g1_e3_live_driver import (
    GraphCapture,
    ObservedGraph,
    catalog_http_observer,
    measure_empty_preflight,
)
from tests.run_g1_evaluation import grade


@pytest.fixture
def anyio_backend():
    return "asyncio"


def test_trace_domains_do_not_make_other_domains_complete():
    observation = {
        "requestId": "one",
        "trace": {
            "requestId": "one",
            "complete": False,
            "completeDomains": ["catalogHttp"],
            "catalogHttp": [
                {"name": "catalog.search_products", "method": "GET", "path": "/api/products"}
            ],
        },
    }
    assert grade("trace.catalog_called", observation) == "PASS"
    assert grade("trace.no_unrequested_write", observation) == "NOT_RUN"
    observation["trace"]["completeDomains"].append("tools")
    observation["trace"]["tools"] = [
        {"callId": "actual-call", "name": "catalog.search_products", "status": "success"}
    ]
    observation["trace"]["catalogHttp"][0]["callId"] = "actual-call"
    assert grade("trace.tool_http_joined", observation) == "PASS"
    assert grade("trace.no_unverified_success", observation) == "NOT_RUN"
    observation["trace"]["requestId"] = "other"
    assert grade("trace.catalog_called", observation) == "NOT_RUN"


@pytest.mark.anyio
async def test_callback_captures_real_langgraph_nodes_without_state():
    def plan(state):
        return state | {"planned": True}

    def execute(state):
        return state | {"executed": True}

    graph = (
        StateGraph(dict)
        .add_node("plan_turn", plan)
        .add_node("execute_turn", execute)
        .add_edge(START, "plan_turn")
        .add_edge("plan_turn", "execute_turn")
        .add_edge("execute_turn", END)
        .compile()
    )
    capture = GraphCapture()
    await ObservedGraph(graph, capture).ainvoke(
        {
            "private": "not collected",
            "decision": IntentDecision(intent="general", request_type_hint="chat"),
        }
    )
    nodes = capture.nodes
    assert {n["name"] for n in nodes} == {"plan_turn", "execute_turn"}
    assert capture.route_intent == "general"
    assert "private" not in repr(nodes)


@pytest.mark.anyio
async def test_catalog_observer_records_http_and_call_identity_without_headers(monkeypatch):
    records = []
    _, observed = catalog_http_observer("http://catalog.local", records)
    monkeypatch.setattr(httpx.AsyncClient, "send", observed)
    token = catalog_tool_call_id.set("call-123")
    try:
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(lambda _: httpx.Response(200, json={"products": []}))
        ) as client:
            await client.get(
                "http://catalog.local/api/products?category=lip",
                headers={"Authorization": "not-recorded"},
            )
            await client.get("http://catalog.local/api/products/test-product")
            await client.get("http://unrelated.local/api/products")
    finally:
        catalog_tool_call_id.reset(token)
    assert records == [
        {
            "name": "catalog.search_products",
            "method": "GET",
            "path": "/api/products",
            "callId": "call-123",
            "category": "lip",
            "status": 200,
        },
        {
            "name": "catalog.get_product_detail",
            "method": "GET",
            "path": "/api/products/{productId}",
            "productId": "test-product",
            "callId": "call-123",
            "category": None,
            "status": 200,
        },
    ]


@pytest.mark.anyio
async def test_empty_preflight_uses_actual_http_and_is_bound_to_run():
    seen = []

    def reply(request):
        seen.append(request.url.params.get("q"))
        return httpx.Response(200, json={"products": []})

    async with httpx.AsyncClient(transport=httpx.MockTransport(reply)) as client:
        result = await measure_empty_preflight(
            client, "http://catalog.local", "없는립", "run-1", "fixture"
        )
    assert seen == ["없는립"]
    observation = {
        "environment": "E3",
        "runId": "run-1",
        "sourceSnapshotId": "snapshot",
        "fixtureRowSha256": "fixture",
        "request": {"body": {"message": "없는립 보여줘"}},
        "catalogPreflight": result,
    }
    assert grade("catalog.preflight_empty", observation) == "PASS"
    assert grade("catalog.preflight_empty", observation | {"runId": "other"}) == "NOT_RUN"
    assert (
        grade("catalog.preflight_empty", observation | {"fixtureRowSha256": "other"}) == "NOT_RUN"
    )
    mismatched = dict(result, query="다른검색어")
    assert (
        grade("catalog.preflight_empty", observation | {"catalogPreflight": mismatched})
        == "NOT_RUN"
    )
    assert (
        grade(
            "catalog.preflight_empty",
            observation | {"catalogPreflight": dict(result, productIds=["p"])},
        )
        == "FAIL"
    )


@pytest.mark.anyio
async def test_preflight_does_not_treat_http_error_as_empty():
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda _: httpx.Response(503))
    ) as client:
        with pytest.raises(httpx.HTTPStatusError):
            await measure_empty_preflight(client, "http://catalog.local", "q", "run-1", "fixture")


def test_auth_results_do_not_create_an_unobserved_foreign_session():
    normal_response = {
        "response": {"answer": "ok", "products": []},
        "httpStatus": 200,
        "auth": {"results": [200], "baselineResults": [200]},
    }
    assert grade("security.no_cross_user_leak", normal_response) == "NOT_RUN"

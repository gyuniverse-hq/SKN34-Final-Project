"""Collect a real G1 model turn through the chatbot ASGI route.

The caller supplies an independently verified E1 fixture preflight JSON via
G1_E3_PREFLIGHT and the local Catalog HTTP base via G1_E3_CATALOG_URL. This
driver does not perform authentication, Redis-session, or UI verification.
G1_E3_ENV_FILE can point to a private configuration file outside the checkout.
"""
# This executable is launched by path from the collector, outside package mode.
# ruff: noqa: E402

import asyncio
import contextlib
import hashlib
import json
import logging
import os
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import unquote

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
LOCAL_ENV = Path(__file__).resolve().parents[3] / ".env.local"
CHATBOT_ROOT = Path(__file__).resolve().parents[1]

import httpx
from dotenv import dotenv_values
from langchain_core.callbacks.base import BaseCallbackHandler

from app.clients.catalog_client import CatalogClient
from app.clients.llm_client import LlmClient
from app.core.auth import ChatPrincipal, chat_principal
from app.core.config import get_settings
from app.core.observability import catalog_tool_call_id
from app.core.ratelimit import MemoryRateLimiter, get_rate_limiter
from app.main import app
from app.services import chat_service
from app.services.chat_service import ChatService, get_chat_service
from app.services.g1_model_service import PROMPT_VERSION


class Capture(logging.Handler):
    def __init__(self):
        super().__init__()
        self.events = []

    def emit(self, record):
        if record.msg in {
            "g1_model_completion",
            "catalog_http",
            "g1_catalog_tool_result",
            "g1_catalog_tool_retry",
            "g1_model_tool_rejected",
        }:
            fields = (
                "model_id",
                "model_response_id",
                "prompt_version",
                "request_type",
                "tool_call_id",
                "tool_name",
                "path",
                "status",
                "method",
                "error_type",
                "result_type",
                "product_ids",
                "reason",
            )
            self.events.append(
                {"event": record.msg}
                | {k: getattr(record, k) for k in fields if hasattr(record, k)}
            )


class RecordedLlm(LlmClient):
    def __init__(self, *args):
        super().__init__(*args)
        self.calls = []

    async def complete_with_tools(self, messages, tools, *, required_tool=None):
        result, duration = await super().complete_with_tools(
            messages, tools, required_tool=required_tool
        )
        self.calls.append(
            {
                "responseId": result.get("id"),
                "modelId": result.get("model"),
                "durationMs": duration,
                "finishReason": result.get("choices", [{}])[0].get("finish_reason"),
                "toolCalls": result.get("choices", [{}])[0]
                .get("message", {})
                .get("tool_calls", []),
            }
        )
        return result, duration

    async def complete(self, messages):
        result = await super().complete(messages)
        self.calls.append({"kind": "explanation", "response": result})
        return result


class RecordedCatalog(CatalogClient):
    def __init__(self, base):
        super().__init__(base)
        self.results = []

    async def search_products(self, **kwargs):
        products = await super().search_products(**kwargs)
        self.results.append(
            {
                "operation": "search",
                "arguments": kwargs,
                "products": [p.model_dump(mode="json", by_alias=True) for p in products],
            }
        )
        return products

    async def get_product(self, product_id):
        product = await super().get_product(product_id)
        self.results.append(
            {
                "operation": "detail",
                "productId": product_id,
                "product": product.model_dump(mode="json", by_alias=True) if product else None,
            }
        )
        return product


def detail_source_shade_pairs(results):
    """Return only fully observed detail-product shade lists, never inferred response shades."""
    if not results or any(result.get("operation") != "detail" for result in results):
        return None
    pairs = []
    for result in results:
        product = result.get("product")
        if (
            not isinstance(product, dict)
            or not isinstance(product.get("id"), str)
            or not product["id"].strip()
            or product["id"] != result.get("productId")
        ):
            return None
        shades = product.get("shades")
        if not isinstance(shades, list):
            return None
        for shade in shades:
            if (
                not isinstance(shade, dict)
                or not isinstance(shade.get("id"), str)
                or not shade["id"].strip()
            ):
                return None
            pairs.append({"productId": product["id"], "shadeId": shade["id"]})
    return pairs


class GraphCapture(BaseCallbackHandler):
    """Observe completed graph nodes without retaining their input or output state."""

    def __init__(self):
        self.active = {}
        self.nodes = []
        self.route_intent = None

    def on_chain_start(self, serialized, inputs, *, run_id, name=None, **kwargs):
        if name in {"plan_turn", "execute_turn"}:
            self.active[run_id] = name
        if name == "plan_turn" and isinstance(inputs, dict):
            decision = inputs.get("decision")
            intent = getattr(decision, "intent", None)
            if isinstance(intent, str) and intent.strip():
                self.route_intent = intent

    def on_chain_end(self, outputs, *, run_id, **kwargs):
        name = self.active.pop(run_id, None)
        if name:
            self.nodes.append({"name": name, "runId": str(run_id)})

    def on_chain_error(self, error, *, run_id, **kwargs):
        self.active.pop(run_id, None)


class ObservedGraph:
    def __init__(self, graph, callback):
        self.graph = graph
        self.callback = callback

    async def ainvoke(self, value, **kwargs):
        config = dict(kwargs.pop("config", {}) or {})
        config["callbacks"] = [*config.get("callbacks", []), self.callback]
        return await self.graph.ainvoke(value, config=config, **kwargs)


def catalog_http_observer(base, records):
    """Observe real HTTP sends to the configured Catalog origin during this one request."""
    origin = httpx.URL(base)
    original = httpx.AsyncClient.send

    async def send(client, request, *args, **kwargs):
        is_catalog = (request.url.scheme, request.url.host, request.url.port) == (
            origin.scheme,
            origin.host,
            origin.port,
        )
        entry = None
        if is_catalog:
            path = request.url.path
            product_id = None
            if path == "/api/products":
                name = "catalog.search_products"
            elif path.startswith("/api/products/") and path.count("/") == 3:
                product_id = unquote(path.rsplit("/", 1)[-1])
                path, name = "/api/products/{productId}", "catalog.get_product_detail"
            else:
                name = "catalog.other"
            entry = {
                "name": name,
                "method": request.method,
                "path": path,
                "callId": catalog_tool_call_id.get(),
                "category": request.url.params.get("category"),
            }
            if product_id is not None:
                entry["productId"] = product_id
        try:
            result = await original(client, request, *args, **kwargs)
        except Exception:
            if entry is not None:
                entry["status"] = None
                records.append(entry)
            raise
        if entry is not None:
            entry["status"] = result.status_code
            records.append(entry)
        return result

    return original, send


async def measure_empty_preflight(client, base, query, run_id, fixture_hash):
    response = await client.get(base.rstrip("/") + "/api/products", params={"q": query})
    response.raise_for_status()
    if response.status_code != 200:
        raise ValueError("Unexpected Catalog preflight status")
    rows = response.json()["products"]
    if not isinstance(rows, list) or any(
        not isinstance(row, dict) or not isinstance(row.get("id"), str) for row in rows
    ):
        raise ValueError("Invalid Catalog preflight response")
    return {
        "runId": run_id,
        "query": query,
        "httpStatus": response.status_code,
        "productIds": [row["id"] for row in rows],
        "fixtureRowSha256": fixture_hash,
        "observedAtUtc": datetime.now(UTC).isoformat(),
    }


async def run(item):
    case, variant, run_id = item["case"], item["variantId"], item["runId"]
    identity = {
        "caseId": case["caseId"],
        "caseRevision": case["caseRevision"],
        "variantId": variant,
        "environment": "E3",
        "runId": run_id,
    }

    def blocked(reason, status="BLOCKED_DEPENDENCY"):
        return {
            "observation": identity | {"status": status, "blockedReason": reason},
            "artifacts": {},
        }

    env_file = Path(os.environ.get("G1_E3_ENV_FILE", str(LOCAL_ENV)))
    env = await asyncio.to_thread(dotenv_values, env_file)
    if not env.get("LLM_API_KEY") or not env.get("LLM_MODEL"):
        return blocked("real_llm_configuration_missing")
    catalog_base = os.getenv("G1_E3_CATALOG_URL")
    if not catalog_base:
        return blocked("local_catalog_http_not_configured")
    commit = (
        await asyncio.to_thread(
            subprocess.check_output,
            ["git", "-C", str(CHATBOT_ROOT), "rev-parse", "HEAD"],
            text=True,
        )
    ).strip()
    dirty = bool(
        await asyncio.to_thread(
            subprocess.check_output,
            ["git", "-C", str(CHATBOT_ROOT), "status", "--porcelain"],
            text=True,
        )
    )
    preflight = None
    if case["data"].get("catalogFixtureRef"):
        path = os.getenv("G1_E3_PREFLIGHT")
        if not path or not await asyncio.to_thread(Path(path).is_file):
            return blocked("catalog_fixture_preflight_missing")
        preflight = json.loads(await asyncio.to_thread(Path(path).read_text, encoding="utf-8"))
        if (
            preflight.get("verified") is not True
            or preflight.get("catalogFixtureRef") != case["data"]["catalogFixtureRef"]
        ):
            return blocked("catalog_fixture_preflight_not_verified", "BLOCKED_DATA")
    get_settings().g1_supervisor_enabled = True
    llm = RecordedLlm(
        env.get("LLM_BASE_URL") or "https://api.openai.com/v1",
        env["LLM_API_KEY"],
        env["LLM_MODEL"],
        45,
    )
    catalog = RecordedCatalog(catalog_base)
    service = ChatService(None, llm, catalog, sessions=None)
    app.dependency_overrides[get_chat_service] = lambda: service
    app.dependency_overrides[chat_principal] = lambda: ChatPrincipal(
        rate_limit_key="guest:g1-e3-local"
    )
    app.dependency_overrides[get_rate_limiter] = lambda: MemoryRateLimiter(100)
    inp = case["input"]
    variant_spec = next(
        (v for v in inp.get("requiredVariants", []) if v["variantId"] == variant), {}
    )
    screen = inp.get("screenContext")
    if screen:
        screen = dict(screen)
        fixture = preflight.get("fixtureValues", {}) if preflight else {}
        for field, value in screen.items():
            if isinstance(value, str) and value.startswith("${FIXTURE."):
                key = value.removeprefix("${FIXTURE.").removesuffix("}")
                if key not in fixture:
                    return blocked("fixture_value_missing", "BLOCKED_DATA")
                screen[field] = fixture[key]
    body = {
        "message": inp["message"],
        "locale": inp["locale"],
        "requestType": variant_spec.get("requestType", inp["requestType"]),
        "screenContext": screen,
    }
    catalog_preflight = None
    if case["caseId"] == "G1-CAT-07":
        query = case["expected"].get("allowedArgs", {}).get("q")
        if not isinstance(query, str) or not query.strip() or query not in body["message"]:
            return blocked("empty_preflight_query_missing", "BLOCKED_DATA")
        try:
            async with httpx.AsyncClient(timeout=45) as preflight_client:
                catalog_preflight = await measure_empty_preflight(
                    preflight_client, catalog_base, query, run_id, preflight["fixtureRowSha256"]
                )
            if catalog_preflight["productIds"]:
                return blocked("empty_preflight_data_mismatch", "BLOCKED_DATA")
        except (httpx.HTTPError, KeyError, ValueError, TypeError):
            return blocked("empty_preflight_http_unavailable")
    capture = Capture()
    root = logging.getLogger()
    root.addHandler(capture)
    root.setLevel(logging.INFO)
    http_events = []
    original_send, recorded_send = catalog_http_observer(catalog_base, http_events)
    original_graph = chat_service.product_supervisor
    graph_capture = GraphCapture()
    chat_service.product_supervisor = ObservedGraph(original_graph, graph_capture)
    started_at = datetime.now(UTC).isoformat()
    httpx.AsyncClient.send = recorded_send
    try:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://g1-local"
        ) as client:
            response = await client.post("/api/chat", json=body, headers={"X-Request-ID": run_id})
    except (httpx.HTTPError, OSError, TimeoutError):
        return blocked("chat_transport_unavailable")
    finally:
        httpx.AsyncClient.send = original_send
        chat_service.product_supervisor = original_graph
        root.removeHandler(capture)
    payload = response.json()
    model_event = next(
        (e for e in reversed(capture.events) if e["event"] == "g1_model_completion"), None
    )
    nodes = graph_capture.nodes
    domains = ["catalogHttp", "modelCalls"]
    if nodes:
        domains.append("graphNodes")
    tools = []
    if model_event and model_event.get("tool_call_id"):
        call_id = model_event["tool_call_id"]
        matching_http = [event for event in http_events if event.get("callId") == call_id]
        if matching_http:
            tool_event = next(
                (
                    event
                    for event in capture.events
                    if event["event"] == "g1_catalog_tool_result"
                    and event.get("tool_call_id") == call_id
                ),
                None,
            )
            tools.append(
                {
                    "callId": call_id,
                    "name": matching_http[0]["name"],
                    "status": "success" if tool_event else "error",
                }
            )
            domains.append("tools")
    trace = {
        "complete": False,
        "completeDomains": domains,
        "requestId": run_id,
        "rawEvents": capture.events,
        "graphNodes": nodes,
        "catalogHttp": http_events,
        "modelCalls": llm.calls,
        "tools": tools,
    }
    observation = identity | {
        "isMock": False,
        "isSynthetic": False,
        "gitCommit": commit,
        "workingTreeDirty": dirty,
        "executionStartedAtUtc": started_at,
        "requestId": run_id,
        "request": {"method": "POST", "path": "/api/chat", "body": body},
        "httpStatus": response.status_code,
        "response": payload,
        "executionPath": (
            "chatbot ASGI route; auth and local limiter overridden; Redis sessions disabled"
        ),
        "trace": trace,
    }
    if graph_capture.route_intent is not None:
        observation["routeIntent"] = graph_capture.route_intent
    if catalog_preflight is not None:
        observation["catalogPreflight"] = catalog_preflight
    if preflight:
        observation.update(
            {
                "catalogFixtureRef": preflight["catalogFixtureRef"],
                "fixtureRowSha256": preflight["fixtureRowSha256"],
                "sourceSnapshotId": preflight["catalogFixtureRef"],
                "sourceSnapshotScope": "fingerprint of selected fixture rows, not full database",
                "fixtureObservedAtUtc": preflight.get("observedAtUtc"),
            }
        )
    source_products = []
    for result in catalog.results:
        source_products.extend(result.get("products", []))
        if result.get("product"):
            source_products.append(result["product"])
    if catalog.results:
        observation["sourceProductIds"] = [p["id"] for p in source_products]
    source_shade_pairs = detail_source_shade_pairs(catalog.results)
    if source_shade_pairs is not None:
        observation["sourceShadePairs"] = source_shade_pairs
    tool_result = next(
        (e for e in reversed(capture.events) if e["event"] == "g1_catalog_tool_result"), None
    )
    if tool_result and isinstance(tool_result.get("product_ids"), list):
        observation["catalogResultCount"] = len(tool_result["product_ids"])
    expected = case["expected"].get("allowedArgs", {})
    if expected.get("category"):
        observation["expectedCategory"] = expected["category"]
    if expected.get("q"):
        observation["expectedBrand"] = expected["q"]
    if screen and screen.get("productId"):
        observation["screenProductId"] = screen["productId"]
    if model_event:
        mid = model_event["model_id"]
        observation.update(
            {
                "llmModelId": mid,
                "llmModelVersion": mid,
                "modelVersionEvidence": "provider response model field; may be a mutable alias",
                "model": {
                    "isMock": False,
                    "modelId": mid,
                    "modelVersion": mid,
                    "responseId": model_event["model_response_id"],
                    "promptVersion": model_event["prompt_version"],
                    "requestId": run_id,
                },
            }
        )
    if response.status_code >= 400:
        observation.update(
            {"status": "FAIL", "failureReason": "chat_endpoint_http_" + str(response.status_code)}
        )
    common = {
        "runId": run_id,
        "gitCommit": commit,
        "request": body,
        "executionStartedAtUtc": started_at,
        "driverSha256": hashlib.sha256(
            await asyncio.to_thread(Path(__file__).read_bytes)
        ).hexdigest(),
    }
    artifacts = {
        "nonmock_llm_span": common | {"calls": llm.calls, "events": capture.events},
        "model_and_prompt_version": common
        | {
            "configuredModel": env["LLM_MODEL"],
            "actualModel": model_event.get("model_id") if model_event else None,
            "promptVersion": PROMPT_VERSION,
        },
        "tool_trace_or_no_tool_trace": common
        | {
            "events": capture.events,
            "catalogHttp": http_events,
            "graphNodes": nodes,
            "routeIntent": graph_capture.route_intent,
            "catalogPreflight": catalog_preflight,
            "catalogResults": catalog.results,
        },
        "response_snapshot": common | {"response": payload, "httpStatus": response.status_code},
    }
    return {"observation": observation, "artifacts": artifacts}


if __name__ == "__main__":
    try:
        sys.stdin.reconfigure(encoding="utf-8")
        with contextlib.redirect_stdout(sys.stderr):
            data = asyncio.run(run(json.load(sys.stdin)))
    except Exception as exc:
        print("driver failed: " + type(exc).__name__, file=sys.stderr)
        sys.exit(1)
    print(json.dumps(data, ensure_ascii=True))

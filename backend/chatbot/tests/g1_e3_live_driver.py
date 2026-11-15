"""Collect a real G1 model turn through the chatbot ASGI route.

The caller supplies an independently verified E1 fixture preflight JSON via
G1_E3_PREFLIGHT and the local Catalog HTTP base via G1_E3_CATALOG_URL. This
driver does not perform authentication, Redis-session, or UI verification.
"""
# This executable is launched by path from the collector, outside package mode.
# ruff: noqa: E402

import asyncio
import contextlib
import json
import logging
import os
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
LOCAL_ENV = Path(__file__).resolve().parents[3] / ".env.local"

import httpx
from dotenv import dotenv_values

from app.clients.catalog_client import CatalogClient
from app.clients.llm_client import LlmClient
from app.core.auth import ChatPrincipal, chat_principal
from app.core.config import get_settings
from app.core.ratelimit import MemoryRateLimiter, get_rate_limiter
from app.main import app
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

    env = await asyncio.to_thread(dotenv_values, LOCAL_ENV)
    if not env.get("LLM_API_KEY") or not env.get("LLM_MODEL"):
        return blocked("real_llm_configuration_missing")
    catalog_base = os.getenv("G1_E3_CATALOG_URL")
    if not catalog_base:
        return blocked("local_catalog_http_not_configured")
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
    capture = Capture()
    root = logging.getLogger()
    root.addHandler(capture)
    root.setLevel(logging.INFO)
    try:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://g1-local"
        ) as client:
            response = await client.post("/api/chat", json=body, headers={"X-Request-ID": run_id})
    except (httpx.HTTPError, OSError, TimeoutError):
        return blocked("chat_transport_unavailable")
    finally:
        root.removeHandler(capture)
    payload = response.json()
    commit = (
        await asyncio.to_thread(subprocess.check_output, ["git", "rev-parse", "HEAD"], text=True)
    ).strip()
    model_event = next(
        (e for e in reversed(capture.events) if e["event"] == "g1_model_completion"), None
    )
    observation = identity | {
        "isMock": False,
        "isSynthetic": False,
        "gitCommit": commit,
        "requestId": run_id,
        "request": {"method": "POST", "path": "/api/chat", "body": body},
        "httpStatus": response.status_code,
        "response": payload,
        "executionPath": (
            "chatbot ASGI route; auth and local limiter overridden; Redis sessions disabled"
        ),
        "trace": {"complete": False, "requestId": run_id, "rawEvents": capture.events},
    }
    if preflight:
        observation.update(
            {
                "catalogFixtureRef": preflight["catalogFixtureRef"],
                "fixtureRowSha256": preflight["fixtureRowSha256"],
                "sourceSnapshotId": preflight["catalogFixtureRef"],
            }
        )
    if model_event:
        mid = model_event["model_id"]
        observation.update(
            {
                "llmModelId": mid,
                "llmModelVersion": mid,
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
    common = {"runId": run_id, "gitCommit": commit, "request": body}
    artifacts = {
        "nonmock_llm_span": common | {"calls": llm.calls, "events": capture.events},
        "model_and_prompt_version": common
        | {
            "configuredModel": env["LLM_MODEL"],
            "actualModel": model_event.get("model_id") if model_event else None,
            "promptVersion": PROMPT_VERSION,
        },
        "tool_trace_or_no_tool_trace": common
        | {"events": capture.events, "catalogResults": catalog.results},
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

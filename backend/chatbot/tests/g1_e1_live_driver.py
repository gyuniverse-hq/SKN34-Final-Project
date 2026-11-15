"""Collect supported E1 cases against real Catalog HTTP and read-only PostgreSQL.

The model plan and auth are explicitly fixtures. Unsupported cases are NOT_RUN, not copied
from a smoke run. PostgreSQL is read only by the independent evaluation helper process.
"""

import asyncio
import hashlib
import json
import os
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

import httpx
from pydantic import ValidationError

ROOT = Path(__file__).resolve().parents[3]
CHATBOT = ROOT / "backend/chatbot"
sys.path.insert(0, str(CHATBOT))

from app.clients.catalog_client import CatalogClient  # noqa: E402
from app.core.auth import ChatPrincipal, chat_principal  # noqa: E402
from app.core.config import get_settings  # noqa: E402
from app.core.ratelimit import MemoryRateLimiter, get_rate_limiter  # noqa: E402
from app.main import create_app  # noqa: E402
from app.schemas.chat import ChatResponse  # noqa: E402
from app.services.chat_service import ChatService, get_chat_service  # noqa: E402

SUPPORTED = {
    "G1-CAT-01",
    "G1-CAT-03",
    "G1-CAT-07",
    "G1-CAT-08",
    "G1-CAT-09",
    "G1-CAT-11",
    "G1-CAT-12",
    "G1-CAT-14",
    "G1-RUN-01",
    "G1-UI-01",
}


class FixtureModel:
    configured = True

    def __init__(self, case):
        args = case["expected"].get("allowedArgs", {})
        self.detail = case.get("caseId") in {"G1-CAT-11", "G1-CAT-12"}
        self.arguments = {}
        if args.get("category"):
            self.arguments["category"] = args["category"]
        if args.get("q"):
            self.arguments["query"] = args["q"]
        if self.detail:
            self.arguments = {"intent": "detail"}
        elif not self.arguments:
            self.arguments["category"] = "lip"
        self.calls = 0

    async def complete_with_tools(self, messages, tools, **kwargs):
        self.calls += 1
        return {
            "id": "e1-fixture-completion",
            "model": "e1-fixture-model",
            "choices": [
                {
                    "finish_reason": "tool_calls",
                    "message": {
                        "tool_calls": [
                            {
                                "id": "e1-fixture-call",
                                "type": "function",
                                "function": {
                                    "name": (
                                        "catalog_get_product_detail"
                                        if self.detail
                                        else "catalog_search_products"
                                    ),
                                    "arguments": json.dumps(self.arguments, ensure_ascii=False),
                                },
                            }
                        ]
                    },
                }
            ],
        }, 0

    async def complete(self, messages):
        return "틴트와 립스틱은 제품에 따라 발색과 지속감이 다를 수 있어요."


def pg_read(ids):
    default_python = (
        ROOT / "backend/api/.venv" / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    )
    python = Path(os.environ.get("G1_E1_API_PYTHON", default_python))
    if not python.is_file():
        return {"status": "BLOCKED_DEPENDENCY", "reason": "api_python_missing"}
    result = subprocess.run(
        [str(python), "-B", str(CHATBOT / "tests/g1_e1_postgres.py")],
        input=json.dumps({"productIds": ids}, ensure_ascii=False),
        encoding="utf-8",
        text=True,
        capture_output=True,
        timeout=60,
        check=False,
    )
    if result.returncode:
        return {"status": "BLOCKED_DEPENDENCY", "reason": "postgres_helper_failed"}
    return json.loads(result.stdout)


def product_identity_matches(response_products, db_products):
    source = {p["id"]: p for p in db_products}
    return all(
        p["id"] in source
        and p["brand"] == source[p["id"]]["brand"]
        and p["category"] == source[p["id"]]["category"]
        for p in response_products
    )


def catalog_rows_match_db(ids, catalog_products, db_products, db_shades):
    """Check only returned product IDs, including every shade visible in their API rows."""
    source = {row["id"]: row for row in db_products}
    api = {row["id"]: row for row in catalog_products}
    if len(api) != len(catalog_products):
        return False
    fields = {
        "brand": "brand",
        "name": "name",
        "nameKo": "name_ko",
        "category": "category",
        "priceKRW": "price_krw",
    }
    for pid in ids:
        if pid not in source or pid not in api:
            return False
        row = api[pid]
        if any(k not in row or row[k] != source[pid][v] for k, v in fields.items()):
            return False
        if not isinstance(row.get("shades"), list):
            return False
        catalog_shades = [(s["id"], s["name"], s["hex"]) for s in row["shades"]]
        database_shades = [
            (s["id"], s["name"], s["hex"]) for s in db_shades if s["product_id"] == pid
        ]
        if len(catalog_shades) != len(set(catalog_shades)) or set(catalog_shades) != set(
            database_shades
        ):
            return False
    return True


def detail_ownership_matches(fixture, db):
    """Verify the two pinned products and their distinct shade ownership in PostgreSQL."""
    target, foreign = fixture["productId"], fixture["foreignProductId"]
    target_shade, foreign_shade = fixture["shadeId"], fixture["foreignShadeId"]
    pairs = [(row["product_id"], row["id"]) for row in db["shades"]]
    product_ids = [row["id"] for row in db["products"]]
    return (
        target != foreign
        and target_shade != foreign_shade
        and product_ids.count(target) == 1
        and product_ids.count(foreign) == 1
        and pairs.count((target, target_shade)) == 1
        and pairs.count((foreign, foreign_shade)) == 1
        and (target, foreign_shade) not in pairs
    )


def response_shade_pairs(payload):
    """Measure shade-bearing structured response fields rather than inferring from products."""
    context = payload.get("chatContext") or {}
    pairs = [
        {"productId": product_id, "shadeId": shade_id}
        for product_id, shade_id in context.get("shadeSelections", {}).items()
    ]
    for item in payload.get("ingredientResults") or []:
        if item.get("shadeId"):
            pairs.append({"productId": item["productId"], "shadeId": item["shadeId"]})
    return pairs


def detail_response_failure(case_id, payload, fixture):
    """Record unsafe detail results as FAIL; never repair the observed response."""
    try:
        response = ChatResponse.model_validate(payload)
    except (TypeError, ValidationError, ValueError):
        return "invalid_chat_response"
    if not response.answer.strip():
        return "empty_chat_response"
    context = payload.get("chatContext") or {}
    if case_id == "G1-CAT-11" and (payload.get("resultType") != "empty" or payload.get("products")):
        return "nonexistent_product_exposed"
    if case_id == "G1-CAT-12" and (
        payload.get("resultType") != "clarification"
        or payload.get("products")
        or payload.get("evidence")
        or payload.get("ingredientResults")
        or payload.get("ingredientComparison")
        or payload.get("arResult")
        or context.get("candidateIds")
        or context.get("scopeIds")
        or context.get("selectedProductId")
        or context.get("shadeSelections")
        or fixture["foreignShadeName"] in response.answer
    ):
        return "foreign_shade_exposed_or_not_clarified"
    return None


async def run(item):
    case, variant, run_id = item["case"], item["variantId"], item["runId"]
    identity = {
        "caseId": case["caseId"],
        "caseRevision": case["caseRevision"],
        "variantId": variant,
        "environment": "E1",
        "runId": run_id,
    }

    def blocked(reason, status="BLOCKED_DEPENDENCY"):
        return {
            "observation": identity | {"status": status, "blockedReason": reason},
            "artifacts": {},
        }

    if case["caseId"] not in SUPPORTED:
        return blocked("case_observation_not_implemented", "NOT_RUN")
    base = os.getenv("G1_E1_CATALOG_URL")
    if not base:
        return blocked("catalog_http_not_configured")
    binding = json.loads(
        (ROOT / "docs/ai-alignment/04_llm_stage4_evaluation/g1_manifest_PROPOSED.json").read_text(
            encoding="utf-8"
        )
    )["catalogFixtureBinding"]
    fv = binding["fixtureRowValue"]
    timeout = httpx.Timeout(30)
    async with httpx.AsyncClient(base_url=base, timeout=timeout, trust_env=False) as client:
        target = await client.get("/api/products/" + fv["productId"])
        foreign = await client.get("/api/products/" + fv["foreignProductId"])
        empty = await client.get("/api/products", params={"q": "G1평가전용_없는립_20261115"})
        missing = await client.get("/api/products/g1-eval-nonexistent-20261115")
    t = target.json().get("product", {})
    f = foreign.json().get("product", {})
    checks = {
        "targetStatus": target.status_code == 200,
        "foreignStatus": foreign.status_code == 200,
        "productFields": all(
            t.get(k) == fv[v]
            for k, v in (
                ("id", "productId"),
                ("brand", "brand"),
                ("nameKo", "nameKo"),
                ("category", "category"),
                ("priceKRW", "priceKRW"),
            )
        ),
        "targetShade": any(
            s.get("id") == fv["shadeId"]
            and s.get("name") == fv["shadeName"]
            and s.get("hex") == fv["shadeHex"]
            for s in t.get("shades", [])
        ),
        "foreignShade": any(
            s.get("id") == fv["foreignShadeId"]
            and s.get("name") == fv["foreignShadeName"]
            and s.get("hex") == fv["foreignShadeHex"]
            for s in f.get("shades", [])
        ),
        "foreignAbsent": all(s.get("id") != fv["foreignShadeId"] for s in t.get("shades", [])),
        "empty": empty.status_code == 200 and empty.json().get("products") == [],
        "missing": missing.status_code == 404,
    }
    if not all(checks.values()):
        return blocked("catalog_http_fixture_mismatch", "BLOCKED_DATA")

    model = FixtureModel(case)
    get_settings().g1_supervisor_enabled = True
    app = create_app()
    app.dependency_overrides[get_chat_service] = lambda: ChatService(
        None, model, CatalogClient(base)
    )
    app.dependency_overrides[chat_principal] = lambda: ChatPrincipal(rate_limit_key="guest:g1-e1")
    app.dependency_overrides[get_rate_limiter] = lambda: MemoryRateLimiter(100)
    inputs = case["input"]
    entry = next((x for x in inputs.get("requiredVariants", []) if x["variantId"] == variant), {})
    body = {
        "message": inputs["message"],
        "locale": inputs["locale"],
        "requestType": entry.get("requestType", inputs["requestType"]),
    }
    if inputs.get("screenContext"):
        screen = dict(inputs["screenContext"])
        for key, value in screen.items():
            if isinstance(value, str) and value.startswith("${FIXTURE.") and value.endswith("}"):
                name = value.removeprefix("${FIXTURE.").removesuffix("}")
                if name not in fv:
                    return blocked("fixture_screen_value_missing", "BLOCKED_DATA")
                screen[key] = fv[name]
        body["screenContext"] = screen
    events = []
    original = httpx.AsyncClient.send
    origin = httpx.URL(base)

    async def send(client, request, *args, **kwargs):
        response = await original(client, request, *args, **kwargs)
        if (request.url.scheme, request.url.host, request.url.port) == (
            origin.scheme,
            origin.host,
            origin.port,
        ):
            is_detail = request.url.path.startswith("/api/products/")
            event = {
                "name": "catalog.get_product_detail" if is_detail else "catalog.search_products",
                "method": request.method,
                "path": "/api/products/{productId}" if is_detail else request.url.path,
                "actualPath": request.url.path,
                "status": response.status_code,
                "query": dict(request.url.params),
            }
            if is_detail:
                event["productId"] = request.url.path.removeprefix("/api/products/")
                if response.status_code == 200:
                    event["returnedProduct"] = response.json()["product"]
            if request.url.path == "/api/products" and response.status_code == 200:
                event["returnedProducts"] = response.json()["products"]
                event["returnedProductIds"] = [p["id"] for p in event["returnedProducts"]]
            events.append(event)
        return response

    httpx.AsyncClient.send = send
    started = datetime.now(UTC).isoformat()
    try:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://g1-test"
        ) as client:
            response = await client.post("/api/chat", json=body, headers={"X-Request-ID": run_id})
    finally:
        httpx.AsyncClient.send = original
    payload = response.json()
    ids = [p["id"] for p in payload.get("products", [])]
    screen_id = (body.get("screenContext") or {}).get("productId")
    db = await asyncio.to_thread(
        pg_read,
        list(
            dict.fromkeys(
                ids + [fv["productId"], fv["foreignProductId"]] + ([screen_id] if screen_id else [])
            )
        ),
    )
    if db.get("status") != "OK":
        return blocked(
            db.get("reason", "postgres_preflight_failed"), db.get("status", "BLOCKED_DEPENDENCY")
        )
    products = {p["id"]: p for p in db["products"]}
    is_detail = case["caseId"] in {"G1-CAT-11", "G1-CAT-12"}
    details = [event for event in events if event["name"] == "catalog.get_product_detail"]
    if is_detail and (len(details) != 1 or details[0].get("productId") != screen_id):
        return blocked("detail_request_not_observed", "NOT_RUN")
    if case["caseId"] == "G1-CAT-11" and screen_id in products:
        return blocked("nonexistent_fixture_id_exists_in_postgres", "BLOCKED_DATA")
    if case["caseId"] == "G1-CAT-12" and not detail_ownership_matches(fv, db):
        return blocked("shade_ownership_fixture_mismatch", "BLOCKED_DATA")
    search_events = [event for event in events if "returnedProducts" in event]
    catalog_rows = [row for event in search_events for row in event["returnedProducts"]]
    selected_rows = [row for row in catalog_rows if row["id"] in ids]
    verified = product_identity_matches(payload.get("products", []), db["products"])
    if is_detail:
        if details[0]["status"] == 200:
            selected_rows = [details[0]["returnedProduct"]]
            verified = verified and catalog_rows_match_db(
                [screen_id], selected_rows, db["products"], db["shades"]
            )
        elif details[0]["status"] == 404:
            # A hallucinated chat response is a feature failure, not DB drift.
            verified = screen_id not in products
        else:
            # A live HTTP error is a feature failure; preserve the actual trace for grading.
            verified = True
        if case["caseId"] == "G1-CAT-12":
            verified = verified and catalog_rows_match_db(
                [fv["productId"], fv["foreignProductId"]], [t, f], db["products"], db["shades"]
            )
    else:
        verified = verified and catalog_rows_match_db(
            ids, selected_rows, db["products"], db["shades"]
        )
    if not verified:
        return blocked("returned_catalog_data_disagrees_with_db", "BLOCKED_DATA")
    commit = (
        await asyncio.to_thread(
            subprocess.check_output, ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True
        )
    ).strip()
    dirty = bool(
        await asyncio.to_thread(
            subprocess.check_output, ["git", "status", "--porcelain"], cwd=ROOT, text=True
        )
    )
    observation = identity | {
        "isMock": False,
        "isSynthetic": False,
        "syntheticDependencies": ["model", "auth"],
        "requestId": run_id,
        "httpStatus": response.status_code,
        "response": payload,
        "catalogFixtureRef": db["catalogFixtureRef"],
        "fixtureRowSha256": db["fixtureRowSha256"],
        "sourceSnapshotId": db["catalogFixtureRef"],
        "sourceProductIds": list(products),
        "catalogPreflight": {"httpStatus": empty.status_code, "productIds": []},
        "trace": {
            "complete": False,
            "completeDomains": ["catalogHttp"],
            "requestId": run_id,
            "catalogHttp": events,
        },
    }
    search_events = [event for event in events if "returnedProductIds" in event]
    if len(search_events) == 1:
        observation["catalogResultCount"] = len(search_events[0]["returnedProductIds"])
    if is_detail:
        observation["screenProductId"] = screen_id
        observation["responseShadePairs"] = response_shade_pairs(payload)
        observation["sourceShadePairs"] = [
            {"productId": row["product_id"], "shadeId": row["id"]}
            for row in db["shades"]
            if row["product_id"] == screen_id
        ]
        if details[0]["status"] == 404:
            observation["catalogResultCount"] = 0
    args = case["expected"].get("allowedArgs", {})
    if args.get("category"):
        observation["expectedCategory"] = args["category"]
    if args.get("q") and case["caseId"] == "G1-CAT-03":
        observation["expectedBrand"] = args["q"]
    if response.status_code >= 400:
        observation.update(
            status="FAIL", failureReason=f"chat_endpoint_http_{response.status_code}"
        )
    if is_detail and details[0]["status"] not in {200, 404}:
        observation.update(status="FAIL", failureReason=f"catalog_http_{details[0]['status']}")
    if is_detail and response.status_code < 400:
        reason = detail_response_failure(case["caseId"], payload, fv)
        if reason:
            observation.update(status="FAIL", failureReason=reason)
    common = {
        "runId": run_id,
        "gitCommit": commit,
        "workingTreeDirty": dirty,
        "driverSha256": hashlib.sha256(
            await asyncio.to_thread(Path(__file__).read_bytes)
        ).hexdigest(),
        "startedAtUtc": started,
        "request": body,
        "model": "synthetic_fixture",
        "authentication": "synthetic_fixture",
    }
    return {
        "observation": observation,
        "artifacts": {
            "live_catalog_http_trace": common
            | {
                "events": events,
                "httpStatus": response.status_code,
                "response": payload,
                "fixtureModelCalls": model.calls,
            },
            "postgres_source_snapshot_id": common | {"source": db},
            "fixture_fingerprint_preflight": common
            | {"checks": checks, "rowSha256": db["fixtureRowSha256"]},
            "product_and_shade_id_revalidation": common
            | {
                "responseProductIds": ids,
                "dbProducts": db["products"],
                "dbShades": db["shades"],
                "matches": verified,
            },
        },
    }


if __name__ == "__main__":
    sys.stdin.reconfigure(encoding="utf-8")
    sys.stdout.reconfigure(encoding="utf-8")
    item = json.load(sys.stdin)
    try:
        print(json.dumps(asyncio.run(run(item)), ensure_ascii=False))
    except Exception as exc:
        identity = {
            "caseId": item["case"]["caseId"],
            "caseRevision": item["case"]["caseRevision"],
            "variantId": item["variantId"],
            "environment": "E1",
            "runId": item["runId"],
        }
        status = (
            "BLOCKED_DEPENDENCY"
            if isinstance(exc, (httpx.HTTPError, OSError, subprocess.SubprocessError, TimeoutError))
            else "NOT_RUN"
        )
        print(
            json.dumps(
                {
                    "observation": identity
                    | {"status": status, "blockedReason": type(exc).__name__},
                    "artifacts": {},
                }
            )
        )

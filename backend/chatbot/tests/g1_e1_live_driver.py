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
    "G1-CAT-02",
    "G1-CAT-03",
    "G1-CAT-04",
    "G1-CAT-05",
    "G1-CAT-06",
    "G1-CAT-07",
    "G1-CAT-08",
    "G1-CAT-09",
    "G1-CAT-10",
    "G1-CAT-11",
    "G1-CAT-12",
    "G1-CAT-13",
    "G1-CAT-14",
    "G1-RUN-01",
    "G1-REG-07",
    "G1-UI-01",
}


class FixtureModel:
    configured = True

    def __init__(self, case):
        args = case["expected"].get("allowedArgs", {})
        self.detail = case.get("caseId") in {
            "G1-CAT-04",
            "G1-CAT-06",
            "G1-CAT-11",
            "G1-CAT-12",
            "G1-CAT-13",
            "G1-ERR-04",
            "G1-ERR-05",
        }
        self.arguments = {}
        if args.get("category"):
            self.arguments["category"] = args["category"]
        if args.get("q"):
            self.arguments["query"] = args["q"]
        for source, target in (
            ("internalIntent.maxPriceKRW", "maxPriceKRW"),
            ("internalIntent.moisturizing", "moisturizing"),
            ("internalIntent.fragranceFree", "fragrance_free"),
        ):
            if source in args:
                self.arguments[target] = args[source]
        if self.detail:
            self.arguments = {"intent": "price" if case.get("caseId") == "G1-CAT-06" else "detail"}
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


def catalog_row_difference(before, after):
    """Report exact differing fields without serializing unrestricted upstream values."""
    fields = []
    for key in sorted(before.keys() | after.keys()):
        if (key in before) == (key in after) and before.get(key) == after.get(key):
            continue
        entry = {"field": key, "beforePresent": key in before, "afterPresent": key in after}
        for label, row in (("before", before), ("after", after)):
            value = json.dumps(row.get(key), sort_keys=True, ensure_ascii=False)
            entry[label + "Sha256"] = hashlib.sha256(value.encode()).hexdigest()
        fields.append(entry)
    return {"productId": before.get("id"), "fields": fields}


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


def detail_answer_shade_pairs(payload, product_id, source_shades):
    """Bind every explicitly listed shade name to an exact DB-owned shade, or withhold evidence."""
    answer = payload.get("answer")
    marker = "확인된 색상:"
    if not isinstance(answer, str) or marker not in answer:
        return None, None
    names = [name.strip() for name in answer.rsplit(marker, 1)[1].strip().split(",")]
    if not names or any(not name for name in names):
        return None, None
    by_name = {}
    for shade in source_shades:
        if shade["product_id"] == product_id:
            by_name.setdefault(shade["name"], []).append(shade["id"])
    unknown_names = {name for name in names if name not in by_name}
    if unknown_names:
        foreign_names = {
            shade["name"] for shade in source_shades if shade["product_id"] != product_id
        }
        return (None, "foreign_shade_name") if unknown_names & foreign_names else (None, None)
    if any(len(by_name[name]) != 1 for name in names):
        return None, None
    if len(names) != len(set(names)) or set(names) != set(by_name):
        return None, None
    return [{"productId": product_id, "shadeId": by_name[name][0]} for name in names], None


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


def observe_detail_shades(case_id, payload, product_id, source_shades, fixture):
    """Collect response fields and exact listed names; missing prose evidence stays missing."""
    observation = {}
    if case_id == "G1-CAT-04":
        pairs, failure = detail_answer_shade_pairs(payload, product_id, source_shades)
        if pairs is not None:
            observation["responseShadePairs"] = pairs
        if failure:
            observation.update(status="FAIL", failureReason=failure)
    elif case_id == "G1-CAT-12":
        failure = detail_response_failure(case_id, payload, fixture)
        observation["responseShadePairs"] = response_shade_pairs(payload)
        observation["shadeResponseAudit"] = {
            "scope": "structured response selection and evidence; foreign fixture name in answer",
            "resultType": payload.get("resultType"),
            "failureReason": failure,
        }
        if failure:
            observation.update(status="FAIL", failureReason=failure)
    return observation


async def observe_reg07(case, run_id, catalog, artifact_name):
    """Make independent guest, fixture-user and active foreign-session requests.

    Token verification and session storage are fixtures; chat_principal and ChatService are real.
    No independent develop baseline is claimed or fabricated.
    """
    from uuid import uuid4

    from app.core import auth
    from app.repositories.chat_session_repository import ChatSessionRepository
    from app.schemas.chat import ChatSessionRef
    from tests.drive_g1_e2 import safe
    from tests.test_chat_sessions import RedisDouble

    class FixtureVerifier:
        async def verify(self, token):
            if token == "g1-fixture-user":
                return {"sub": "g1-fixture-user", "role": "authenticated"}
            return None

    old_verifier = auth.get_verifier
    settings = get_settings()
    old_enabled = settings.g1_supervisor_enabled
    auth.get_verifier = lambda: FixtureVerifier()
    settings.g1_supervisor_enabled = True
    redis = RedisDouble()
    repo = ChatSessionRepository(redis)
    model = FixtureModel(case)
    service = ChatService(None, model, catalog, sessions=repo)
    app = create_app()
    app.dependency_overrides[get_chat_service] = lambda: service
    limiter = MemoryRateLimiter(100)
    app.dependency_overrides[get_rate_limiter] = lambda: limiter
    supervisor_calls, interpret_calls, catalog_calls, model_calls = [], [], [], []
    original_supervisor, original_interpret = service._run_supervisor, service._interpret_beauty

    async def supervisor(*args, **kwargs):
        supervisor_calls.append("_run_supervisor")
        return await original_supervisor(*args, **kwargs)

    async def interpret(*args, **kwargs):
        interpret_calls.append("_interpret_beauty")
        return await original_interpret(*args, **kwargs)

    service._run_supervisor, service._interpret_beauty = supervisor, interpret
    for name in ("search_products", "get_product", "get_ingredients"):
        if not hasattr(catalog, name):
            continue
        original = getattr(catalog, name)

        async def recorded(*args, _name=name, _original=original, **kwargs):
            catalog_calls.append(_name)
            return await _original(*args, **kwargs)

        setattr(catalog, name, recorded)
    for name in ("complete", "complete_with_tools"):
        original = getattr(model, name)

        async def recorded_model(*args, _name=name, _original=original, **kwargs):
            model_calls.append(_name)
            return await _original(*args, **kwargs)

        setattr(model, name, recorded_model)
    body = {
        "message": case["input"]["message"],
        "locale": case["input"]["locale"],
        "requestType": case["input"]["requestType"],
    }
    owner_a = "g1-owner-a-" + run_id
    owner_b = "g1-owner-b-" + run_id
    foreign_request_id = uuid4().hex
    evidence_ref = f"{run_id}/{artifact_name}.json"
    try:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://g1-reg07"
        ) as client:
            authorized = await client.post(
                "/api/chat",
                json=body,
                headers={"X-Request-ID": run_id, "X-Vishue-Anonymous-Id": owner_a},
            )
            user_id = uuid4().hex
            user = await client.post(
                "/api/chat",
                json=body,
                headers={"X-Request-ID": user_id, "Authorization": "Bearer g1-fixture-user"},
            )
            bootstrap_id = str(uuid4())
            bootstrap_request_id = uuid4().hex
            bootstrap_body = {
                "message": "립 제품 추천해줘",
                "locale": "ko",
                "requestType": "beauty_consultation",
                "requestId": bootstrap_id,
            }
            bootstrap = await client.post(
                "/api/chat",
                json=bootstrap_body,
                headers={"X-Request-ID": bootstrap_request_id, "X-Vishue-Anonymous-Id": owner_a},
            )
            authorized_data = safe(authorized.json())
            request = {"method": "POST", "path": "/api/chat", "body": body}
            auth_observation = {
                "results": [
                    {"principal": "guest", "status": authorized.status_code},
                    {"principal": "fixture-user", "status": user.status_code},
                ]
            }
            authorized_part = {
                "runId": run_id,
                "requestId": run_id,
                "request": request,
                "httpStatus": authorized.status_code,
                "response": authorized_data,
                "evidenceRef": evidence_ref,
            }
            observations = {"authorized": authorized_part, "authEvidenceRef": evidence_ref}
            steps = [
                {"stage": "guest", "status": authorized.status_code},
                {
                    "stage": "fixture_user",
                    "status": user.status_code,
                    "requestId": user_id,
                    "request": request,
                    "response": safe(user.json()),
                },
                {
                    "stage": "session_bootstrap",
                    "status": bootstrap.status_code,
                    "requestId": bootstrap_request_id,
                    "request": {"method": "POST", "path": "/api/chat", "body": bootstrap_body},
                    "response": safe(bootstrap.json()),
                },
            ]
            if bootstrap.status_code == 200 and bootstrap.json().get("chatContext", {}).get(
                "session"
            ):
                context = bootstrap.json()["chatContext"]
                ref = ChatSessionRef.model_validate(context["session"])
                owner_key = "guest:" + hashlib.sha256(owner_a.encode("ascii")).hexdigest()
                try:
                    state = await repo.load(owner_key, ref)
                    active = (
                        state.state_version == ref.state_version
                        and state.result_set_id == ref.result_set_id
                    )
                except Exception:
                    active = False
                if active:
                    foreign_body = {
                        "message": "두 번째 제품 보여줘",
                        "locale": "ko",
                        "requestType": "beauty_consultation",
                        "requestId": str(uuid4()),
                        "chatContext": context,
                    }
                    before = (
                        len(supervisor_calls),
                        len(interpret_calls),
                        len(catalog_calls),
                        len(model_calls),
                    )
                    foreign = await client.post(
                        "/api/chat",
                        json=foreign_body,
                        headers={
                            "X-Request-ID": foreign_request_id,
                            "X-Vishue-Anonymous-Id": owner_b,
                        },
                    )
                    after = (
                        len(supervisor_calls),
                        len(interpret_calls),
                        len(catalog_calls),
                        len(model_calls),
                    )
                    foreign_data = safe(foreign.json())
                    foreign_part = {
                        "runId": run_id,
                        "requestId": foreign_request_id,
                        "request": {
                            "method": "POST",
                            "path": "/api/chat",
                            "body": safe(foreign_body),
                        },
                        "httpStatus": foreign.status_code,
                        "response": foreign_data,
                        "session": {"fixtureActive": True},
                        "evidenceRef": evidence_ref,
                        "responseEvidenceRef": evidence_ref,
                        "trace": {
                            "complete": False,
                            "completeDomains": ["tools"] if before == after else [],
                            "requestId": foreign_request_id,
                            "tools": [] if before == after else [{"name": "observed_call"}],
                        },
                    }
                    if foreign_data == {
                        "error": "Chat session access denied",
                        "code": "chat_session_forbidden",
                    }:
                        foreign_part["claimAudit"] = {
                            "complete": True,
                            "responseEvidenceRef": evidence_ref,
                            "claims": [],
                        }
                    observations["foreignSession"] = foreign_part
                    steps.append(
                        {
                            "stage": "foreign_session",
                            "status": foreign.status_code,
                            "boundaryCountsBefore": before,
                            "boundaryCountsAfter": after,
                        }
                    )
            return {
                "request": request,
                "requestId": run_id,
                "httpStatus": authorized.status_code,
                "response": authorized_data,
                "securityObservations": observations,
                "auth": auth_observation,
                "steps": steps,
                "modelCalls": len(model_calls),
                "fixtureIdentity": {
                    "auth": "real chat_principal; token verifier fixture",
                    "sessionStore": "RedisDouble fixture",
                    "llm": "fixture",
                },
            }
    finally:
        auth.get_verifier = old_verifier
        settings.g1_supervisor_enabled = old_enabled


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
        result = blocked("catalog_http_fixture_mismatch", "BLOCKED_DATA")
        result["observation"]["dataDiagnostics"] = {
            "checks": checks,
            "httpStatuses": {
                "target": target.status_code,
                "foreign": foreign.status_code,
                "empty": empty.status_code,
                "missing": missing.status_code,
            },
            "observedAt": datetime.now(UTC).isoformat(),
            "targetId": fv["productId"],
            "foreignId": fv["foreignProductId"],
        }
        return result

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
                "observedAt": datetime.now(UTC).isoformat(),
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
    security_result = None
    try:
        if case["caseId"] == "G1-REG-07":
            security_result = await observe_reg07(
                case, run_id, CatalogClient(base), "live_catalog_http_trace"
            )
            payload = security_result["response"]
            http_status = security_result["httpStatus"]
            body = security_result["request"]["body"]
        else:
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app), base_url="http://g1-test"
            ) as client:
                response = await client.post(
                    "/api/chat", json=body, headers={"X-Request-ID": run_id}
                )
            payload = response.json()
            http_status = response.status_code
    finally:
        httpx.AsyncClient.send = original
    ids = [p["id"] for p in payload.get("products", [])]
    all_ids = list(ids)
    if security_result:
        for step in security_result["steps"]:
            all_ids.extend(p["id"] for p in step.get("response", {}).get("products", []))
    screen_id = (body.get("screenContext") or {}).get("productId")
    db = await asyncio.to_thread(
        pg_read,
        list(
            dict.fromkeys(
                all_ids
                + [fv["productId"], fv["foreignProductId"]]
                + ([screen_id] if screen_id else [])
            )
        ),
    )
    if db.get("status") != "OK":
        return blocked(
            db.get("reason", "postgres_preflight_failed"), db.get("status", "BLOCKED_DEPENDENCY")
        )
    products = {p["id"]: p for p in db["products"]}
    is_detail = model.detail
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
    if security_result:
        unique_rows = {}
        for row in catalog_rows:
            if row["id"] in all_ids:
                if row["id"] in unique_rows and unique_rows[row["id"]] != row:
                    result = blocked(
                        "returned_catalog_data_changed_between_requests", "BLOCKED_DATA"
                    )
                    result["observation"]["dataDiagnostics"] = {
                        "difference": catalog_row_difference(unique_rows[row["id"]], row),
                        "requests": [
                            {key: event[key] for key in ("observedAt", "method", "path", "status")}
                            | {
                                "returnedCount": len(event["returnedProducts"]),
                                "restrictedIds": "ids" in event["query"],
                            }
                            for event in search_events
                            if row["id"] in event["returnedProductIds"]
                        ],
                        "beforeMatchesDatabase": catalog_rows_match_db(
                            [row["id"]], [unique_rows[row["id"]]], db["products"], db["shades"]
                        ),
                        "afterMatchesDatabase": catalog_rows_match_db(
                            [row["id"]], [row], db["products"], db["shades"]
                        ),
                        "databaseObservedAt": datetime.now(UTC).isoformat(),
                    }
                    return result
                unique_rows[row["id"]] = row
        selected_rows = list(unique_rows.values())
        for step in security_result["steps"]:
            verified = verified and product_identity_matches(
                step.get("response", {}).get("products", []), db["products"]
            )
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
            all_ids if security_result else ids, selected_rows, db["products"], db["shades"]
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
        "httpStatus": http_status,
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
    if security_result:
        observation.update(
            request=security_result["request"],
            securityObservations=security_result["securityObservations"],
            auth=security_result["auth"],
            syntheticDependencies=["model", "auth_verifier", "session_store"],
        )
    search_events = [event for event in events if "returnedProductIds" in event]
    if len(search_events) == 1:
        observation["catalogResultCount"] = len(search_events[0]["returnedProductIds"])
    if is_detail:
        observation["screenProductId"] = screen_id
        shade_pairs = response_shade_pairs(payload)
        # CAT-04 describes multiple names in prose; validate each exact name against DB.
        # A screen selection alone cannot establish which names the answer described.
        if case["caseId"] == "G1-CAT-04":
            shade_pairs, shade_failure = detail_answer_shade_pairs(payload, screen_id, db["shades"])
            if shade_failure:
                observation.update(status="FAIL", failureReason=shade_failure)
        if shade_pairs is not None and (shade_pairs or case["caseId"] == "G1-CAT-12"):
            observation["responseShadePairs"] = shade_pairs
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
    if http_status >= 400:
        observation.update(status="FAIL", failureReason=f"chat_endpoint_http_{http_status}")
    if is_detail and details[0]["status"] not in {200, 404}:
        observation.update(status="FAIL", failureReason=f"catalog_http_{details[0]['status']}")
    if is_detail and http_status < 400:
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
                "httpStatus": http_status,
                "response": payload,
                "fixtureModelCalls": security_result["modelCalls"]
                if security_result
                else model.calls,
                **(
                    {
                        "securityObservations": security_result["securityObservations"],
                        "auth": security_result["auth"],
                        "steps": security_result["steps"],
                        "fixtureIdentity": security_result["fixtureIdentity"],
                    }
                    if security_result
                    else {}
                ),
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

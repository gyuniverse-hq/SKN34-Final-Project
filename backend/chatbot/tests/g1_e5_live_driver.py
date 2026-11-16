"""Collect correlated local Expo UI, chatbot, Catalog and database observations.

CDP captures are exploratory until the Expo and chatbot process sources are independently
attested against the checkout. Operator-supplied files are not proof of live origin.
"""

import base64
import hashlib
import json
import os
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
MAX_IMAGE_BYTES = 5_000_000


def _identity(item):
    return {
        "caseId": item["case"]["caseId"],
        "caseRevision": item["case"]["caseRevision"],
        "variantId": item["variantId"],
        "environment": "E5",
        "runId": item["runId"],
    }


def _screen_entry(case, fixture):
    """Use the existing product deep link; never inject application state."""
    from urllib.parse import urlencode

    screen = dict(case["input"].get("screenContext") or {})
    for key, value in screen.items():
        if isinstance(value, str) and value.startswith("${FIXTURE."):
            name = value.removeprefix("${FIXTURE.").removesuffix("}")
            if name not in fixture:
                raise ValueError("screen_fixture_missing")
            screen[key] = fixture[name]
    if not screen:
        return "/chat", None
    if not screen.get("productId"):
        raise ValueError("screen_product_missing")
    query = {key: screen[key] for key in ("productId", "shadeId") if screen.get(key)}
    return "/chat?" + urlencode(query), screen


def _matches_chat_origin(url, expected_origin):
    from urllib.parse import urlsplit

    actual = urlsplit(url)
    expected = urlsplit(expected_origin)
    return (
        actual.scheme == expected.scheme
        and actual.hostname == expected.hostname
        and actual.port == expected.port
        and actual.path == "/api/chat"
        and not actual.username
        and not actual.password
    )


def _not_run(item, reason):
    return {
        "observation": _identity(item) | {"status": "NOT_RUN", "blockedReason": reason},
        "artifacts": {},
    }


def _read_screen(directory, screen):
    path = (directory / screen["path"]).resolve(strict=True)
    path.relative_to(directory.resolve(strict=True))
    image = path.read_bytes()
    if not 0 < len(image) <= MAX_IMAGE_BYTES:
        raise ValueError("invalid_screen_size")
    if not (image.startswith(b"\x89PNG\r\n\x1a\n") or image.startswith(b"\xff\xd8\xff")):
        raise ValueError("invalid_screen_format")
    digest = hashlib.sha256(image).hexdigest()
    if digest != screen["sha256"]:
        raise ValueError("screen_hash_mismatch")
    return {"sha256": digest, "bytesBase64": base64.b64encode(image).decode("ascii")}


def _read_trace(directory, reference):
    path = (directory / reference["path"]).resolve(strict=True)
    path.relative_to(directory.resolve(strict=True))
    raw = path.read_bytes()
    if not 0 < len(raw) <= MAX_IMAGE_BYTES:
        raise ValueError("invalid_trace_size")
    if hashlib.sha256(raw).hexdigest() != reference["sha256"]:
        raise ValueError("trace_hash_mismatch")
    return json.loads(raw.decode("utf-8"))


def bind(item, capture, directory, commit):
    """Validate the operator's recorded evidence; never manufacture a missing trace."""
    identity = _identity(item)
    if any(capture.get(k) != v for k, v in identity.items()):
        raise ValueError("run_identity_mismatch")
    provenance = capture["provenance"]
    if (
        provenance["kind"] != "actual_expo_ui"
        or provenance["target"] != "expo_web"
        or provenance["commitSha"] != commit
        or not provenance["operator"]
    ):
        raise ValueError("ui_provenance_incomplete")
    captured_at = datetime.fromisoformat(provenance["capturedAt"].replace("Z", "+00:00"))
    if captured_at.tzinfo is None:
        raise ValueError("ui_capture_timezone_missing")
    client = capture["client"]
    request, response = client["request"], client["response"]
    body = request["body"]
    if request["method"] != "POST" or request["path"] != "/api/chat":
        raise ValueError("unexpected_ui_request")
    if body["message"] != item["case"]["input"]["message"]:
        raise ValueError("question_mismatch")
    variants = item["case"]["input"].get("requiredVariants", [])
    variant = next((v for v in variants if v["variantId"] == item["variantId"]), {})
    expected_type = variant.get("requestType", item["case"]["input"]["requestType"])
    if body.get("requestType", "chat") != expected_type:
        raise ValueError("request_type_mismatch")
    request_id = request["requestId"]
    server = capture["serverTrace"]
    if not request_id or server["requestId"] != request_id or not server["events"]:
        raise ValueError("server_trace_mismatch")
    recorded_client = _read_trace(directory, capture["clientTrace"])
    recorded_server = _read_trace(directory, capture["serverTraceFile"])
    if recorded_client != client or recorded_server != server:
        raise ValueError("trace_contents_mismatch")
    if not isinstance(response, dict) or not isinstance(client["httpStatus"], int):
        raise ValueError("invalid_response_capture")
    ui = capture["ui"]
    if not isinstance(ui["renderedElements"], str) or not ui["renderedElements"].strip():
        raise ValueError("ui_elements_missing")
    screen = _read_screen(directory, capture["screen"])
    observation = identity | {
        "isMock": False,
        "isSynthetic": False,
        "gitCommit": commit,
        "requestId": request_id,
        "request": request,
        "response": response,
        "httpStatus": client["httpStatus"],
        "ui": ui,
        "catalogFixtureRef": capture["fixture"]["catalogFixtureRef"],
        "fixtureRowSha256": capture["fixture"]["fixtureRowSha256"],
        "trace": server,
    }
    # Only include facts actually captured by the operator; missing facts stay NOT_RUN.
    for key in (
        "sourceProductIds",
        "sourceShadePairs",
        "sourceSnapshotId",
        "claimAudit",
        "expectedUnknownConditions",
        "routeIntent",
        "expectedCategory",
    ):
        if key in capture:
            observation[key] = capture[key]
    # Separate files and hashes establish integrity, not their capture origin. Until an
    # authenticated browser/network capture adapter is available, do not certify a
    # user-supplied bundle as an actual UI run (even when the contents appear valid).
    observation.update(status="NOT_RUN", blockedReason="ui_capture_origin_not_verified")
    common = identity | {"requestId": request_id, "provenance": provenance}
    return {
        "observation": observation,
        "artifacts": {
            "app_request_and_response_trace": common
            | {
                "request": request,
                "response": response,
                "httpStatus": client["httpStatus"],
                "serverTrace": server,
                "clientTraceSha256": capture["clientTrace"]["sha256"],
                "serverTraceSha256": capture["serverTraceFile"]["sha256"],
            },
            "UI_rendered_elements_or_screen_recording": common
            | {
                "renderedElements": ui["renderedElements"],
                "screen": screen,
            },
            "card_and_navigation_ids_if_present": common | {"ui": ui},
        },
    }


def _local_http_url(value):
    from urllib.parse import urlparse

    parsed = urlparse(value)
    if (
        parsed.scheme != "http"
        or parsed.hostname not in {"localhost", "127.0.0.1"}
        or parsed.username
        or parsed.password
        or parsed.query
        or parsed.fragment
    ):
        raise ValueError("local_http_endpoint_required")
    return value.rstrip("/")


def _read_shared_log(path, offset):
    """Read an append-only log even while a Windows writer holds it open for writing."""
    if os.name != "nt":
        with path.open("rb") as source:
            source.seek(offset)
            return source.read()
    import ctypes
    import msvcrt
    from ctypes import wintypes

    api = ctypes.WinDLL("kernel32", use_last_error=True)
    create = api.CreateFileW
    create.argtypes = [
        wintypes.LPCWSTR,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.LPVOID,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.HANDLE,
    ]
    create.restype = wintypes.HANDLE
    handle = create(str(path), 0x80000000, 0x00000001 | 0x00000002, None, 3, 0, None)
    if handle == wintypes.HANDLE(-1).value:
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        descriptor = msvcrt.open_osfhandle(handle, os.O_RDONLY | os.O_BINARY)
    except OSError:
        api.CloseHandle(handle)
        raise
    with os.fdopen(descriptor, "rb") as source:
        source.seek(offset)
        return source.read()


def _pg_search_count(query):
    """Query the isolated evaluator's API Python, with a read-only PostgreSQL transaction."""
    default = (
        ROOT / "backend/api/.venv" / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    )
    python = Path(os.environ.get("G1_E1_API_PYTHON", default))
    if not python.is_file():
        return {"status": "BLOCKED_DEPENDENCY", "reason": "api_python_missing"}
    program = r"""
import asyncio,json,os,sys
from pathlib import Path
from dotenv import dotenv_values
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine
async def run():
    args=json.load(sys.stdin)
    env=dotenv_values(Path(args["envPath"]))
    engine=create_async_engine(env["DATABASE_URL"],connect_args={"timeout":15})
    try:
        async with engine.connect() as conn:
            await conn.execute(text("SET TRANSACTION READ ONLY"))
            query=text("SELECT count(*) FROM public.products "
                       "WHERE position(:term in search_text) > 0")
            count=(await conn.execute(query,{"term":args["query"].lower()})).scalar_one()
            return {"status":"OK","count":count,"transactionReadOnly":True}
    finally:
        await engine.dispose()
try:
    print(json.dumps(asyncio.run(run())))
except Exception as exc:
    print(json.dumps({"status":"BLOCKED_DEPENDENCY","reason":type(exc).__name__}))
"""
    result = subprocess.run(
        [str(python), "-B", "-c", program],
        input=json.dumps(
            {"query": query, "envPath": os.environ.get("G1_E1_ENV_PATH", str(ROOT / ".env.local"))}
        ),
        text=True,
        encoding="utf-8",
        capture_output=True,
        timeout=40,
        check=False,
    )
    if result.returncode:
        return {"status": "BLOCKED_DEPENDENCY", "reason": "postgres_search_helper_failed"}
    return json.loads(result.stdout)


def _matching_server_events(lines, request_id):
    """Extract only trace fields that are needed; never expose auth headers or logs wholesale."""
    fields = (
        "ts",
        "msg",
        "request_id",
        "method",
        "path",
        "status",
        "model_id",
        "model_response_id",
        "prompt_version",
        "request_type",
        "tool_call_id",
        "tool_name",
        "product_ids",
        "result_type",
        "node",
        "graph_run_id",
        "route_intent",
        "query",
        "category",
        "result_count",
        "response_sha256",
    )
    result = []
    for line in lines:
        try:
            event = json.loads(line)
        except (ValueError, TypeError):
            continue
        if isinstance(event, dict) and event.get("request_id") == request_id:
            result.append({name: event[name] for name in fields if name in event})
    return result


def _verified_catalog_trace(events):
    nodes = {e.get("node") for e in events if e.get("msg") == "g1_graph_node_end"}
    if not {"plan_turn", "execute_turn"} <= nodes:
        return False
    models = [e for e in events if e.get("msg") == "g1_model_completion"]
    requests = [e for e in events if e.get("msg") == "catalog_http"]
    tools = [e for e in events if e.get("msg") == "g1_catalog_tool_result"]
    return any(
        model.get("model_id")
        and model.get("model_response_id")
        and model.get("prompt_version")
        and model.get("tool_call_id")
        and request.get("status") == 200
        and request.get("path") == "/api/products"
        and request.get("tool_call_id") == model.get("tool_call_id")
        and tool.get("tool_call_id") == model.get("tool_call_id")
        for model in models
        for request in requests
        for tool in tools
    )


def _verified_tool_products(events, ids):
    models = {e.get("tool_call_id") for e in events if e.get("msg") == "g1_model_completion"}
    requests = {
        e.get("tool_call_id")
        for e in events
        if e.get("msg") == "catalog_http"
        and e.get("path") == "/api/products"
        and e.get("status") == 200
    }
    return any(
        e.get("msg") == "g1_catalog_tool_result"
        and e.get("tool_call_id")
        and e["tool_call_id"] in models & requests
        and isinstance(e.get("product_ids"), list)
        and set(ids).issubset(e["product_ids"])
        for e in events
    )


def _verified_empty_search(events, query):
    """Bind a completed, empty tool search to the observed model call and HTTP request."""
    models = {e.get("tool_call_id") for e in events if e.get("msg") == "g1_model_completion"}
    requests = {
        e.get("tool_call_id")
        for e in events
        if e.get("msg") == "catalog_http"
        and e.get("path") == "/api/products"
        and e.get("status") == 200
    }
    results = {e.get("tool_call_id") for e in events if e.get("msg") == "g1_catalog_tool_result"}
    return any(
        e.get("msg") == "g1_e5_catalog_search"
        and isinstance(e.get("query"), str)
        and e["query"].casefold() == query.casefold()
        and e.get("result_count") == 0
        and e.get("tool_call_id")
        and e["tool_call_id"] in models & requests & results
        for e in events
    )


def _response_hash(data):
    safe = _safe_response(data)
    raw = json.dumps(safe, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _verified_server_response(events, response):
    digest = _response_hash(response)
    return any(
        e.get("msg") == "g1_e5_response_hash" and e.get("response_sha256") == digest for e in events
    )


def _rendered_shade_pairs(labels, rows):
    expected = {}
    prefixes = [row["name"] + ", " for row in rows]
    for row in rows:
        for shade in row.get("shades", []):
            label = row["name"] + ", " + shade["name"]
            expected.setdefault(label, []).append({"productId": row["id"], "shadeId": shade["id"]})
    observed = [
        label
        for label in labels
        if any(label.startswith(prefix) for prefix in prefixes) and not label.endswith(", 상세보기")
    ]
    if not observed or len(set(observed)) != len(observed):
        return None
    if any(label not in expected or len(expected[label]) != 1 for label in observed):
        return None
    return [expected[label][0] for label in observed]


def _safe_response(data):
    """Drop the session capability while retaining the public ChatResponse structure."""
    response = json.loads(json.dumps(data))
    context = response.get("chatContext")
    if isinstance(context, dict):
        context.pop("session", None)
    return response


async def _cdp_live(item, owned=None):
    """Run supported cases through a fresh Chrome process; unsupported cases stay NOT_RUN."""
    import asyncio
    import tempfile
    from urllib.parse import parse_qs, quote, urlparse

    import httpx
    import websockets

    sys.path.insert(0, str(ROOT / "backend/chatbot"))
    from tests.g1_e1_live_driver import catalog_rows_match_db, pg_read

    supported = {
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
        "G1-CAT-12",
        "G1-CAT-13",
        "G1-CAT-14",
        "G1-UI-01",
    }
    if item["case"]["caseId"] not in supported:
        return _not_run(item, "cdp_case_not_implemented")
    app_url, catalog_url = os.environ.get("G1_E5_APP_URL"), os.environ.get("G1_E5_CATALOG_URL")
    log_file = os.environ.get("G1_E5_SERVER_LOG")
    if not app_url or not catalog_url or not log_file:
        return {
            "observation": _identity(item)
            | {
                "status": "BLOCKED_DEPENDENCY",
                "blockedReason": "cdp_live_environment_not_configured",
            },
            "artifacts": {},
        }
    app_url, catalog_url = _local_http_url(app_url), _local_http_url(catalog_url)
    chat_url = os.environ.get("G1_E5_CHAT_URL")
    if chat_url:
        chat_url = _local_http_url(chat_url)
    log_path = await asyncio.to_thread(Path(log_file).resolve, strict=True)
    commit = (
        await asyncio.to_thread(
            subprocess.check_output, ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True
        )
    ).strip()
    dirty = bool(
        (
            await asyncio.to_thread(
                subprocess.check_output, ["git", "status", "--porcelain"], cwd=ROOT, text=True
            )
        ).strip()
    )
    if dirty and os.environ.get("G1_E5_EXPLORATORY") != "1":
        return _not_run(item, "worktree_not_clean")
    chrome = Path(
        os.environ.get("G1_E5_CHROME", r"C:\Program Files\Google\Chrome\Application\chrome.exe")
    )
    if not await asyncio.to_thread(chrome.is_file):
        return {
            "observation": _identity(item)
            | {"status": "BLOCKED_DEPENDENCY", "blockedReason": "chrome_not_available"},
            "artifacts": {},
        }
    before = (await asyncio.to_thread(log_path.stat)).st_size
    started_at = datetime.now().astimezone().isoformat()
    manifest_path = ROOT / "docs/ai-alignment/04_llm_stage4_evaluation/g1_manifest_PROPOSED.json"
    manifest = json.loads(await asyncio.to_thread(manifest_path.read_text, encoding="utf-8"))[
        "catalogFixtureBinding"
    ]
    fixture = manifest["fixtureRowValue"]
    fixed_ids = [fixture["productId"], fixture["foreignProductId"]]
    fixed_db = await asyncio.to_thread(pg_read, fixed_ids)
    if fixed_db.get("status") != "OK":
        return {
            "observation": _identity(item)
            | {
                "status": fixed_db.get("status", "BLOCKED_DEPENDENCY"),
                "blockedReason": fixed_db.get("reason", "postgres_preflight_failed"),
            },
            "artifacts": {},
        }
    if fixed_db.get("catalogFixtureRef") != item["case"]["data"].get("catalogFixtureRef"):
        return {
            "observation": _identity(item)
            | {"status": "BLOCKED_DATA", "blockedReason": "fixture_reference_mismatch"},
            "artifacts": {},
        }
    async with httpx.AsyncClient(trust_env=False, timeout=20) as http:
        fixed_rows = []
        for product_id in fixed_ids:
            fixed_response = await http.get(
                catalog_url + "/api/products/" + quote(product_id, safe="")
            )
            if fixed_response.status_code != 200:
                return _not_run(item, "fixture_catalog_http_unavailable")
            fixed_rows.append(fixed_response.json()["product"])
    if not catalog_rows_match_db(fixed_ids, fixed_rows, fixed_db["products"], fixed_db["shades"]):
        return {
            "observation": _identity(item)
            | {"status": "BLOCKED_DATA", "blockedReason": "fixture_catalog_postgres_mismatch"},
            "artifacts": {},
        }
    empty_preflight = None
    if item["case"]["caseId"] == "G1-CAT-07":
        query = item["case"]["expected"]["allowedArgs"]["q"]
        async with httpx.AsyncClient(trust_env=False, timeout=20) as http:
            response = await http.get(catalog_url + "/api/products", params={"q": query})
        if response.status_code != 200:
            return {
                "observation": _identity(item)
                | {
                    "status": "BLOCKED_DEPENDENCY",
                    "blockedReason": "empty_preflight_http_unavailable",
                },
                "artifacts": {},
            }
        database = await asyncio.to_thread(_pg_search_count, query)
        if database.get("status") != "OK":
            return {
                "observation": _identity(item)
                | {
                    "status": "BLOCKED_DEPENDENCY",
                    "blockedReason": database.get("reason", "empty_preflight_db_unavailable"),
                },
                "artifacts": {},
            }
        if response.json().get("products") != [] or database.get("count") != 0:
            return {
                "observation": _identity(item)
                | {"status": "BLOCKED_DATA", "blockedReason": "empty_preflight_not_empty"},
                "artifacts": {},
            }
        empty_preflight = {
            "query": query,
            "httpStatus": 200,
            "databaseCount": 0,
            "databaseReadOnly": database["transactionReadOnly"],
        }
    brand_preflight = None
    if item["case"]["caseId"] == "G1-CAT-03":
        args = item["case"]["expected"]["allowedArgs"]
        async with httpx.AsyncClient(trust_env=False, timeout=20) as client:
            check = await client.get(
                catalog_url + "/api/products", params={"q": args["q"], "category": args["category"]}
            )
        if check.status_code != 200:
            return {
                "observation": _identity(item)
                | {
                    "status": "BLOCKED_DEPENDENCY",
                    "blockedReason": "brand_preflight_http_unavailable",
                },
                "artifacts": {},
            }
        matches = check.json().get("products")
        if not isinstance(matches, list) or not matches:
            return {
                "observation": _identity(item)
                | {"status": "BLOCKED_DATA", "blockedReason": "brand_fixture_has_no_products"},
                "artifacts": {},
            }
        brand_preflight = {
            "query": args["q"],
            "category": args["category"],
            "productId": matches[0]["id"],
            "httpStatus": check.status_code,
        }
    with tempfile.TemporaryDirectory(prefix="vishue-g1-chrome-") as profile:
        process = await asyncio.to_thread(
            subprocess.Popen,
            [
                str(chrome),
                "--headless=new",
                "--disable-gpu",
                "--no-first-run",
                "--no-default-browser-check",
                "--remote-debugging-port=0",
                "--window-size=1280,900",
                "--user-data-dir=" + profile,
                "about:blank",
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        try:
            port_file = Path(profile) / "DevToolsActivePort"
            port = None
            for _ in range(100):
                if port_file.is_file():
                    try:
                        lines = (
                            (await asyncio.to_thread(_read_shared_log, port_file, 0))
                            .decode("utf-8")
                            .splitlines()
                        )
                        port = int(lines[0]) if lines else None
                        if port is not None and 0 < port < 65536:
                            break
                    except (OSError, ValueError):
                        port = None
                if process.poll() is not None:
                    raise OSError("chrome_exited_before_debugging_ready")
                await asyncio.sleep(0.1)
            if port is None or not 0 < port < 65536:
                raise TimeoutError("chrome_debugging_not_ready")
            async with httpx.AsyncClient(trust_env=False, timeout=20) as http:
                target = await http.put(f"http://127.0.0.1:{port}/json/new?about:blank")
                target.raise_for_status()
                ws_url = target.json()["webSocketDebuggerUrl"]
            if not ws_url.startswith(f"ws://127.0.0.1:{port}/"):
                raise ValueError("unexpected_debugging_endpoint")
            async with websockets.connect(ws_url, max_size=80_000_000) as ws:
                counter, network = 0, []

                async def call(method, params=None):
                    nonlocal counter
                    counter += 1
                    ident = counter
                    await ws.send(
                        json.dumps({"id": ident, "method": method, "params": params or {}})
                    )
                    while True:
                        message = json.loads(await asyncio.wait_for(ws.recv(), 30))
                        if message.get("id") == ident:
                            if "error" in message:
                                raise ValueError("chrome_protocol_error")
                            return message.get("result", {})
                        if message.get("method", "").startswith("Network."):
                            network.append(message)

                async def js(expression):
                    result = await call(
                        "Runtime.evaluate",
                        {"expression": expression, "returnByValue": True, "awaitPromise": True},
                    )
                    if result.get("exceptionDetails"):
                        raise ValueError("ui_javascript_error")
                    return result.get("result", {}).get("value")

                async def click(label):
                    expr = (
                        "(() => {const name = LABEL; "
                        "const els = [...document.querySelectorAll("
                        "'button,[role=button],textarea,input')]; "
                        "const e = els.find(x => "
                        "(x.getAttribute('aria-label')||x.textContent||'').trim()===name); "
                        "if(!e)return null; e.scrollIntoView({block:'nearest',inline:'nearest'}); "
                        "const r=e.getBoundingClientRect(); "
                        "return {x:r.x+r.width/2,y:r.y+r.height/2,"
                        "width:r.width,height:r.height};})()"
                    ).replace("LABEL", json.dumps(label, ensure_ascii=False))
                    point = await js(expr)
                    if not point or point["width"] <= 0 or point["height"] <= 0:
                        raise ValueError("ui_control_missing")
                    for kind in ("mousePressed", "mouseReleased"):
                        await call(
                            "Input.dispatchMouseEvent",
                            {
                                "type": kind,
                                "x": point["x"],
                                "y": point["y"],
                                "button": "left",
                                "clickCount": 1,
                            },
                        )

                await call("Page.enable")
                await call("Runtime.enable")
                await call(
                    "Network.enable",
                    {"maxTotalBufferSize": 100_000_000, "maxResourceBufferSize": 50_000_000},
                )
                entry_path, expected_screen = _screen_entry(item["case"], fixture)
                await call("Page.navigate", {"url": app_url + entry_path})
                for _ in range(120):
                    ready = await js(
                        "!!document.querySelector('[aria-label=\"궁금한 점을 입력하세요\"]')"
                    )
                    if ready:
                        break
                    await asyncio.sleep(0.5)
                if not ready:
                    raise TimeoutError("expo_chat_screen_not_ready")
                variants = item["case"]["input"].get("requiredVariants", [])
                spec = next((v for v in variants if v["variantId"] == item["variantId"]), {})
                expected_type = spec.get("requestType", item["case"]["input"]["requestType"])
                if expected_type == "beauty_consultation" and expected_screen is None:
                    await click("지금 쓰는 립이 너무 건조해")
                await click("궁금한 점을 입력하세요")
                await call(
                    "Input.dispatchKeyEvent",
                    {
                        "type": "rawKeyDown",
                        "key": "a",
                        "code": "KeyA",
                        "modifiers": 2,
                        "windowsVirtualKeyCode": 65,
                        "commands": ["selectAll"],
                    },
                )
                await call(
                    "Input.dispatchKeyEvent",
                    {"type": "keyUp", "key": "a", "code": "KeyA", "modifiers": 2},
                )
                await call("Input.insertText", {"text": item["case"]["input"]["message"]})
                value = await js(
                    "document.querySelector('[aria-label=\"궁금한 점을 입력하세요\"]').value"
                )
                if value != item["case"]["input"]["message"]:
                    return _not_run(item, "ui_question_input_mismatch")
                await click("보내기")
                request_id, network_id, response_info = None, None, None
                for _ in range(180):
                    await js("document.readyState")
                    for event in network:
                        params = event.get("params", {})
                        if event.get("method") == "Network.requestWillBeSent":
                            req = params.get("request", {})
                            if req.get("method") == "POST" and _matches_chat_origin(
                                req.get("url", ""), chat_url or "http://127.0.0.1:8402"
                            ):
                                try:
                                    body = json.loads(req.get("postData", ""))
                                except ValueError:
                                    continue
                                if body.get("message") == item["case"]["input"]["message"]:
                                    network_id, request_body = params.get("requestId"), body
                        elif (
                            event.get("method") == "Network.responseReceived"
                            and params.get("requestId") == network_id
                        ):
                            response_info = params.get("response", {})
                        elif (
                            event.get("method") == "Network.loadingFinished"
                            and params.get("requestId") == network_id
                        ):
                            if response_info:
                                request_id = network_id
                    if request_id:
                        break
                    await asyncio.sleep(0.5)
                if not request_id or not response_info:
                    return _not_run(item, "browser_request_response_not_observed")
                if (
                    request_body.get("requestType", "chat") != expected_type
                    or request_body.get("screenContext") != expected_screen
                    or request_body.get("chatContext") is not None
                ):
                    return _not_run(item, "browser_request_variant_mismatch")
                raw_body = await call("Network.getResponseBody", {"requestId": request_id})
                data = raw_body.get("body", "")
                if raw_body.get("base64Encoded"):
                    data = base64.b64decode(data).decode("utf-8")
                response = _safe_response(json.loads(data))
                headers = {
                    key.lower(): value for key, value in response_info.get("headers", {}).items()
                }
                server_id = headers.get("x-request-id")
                if not isinstance(server_id, str) or not server_id:
                    return _not_run(item, "server_request_id_missing")
                for _ in range(40):
                    raw = (
                        (await asyncio.to_thread(_read_shared_log, log_path, before))
                        .decode("utf-8", errors="replace")
                        .splitlines()
                    )
                    events = _matching_server_events(raw, server_id)
                    if any(e.get("msg") == "request" for e in events):
                        break
                    await asyncio.sleep(0.25)
                if not events or not any(
                    e.get("msg") == "request" and e.get("status") == int(response_info["status"])
                    for e in events
                ):
                    return _not_run(item, "server_trace_not_observed")
                if owned:
                    bundle_id = None
                    for event in network:
                        params = event.get("params", {})
                        request = params.get("request", {})
                        url = urlparse(request.get("url", ""))
                        if (
                            event.get("method") == "Network.requestWillBeSent"
                            and url.hostname in {"localhost", "127.0.0.1"}
                            and url.port == urlparse(app_url).port
                            and ".bundle" in url.path
                        ):
                            bundle_id = params.get("requestId")
                    finished = any(
                        event.get("method") == "Network.loadingFinished"
                        and event.get("params", {}).get("requestId") == bundle_id
                        for event in network
                    )
                    if not bundle_id or not finished:
                        return _not_run(item, "expo_bundle_not_observed")
                    bundle = await call("Network.getResponseBody", {"requestId": bundle_id})
                    body = bundle.get("body", "")
                    raw_bundle = (
                        base64.b64decode(body, validate=True)
                        if bundle.get("base64Encoded")
                        else body.encode("utf-8")
                    )
                    if not raw_bundle or len(raw_bundle) > 50_000_000:
                        return _not_run(item, "expo_bundle_unavailable")
                    owned["servedBundleSha256"] = hashlib.sha256(raw_bundle).hexdigest()
                if not _verified_server_response(events, response):
                    return _not_run(item, "server_response_hash_missing_or_mismatch")
                if int(response_info["status"]) < 400 and not _verified_catalog_trace(events):
                    return _not_run(item, "real_model_catalog_trace_missing")
                ids = [p["id"] for p in response.get("products", [])]
                if (
                    int(response_info["status"]) < 400
                    and ids
                    and not _verified_tool_products(events, ids)
                ):
                    return _not_run(item, "response_products_not_bound_to_tool_result")
                if int(response_info["status"]) >= 400:
                    db = await asyncio.to_thread(pg_read, [])
                    if db.get("status") != "OK":
                        return {
                            "observation": _identity(item)
                            | {
                                "status": db.get("status", "BLOCKED_DEPENDENCY"),
                                "blockedReason": db.get("reason", "postgres_preflight_failed"),
                            },
                            "artifacts": {},
                        }
                    if db.get("catalogFixtureRef") != item["case"]["data"]["catalogFixtureRef"]:
                        return {
                            "observation": _identity(item)
                            | {
                                "status": "BLOCKED_DATA",
                                "blockedReason": "fixture_reference_mismatch",
                            },
                            "artifacts": {},
                        }
                    for _ in range(40):
                        loading = await js("!!document.querySelector('[role=progressbar]')")
                        if not loading:
                            break
                        await asyncio.sleep(0.25)
                    rendered = await js("document.body.innerText")
                    failed_image = (await call("Page.captureScreenshot", {"format": "png"})).get(
                        "data", ""
                    )
                    image = base64.b64decode(failed_image, validate=True)
                    if not image.startswith(b"\x89PNG\r\n\x1a\n") or len(image) > MAX_IMAGE_BYTES:
                        return _not_run(item, "browser_screenshot_invalid")
                    common = _identity(item) | {
                        "gitCommit": commit,
                        "requestId": server_id,
                        "workingTreeDirty": dirty,
                        "browser": "isolated_headless_chrome_cdp",
                    }
                    observation = _identity(item) | {
                        "isMock": False,
                        "isSynthetic": False,
                        "gitCommit": commit,
                        "requestId": server_id,
                        "response": response,
                        "httpStatus": int(response_info["status"]),
                        "catalogFixtureRef": db["catalogFixtureRef"],
                        "fixtureRowSha256": db["fixtureRowSha256"],
                        "status": "FAIL",
                        "failureReason": "chat_endpoint_http_" + str(int(response_info["status"])),
                    }
                    if dirty or not owned:
                        observation.update(
                            status="NOT_RUN",
                            blockedReason=(
                                "dirty_worktree_exploratory_only"
                                if dirty
                                else "runtime_source_identity_not_verified"
                            ),
                        )
                    return {
                        "observation": observation,
                        "artifacts": {
                            "app_request_and_response_trace": common
                            | {
                                "requestBody": request_body,
                                "response": response,
                                "httpStatus": int(response_info["status"]),
                                "serverTrace": events,
                                "browserNetworkRequestId": request_id,
                            },
                            "UI_rendered_elements_or_screen_recording": common
                            | {
                                "renderedElements": rendered,
                                "screenshot": {
                                    "sha256": hashlib.sha256(image).hexdigest(),
                                    "bytesBase64": failed_image,
                                },
                            },
                            "card_and_navigation_ids_if_present": common
                            | {"postgres": db, "capturedOnError": True},
                        },
                    }

                async def captured_incomplete(reason):
                    # Keep actual browser/server evidence even when a later gate is missing.
                    rendered = await js("document.body.innerText")
                    screenshot = await call("Page.captureScreenshot", {"format": "png"})
                    encoded = screenshot.get("data", "")
                    image = base64.b64decode(encoded, validate=True)
                    if not image.startswith(b"\x89PNG\r\n\x1a\n") or len(image) > MAX_IMAGE_BYTES:
                        return _not_run(item, "browser_screenshot_invalid")
                    common = _identity(item) | {"gitCommit": commit, "requestId": server_id}
                    return {
                        "observation": common
                        | {
                            "status": "NOT_RUN",
                            "blockedReason": reason,
                            "isMock": False,
                            "isSynthetic": False,
                            "httpStatus": int(response_info["status"]),
                            "response": response,
                        },
                        "artifacts": {
                            "app_request_and_response_trace": common
                            | {
                                "request": request_body,
                                "response": response,
                                "serverTrace": events,
                            },
                            "UI_rendered_elements_or_screen_recording": common
                            | {
                                "renderedElements": rendered,
                                "screenshot": {
                                    "sha256": hashlib.sha256(image).hexdigest(),
                                    "bytesBase64": encoded,
                                },
                            },
                            "card_and_navigation_ids_if_present": common
                            | {
                                "responseProductIds": ids,
                                "postgres": fixed_db,
                                "navigationObserved": False,
                            },
                        },
                    }

                if item["case"]["caseId"] == "G1-CAT-07":
                    if not _verified_empty_search(events, empty_preflight["query"]):
                        return await captured_incomplete("empty_search_trace_not_observed")
                    rendered = ""
                    labels = []
                    for _ in range(40):
                        rendered = await js("document.body.innerText")
                        labels = await js(
                            "[...document.querySelectorAll('button,[role=button]')].map(e=>e.getAttribute('aria-label')||'').filter(Boolean)"
                        )
                        if "현재 조건과 근거로 추천할 제품이 없어요" in rendered:
                            break
                        await asyncio.sleep(0.25)
                    screen_data = (await call("Page.captureScreenshot", {"format": "png"})).get(
                        "data", ""
                    )
                    image = base64.b64decode(screen_data, validate=True)
                    if not image.startswith(b"\x89PNG\r\n\x1a\n") or len(image) > MAX_IMAGE_BYTES:
                        return _not_run(item, "browser_screenshot_invalid")
                    card_labels = [label for label in labels if label.endswith(", 상세보기")]
                    valid = (
                        response.get("resultType") == "empty"
                        and not ids
                        and not card_labels
                        and "현재 조건과 근거로 추천할 제품이 없어요" in rendered
                    )
                    observation = _identity(item) | {
                        "isMock": False,
                        "isSynthetic": False,
                        "gitCommit": commit,
                        "requestId": server_id,
                        "response": response,
                        "httpStatus": int(response_info["status"]),
                        "catalogFixtureRef": fixed_db["catalogFixtureRef"],
                        "fixtureRowSha256": fixed_db["fixtureRowSha256"],
                        "sourceSnapshotId": fixed_db["catalogFixtureRef"],
                        "sourceProductIds": [],
                        "catalogResultCount": 0,
                        "ui": {"state": "empty", "cardIds": []}
                        if valid
                        else {"state": "unexpected", "observedCardLabels": card_labels},
                    }
                    if not valid:
                        observation.update(
                            status="FAIL", failureReason="empty_result_or_ui_mismatch"
                        )
                    if dirty or not owned:
                        observation.update(
                            status="NOT_RUN",
                            blockedReason=(
                                "dirty_worktree_exploratory_only"
                                if dirty
                                else "runtime_source_identity_not_verified"
                            ),
                        )
                    common = _identity(item) | {
                        "gitCommit": commit,
                        "requestId": server_id,
                        "browser": "isolated_headless_chrome_cdp",
                        "workingTreeDirty": dirty,
                        "startedAt": started_at,
                        "syntheticDependencies": [],
                        "fixturePreflight": {
                            "productIds": fixed_ids,
                            "fingerprint": fixed_db["fixtureRowSha256"],
                        },
                        "emptyPreflight": empty_preflight,
                    }
                    return {
                        "observation": observation,
                        "artifacts": {
                            "app_request_and_response_trace": common
                            | {
                                "requestBody": request_body,
                                "response": response,
                                "httpStatus": int(response_info["status"]),
                                "serverTrace": events,
                                "browserNetworkRequestId": request_id,
                            },
                            "UI_rendered_elements_or_screen_recording": common
                            | {
                                "renderedElements": rendered,
                                "labels": labels,
                                "screenshot": {
                                    "sha256": hashlib.sha256(image).hexdigest(),
                                    "bytesBase64": screen_data,
                                },
                            },
                            "card_and_navigation_ids_if_present": common
                            | {"observedCardLabels": card_labels, "postgres": fixed_db},
                        },
                    }
                if not ids:
                    if item["case"]["caseId"] == "G1-CAT-12":
                        from tests.g1_e1_live_driver import observe_detail_shades

                        captured = await captured_incomplete("clarification_render_not_verified")
                        ui_artifact = captured["artifacts"].get(
                            "UI_rendered_elements_or_screen_recording", {}
                        )
                        answer = response.get("answer", "")
                        if answer and answer in ui_artifact.get("renderedElements", ""):
                            observation = captured["observation"]
                            observation.pop("status", None)
                            observation.pop("blockedReason", None)
                            observation.update(
                                sourceSnapshotId=fixed_db["catalogFixtureRef"],
                                sourceShadePairs=[
                                    {"productId": row["product_id"], "shadeId": row["id"]}
                                    for row in fixed_db["shades"]
                                    if row["product_id"] == expected_screen["productId"]
                                ],
                            )
                            observation.update(
                                observe_detail_shades(
                                    "G1-CAT-12",
                                    response,
                                    expected_screen["productId"],
                                    fixed_db["shades"],
                                    fixture,
                                )
                            )
                        return captured
                    return await captured_incomplete("no_product_card_to_validate")
                manifest = json.loads(
                    (
                        ROOT
                        / "docs/ai-alignment/04_llm_stage4_evaluation/g1_manifest_PROPOSED.json"
                    ).read_text(encoding="utf-8")
                )["catalogFixtureBinding"]
                fixture = manifest["fixtureRowValue"]
                source_ids = list(
                    dict.fromkeys(
                        ids
                        + [fixture["productId"], fixture["foreignProductId"]]
                        + ([brand_preflight["productId"]] if brand_preflight else [])
                    )
                )
                db = await asyncio.to_thread(pg_read, source_ids)
                if db.get("status") != "OK":
                    return {
                        "observation": _identity(item)
                        | {
                            "status": db.get("status", "BLOCKED_DEPENDENCY"),
                            "blockedReason": db.get("reason", "postgres_preflight_failed"),
                        },
                        "artifacts": {},
                    }
                if db.get("catalogFixtureRef") != item["case"]["data"]["catalogFixtureRef"]:
                    return {
                        "observation": _identity(item)
                        | {"status": "BLOCKED_DATA", "blockedReason": "fixture_reference_mismatch"},
                        "artifacts": {},
                    }
                async with httpx.AsyncClient(trust_env=False, timeout=20) as http:
                    source_rows = []
                    for pid in source_ids:
                        detail = await http.get(
                            catalog_url + "/api/products/" + quote(pid, safe="")
                        )
                        if detail.status_code != 200:
                            return _not_run(item, "catalog_card_detail_unavailable")
                        source_rows.append(detail.json()["product"])
                if not catalog_rows_match_db(source_ids, source_rows, db["products"], db["shades"]):
                    return {
                        "observation": _identity(item)
                        | {
                            "status": "BLOCKED_DATA",
                            "blockedReason": "catalog_postgres_card_mismatch",
                        },
                        "artifacts": {},
                    }
                row_by_id = {row["id"]: row for row in source_rows}
                rows = [row_by_id[pid] for pid in ids]
                # The app has a development fallback: require the browser's own real
                # Catalog response, not a separate API query or matching display names.
                browser_catalog = None
                for _ in range(40):
                    await js("document.readyState")
                    requests = {}
                    responses = {}
                    finished = set()
                    for event in network:
                        params = event.get("params", {})
                        net_id = params.get("requestId")
                        if event.get("method") == "Network.requestWillBeSent":
                            req = params.get("request", {})
                            url = urlparse(req.get("url", ""))
                            query = parse_qs(url.query)
                            if (
                                req.get("method") == "GET"
                                and url.path == "/api/products"
                                and url.hostname in {"localhost", "127.0.0.1"}
                                and url.port == urlparse(catalog_url).port
                                and set(query.get("ids", [""])[0].split(",")) == set(ids)
                            ):
                                requests[net_id] = {
                                    "method": "GET",
                                    "path": url.path,
                                    "requestedIds": query["ids"][0].split(","),
                                }
                        elif event.get("method") == "Network.responseReceived":
                            responses[net_id] = params.get("response", {})
                        elif event.get("method") == "Network.loadingFinished":
                            finished.add(net_id)
                    matched = [
                        (key, req, responses.get(key))
                        for key, req in requests.items()
                        if responses.get(key) and key in finished
                    ]
                    if matched:
                        catalog_network_id, browser_request, browser_response = matched[-1]
                        if int(browser_response.get("status", 0)) != 200:
                            return _not_run(item, "browser_catalog_request_failed")
                        captured = await call(
                            "Network.getResponseBody", {"requestId": catalog_network_id}
                        )
                        value = captured.get("body", "")
                        if captured.get("base64Encoded"):
                            value = base64.b64decode(value).decode("utf-8")
                        payload = json.loads(value)
                        browser_rows = payload.get("products")
                        if (
                            not isinstance(browser_rows, list)
                            or {row.get("id") for row in browser_rows} != set(ids)
                            or not catalog_rows_match_db(
                                ids, browser_rows, db["products"], db["shades"]
                            )
                        ):
                            return _not_run(item, "browser_catalog_response_mismatch")
                        browser_catalog = {
                            "request": browser_request,
                            "httpStatus": 200,
                            "response": payload,
                            "networkRequestId": catalog_network_id,
                        }
                        break
                    await asyncio.sleep(0.25)
                if browser_catalog is None:
                    result = _not_run(item, "browser_catalog_request_not_observed")
                    result["observation"]["partialCapture"] = {
                        "requestId": server_id,
                        "httpStatus": int(response_info["status"]),
                        "response": _safe_response(response),
                        "serverTrace": events,
                        "catalogRequestCount": len(requests),
                        "catalogResponseStatuses": [
                            responses[key].get("status") for key in requests if key in responses
                        ],
                        "catalogLoadingFailures": [
                            {
                                "networkRequestId": event["params"]["requestId"],
                                "corsError": event["params"]
                                .get("corsErrorStatus", {})
                                .get("corsError"),
                            }
                            for event in network
                            if event.get("method") == "Network.loadingFailed"
                            and event.get("params", {}).get("requestId") in requests
                        ],
                    }
                    return result
                # Only certify rendered cards when the browser actually exposes each label.
                labels = await js(
                    "[...document.querySelectorAll('button,[role=button]')].map(e=>e.getAttribute('aria-label')||'').filter(Boolean)"
                )
                expected_labels = [f"{row['brand']} {row['name']}, 상세보기" for row in rows]
                if (
                    not isinstance(labels, list)
                    or len(set(expected_labels)) != len(ids)
                    or any(labels.count(label) != 1 for label in expected_labels)
                ):
                    return _not_run(item, "rendered_card_identity_unverified")
                if [label for label in labels if label in expected_labels] != expected_labels:
                    return _not_run(item, "rendered_card_order_unverified")
                screenshot = await call("Page.captureScreenshot", {"format": "png"})
                screen_data = screenshot.get("data", "")
                image = base64.b64decode(screen_data, validate=True)
                if not image.startswith(b"\x89PNG\r\n\x1a\n") or len(image) > MAX_IMAGE_BYTES:
                    return _not_run(item, "browser_screenshot_invalid")
                # Click the card via the actual browser input and verify the detail route.
                await click(expected_labels[0])
                detail_path = "/product/" + quote(ids[0], safe="")
                for _ in range(60):
                    shown_path = await js("window.location.pathname")
                    if shown_path == detail_path:
                        break
                    await asyncio.sleep(0.5)
                if shown_path != detail_path:
                    return _not_run(item, "product_detail_navigation_unverified")
                wanted_name = json.dumps(rows[0]["name"], ensure_ascii=False)
                detail_ready = False
                for _ in range(60):
                    detail_ready = await js(
                        "[...document.querySelectorAll('h1,[role=heading]')]"
                        ".some(e=>(e.innerText||e.textContent||'').includes(" + wanted_name + "))"
                    )
                    if detail_ready:
                        break
                    await asyncio.sleep(0.5)
                if not detail_ready:
                    return _not_run(item, "product_detail_screen_unverified")
                await js(
                    "[...document.querySelectorAll('h1,[role=heading]')]"
                    ".find(e=>(e.innerText||e.textContent||'').includes(" + wanted_name + "))"
                    ".scrollIntoView({block:'center'})"
                )
                detail_screenshot = await call("Page.captureScreenshot", {"format": "png"})
                detail_data = detail_screenshot.get("data", "")
                detail_image = base64.b64decode(detail_data, validate=True)
                if (
                    not detail_image.startswith(b"\x89PNG\r\n\x1a\n")
                    or len(detail_image) > MAX_IMAGE_BYTES
                ):
                    return _not_run(item, "detail_screenshot_invalid")
                observation = _identity(item) | {
                    "isMock": False,
                    "isSynthetic": False,
                    "gitCommit": commit,
                    "requestId": server_id,
                    "response": response,
                    "httpStatus": int(response_info["status"]),
                    "catalogFixtureRef": db["catalogFixtureRef"],
                    "fixtureRowSha256": db["fixtureRowSha256"],
                    "sourceSnapshotId": db["catalogFixtureRef"],
                    "sourceProductIds": ids,
                    "ui": {"cardIds": ids, "clickedCardId": ids[0], "detailId": ids[0]},
                }
                if item["case"]["caseId"] == "G1-UI-01":
                    pairs = _rendered_shade_pairs(labels, rows)
                    if pairs is None:
                        observation.update(
                            status="NOT_RUN",
                            blockedReason="rendered_shades_not_observed_or_unverified",
                        )
                    else:
                        observation["ui"]["shadePairs"] = pairs
                    observation["sourceShadePairs"] = [
                        {"productId": row["product_id"], "shadeId": row["id"]}
                        for row in db["shades"]
                        if row["product_id"] in ids
                    ]
                route = next(
                    (
                        e.get("route_intent")
                        for e in events
                        if e.get("msg") == "g1_graph_node_end" and e.get("node") == "plan_turn"
                    ),
                    None,
                )
                if route:
                    observation["routeIntent"] = route
                if item["case"]["caseId"] == "G1-CAT-14":
                    observation.update(
                        status="NOT_RUN", blockedReason="combined_explanation_human_review_pending"
                    )
                if dirty or not owned:
                    observation.update(
                        status="NOT_RUN",
                        blockedReason=(
                            "dirty_worktree_exploratory_only"
                            if dirty
                            else "runtime_source_identity_not_verified"
                        ),
                    )
                common = _identity(item) | {
                    "gitCommit": commit,
                    "requestId": server_id,
                    "browser": "isolated_headless_chrome_cdp",
                    "fixturePreflight": {
                        "productIds": fixed_ids,
                        "fingerprint": fixed_db["fixtureRowSha256"],
                    },
                    "emptyPreflight": empty_preflight,
                    "workingTreeDirty": dirty,
                    "startedAt": started_at,
                    "syntheticDependencies": [],
                }
                return {
                    "observation": observation,
                    "artifacts": {
                        "app_request_and_response_trace": common
                        | {
                            "requestBody": request_body,
                            "response": response,
                            "httpStatus": int(response_info["status"]),
                            "serverTrace": events,
                            "browserNetworkRequestId": request_id,
                            "browserCatalog": browser_catalog,
                        },
                        "UI_rendered_elements_or_screen_recording": common
                        | {
                            "labels": labels,
                            "screenshot": {
                                "sha256": hashlib.sha256(image).hexdigest(),
                                "bytesBase64": screen_data,
                            },
                            "detailScreenshot": {
                                "sha256": hashlib.sha256(detail_image).hexdigest(),
                                "bytesBase64": detail_data,
                            },
                        },
                        "card_and_navigation_ids_if_present": common
                        | {
                            "cardIds": ids,
                            "labels": expected_labels,
                            "clickedCardId": ids[0],
                            "detailPath": shown_path,
                            "catalogRows": rows,
                            "brandPreflight": brand_preflight,
                            "postgres": db,
                        },
                    },
                }
        finally:
            if process.poll() is None:
                if os.name == "nt":
                    # Chrome's children also hold the private profile open on Windows.
                    await asyncio.to_thread(
                        subprocess.run,
                        ["taskkill", "/PID", str(process.pid), "/T", "/F"],
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                        check=False,
                        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                    )
                else:
                    process.terminate()
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=10)


def run_captured_server():
    """Start the existing app with read-only graph callbacks for local E5 evaluation."""
    import logging
    import threading

    import uvicorn
    from langchain_core.callbacks.base import BaseCallbackHandler

    sys.path.insert(0, str(ROOT / "backend/chatbot"))
    from app.clients.catalog_client import CatalogClient
    from app.core.observability import catalog_tool_call_id, request_id_var
    from app.main import app
    from app.services import chat_service
    from tests.g1_e3_live_driver import ObservedGraph

    class RequestGraphCapture(BaseCallbackHandler):
        def __init__(self):
            super().__init__()
            self.active = {}
            self.lock = threading.Lock()

        def on_chain_start(self, serialized, inputs, *, run_id, name=None, **kwargs):
            request_id = request_id_var.get()
            if name in {"plan_turn", "execute_turn"} and request_id != "-":
                decision = inputs.get("decision") if isinstance(inputs, dict) else None
                route = getattr(decision, "intent", None) if name == "plan_turn" else None
                with self.lock:
                    self.active[run_id] = (request_id, name, route)

        def on_chain_end(self, outputs, *, run_id, **kwargs):
            with self.lock:
                info = self.active.pop(run_id, None)
            if info:
                request_id, name, route = info
                fields = {"request_id": request_id, "node": name, "graph_run_id": str(run_id)}
                if isinstance(route, str) and route.strip():
                    fields["route_intent"] = route
                logging.getLogger("g1_e5_graph").info("g1_graph_node_end", extra=fields)

        def on_chain_error(self, error, *, run_id, **kwargs):
            with self.lock:
                self.active.pop(run_id, None)

    original_search = CatalogClient.search_products

    async def observed_search(self, *, category=None, q="", ids=None):
        rows = await original_search(self, category=category, q=q, ids=ids)
        logging.getLogger("g1_e5_catalog").info(
            "g1_e5_catalog_search",
            extra={
                "query": q,
                "category": category,
                "result_count": len(rows),
                "tool_call_id": catalog_tool_call_id.get(),
            },
        )
        return rows

    CatalogClient.search_products = observed_search
    chat_service.product_supervisor = ObservedGraph(
        chat_service.product_supervisor, RequestGraphCapture()
    )

    async def observed_app(scope, receive, send):
        if scope.get("type") != "http" or scope.get("path") != "/api/chat":
            return await app(scope, receive, send)
        chunks = []
        identity = None

        async def capture(message):
            nonlocal identity
            if message.get("type") == "http.response.start":
                for key, value in message.get("headers", []):
                    if key.lower() == b"x-request-id":
                        identity = value.decode("latin-1")
            elif message.get("type") == "http.response.body":
                chunks.append(message.get("body", b""))
                if not message.get("more_body", False) and identity:
                    try:
                        body = json.loads(b"".join(chunks))
                        digest = _response_hash(body)
                    except (ValueError, TypeError, AttributeError):
                        pass
                    else:
                        logging.getLogger("g1_e5_response").info(
                            "g1_e5_response_hash",
                            extra={"request_id": identity, "response_sha256": digest},
                        )
            await send(message)

        return await app(scope, receive, capture)

    uvicorn.run(
        observed_app,
        host="127.0.0.1",
        port=int(os.getenv("G1_E5_SERVER_PORT", "8402")),
        log_config=None,
    )


def _listening_pids(port):
    """Read OS socket owners without trusting configured process identifiers."""
    if os.name != "nt":
        return set()
    result = subprocess.run(
        ["netstat", "-ano", "-p", "TCP"], capture_output=True, text=True, timeout=15, check=True
    )
    found = set()
    for line in result.stdout.splitlines():
        parts = line.split()
        if len(parts) >= 5 and parts[0] == "TCP" and parts[3] == "LISTENING":
            try:
                if int(parts[1].rsplit(":", 1)[-1]) == port:
                    found.add(int(parts[4]))
            except ValueError:
                continue
    return found


def _owns_listener(port, process):
    """Windows venv Python uses a direct child; reject unrelated socket owners."""
    if process.poll() is not None:
        return False
    owners = _listening_pids(port)
    if owners == {process.pid}:
        return True
    if len(owners) != 1:
        return False
    owner = next(iter(owners))
    result = subprocess.run(
        [
            "powershell",
            "-NoProfile",
            "-Command",
            f"Get-CimInstance Win32_Process -Filter 'ProcessId={int(owner)}' | "
            "Select-Object ParentProcessId,Name | ConvertTo-Json -Compress",
        ],
        capture_output=True,
        text=True,
        timeout=15,
        check=True,
    )
    try:
        child = json.loads(result.stdout)
        return (
            child.get("ParentProcessId") == process.pid
            and child.get("Name", "").lower() == "python.exe"
        )
    except (ValueError, AttributeError):
        return False


def _owned_ready(http, app_url, chat_url):
    return (
        http.get(app_url + "/chat").status_code == 200
        and http.get(chat_url + "/healthz").status_code == 200
    )


def _runtime_log_event(raw):
    """Keep diagnostic markers, never arbitrary process output or credentials."""
    text = raw.decode("utf-8", errors="replace")
    markers = (
        "Traceback",
        "ModuleNotFoundError",
        "ImportError",
        "ValidationError",
        "PermissionError",
        "EADDRINUSE",
        "ENOENT",
        "Cannot find module",
        "No modules in context",
        "Unable to resolve",
        "Error:",
        "Bundled",
        "Bundling failed",
        "Starting Metro",
        "Waiting on",
        "Application startup complete",
        "Uvicorn running",
        "CommandError",
        "SyntaxError",
        "TypeError",
        "Cannot load skin-analysis-v4",
        "heap out of memory",
        "FATAL ERROR",
        "Allocation failed",
        "ERR_WORKER_OUT_OF_MEMORY",
    )
    return {
        "capturedAt": datetime.now().astimezone().isoformat(),
        "lineSha256": hashlib.sha256(raw).hexdigest(),
        "markers": [marker for marker in markers if marker in text],
    }


def _owned_environment(inherited, file_values, catalog_url, app_port, chat_port):
    env = inherited.copy()
    for key, value in file_values.items():
        if value is not None:
            env.setdefault(key, value)
    env.update(
        {
            "CI": "1",
            "EXPO_NO_DOTENV": "1",
            "G1_SUPERVISOR_ENABLED": "true",
            "G1_E5_SERVER_PORT": str(chat_port),
            "CATALOG_API_URL": catalog_url,
            "EXPO_PUBLIC_API_BASE_URL": catalog_url,
            "EXPO_PUBLIC_CHAT_API_BASE_URL": f"http://127.0.0.1:{chat_port}",
            "CORS_ORIGINS": json.dumps([f"http://localhost:{app_port}"]),
            "PYTHONPATH": str(ROOT / "backend/chatbot"),
            "PYTHONUNBUFFERED": "1",
        }
    )
    return env


def _run_owned(item):
    """Launch and own the exact local checkout's Expo and captured chatbot processes."""
    import asyncio
    import shutil
    import tempfile
    import threading

    import httpx
    from dotenv import dotenv_values

    diagnostics = {"expo": [], "chatbot": [], "readiness": []}

    def blocked(reason):
        return {
            "observation": _identity(item)
            | {
                "status": "BLOCKED_DEPENDENCY",
                "blockedReason": reason,
                "runtimeDiagnostics": diagnostics,
            },
            "artifacts": {},
        }

    if os.name != "nt":
        return blocked("windows_socket_owner_check_required")
    try:
        commit = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
        diagnostic_only = os.environ.get("G1_E5_DIAGNOSTIC_ONLY") == "1"
        dirty = bool(
            subprocess.check_output(["git", "status", "--porcelain"], cwd=ROOT, text=True).strip()
        )
        diagnostics.update({"gitCommit": commit, "worktreeDirty": dirty})
        if dirty and not diagnostic_only:
            return _not_run(item, "worktree_not_clean")
        node = shutil.which("node")
        expo = ROOT / "node_modules/expo/bin/cli"
        environment_path = Path(os.environ.get("G1_E1_ENV_PATH", ROOT / ".env.local"))
        catalog_url = _local_http_url(os.environ["G1_E5_CATALOG_URL"])
        if not node or not expo.is_file() or not environment_path.is_file():
            return blocked("owned_runtime_dependency_missing")
        app_port = int(os.environ.get("G1_E5_OWNED_APP_PORT", "8098"))
        chat_port = int(os.environ.get("G1_E5_OWNED_CHAT_PORT", "8403"))
        if app_port == chat_port or _listening_pids(app_port) or _listening_pids(chat_port):
            return blocked("owned_runtime_port_unavailable")
        env = _owned_environment(
            os.environ, dotenv_values(environment_path), catalog_url, app_port, chat_port
        )
        # Child environments can contain keys and are never included in evidence.
        with tempfile.TemporaryDirectory(prefix="g1-e5-owned-") as temp:
            log = Path(temp) / "server.jsonl"
            log.touch()
            started = datetime.now().astimezone().isoformat()
            chat = subprocess.Popen(
                [sys.executable, "-u", "-m", "tests.g1_e5_live_driver", "--serve-captured"],
                cwd=ROOT / "backend/chatbot",
                env=env,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
            )
            expo_process = None

            def copy_log():
                for line in iter(chat.stdout.readline, b""):
                    diagnostics["chatbot"].append(_runtime_log_event(line))
                    del diagnostics["chatbot"][:-100]
                    try:
                        decoded = line.decode("utf-8")
                        event = json.loads(decoded)
                        request_id = event.get("request_id")
                        safe = _matching_server_events([decoded], request_id) if request_id else []
                        if safe:
                            with log.open("ab") as target:
                                target.write(
                                    (json.dumps(safe[0], ensure_ascii=False) + "\n").encode("utf-8")
                                )
                    except (OSError, ValueError, TypeError, AttributeError):
                        continue

            thread = threading.Thread(target=copy_log, daemon=True)
            thread.start()
            try:
                expo_process = subprocess.Popen(
                    [node, str(expo), "start", "--web", "--port", str(app_port)],
                    cwd=ROOT,
                    env=env,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                )

                def copy_expo_log():
                    for line in iter(expo_process.stdout.readline, b""):
                        diagnostics["expo"].append(_runtime_log_event(line))
                        del diagnostics["expo"][:-100]

                expo_thread = threading.Thread(target=copy_expo_log, daemon=True)
                expo_thread.start()
                app_url = f"http://localhost:{app_port}"
                chat_url = f"http://127.0.0.1:{chat_port}"
                deadline = time.monotonic() + 120
                with httpx.Client(timeout=httpx.Timeout(30, connect=2), trust_env=False) as http:
                    while time.monotonic() < deadline:
                        if chat.poll() is not None or expo_process.poll() is not None:
                            diagnostics["exitCodes"] = {
                                "chatbot": chat.poll(),
                                "expo": expo_process.poll(),
                            }
                            return blocked("owned_runtime_process_exited")
                        try:
                            if _owned_ready(http, app_url, chat_url):
                                break
                        except httpx.HTTPError as exc:
                            diagnostics["readiness"].append(type(exc).__name__)
                            del diagnostics["readiness"][:-30]
                        time.sleep(1)
                    else:
                        return blocked("owned_runtime_startup_timeout")
                if diagnostic_only and os.environ.get("G1_E5_EXPLORATORY") != "1":
                    result = _not_run(item, "diagnostic_only_runtime_ready")
                    result["observation"]["runtimeDiagnostics"] = diagnostics
                    return result
                if not _owns_listener(app_port, expo_process) or not _owns_listener(
                    chat_port, chat
                ):
                    return blocked("owned_runtime_socket_pid_mismatch")
                os.environ.update(
                    {
                        "G1_E5_APP_URL": app_url,
                        "G1_E5_CHAT_URL": chat_url,
                        "G1_E5_SERVER_LOG": str(log),
                        "G1_E5_CATALOG_URL": catalog_url,
                    }
                )
                owned = {
                    "checkout": str(ROOT),
                    "gitCommit": commit,
                    "startedAt": started,
                    "expoPid": expo_process.pid,
                    "chatbotPid": chat.pid,
                    "expoPort": app_port,
                    "chatbotPort": chat_port,
                    "expoDependencyPath": str(expo.resolve()),
                }
                result = asyncio.run(_cdp_live(item, owned=owned))
                if diagnostic_only:
                    result["observation"]["diagnosticCaptureReason"] = result["observation"].get(
                        "blockedReason"
                    )
                    if result["observation"].get("status") not in {
                        "FAIL",
                        "BLOCKED_DEPENDENCY",
                        "BLOCKED_DATA",
                        "BLOCKED",
                    }:
                        result["observation"]["status"] = "NOT_RUN"
                        result["observation"]["blockedReason"] = "diagnostic_only_ui_capture"
                    result["observation"]["runtimeDiagnostics"] = diagnostics
                    return result
                clean = (
                    subprocess.check_output(
                        ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True
                    ).strip()
                    == commit
                    and not subprocess.check_output(
                        ["git", "status", "--porcelain"], cwd=ROOT, text=True
                    ).strip()
                )
                live = (
                    chat.poll() is None
                    and expo_process.poll() is None
                    and _owns_listener(app_port, expo_process)
                    and _owns_listener(chat_port, chat)
                )
                if not clean or not live or not owned.get("servedBundleSha256"):
                    return _not_run(item, "owned_runtime_identity_changed_or_unverified")
                for artifact in result.get("artifacts", {}).values():
                    artifact["ownedRuntime"] = owned
                return result
            finally:
                for process in (expo_process, chat):
                    if process is not None and process.poll() is None:
                        subprocess.run(
                            ["taskkill", "/PID", str(process.pid), "/T", "/F"],
                            stdout=subprocess.DEVNULL,
                            stderr=subprocess.DEVNULL,
                            check=False,
                        )
                        try:
                            process.wait(timeout=10)
                        except subprocess.TimeoutExpired:
                            process.kill()
                            process.wait(timeout=10)
                thread.join(timeout=3)
    except (OSError, ValueError, KeyError, subprocess.SubprocessError) as exc:
        import traceback

        diagnostics["exception"] = {
            "type": type(exc).__name__,
            "frames": [
                {"file": Path(frame.filename).name, "line": frame.lineno, "function": frame.name}
                for frame in traceback.extract_tb(exc.__traceback__)[-8:]
            ],
        }
        return blocked("owned_runtime_setup_incomplete")


def run(item):
    if os.environ.get("G1_E5_OWNED") == "1":
        return _run_owned(item)
    if os.environ.get("G1_E5_CDP") == "1":
        import asyncio

        try:
            return asyncio.run(_cdp_live(item))
        except (OSError, TimeoutError, ValueError, KeyError, subprocess.SubprocessError):
            return _not_run(item, "cdp_capture_incomplete")
    configured = os.environ.get("G1_E5_CAPTURE_DIR")
    if not configured:
        return {
            "observation": _identity(item)
            | {
                "status": "BLOCKED_DEPENDENCY",
                "blockedReason": "ui_capture_directory_not_configured",
            },
            "artifacts": {},
        }
    directory = Path(configured).resolve(strict=True)
    if directory == ROOT or ROOT in directory.parents:
        raise ValueError("capture_directory_must_be_outside_repository")
    commit = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
    if subprocess.check_output(["git", "status", "--porcelain"], cwd=ROOT, text=True).strip():
        return _not_run(item, "worktree_not_clean")
    run_id = item["runId"]
    request_file = directory / f"request-{run_id}.json"
    result_file = directory / f"result-{run_id}.json"
    request_file.write_text(json.dumps(item, ensure_ascii=False), encoding="utf-8")
    timeout = min(160, max(0, int(os.environ.get("G1_E5_CAPTURE_TIMEOUT", "150"))))
    deadline = time.monotonic() + timeout
    while not result_file.is_file():
        if time.monotonic() >= deadline:
            return _not_run(item, "operator_ui_capture_missing")
        time.sleep(0.5)
    try:
        return bind(item, json.loads(result_file.read_text(encoding="utf-8")), directory, commit)
    except (KeyError, OSError, TypeError, ValueError, json.JSONDecodeError):
        return _not_run(item, "ui_capture_invalid_or_unmatched")


if __name__ == "__main__":
    if sys.argv[1:] == ["--serve-captured"]:
        run_captured_server()
    else:
        sys.stdin.reconfigure(encoding="utf-8")
        sys.stdout.reconfigure(encoding="utf-8")
        print(json.dumps(run(json.load(sys.stdin)), ensure_ascii=True))

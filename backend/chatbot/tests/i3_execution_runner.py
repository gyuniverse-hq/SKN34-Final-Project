"""Run pinned I-3 services in isolated test infrastructure; never generate predictions.

The caller must have existing #229 Python environments and local Docker images.
This tool starts its own run-labelled containers and only cleans up verified IDs.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import importlib.util
import json
import os
import socket
import subprocess
import sys
import time
from copy import deepcopy
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

EVAL_ROOT = Path(__file__).resolve().parents[3]
SUT_ROOT = Path(r"C:\Users\playdata2\.codex\worktrees\i3-service-sut\SKN34-Final-Project")
SUT_SHA = "5a112874578069dab10bd6eaebbbd50e54d71db2"
EVAL_SHA = "6acc98e434cb8800893f878fe3a2e061a94ee744"
ARTIFACTS = Path(
    r"C:\Users\playdata2\.codex\visualizations\2026\11\11\01a1c95a-645e-7e00-a435-7ab332cfafb4"
)
RAW = ARTIFACTS / "i3-service-observations.jsonl"
SCORED = ARTIFACTS / "i3-service-scoring.jsonl"
REPORT = ARTIFACTS / "i3-service-report.json"
MAPPING = ARTIFACTS / "i3-ingredient-mapping.json"
COMPOSE = EVAL_ROOT / "infra/compose/i3-evaluation.yml"
SEED = EVAL_ROOT / "backend/api/tests/i3_execution_seed.py"
OBSERVER = EVAL_ROOT / "backend/chatbot/tests/i3_execution_observer.py"
PLANS = EVAL_ROOT / "docs/ai-alignment/04_i3_eval/i3_execution_plans.json"
API_PY = Path(r"D:\dev\02_TeamProjects\SKN34-Final-Project\backend\api\.venv\Scripts\python.exe")
CHAT_PY = Path(
    r"D:\dev\02_TeamProjects\SKN34-Final-Project\backend\chatbot\.venv\Scripts\python.exe"
)


def command(args, *, env=None, cwd=None, timeout=120):
    result = subprocess.run(
        [str(x) for x in args],
        env=env,
        cwd=cwd,
        text=True,
        capture_output=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
    )
    if result.returncode:
        raise RuntimeError(
            f"{Path(str(args[0])).name} failed ({result.returncode}): {result.stderr[-1200:]}"
        )
    return result.stdout.strip()


def digest(value):
    return hashlib.sha256(
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def parse_chat_response(response):
    """Preserve malformed JSON values; hash non-JSON bytes without leaking content."""
    try:
        return response.json(), None
    except ValueError:
        return None, hashlib.sha256(response.content).hexdigest()


def load_observer():
    spec = importlib.util.spec_from_file_location("i3_execution_observer", OBSERVER)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def check_commits():
    actual = command(["git", "-C", SUT_ROOT, "rev-parse", "HEAD"])
    if actual != SUT_SHA:
        raise RuntimeError("SUT checkout differs from pinned #229 commit")
    if command(["git", "-C", SUT_ROOT, "status", "--porcelain", "--untracked-files=no"]):
        raise RuntimeError("SUT tracked files are modified")
    command([
        "git", "-C", EVAL_ROOT, "diff", "--quiet", EVAL_SHA, "--",
        "backend/chatbot/tests/i3_eval_adapter.py",
        "backend/chatbot/tests/run_i3_eval.py",
    ])
    for relative in (
        "docs/ai-alignment/04_i3_eval/cases.candidate.jsonl",
        "docs/ai-alignment/04_i3_eval/fixtures.synthetic.json",
    ):
        original = command(["git", "-C", EVAL_ROOT, "show", f"{EVAL_SHA}:{relative}"])
        if original.splitlines() != (EVAL_ROOT / relative).read_text(encoding="utf-8").splitlines():
            raise RuntimeError(f"Pinned #230 evaluation data changed: {relative}")
    for rel in ("backend/api/.env", "backend/chatbot/.env"):
        if (SUT_ROOT / rel).exists():
            raise RuntimeError("SUT worktree contains .env; refusing inherited credentials")
    if not API_PY.is_file() or not CHAT_PY.is_file():
        raise RuntimeError("Existing isolated Python environments unavailable")


def docker(args, env=None):
    return command(["docker", *args], env=env, timeout=120)


def project_objects(project):
    value = docker(
        ["ps", "--no-trunc", "-aq", "--filter", f"label=com.docker.compose.project={project}"]
    )
    return [x for x in value.splitlines() if x]


def inspect(container):
    result = json.loads(docker(["inspect", container]))
    if len(result) != 1 or result[0]["Id"] != container:
        raise RuntimeError("Container ID cannot be verified")
    return result[0]


def verify_container(container, project, run_id, service, expected_image, expected_port):
    item = inspect(container)
    labels = item["Config"].get("Labels") or {}
    if (
        labels.get("com.docker.compose.project") != project
        or labels.get("com.docker.compose.service") != service
        or labels.get("io.vishue.i3-eval.run-id") != run_id
        or labels.get("io.vishue.i3-eval.purpose") != "synthetic-only"
        or item["Config"]["Image"] != expected_image
    ):
        raise RuntimeError("Container identity mismatch; refusing access")
    ports = item["NetworkSettings"]["Ports"].get(f"{expected_port}/tcp")
    if not isinstance(ports, list) or len(ports) != 1 or ports[0]["HostIp"] != "127.0.0.1":
        raise RuntimeError("Container is not exclusively loopback-bound")
    host_port = int(ports[0]["HostPort"])
    if not 1 <= host_port <= 65535:
        raise RuntimeError("Invalid container port")
    return host_port


def unique_environment():
    # Do not use an explicit remote daemon or context. Verify the selected endpoint too.
    if os.environ.get("DOCKER_HOST") or os.environ.get("DOCKER_CONTEXT"):
        raise RuntimeError("Explicit Docker host/context is not allowed")
    contexts = json.loads(docker(["context", "inspect"]))
    if len(contexts) != 1:
        raise RuntimeError("Docker context is ambiguous")
    endpoint = contexts[0].get("Endpoints", {}).get("docker", {}).get("Host", "")
    if not endpoint.lower().startswith("npipe:////./pipe/"):
        raise RuntimeError("Docker endpoint is not a local Windows named pipe")
    run_id = uuid4().hex
    project = "i3-eval-" + run_id
    env = os.environ.copy()
    env["I3_EVAL_RUN_ID"] = run_id
    if project_objects(project):
        raise RuntimeError("Compose project already has containers")
    for kind in ("network", "volume"):
        objects = docker(
            [kind, "ls", "-q", "--filter", f"label=com.docker.compose.project={project}"]
        )
        if objects:
            raise RuntimeError("Compose project already has network/volume objects")
    return run_id, project, env


def cleanup(project, run_id, known_ids):
    # Never select a target by name/pattern alone; re-read exact IDs and labels first.
    for cid in known_ids:
        item = inspect(cid)
        labels = item["Config"].get("Labels") or {}
        if (
            labels.get("com.docker.compose.project") != project
            or labels.get("io.vishue.i3-eval.run-id") != run_id
        ):
            raise RuntimeError("Cleanup identity changed; no container deletion performed")
    if known_ids:
        docker(["rm", "-f", *known_ids])
    networks = docker(
        [
            "network",
            "ls",
            "--no-trunc",
            "-q",
            "--filter",
            f"label=com.docker.compose.project={project}",
        ]
    )
    for nid in networks.splitlines():
        data = json.loads(docker(["network", "inspect", nid]))[0]
        if (
            data.get("Id") != nid
            or (data.get("Labels") or {}).get("com.docker.compose.project") != project
            or data.get("Containers")
        ):
            raise RuntimeError("Network identity/occupancy changed; network retained")
        docker(["network", "rm", nid])


def start_environment():
    run_id, project, env = unique_environment()
    ids = []
    try:
        docker(
            ["compose", "-p", project, "-f", COMPOSE, "up", "-d", "--no-build", "--pull", "never"],
            env,
        )
        ids = project_objects(project)
        if len(ids) != 2:
            raise RuntimeError("Expected exactly two isolated containers")
        items = [inspect(i) for i in ids]
        by_service = {
            (x["Config"].get("Labels") or {}).get("com.docker.compose.service"): x["Id"]
            for x in items
        }
        if set(by_service) != {"postgres", "redis"}:
            raise RuntimeError("Unexpected isolated service set")
        pg = verify_container(
            by_service["postgres"], project, run_id, "postgres", "postgres:17-alpine", 5432
        )
        redis = verify_container(
            by_service["redis"], project, run_id, "redis", "redis:7-alpine", 6379
        )
        deadline = time.monotonic() + 75
        while time.monotonic() < deadline:
            if all(
                inspect(cid).get("State", {}).get("Health", {}).get("Status") == "healthy"
                for cid in ids
            ):
                break
            time.sleep(0.5)
        else:
            raise RuntimeError("Isolated containers failed health checks")
        return run_id, project, env, ids, by_service, pg, redis
    except Exception as primary:
        # Preserve the actual setup failure even if cleanup is also unavailable.
        try:
            ids = ids or project_objects(project)
            cleanup(project, run_id, ids)
        except Exception as cleanup_error:
            raise RuntimeError(
                f"setup failed ({type(primary).__name__}: {primary}); "
                f"cleanup failed ({type(cleanup_error).__name__}: {cleanup_error})"
            ) from primary
        raise


def verify_connections(pg_port, redis_port, run_id, container_ids):
    db_url = f"postgresql+asyncpg://i3_eval:i3_eval@127.0.0.1:{pg_port}/i3_eval"
    # Read both the TCP server and the exact labelled Docker container before any write.
    pgcheck = "\n".join(
        [
            "import asyncio,asyncpg,sys",
            "async def run():",
            " c=await asyncpg.connect(sys.argv[1])",
            ' r=await c.fetchrow("SELECT current_database(),current_user,"',
            "                  \"current_setting('i3_eval.run_id',true)\")",
            " print('|'.join(str(x) for x in r))",
            " await c.close()",
            "asyncio.run(run())",
        ]
    )
    seen = command(
        [API_PY, "-B", "-c", pgcheck, db_url.replace("postgresql+asyncpg:", "postgresql:")],
        cwd=SUT_ROOT / "backend/api",
        env=sanitized_environment(db_url, redis_port),
    )
    if seen != "i3_eval|i3_eval|" + run_id:
        raise RuntimeError("PostgreSQL TCP identity mismatch")
    docker_pg = docker(
        [
            "exec",
            container_ids["postgres"],
            "psql",
            "-U",
            "i3_eval",
            "-d",
            "i3_eval",
            "-Atc",
            "SELECT current_setting('i3_eval.run_id',true)",
        ]
    )
    if docker_pg != run_id:
        raise RuntimeError("PostgreSQL container identity mismatch")
    redischeck = "\n".join(
        [
            "import redis,sys",
            "r=redis.Redis(host='127.0.0.1',port=int(sys.argv[1]),decode_responses=True)",
            "print(r.info('server')['run_id'])",
        ]
    )
    tcp_id = command(
        [CHAT_PY, "-B", "-c", redischeck, str(redis_port)],
        cwd=SUT_ROOT / "backend/chatbot",
        env=sanitized_environment(db_url, redis_port),
    )
    info = docker(["exec", container_ids["redis"], "redis-cli", "INFO", "server"])
    ids = [s.split(":", 1)[1].strip() for s in info.splitlines() if s.startswith("run_id:")]
    if len(ids) != 1 or ids[0] != tcp_id:
        raise RuntimeError("Redis TCP and labelled container differ")
    return db_url


def sanitized_environment(database_url, redis_port):
    allowed = {"PATH", "SYSTEMROOT", "WINDIR", "TEMP", "TMP", "PATHEXT", "COMSPEC"}
    env = {key: value for key, value in os.environ.items() if key.upper() in allowed}
    env.update(
        {
            "ENV": "local",
            "PYTHONDONTWRITEBYTECODE": "1",
            "DATABASE_URL": database_url,
            "REDIS_URL": f"redis://127.0.0.1:{redis_port}/0",
            "INGREDIENT_MAPPING_PATH": str(MAPPING),
            "SKINCARE_REFRESH_ENABLED": "false",
            "LLM_API_KEY": "",
            "LLM_MODEL": "",
            "LLM_BASE_URL": "http://127.0.0.1:1",
            "CHAT_REQUESTS_PER_MINUTE": "1000",
        }
    )
    return env


def seed_environment(run_id, scenario, pg_port, redis_port, container_ids):
    url = verify_connections(pg_port, redis_port, run_id, container_ids)
    env = sanitized_environment(url, redis_port)
    env["PYTHONPATH"] = str(SUT_ROOT / "backend/api")
    command(
        [API_PY, "-B", "-m", "alembic", "upgrade", "head"],
        env=env,
        cwd=SUT_ROOT / "backend/api",
        timeout=180,
    )
    output = command(
        [
            API_PY,
            "-B",
            SEED,
            "--database-url",
            url,
            "--isolation-token",
            run_id,
            "--mapping-path",
            MAPPING,
            "--scenario",
            scenario,
            "--manifest",
        ],
        env=env,
        cwd=SUT_ROOT / "backend/api",
        timeout=120,
    )
    manifest = json.loads(output.splitlines()[-1])
    if manifest.get("synthetic") is not True or manifest.get("scenario") != scenario:
        raise RuntimeError("Seed manifest provenance mismatch")
    return env, manifest


def allocate_socket():
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.bind(("127.0.0.1", 0))
    sock.listen(128)
    sock.set_inheritable(False)
    return sock


def api_worker():
    # This process is always started in the pinned API working directory.
    sys.path.insert(0, str(SUT_ROOT / "backend/api"))
    import uvicorn
    from app.core.db import get_session
    from app.repositories.claim_publication_repository import ClaimPublicationRepository
    from app.services.claim_publication_service import (
        ClaimPublicationService,
        get_claim_publication_service,
    )
    from fastapi import Depends, Request
    from fastapi.responses import JSONResponse
    from sqlalchemy.ext.asyncio import AsyncSession

    from app.main import create_app

    if os.environ.get("I3_ISOLATED_TEST_API") != "yes":
        raise RuntimeError("Test-only API override requires explicit isolated mode")
    import re
    from urllib.parse import urlsplit

    import asyncpg

    run_id = os.environ.get("I3_RUN_ID", "")
    database_url = os.environ.get("DATABASE_URL", "")
    target = urlsplit(database_url)
    if (
        not re.fullmatch(r"[a-f0-9]{32}", run_id)
        or target.hostname != "127.0.0.1"
        or target.username != "i3_eval"
        or target.path != "/i3_eval"
        or not target.port
    ):
        raise RuntimeError("Test API DB target is not isolated")

    async def check_marker():
        conn = await asyncpg.connect(database_url.replace("postgresql+asyncpg:", "postgresql:"))
        try:
            return await conn.fetchrow(
                "SELECT current_database(),current_user,current_setting('i3_eval.run_id',true)"
            )
        finally:
            await conn.close()

    if list(asyncio.run(check_marker())) != ["i3_eval", "i3_eval", run_id]:
        raise RuntimeError("Test API DB server marker mismatch")

    class TestClaims(ClaimPublicationService):
        async def search(self, request):
            return await self._search(request, allow_test=True)

    async def test_claims(session: AsyncSession = Depends(get_session)):
        return TestClaims(ClaimPublicationRepository(session))

    app = create_app()
    app.dependency_overrides[get_claim_publication_service] = test_claims
    if os.environ.get("I3_FAULT_CLAIMS") == "503":

        @app.middleware("http")
        async def fault_claims(request: Request, call_next):
            if request.url.path == "/api/catalog/ingredient-claims/search":
                return JSONResponse(
                    {"error": "Synthetic injected claim outage", "code": "fixture_outage"},
                    status_code=503,
                )
            return await call_next(request)

    uvicorn.run(
        app,
        host="127.0.0.1",
        port=int(os.environ["I3_API_PORT"]),
        lifespan="off",
        access_log=False,
        log_level="warning",
    )


def wait_api(port, process):
    import httpx

    deadline = time.monotonic() + 45
    with httpx.Client(timeout=1, trust_env=False) as client:
        while time.monotonic() < deadline:
            if process.poll() is not None:
                raise RuntimeError(f"API exited during startup ({process.returncode})")
            try:
                if client.get(f"http://127.0.0.1:{port}/healthz").status_code < 500:
                    return
            except httpx.HTTPError:
                pass
            time.sleep(0.2)
    raise RuntimeError("Isolated API startup timeout")


def transformed(value, reverse):
    # Exact, previously-declared identifiers only; no answer/oracle enrichment.
    if isinstance(value, dict):
        return {reverse.get(k, k): transformed(v, reverse) for k, v in value.items()}
    if isinstance(value, list):
        return [transformed(v, reverse) for v in value]
    if isinstance(value, str):
        return reverse.get(value, value)
    return value


async def execute_chat(case, plans, api_port, redis_port, run_id, manifest, scenario, bootstrap):
    sys.path.insert(0, str(SUT_ROOT / "backend/chatbot"))
    import httpx
    import uvicorn
    from redis.asyncio import Redis

    from app.clients.catalog_client import CatalogClient
    from app.core.ratelimit import MemoryRateLimiter, get_rate_limiter
    from app.main import create_app
    from app.repositories.chat_session_repository import ChatSessionRepository
    from app.services.chat_service import ChatService, get_chat_service

    observer = load_observer()

    class TestInterpreter:
        configured = True

        def __init__(self):
            self.plan = None
            self.observed_prompt_hash = None

        async def complete(self, messages):
            self.observed_prompt_hash = digest(messages)
            return json.dumps(self.plan, ensure_ascii=False)

    llm = TestInterpreter()
    redis = Redis.from_url(f"redis://127.0.0.1:{redis_port}/0")
    service = ChatService(
        None,
        llm,
        CatalogClient(f"http://127.0.0.1:{api_port}"),
        sessions=ChatSessionRepository(redis),
    )
    app = create_app()
    app.dependency_overrides[get_chat_service] = lambda: service
    app.dependency_overrides[get_rate_limiter] = lambda: MemoryRateLimiter(1000)
    sock = allocate_socket()
    port = sock.getsockname()[1]
    server = uvicorn.Server(
        uvicorn.Config(
            app, host="127.0.0.1", port=port, lifespan="off", access_log=False, log_level="warning"
        )
    )
    task = asyncio.create_task(server.serve(sockets=[sock]))
    anonymous = "fixture-i3-" + run_id
    owner = "guest:" + hashlib.sha256(anonymous.encode("ascii")).hexdigest()
    records, previous, prior_request, prior_response = [], None, None, None
    bootstrap_record = None
    try:
        deadline = time.monotonic() + 30
        while not server.started:
            if task.done() or time.monotonic() >= deadline:
                raise RuntimeError("Chat server failed to start")
            await asyncio.sleep(0.1)
        async with httpx.AsyncClient(
            base_url=f"http://127.0.0.1:{port}",
            timeout=45,
            trust_env=False,
            headers={"X-Vishue-Anonymous-Id": anonymous},
        ) as client:
            if bootstrap:
                llm.plan = bootstrap["plan"]
                prep = {
                    "message": bootstrap["message"],
                    "locale": "ko",
                    "requestType": "beauty_consultation",
                    "requestId": str(uuid4()),
                }
                prep_before = await observer.snapshot_session(
                    redis, owner=owner, request_id=prep["requestId"], fresh=True
                )
                with observer.ObservationCapture(f"http://127.0.0.1:{api_port}") as captured:
                    prep_response = await client.post("/api/chat", json=prep)
                prep_body = prep_response.json()
                context = prep_body.get("chatContext") or {}
                session = context.get("session") or {}
                prep_after = await observer.snapshot_session(
                    redis,
                    owner=owner,
                    request_id=prep["requestId"],
                    session_id=session.get("sessionId"),
                    fresh=not session,
                )
                bootstrap_record = {
                    "request": observer.redact(prep),
                    "httpStatus": prep_response.status_code,
                    "response": observer.redact(prep_body),
                    "trace": observer.redact(captured.trace),
                    "stateBefore": prep_before,
                    "stateAfter": prep_after,
                }
                if (
                    prep_response.status_code == 200
                    and len(context.get("candidateIds", [])) == 2
                    and session
                ):
                    previous = context
                else:
                    return [], bootstrap_record
            for index, turn in enumerate(case.turns):
                if index >= len(plans):
                    break
                if (index or bootstrap) and not previous:
                    break  # No session capability: cannot construct an observed follow-up.
                llm.plan = plans[index]
                llm.observed_prompt_hash = None
                request = deepcopy(turn.request)
                request["requestId"] = str(uuid4())
                if previous:
                    request["chatContext"] = deepcopy(previous)
                if turn.replayOfTurn:
                    if prior_request is None:
                        break
                    request = deepcopy(prior_request)
                if scenario == "M01" and index == 1 and request.get("chatContext"):
                    request["chatContext"]["candidateIds"].reverse()
                session = (request.get("chatContext") or {}).get("session") or {}
                before = await observer.snapshot_session(
                    redis,
                    owner=owner,
                    request_id=request["requestId"],
                    session_id=session.get("sessionId"),
                    fresh=not session,
                )
                with observer.ObservationCapture(f"http://127.0.0.1:{api_port}") as capture:
                    response = await client.post("/api/chat", json=request)
                body, non_json_hash = parse_chat_response(response)
                if non_json_hash is not None:
                    capture.trace["nonJsonResponseSha256"] = non_json_hash
                body_object = body if isinstance(body, dict) else {}
                response_context = body_object.get("chatContext")
                response_context = response_context if isinstance(response_context, dict) else {}
                response_session = response_context.get("session")
                response_session = response_session if isinstance(response_session, dict) else {}
                after = await observer.snapshot_session(
                    redis,
                    owner=owner,
                    request_id=request["requestId"],
                    session_id=response_session.get("sessionId") or session.get("sessionId"),
                    fresh=not (response_session or session),
                )
                trace = capture.trace
                if llm.observed_prompt_hash is not None:
                    trace["observedPromptHash"] = llm.observed_prompt_hash
                if turn.replayOfTurn and prior_response is not None:
                    trace["priorResponse"] = observer.redact(prior_response)
                record = {
                    "recordType": "observation",
                    "runId": run_id,
                    "caseId": case.caseId,
                    "turn": turn.turn,
                    "repeat": 1,
                    "provenance": {
                        "mode": "synthetic_contract",
                        "planner": "fixture",
                        "dataKind": "synthetic",
                        "sutCommit": SUT_SHA,
                        "model": "controlled-plan-test-double",
                        "promptHash": digest(plans),
                        "fixtureHash": manifest["fixtureHash"],
                        "dataSnapshotHash": manifest["dataSnapshotHash"],
                        "dictionaryHash": manifest["dictionaryHash"],
                        "executionRef": "isolated:" + run_id,
                        "executedAt": datetime.now(UTC).isoformat(),
                        "settings": {
                            "catalog": "real-http",
                            "chat": "real-http",
                            "postgres": "real-isolated",
                            "redis": "real-isolated",
                            "testOnlyPublicationOverride": True,
                            "fault": "claim-http-503" if scenario == "E06" else "none",
                            "mappingVersion": "seed-manifest-v1",
                            "promptHashBasis": "controlled-plan-digest-not-runtime-prompt",
                            "dataSnapshotHashBasis": "seed-input-manifest-not-database-readback",
                            "publicationIdInjectedAtCreation": manifest.get(
                                "publicationIdInjectedAtCreation", False
                            ),
                        },
                    },
                    "request": observer.redact(request),
                    "httpStatus": response.status_code,
                    "response": observer.redact(body),
                    "trace": observer.redact(trace),
                    "stateBefore": before,
                    "stateAfter": after,
                }
                records.append(record)
                if not turn.replayOfTurn:
                    prior_request, prior_response = deepcopy(request), deepcopy(body)
                previous = response_context if response.status_code == 200 else None
                if previous and not previous.get("session"):
                    previous = None
    except Exception as exc:
        if not records:
            raise
        bootstrap_record = {
            "priorBootstrap": bootstrap_record,
            "interruptedAfterObservedTurns": len(records),
            "error": type(exc).__name__ + ": " + str(exc),
        }
    finally:
        server.should_exit = True
        await asyncio.wait_for(task, timeout=15)
        await redis.aclose()
        sock.close()
    return records, bootstrap_record


async def run_scenario(case, plans, bootstrap):
    scenario = case.fixtureRef
    run_id, project, env, ids, containers, pg_port, redis_port = start_environment()
    process = None
    cleanup_errors = []
    try:
        env, manifest = seed_environment(run_id, scenario, pg_port, redis_port, containers)
        if manifest["fixtureHash"] != case.fixtureHash:
            raise RuntimeError("Seed fixture hash mismatch")
        sock = allocate_socket()
        api_port = sock.getsockname()[1]
        sock.close()
        env.update(
            {
                "I3_ISOLATED_TEST_API": "yes",
                "I3_RUN_ID": run_id,
                "I3_API_PORT": str(api_port),
                "I3_FAULT_CLAIMS": "503" if scenario == "E06" else "none",
            }
        )
        process = await asyncio.to_thread(
            subprocess.Popen,
            [str(API_PY), "-B", str(Path(__file__)), "--internal-api"],
            cwd=SUT_ROOT / "backend/api",
            env=env,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        wait_api(api_port, process)
        old_env = os.environ.copy()
        os.environ.clear()
        os.environ.update(env)
        try:
            raw, bootstrap_record = await execute_chat(
                case, plans, api_port, redis_port, run_id, manifest, scenario, bootstrap
            )
        finally:
            os.environ.clear()
            os.environ.update(old_env)
        physical = {**manifest["logicalToPhysicalProduct"], **manifest["logicalToPhysicalOption"]}
        if len(set(physical.values())) != len(physical):
            raise RuntimeError("Synthetic ID mapping is not one-to-one")
        reverse = {v: k for k, v in physical.items()}
        mapped = [transformed(r, reverse) for r in raw]
        return (
            raw,
            mapped,
            {
                "idMapping": physical,
                "manifest": manifest,
                "bootstrap": bootstrap_record,
                "cleanupErrors": cleanup_errors,
                "containerIds": ids,
                "instrumentation": (
                    "real HTTP, real isolated Catalog/Postgres/Redis; "
                    "test interpreter and test-only claim override"
                ),
            },
        )
    finally:
        primary = sys.exc_info()[1]
        if process is not None:
            try:
                process.terminate()
                try:
                    process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=10)
            except Exception as process_error:
                cleanup_errors.append(type(process_error).__name__ + ": " + str(process_error))
        try:
            cleanup(project, run_id, ids)
        except Exception as cleanup_error:
            cleanup_errors.append(type(cleanup_error).__name__ + ": " + str(cleanup_error))
            if primary is not None:
                raise RuntimeError(
                    f"scenario failed ({type(primary).__name__}: {primary}); "
                    f"cleanup failed ({type(cleanup_error).__name__}: {cleanup_error})"
                ) from primary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--internal-api", action="store_true")
    parser.add_argument("--cases", default="all", help="all or comma-separated I3 case IDs")
    args = parser.parse_args()
    if args.internal_api:
        api_worker()
        return 0
    check_commits()
    # Evaluation package is loaded from #230, never SUT test helpers.
    sys.path.insert(0, str(EVAL_ROOT / "backend/chatbot"))
    from tests.run_i3_eval import grade, load_package

    cases = load_package()
    requested = (
        {c.caseId for c in cases}
        if args.cases == "all"
        else {x.strip() for x in args.cases.split(",")}
    )
    if not requested <= {c.caseId for c in cases}:
        raise ValueError("Unknown case ID")
    plan_data = json.loads(PLANS.read_text(encoding="utf-8"))
    if plan_data.get("planner") != "test_double":
        raise ValueError("Only controlled test interpreter is allowed")
    raw, scored, outcomes = [], [], {}
    infrastructure_error = None
    for case in cases:
        if case.caseId not in requested:
            outcomes[case.caseId] = {"status": "BLOCKED", "reason": "not_selected"}
            continue
        if case.caseId == "I3-M02":
            outcomes[case.caseId] = {
                "status": "BLOCKED",
                "reason": "current_stock_fixture_not_supported",
            }
            continue
        if infrastructure_error:
            outcomes[case.caseId] = {"status": "BLOCKED", "reason": infrastructure_error}
            continue
        plans = plan_data["cases"].get(case.caseId)
        if not plans:
            outcomes[case.caseId] = {"status": "BLOCKED", "reason": "no_independent_fixture_plan"}
            continue
        bootstrap = plan_data.get("bootstraps", {}).get(case.caseId)
        if case.fixtureRef.startswith("I") and not bootstrap:
            outcomes[case.caseId] = {
                "status": "BLOCKED",
                "reason": "preexisting_session_seed_not_implemented",
            }
            continue
        try:
            rr, ss, details = asyncio.run(run_scenario(case, plans, bootstrap))
            raw.extend(rr)
            scored.extend(ss)
            if details.get("cleanupErrors"):
                infrastructure_error = "prior_isolated_cleanup_failed"
            outcomes[case.caseId] = {
                "status": "EXECUTED" if rr else "BLOCKED",
                "reason": None if rr else "bootstrap_did_not_create_two_candidate_session",
                "observedTurns": len(rr),
                "details": details,
            }
        except Exception as exc:
            reason = type(exc).__name__ + ": " + str(exc)
            outcomes[case.caseId] = {"status": "BLOCKED", "reason": reason}
            if "read-only file system" in reason.lower() or "timed out" in reason.lower():
                infrastructure_error = "docker_unavailable_after_prior_failure"
    grading = grade(cases, scored, "synthetic_contract", 1)
    report = {
        "mode": "synthetic_contract",
        "sutCommit": SUT_SHA,
        "evaluationCommit": EVAL_SHA,
        "planner": "test_double",
        "actualLlmCalled": False,
        "goldApproved": 0,
        "executedScenarios": sum(x["status"] == "EXECUTED" for x in outcomes.values()),
        "executedTurns": len(raw),
        "outcomes": outcomes,
        "grading": grading,
    }
    RAW.write_text("".join(json.dumps(x, ensure_ascii=False) + "\n" for x in raw), encoding="utf-8")
    SCORED.write_text(
        "".join(json.dumps(x, ensure_ascii=False) + "\n" for x in scored), encoding="utf-8"
    )
    REPORT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(
        json.dumps(
            {
                "executedScenarios": report["executedScenarios"],
                "executedTurns": len(raw),
                "scenarioStatusCounts": grading["scenarioStatusCounts"],
                "turnStatusCounts": grading["statusCounts"],
                "actualLlmCalled": False,
                "goldApproved": 0,
            }
        )
    )
    if grading["statusCounts"].get("FAIL"):
        return 1
    if any(item["status"] != "PASS" for item in grading["results"]):
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

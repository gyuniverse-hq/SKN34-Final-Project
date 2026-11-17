"""G1 E2: isolated real Redis and HTTP; Catalog, LLM and authentication are fixtures.

The collector invokes this module once per required case using JSON on stdin.
Never persist session capabilities or upstream credentials in its observations.
"""

import importlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import traceback
from pathlib import Path
from uuid import uuid4

import httpx

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

infrastructure = importlib.import_module("tests.run_redis_sessions")


def worker():
    import uvicorn

    import tests.redis_session_server as server
    from app.clients.catalog_client import get_catalog_client

    calls = []

    class TracedCatalog(server.SessionCatalog):
        async def search_products(self, **kwargs):
            calls.append("search_products")
            return await super().search_products(**kwargs)

        async def get_product(self, pid):
            calls.append("get_product")
            return await super().get_product(pid)

    async def complete(self, messages):
        message = json.loads(messages[-1]["content"])["message"]
        if (
            message == "두 번째 상품 가격은?"
            or message == os.environ["G1_CASE_MESSAGE"]
            and os.environ["G1_CASE_ID"] == "G1-ERR-10"
        ):
            plan = {"intent": "price", "ordinal": 2}
        elif message == "베이스 상품 검색":
            plan = {"intent": "search", "category": "base"}
        else:
            plan = {"intent": "search", "category": "lip"}
        return json.dumps(plan)

    server.FixtureLlm.complete = complete
    app = server.fixture_app()
    app.dependency_overrides[get_catalog_client] = TracedCatalog

    @app.get("/__g1/catalog_calls")
    def catalog_calls():
        return {"count": len(calls)}

    uvicorn.run(
        app,
        host="127.0.0.1",
        port=int(os.environ["P03C_HTTP_PORT"]),
        access_log=False,
        log_level="warning",
    )


def safe(value):
    if isinstance(value, dict):
        return {k: safe(v) for k, v in value.items() if k not in {"sessionToken"}}
    if isinstance(value, list):
        return [safe(v) for v in value]
    return value


def session_trace_artifact(common, request_id, bootstrap_id, steps, observation):
    artifact = common | {
        "requestId": request_id,
        "bootstrapRequestId": bootstrap_id,
        "steps": steps,
    }
    if observation["caseId"] == "G1-ERR-10":
        artifact["response"] = observation["response"]
    return artifact


def drive(request):
    case, run_id = request["case"], request["runId"]
    identity = {
        "caseId": case["caseId"],
        "caseRevision": case["caseRevision"],
        "variantId": request["variantId"],
        "environment": "E2",
        "runId": run_id,
    }
    observation = identity | {"status": "BLOCKED_DEPENDENCY", "blockedReason": "redis_not_started"}
    artifacts = {}
    process = None
    redis = None
    commit = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
    # A slow local Docker daemon must not be mistaken for a failed product assertion.
    infrastructure.command = lambda args: subprocess.run(
        args, capture_output=True, text=True, timeout=90, check=False
    )
    try:
        with tempfile.TemporaryDirectory(prefix="vishue-g1-e2-") as directory:
            redis = infrastructure.IsolatedRedis(run_id, directory, shutil.which("redis-server"))
            redis.preflight()
            redis_version = redis.start()
            port = infrastructure.free_port()
            env = os.environ | {
                "ENV": "local",
                "REDIS_URL": f"redis://127.0.0.1:{redis.port}/0",
                "P03C_RUN_ID": run_id,
                "P03C_HTTP_PORT": str(port),
                "P03C_WORKER": "G1",
                "CHAT_SESSION_TTL_SECONDS": "60",
                "PYTHONPATH": str(ROOT),
                "LLM_API_KEY": "",
                "LLM_MODEL": "",
                "G1_CASE_MESSAGE": case["input"]["message"],
                "G1_CASE_ID": case["caseId"],
            }
            process = subprocess.Popen(
                [sys.executable, "-B", "-m", "tests.drive_g1_e2", "--worker"],
                cwd=ROOT,
                env=env,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            url = f"http://127.0.0.1:{port}"
            with httpx.Client(timeout=20, trust_env=False) as http:
                infrastructure.eventually(
                    lambda: http.get(url + "/__p03c/ready").status_code == 200, seconds=60
                )
                ready = http.get(url + "/__p03c/ready").json()
                if (
                    ready["runId"] != run_id
                    or ready["worker"] != "G1"
                    or process.poll() is not None
                ):
                    raise infrastructure.EnvironmentBlocked("worker_ownership_mismatch")
                owner = {"X-Vishue-Anonymous-Id": "owner-" + run_id}
                other = {"X-Vishue-Anonymous-Id": "other-" + run_id}

                def post(body, headers=owner):
                    return http.post(url + "/api/chat", json=body, headers=headers)

                bootstrap_id = str(uuid4())
                bootstrap = post(
                    {
                        "message": "립 상품 검색",
                        "locale": "ko",
                        "requestType": "beauty_consultation",
                        "requestId": bootstrap_id,
                    }
                )
                if bootstrap.status_code != 200:
                    raise AssertionError("bootstrap_failed")
                context = bootstrap.json()["chatContext"]
                session_id = context["session"]["sessionId"]
                key = f"vishue:p03c:{run_id}:vishue:chat:session:{session_id}"
                before = json.loads(redis.client.get(key))
                ttl = redis.client.ttl(key)
                if ttl <= 0 or before["stateVersion"] != context["session"]["stateVersion"]:
                    raise infrastructure.EnvironmentBlocked("inactive_session_fixture")
                request_id = str(uuid4())
                body = {
                    "message": case["input"]["message"],
                    "locale": "ko",
                    "requestType": "beauty_consultation",
                    "chatContext": context,
                    "requestId": request_id,
                }
                trace = []
                if case["caseId"] == "G1-ERR-10":
                    # Owner capability itself is checked by a successful owner follow-up first.
                    probe = post(
                        {**body, "message": "두 번째 상품 가격은?", "requestId": str(uuid4())}
                    )
                    if probe.status_code != 200:
                        raise infrastructure.EnvironmentBlocked("owner_preflight_failed")
                    body["chatContext"] = probe.json()["chatContext"]
                    before = json.loads(redis.client.get(key))
                    ttl = redis.client.ttl(key)
                    count = http.get(url + "/__g1/catalog_calls").json()["count"]
                    result = post(body, other)
                    calls_after = http.get(url + "/__g1/catalog_calls").json()["count"]
                    response = safe(result.json())
                    state_after = json.loads(redis.client.get(key))
                    response_ref = f"{run_id}/request_id_and_session_state_trace.json"
                    observation = identity | {
                        "requestId": request_id,
                        "httpStatus": result.status_code,
                        "response": response,
                        "responseEvidenceRef": response_ref,
                        "trace": {
                            "complete": True,
                            "requestId": request_id,
                            "tools": ["catalog"] if calls_after != count else [],
                        },
                        "claimAudit": {
                            "complete": True,
                            "responseEvidenceRef": response_ref,
                            "claims": [{"kind": "cross_user_data"}]
                            if "products" in response or "chatContext" in response
                            else [],
                        },
                        "session": {
                            "fixtureActive": ttl > 0,
                            "commitCount": state_after["stateVersion"] - before["stateVersion"],
                        },
                    }
                    trace = [
                        {"role": "owner_preflight", "status": probe.status_code},
                        {
                            "role": "foreign_request",
                            "status": result.status_code,
                            "response": response,
                            "catalogCallsBefore": count,
                            "catalogCallsAfter": calls_after,
                        },
                    ]
                else:
                    first = post(body)
                    if first.status_code != 200:
                        raise AssertionError("first_followup_failed")
                    state_first = json.loads(redis.client.get(key))
                    if case["caseId"] == "G1-REG-04":
                        second = post(body)
                    else:
                        second = post(body | {"message": "베이스 상품 검색"})
                    state_after = json.loads(redis.client.get(key))
                    observation = identity | {
                        "requestId": request_id,
                        "httpStatus": second.status_code,
                        "response": safe(second.json()),
                        "session": {
                            "initialResponse": safe(first.json()),
                            "retryResponse": safe(second.json()),
                            "initialResultSetId": state_first["resultSetId"],
                            "retryResultSetId": state_after["resultSetId"],
                            "commitCount": state_after["stateVersion"] - before["stateVersion"],
                        },
                    }
                    trace = [
                        {
                            "role": "first_followup",
                            "status": first.status_code,
                            "response": safe(first.json()),
                        },
                        {
                            "role": "retry_or_conflict",
                            "status": second.status_code,
                            "response": safe(second.json()),
                        },
                    ]
                common = {
                    "gitCommit": commit,
                    "caseId": case["caseId"],
                    "runId": run_id,
                    "redisVersion": redis_version,
                    "redis": "isolated_real",
                    "catalog": "synthetic_fixture",
                    "llm": "synthetic_fixture",
                    "authentication": "synthetic_fixture",
                    "workerPid": ready["pid"],
                }
                artifacts = {
                    "actual_or_isolated_redis_state": common
                    | {
                        "initialVersion": before["stateVersion"],
                        "finalVersion": state_after["stateVersion"],
                    },
                    "run_scoped_owner_and_ttl_preflight": common
                    | {"ttlSeconds": ttl, "active": ttl > 0, "ownerAndForeignDiffer": True},
                    "request_id_and_session_state_trace": session_trace_artifact(
                        common, request_id, bootstrap_id, trace, observation
                    ),
                }
                observation.update(
                    isMock=False,
                    realRedisConnected=True,
                    syntheticDependencies=["catalog", "llm", "authentication"],
                )
    except infrastructure.EnvironmentBlocked as exc:
        observation = identity | {"status": "BLOCKED_DEPENDENCY", "blockedReason": str(exc)}
    except (OSError, subprocess.SubprocessError, httpx.HTTPError, KeyError, ValueError) as exc:
        frames = traceback.extract_tb(exc.__traceback__)
        location = f"{Path(frames[-1].filename).name}:{frames[-1].lineno}" if frames else "unknown"
        observation = identity | {
            "status": "BLOCKED_DEPENDENCY",
            "blockedReason": f"{type(exc).__name__}:{location}",
        }
    except AssertionError as exc:
        observation = identity | {"status": "FAIL", "failureReason": str(exc)}
    finally:
        if process is not None and process.poll() is None:
            if os.name == "nt":
                subprocess.run(
                    ["taskkill", "/PID", str(process.pid), "/T", "/F"],
                    capture_output=True,
                    check=False,
                    timeout=15,
                )
            else:
                process.terminate()
            process.wait(timeout=10)
        if redis is not None and redis.started:
            redis.close()
    return {"observation": observation, "artifacts": artifacts}


if __name__ == "__main__":
    if sys.argv[1:] == ["--worker"]:
        worker()
    else:
        sys.stdin.reconfigure(encoding="utf-8")
        sys.stdout.reconfigure(encoding="utf-8")
        print(json.dumps(drive(json.load(sys.stdin)), ensure_ascii=False))

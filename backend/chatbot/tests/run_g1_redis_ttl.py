"""Measure actual Redis key expiry and the subsequent HTTP session response.

Uses only a run-owned ephemeral Redis; Catalog, LLM, and authentication are fixtures.
Session capabilities and Redis contents are never written to the report.
"""

import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from uuid import uuid4

import httpx

from tests import run_redis_sessions as infrastructure

ROOT = Path(__file__).resolve().parents[1]


def run():
    run_id = uuid4().hex
    report = {
        "runId": run_id,
        "status": "BLOCKED_DEPENDENCY",
        "redis": "isolated_real",
        "catalog": "synthetic_fixture",
        "llm": "synthetic_fixture",
        "authentication": "synthetic_fixture",
        "gitCommit": subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True
        ).strip(),
    }
    process = None
    redis = None
    infrastructure.command = lambda args: subprocess.run(
        args, capture_output=True, text=True, timeout=90, check=False
    )
    try:
        with tempfile.TemporaryDirectory(prefix="vishue-g1-ttl-") as directory:
            redis = infrastructure.IsolatedRedis(run_id, directory, shutil.which("redis-server"))
            redis.preflight()
            report["redisVersion"] = redis.start()
            report["realRedisConnected"] = True
            port = infrastructure.free_port()
            env = os.environ | {
                "ENV": "local",
                "REDIS_URL": f"redis://127.0.0.1:{redis.port}/0",
                "P03C_RUN_ID": run_id,
                "P03C_HTTP_PORT": str(port),
                "P03C_WORKER": "G1-TTL",
                "CHAT_SESSION_TTL_SECONDS": "8",
                "PYTHONPATH": str(ROOT),
                "LLM_API_KEY": "",
                "LLM_MODEL": "",
            }
            process = subprocess.Popen(
                [sys.executable, "-B", "-m", "tests.redis_session_server"],
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
                if ready["runId"] != run_id or ready["worker"] != "G1-TTL":
                    raise infrastructure.EnvironmentBlocked("worker_ownership_mismatch")
                report["workerPid"] = ready["pid"]
                headers = {"X-Vishue-Anonymous-Id": "ttl-owner-" + run_id}
                bootstrap = http.post(
                    url + "/api/chat",
                    headers=headers,
                    json={
                        "message": "립 상품 검색",
                        "locale": "ko",
                        "requestType": "beauty_consultation",
                        "requestId": str(uuid4()),
                    },
                )
                report["bootstrapStatus"] = bootstrap.status_code
                if bootstrap.status_code != 200:
                    report.update(status="FAIL", failureReason="bootstrap_failed")
                    return report
                context = bootstrap.json()["chatContext"]
                key = f"vishue:p03c:{run_id}:vishue:chat:session:{context['session']['sessionId']}"
                ttl_ms = redis.client.pttl(key)
                report["initialPttlMs"] = ttl_ms
                if ttl_ms <= 0:
                    report.update(status="FAIL", failureReason="missing_session_ttl")
                    return report
                time.sleep(ttl_ms / 1000 + 0.2)
                report["sessionKeyExpired"] = redis.client.get(key) is None
                response = http.post(
                    url + "/api/chat",
                    headers=headers,
                    json={
                        "message": "두 번째 상품 가격은?",
                        "locale": "ko",
                        "requestType": "beauty_consultation",
                        "requestId": str(uuid4()),
                        "chatContext": context,
                    },
                )
                report["expiredRequestStatus"] = response.status_code
                report["expiredRequestCode"] = response.json().get("code")
                report["status"] = (
                    "PASS"
                    if report["sessionKeyExpired"]
                    and report["expiredRequestStatus"] == 410
                    and report["expiredRequestCode"] == "chat_session_expired"
                    else "FAIL"
                )
    except infrastructure.EnvironmentBlocked as exc:
        report["blockedReason"] = str(exc)
    except (OSError, subprocess.SubprocessError, httpx.HTTPError, KeyError, ValueError) as exc:
        report["blockedReason"] = type(exc).__name__
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
        report["cleanup"] = True
    return report


if __name__ == "__main__":
    print(json.dumps(run(), ensure_ascii=True))

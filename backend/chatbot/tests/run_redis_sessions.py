"""Real Redis/TCP integration runner. Never pulls images, runs Compose or touches existing Redis.

Run from backend/chatbot: .venv/Scripts/python.exe -B -m tests.run_redis_sessions
An existing native executable can be selected with --redis-server ABSOLUTE_PATH.
Exit 0=passed, 1=failed, 2=environment blocked. No session tokens are printed.
"""

import argparse
import concurrent.futures
import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import time
from contextlib import ExitStack
from pathlib import Path
from uuid import uuid4

import httpx
from redis import Redis
from redis.exceptions import RedisError

ROOT = Path(__file__).resolve().parents[1]


class EnvironmentBlocked(Exception):
    pass


def command(args):
    return subprocess.run(args, capture_output=True, text=True, timeout=15, check=False)


def free_port():
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        return listener.getsockname()[1]


def container_snapshot():
    result = command(["docker", "ps", "-aq", "--no-trunc"])
    if result.returncode:
        raise EnvironmentBlocked("docker_inventory_unavailable")
    snapshot = {}
    for identifier in result.stdout.split():
        row = command(
            [
                "docker",
                "inspect",
                "--format",
                "{{json .Id}}|{{json .Image}}|{{json .State.Status}}|"
                "{{json .State.StartedAt}}|{{json .HostConfig.PortBindings}}|{{json .Mounts}}",
                identifier,
            ]
        )
        if row.returncode:
            raise EnvironmentBlocked("docker_inventory_changed")
        snapshot[identifier] = row.stdout.strip()
    return snapshot


def eventually(predicate, seconds=8):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        try:
            if predicate():
                return
        except (OSError, httpx.HTTPError, RedisError):
            pass
        time.sleep(0.05)
    raise AssertionError("Readiness condition timed out")


class IsolatedRedis:
    def __init__(self, run_id, directory, executable=None, image="redis:7-alpine"):
        self.run_id, self.directory, self.executable, self.image = (
            run_id,
            directory,
            executable,
            image,
        )
        self.port = free_port()
        self.name = f"vishue-p0-3c-redis-{run_id}"
        self.process = None
        self.client = Redis(
            host="127.0.0.1",
            port=self.port,
            decode_responses=True,
            socket_connect_timeout=1,
            socket_timeout=1,
        )
        self.started = False

    def preflight(self):
        with socket.socket() as listener:
            try:
                listener.bind(("127.0.0.1", self.port))
            except OSError as exc:
                raise EnvironmentBlocked("isolated_redis_port_in_use") from exc
        if self.executable:
            if not Path(self.executable).is_file():
                raise EnvironmentBlocked("redis_executable_missing")
            return
        if not shutil.which("docker"):
            raise EnvironmentBlocked("docker_cli_missing_and_no_native_redis")
        if command(["docker", "info", "--format", "{{.OSType}}"]).returncode:
            raise EnvironmentBlocked("docker_engine_unavailable")
        if command(["docker", "image", "inspect", self.image]).returncode:
            raise EnvironmentBlocked("local_redis_image_missing_no_pull_permitted")
        if command(["docker", "inspect", self.name]).returncode == 0:
            raise EnvironmentBlocked("test_container_name_already_exists")

    def owned_container(self):
        result = command(["docker", "inspect", self.name])
        if result.returncode:
            return False
        record = json.loads(result.stdout)[0]
        return record["Config"].get("Labels", {}).get("vishue.p03c.run") == self.run_id

    def start(self):
        options = [
            "--save",
            "",
            "--appendonly",
            "no",
            "--maxmemory",
            "64mb",
            "--maxmemory-policy",
            "noeviction",
            "--loglevel",
            "warning",
        ]
        if self.executable:
            self.process = subprocess.Popen(
                [self.executable, "--bind", "127.0.0.1", "--port", str(self.port), *options],
                cwd=self.directory,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
        else:
            self.started = True  # Clean up an owned container even if run fails after creation.
            result = command(
                [
                    "docker",
                    "run",
                    "--pull=never",
                    "-d",
                    "--name",
                    self.name,
                    "--label",
                    "vishue.p03c.run=" + self.run_id,
                    "--tmpfs",
                    "/data:rw,size=16m",
                    "-p",
                    f"127.0.0.1:{self.port}:6379",
                    self.image,
                    "redis-server",
                    *options,
                ]
            )
            if result.returncode:
                raise EnvironmentBlocked("isolated_redis_container_start_failed")
        self.started = True
        eventually(self.client.ping)
        info = self.client.info("server")
        if self.executable:
            if self.process.poll() is not None or int(info["process_id"]) != self.process.pid:
                raise AssertionError("Refusing to use an unowned Redis process")
        else:
            if not self.owned_container():
                raise AssertionError("Redis container ownership mismatch")
            inside = command(["docker", "exec", self.name, "redis-cli", "--raw", "INFO", "server"])
            if inside.returncode or f"run_id:{info['run_id']}" not in inside.stdout:
                raise AssertionError("Redis port ownership mismatch")
        return info["redis_version"]

    def stop(self):
        if self.executable and self.process and self.process.poll() is None:
            self.process.terminate()
            self.process.wait(timeout=5)
        elif not self.executable and self.owned_container():
            if command(["docker", "stop", "-t", "1", self.name]).returncode:
                raise AssertionError("Owned Redis stop failed")

    def restart(self):
        if self.executable:
            self.start()
        else:
            if not self.owned_container():
                raise AssertionError("Refusing to restart an unowned container")
            if command(["docker", "start", self.name]).returncode:
                raise AssertionError("Isolated Redis restart failed")
            eventually(self.client.ping)

    def close(self):
        try:
            self.stop()
        finally:
            if (
                not self.executable
                and shutil.which("docker")
                and self.owned_container()
                and command(["docker", "rm", "-v", self.name]).returncode
            ):
                raise AssertionError("Owned Redis removal failed")
            self.client.close()


def run(args):
    run_id = uuid4().hex
    prefix = f"vishue:p03c:{run_id}:"
    report = {
        "status": "blocked",
        "realRedisConnected": False,
        "realHttpProcesses": 0,
        "catalog": "fixture",
        "llm": "fixture",
        "authentication": "fixture",
        "cases": [],
        "cleanup": False,
    }
    processes, handles, tokens = [], [], set()
    baseline = None
    baseline_volumes = None
    with tempfile.TemporaryDirectory(prefix="vishue-p03c-") as directory, ExitStack() as stack:
        redis = IsolatedRedis(run_id, directory, args.redis_server, args.docker_image)
        http = httpx.Client(timeout=12, trust_env=False)
        try:
            redis.preflight()
            if not redis.executable:
                baseline = container_snapshot()
                baseline_volumes = command(["docker", "volume", "ls", "-q"]).stdout.split()
            report["redisVersion"] = redis.start()
            report["realRedisConnected"] = True
            urls = []
            worker_pids = []
            for label in ("A", "B"):
                port = free_port()
                log = stack.enter_context(
                    open(Path(directory) / f"worker-{label}.log", "w", encoding="utf-8")
                )
                handles.append(log)
                env = os.environ | {
                    "ENV": "local",
                    "REDIS_URL": f"redis://127.0.0.1:{redis.port}/0",
                    "P03C_RUN_ID": run_id,
                    "P03C_HTTP_PORT": str(port),
                    "P03C_WORKER": label,
                    "CHAT_SESSION_TTL_SECONDS": "8",
                    "PYTHONPATH": str(ROOT),
                    "LLM_API_KEY": "",
                    "LLM_MODEL": "",
                    "CATALOG_API_URL": "http://127.0.0.1:1",
                    "LLM_BASE_URL": "http://127.0.0.1:1",
                    "LOG_LEVEL": "INFO",
                }
                process = subprocess.Popen(
                    [sys.executable, "-B", "-m", "tests.redis_session_server"],
                    cwd=ROOT,
                    env=env,
                    stdout=log,
                    stderr=subprocess.STDOUT,
                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                )
                processes.append(process)
                url = f"http://127.0.0.1:{port}"
                eventually(lambda url=url: http.get(url + "/__p03c/ready").status_code == 200)
                ready = http.get(url + "/__p03c/ready").json()
                assert ready["runId"] == run_id and ready["worker"] == label
                worker_pids.append(ready["pid"])
                urls.append(url)
            if worker_pids[0] == worker_pids[1]:
                raise AssertionError("Two independent processes are required")
            report["realHttpProcesses"] = 2
            report["workerPids"] = worker_pids
            guest = {"X-Vishue-Anonymous-Id": "guest-" + run_id}
            other = {"X-Vishue-Anonymous-Id": "other-" + run_id}

            def payload(message="립 상품 검색", context=None):
                return {
                    "message": message,
                    "locale": "ko",
                    "requestType": "beauty_consultation",
                    "requestId": str(uuid4()),
                    **({"chatContext": context} if context else {}),
                }

            def post(worker, body, status=200, headers=None, code=None):
                response = http.post(
                    urls[worker] + "/api/chat",
                    json=body,
                    headers=headers if headers is not None else guest,
                )
                if response.status_code != status:
                    raise AssertionError(f"HTTP expected {status}, received {response.status_code}")
                data = response.json()
                if code and data.get("code") != code:
                    raise AssertionError("Unexpected public API error code")
                token = data.get("chatContext", {}).get("session", {}).get("sessionToken")
                if token:
                    tokens.add(token)
                return data

            def search(worker=0, headers=None):
                data = post(worker, payload(), headers=headers)
                if data.get("sessionStatus") != "stored":
                    raise AssertionError("Real Redis commit was not confirmed")
                return data["chatContext"]

            def case(name, test):
                try:
                    test()
                    report["cases"].append({"name": name, "status": "PASS"})
                except Exception as exc:
                    # Exception details/response bodies can include capabilities; never print them.
                    report["cases"].append(
                        {"name": name, "status": "FAIL", "errorType": type(exc).__name__}
                    )

            def cross_process():
                ctx = search()
                reply = post(1, payload("두 번째 상품 가격은?", ctx))
                assert reply["products"][0]["id"] == "b"
                assert reply["chatContext"]["candidateIds"] == ["a", "b"]
                assert reply["chatContext"]["session"]["stateVersion"] == 2

            case("A_search_B_second_product", cross_process)

            def shade():
                ctx = search()
                ctx["selectedProductId"], ctx["shadeSelections"] = "b", {"b": "b-03"}
                reply = post(1, payload("선택 상품 성분", ctx))
                assert reply["ingredientResults"][0]["shadeId"] == "b-03"
                assert reply["ingredientResults"][0]["synthetic"] is True
                follow = post(0, payload("선택 상품 가격", reply["chatContext"]))
                assert follow["products"][0]["id"] == "b"

            case("shade_selection_across_processes", shade)

            def retry():
                ctx = search()
                body = payload("두 번째 상품 가격은?", ctx)
                first = post(0, body)
                again = post(1, body)
                assert first == again and again["chatContext"]["session"]["stateVersion"] == 2

            case("same_UUID_no_duplicate_commit", retry)

            def concurrency(same_request=False):
                ctx = search()
                gate = str(uuid4())
                headers = guest | {"X-P03C-CAS": gate}
                first = payload("두 번째 상품 가격은?", ctx)
                second = first if same_request else payload("두 번째 상품 가격은?", ctx)
                before = int(redis.client.get(prefix + "watch-errors") or 0)
                with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
                    futures = [
                        pool.submit(http.post, urls[i] + "/api/chat", json=body, headers=headers)
                        for i, body in enumerate((first, second))
                    ]
                    responses = [f.result(timeout=12) for f in futures]
                expected = [200, 200] if same_request else [200, 409]
                assert sorted(r.status_code for r in responses) == expected
                assert int(redis.client.get(prefix + "watch-errors") or 0) > before
                report["watchConflictsObserved"] = report.get("watchConflictsObserved", 0) + (
                    int(redis.client.get(prefix + "watch-errors")) - before
                )
                state_key = prefix + "vishue:chat:session:" + ctx["session"]["sessionId"]
                state = json.loads(redis.client.get(state_key))
                assert state["stateVersion"] == 2
                if same_request:
                    assert responses[0].json() == responses[1].json()
                for response in responses:
                    if response.status_code == 200:
                        tokens.add(response.json()["chatContext"]["session"]["sessionToken"])

            case("actual_WATCH_conflict", concurrency)
            case("concurrent_identical_UUID_single_commit", lambda: concurrency(True))

            def stale():
                ctx = search()
                newer = post(1, payload("베이스 상품 검색", ctx))["chatContext"]
                assert newer["session"]["resultSetId"] != ctx["session"]["resultSetId"]
                post(0, payload("두 번째 상품 가격은?", ctx), 409, code="chat_session_conflict")

            case("old_result_set_rejected", stale)

            def expiry():
                ctx = search()
                key = prefix + "vishue:chat:session:" + ctx["session"]["sessionId"]
                assert 0 < redis.client.ttl(key) <= 8
                # SET EX starts at commit time; integer API timestamps can precede physical
                # key expiry by less than one second. Wait for the measured REAL Redis TTL.
                time.sleep(redis.client.pttl(key) / 1000 + 0.1)
                assert redis.client.get(key) is None
                post(1, payload("두 번째 상품 가격은?", ctx), 410, code="chat_session_expired")

            case("real_TTL_expiry_and_cleanup", expiry)

            def eviction():
                ctx = search()
                key = prefix + "vishue:chat:session:" + ctx["session"]["sessionId"]
                settings = redis.client.config_get("maxmemory*")
                before = redis.client.info("stats")["evicted_keys"]
                pressure = []
                try:
                    redis.client.config_set(
                        "maxmemory", redis.client.info("memory")["used_memory"] + 262144
                    )
                    redis.client.config_set("maxmemory-policy", "allkeys-lru")
                    # Never read/touch the target: SCAN observes eviction without refreshing LRU.
                    for _ in range(20):
                        with redis.client.pipeline(transaction=False) as pipe:
                            for _ in range(32):
                                item = prefix + "pressure:" + uuid4().hex
                                pressure.append(item)
                                pipe.set(item, "x" * 65536, ex=15)
                            pipe.execute()
                        if not any(redis.client.scan_iter(match=key)):
                            break
                    assert not any(redis.client.scan_iter(match=key))
                    assert time.time() < ctx["session"]["expiresAt"]
                    assert redis.client.info("stats")["evicted_keys"] > before
                    post(1, payload("두 번째 상품 가격은?", ctx), 410, code="chat_session_expired")
                finally:
                    redis.client.config_set("maxmemory", settings["maxmemory"])
                    redis.client.config_set("maxmemory-policy", settings["maxmemory-policy"])
                    if pressure:
                        redis.client.delete(*pressure)

            case("allkeys_lru_can_expire_session_before_TTL", eviction)

            def ownership():
                ctx = search()
                post(1, payload("두 번째 상품 가격은?", ctx), 403, other, "chat_session_forbidden")
                user_a = {"Authorization": "Bearer fixture-user-A"}
                user_b = {"Authorization": "Bearer fixture-user-B"}
                owned = search(headers=user_a)
                post(
                    1, payload("두 번째 상품 가격은?", owned), 403, user_b, "chat_session_forbidden"
                )
                post(
                    1, payload("두 번째 상품 가격은?", owned), 403, guest, "chat_session_forbidden"
                )

            case("guest_and_user_ownership", ownership)

            def lost_bootstrap():
                body = payload()
                content = json.dumps(body).encode("utf-8")
                port = httpx.URL(urls[0]).port
                headers = (
                    f"POST /api/chat HTTP/1.1\r\nHost: 127.0.0.1:{port}\r\n"
                    "Content-Type: application/json\r\n"
                    f"X-Vishue-Anonymous-Id: {guest['X-Vishue-Anonymous-Id']}\r\n"
                    f"Content-Length: {len(content)}\r\nConnection: close\r\n\r\n"
                ).encode("ascii")
                with socket.create_connection(("127.0.0.1", port), timeout=3) as wire:
                    wire.sendall(headers + content)
                    pattern = prefix + "vishue:chat:request:*:" + body["requestId"]
                    eventually(lambda: any(redis.client.scan_iter(match=pattern)))
                    request_key = next(redis.client.scan_iter(match=pattern))
                    state_key = prefix + "vishue:chat:session:" + redis.client.get(request_key)
                    state = json.loads(redis.client.get(state_key))
                    tokens.add(state["lastResponse"]["chatContext"]["session"]["sessionToken"])
                    # Close without reading even the status line: the app has no capability.
                post(1, body, 409, code="chat_request_conflict")
                search(1)

            case("lost_initial_response_409_fresh_search", lost_bootstrap)

            def outage():
                ctx = search()
                redis.stop()
                try:
                    post(
                        1,
                        payload("두 번째 상품 가격은?", ctx),
                        503,
                        code="chat_session_unavailable",
                    )
                    independent = post(0, payload())
                    assert independent["sessionStatus"] == "unavailable"
                    assert independent["chatContext"].get("session") is None
                finally:
                    redis.restart()
                post(1, payload("두 번째 상품 가격은?", ctx), 410, code="chat_session_expired")
                search(1)

            case("Redis_stop_restart_no_memory_fallback", outage)

            for handle in handles:
                handle.flush()
            log_text = "\n".join(
                p.read_text(encoding="utf-8", errors="replace")
                for p in Path(directory).glob("worker-*.log")
            )
            case(
                "application_logs_do_not_expose_tokens",
                lambda: (
                    None
                    if not any(token in log_text for token in tokens)
                    else (_ for _ in ()).throw(AssertionError("Capability found in logs"))
                ),
            )
            report["status"] = (
                "passed" if all(c["status"] == "PASS" for c in report["cases"]) else "failed"
            )
        except EnvironmentBlocked as exc:
            report["reason"] = str(exc)
        except Exception as exc:
            report["status"], report["errorType"] = "failed", type(exc).__name__
        finally:
            for process in processes:
                if process.poll() is None:
                    process.terminate()
                    try:
                        process.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        process.kill()
                        process.wait(timeout=5)
            for handle in handles:
                handle.close()
            try:
                if redis.started:
                    redis.close()
                report["cleanup"] = True
                if baseline is not None:
                    report["existingContainersUnchanged"] = container_snapshot() == baseline
                    if not report["existingContainersUnchanged"]:
                        report["status"] = "failed"
                    report["volumeInventoryUnchanged"] = (
                        command(["docker", "volume", "ls", "-q"]).stdout.split() == baseline_volumes
                    )
                    if not report["volumeInventoryUnchanged"]:
                        report["status"] = "failed"
            except Exception:
                report["cleanup"] = False
                report["status"] = "failed"
            http.close()
    report["passed"] = sum(c["status"] == "PASS" for c in report["cases"])
    report["failed"] = sum(c["status"] == "FAIL" for c in report["cases"])
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--redis-server", default=shutil.which("redis-server"))
    parser.add_argument("--docker-image", default="redis:7-alpine")
    report = run(parser.parse_args())
    print(json.dumps(report, ensure_ascii=True))
    return {"passed": 0, "failed": 1, "blocked": 2}[report["status"]]


if __name__ == "__main__":
    raise SystemExit(main())

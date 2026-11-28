"""Approved closeout evidence only; never edits product code or existing reports."""

import hashlib
import importlib.util
import json
import os
import re
import secrets
import shutil
import subprocess
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
OUT = Path(__file__).resolve().parent
PG = "vishue-g8-final-closeout-pg"
LABEL = "final-closeout-506ab47f"


def write(name, value):
    (OUT / name).write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")


def read(name):
    return json.loads((OUT / name).read_text(encoding="utf-8"))


def emit(kind, **values):
    with (OUT / "trace.jsonl").open("a", encoding="utf-8") as stream:
        stream.write(
            json.dumps(
                {"at": datetime.now(UTC).isoformat(), "kind": kind, **values}, ensure_ascii=False
            )
            + "\n"
        )


def hashed(path):
    return {
        "path": path.relative_to(ROOT).as_posix(),
        "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
    }


def baseline():
    files = [
        p
        for p in (ROOT / "reports/g8").rglob("*")
        if p.is_file() and OUT not in p.parents and "__pycache__" not in p.parts
    ]
    sources = [
        p
        for base in ("backend", "app", "hooks", "components", "lib", "types")
        for p in (ROOT / base).rglob("*")
        if p.is_file()
        and p.suffix in {".py", ".ts", ".tsx"}
        and not any(x in p.parts for x in (".venv", "__pycache__", "node_modules"))
    ]
    write(
        "manifest.json",
        {
            "at": datetime.now(UTC).isoformat(),
            "branch": subprocess.check_output(
                ["git", "branch", "--show-current"], cwd=ROOT, text=True
            ).strip(),
            "head": subprocess.check_output(
                ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True
            ).strip(),
            "integratedDevelop": "991dd634dba33b99ceeb1c03de4dd8d921ce07f9",
            "sources": [hashed(p) for p in sources],
            "priorEvidence": [hashed(p) for p in files],
            "productEditsAllowed": False,
        },
    )
    print("Recorded immutable source and previous evidence baseline", len(sources), len(files))


def integrity():
    m = read("manifest.json")
    result = {}
    for group in ("sources", "priorEvidence"):
        changed = [
            r["path"]
            for r in m[group]
            if not (ROOT / r["path"]).is_file() or hashed(ROOT / r["path"])["sha256"] != r["sha256"]
        ]
        result[group] = {"checked": len(m[group]), "changed": changed}
    return result


def security():
    values = live_environment()
    protected = [
        value
        for key, value in values.items()
        if any(x in key.upper() for x in ("KEY", "TOKEN", "SECRET", "PASSWORD"))
        and isinstance(value, str)
        and len(value) > 10
        and not key.startswith("EXPO_PUBLIC_")
        and "PUBLISHABLE" not in key
    ]
    private = dict(x.split("=", 1) for x in inspect()["Config"]["Env"] if "=" in x)
    protected.append(private["POSTGRES_PASSWORD"])
    counts = {"environmentValue": 0, "jwt": 0, "privateKey": 0, "email": 0}
    for path in OUT.iterdir():
        if not path.is_file():
            continue
        value = path.read_text(encoding="utf-8", errors="replace")
        counts["environmentValue"] += sum(secret in value for secret in protected)
        counts["jwt"] += len(re.findall(r"eyJ[\w-]{12,}\.[\w-]{12,}\.[\w-]{12,}", value))
        counts["privateKey"] += len(re.findall(r"-----BEGIN [A-Z ]*PRIVATE KEY-----", value))
        if path.name == "manifest.json":
            parsed = json.loads(value)
            diff = parsed.get("uncommittedSourceDiff", {})
            if "gitDiff" in diff:
                diff["gitDiff"] = re.sub(
                    r"(?m)^([ +\-]*)@pytest\.mark\.(?:anyio|parametrize)\b",
                    r"\1PYTEST_DECORATOR",
                    diff["gitDiff"],
                )
                value = json.dumps(parsed)
        counts["email"] += len(re.findall(r"[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}", value))
    with (OUT / "security.log").open("a", encoding="utf-8") as stream:
        stream.write(
            json.dumps({"at": datetime.now(UTC).isoformat(), "supplementalMatches": counts}) + "\n"
        )
    print("Supplemental security pattern counts", counts)
    assert not any(counts.values()), "Review without printing matched values"


def cleanup():
    m = read("manifest.json")
    stopped = []
    for role, pid in m.get("pids", {}).items():
        command = subprocess.check_output(
            [
                "powershell",
                "-NoProfile",
                "-Command",
                f"(Get-CimInstance Win32_Process -Filter 'ProcessId = {pid}').CommandLine",
            ],
            text=True,
        )
        assert str(OUT / "audit.py") in command and "serve-" + role in command
        done = subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"], capture_output=True)
        assert done.returncode == 0
        stopped.append({"role": role, "pid": pid, "exitCode": done.returncode})
    obj = inspect()
    assert obj["Config"]["Labels"]["vishue.g8-evaluation"] == LABEL
    result = subprocess.run(["docker", "rm", "-fv", PG], capture_output=True)
    assert result.returncode == 0
    state = integrity()
    assert not any(v["changed"] for v in state.values())
    write(
        "cleanup.json",
        {
            "at": datetime.now(UTC).isoformat(),
            "container": PG,
            "containerRemovalExit": result.returncode,
            "stopped": stopped,
            "originalWriteCommands": 0,
            "integrity": state,
        },
    )
    print("Removed only labelled validation container and verified owned service PIDs")


def inspect():
    return json.loads(subprocess.check_output(["docker", "inspect", PG], text=True))[0]


def database_env():
    from sqlalchemy.engine import URL

    obj = inspect()
    assert obj["Config"]["Labels"]["vishue.g8-evaluation"] == LABEL
    env = dict(x.split("=", 1) for x in obj["Config"]["Env"] if "=" in x)
    port = obj["NetworkSettings"]["Ports"]["5432/tcp"][0]["HostPort"]
    base = URL.create(
        "postgresql+asyncpg",
        username="g8_eval",
        password=env["POSTGRES_PASSWORD"],
        host="127.0.0.1",
        port=int(port),
    )
    urls = {
        name: base.set(database=name).render_as_string(hide_password=False)
        for name in ("vishue_chat_test", "vishue_api_test", "vishue_api_g7_test")
    }
    return {
        "TEST_CHAT_DATABASE_URL": urls["vishue_chat_test"],
        "CHAT_DATABASE_URL": urls["vishue_chat_test"],
        "TEST_DATABASE_URL": urls["vishue_api_test"],
        "DATABASE_URL": urls["vishue_api_test"],
        "TEST_G7_ACCOUNT_DELETION_DATABASE_URL": urls["vishue_api_g7_test"],
        "G7_ALLOW_DESTRUCTIVE_TESTS": "1",
    }


def clone_url(name):
    from sqlalchemy.engine import make_url

    assert name in {"vishue_final_catalog", "vishue_final_knowledge"}
    return make_url(database_env()["DATABASE_URL"]).set(database=name)


def clone_data():
    prior = json.loads((OUT.parent / "closing5/manifest.json").read_text(encoding="utf-8"))
    for role, name in (("catalog", "vishue_final_catalog"), ("g5", "vishue_final_knowledge")):
        source = next(d for d in prior["dumps"] if d["role"] == role)
        dump = Path(source["privatePath"])
        with dump.open("rb") as stream:
            assert hashlib.file_digest(stream, "sha256").hexdigest() == source["sha256"]
        subprocess.run(["docker", "exec", PG, "createdb", "-U", "g8_eval", name], check=True)
        remote = "/tmp/" + role + ".dump"
        subprocess.run(
            ["docker", "cp", str(dump), PG + ":" + remote], stdout=subprocess.DEVNULL, check=True
        )
        toc = subprocess.check_output(["docker", "exec", PG, "pg_restore", "-l", remote], text=True)
        entries = [
            line
            for line in toc.splitlines()
            if not (role == "catalog" and " TABLE DATA " in line and " public aihub_" in line)
            and not (" INDEX " in line and "hnsw" in line.lower())
        ]
        with (OUT / "db-check.log").open("a", encoding="utf-8") as log:
            result = subprocess.run(
                [
                    "docker",
                    "exec",
                    "-i",
                    PG,
                    "pg_restore",
                    "-U",
                    "g8_eval",
                    "-d",
                    name,
                    "--no-owner",
                    "--no-acl",
                    "--exit-on-error",
                    "-L",
                    "/dev/stdin",
                    remote,
                ],
                input=("\n".join(entries) + "\n").encode(),
                stdout=log,
                stderr=log,
            )
        assert result.returncode == 0
        env = dict(
            live_environment(),
            PYTHONDONTWRITEBYTECODE="1",
            PYTHONUTF8="1",
            SKINCARE_REFRESH_ENABLED="false",
            DATABASE_URL=clone_url(name).render_as_string(hide_password=False),
        )
        prefix = [shutil.which("uv"), "run", "--frozen", "--no-sync", "python", "-B", "-m"]
        if role == "g5":
            checks = prior["g5LegacyChecksReused"]
            assert len(checks) == 3 and all(c["equal"] for c in checks)
            assert (
                checked(
                    prefix + ["alembic", "stamp", "0032"],
                    ROOT / "backend/api",
                    env,
                    "db-check.log",
                    "same-dump legacy G5 schema alignment",
                )
                == 0
            )
        assert (
            checked(
                prefix + ["alembic", "upgrade", "head"],
                ROOT / "backend/api",
                env,
                "db-check.log",
                role + " clone migration",
            )
            == 0
        )
        emit(
            "clone_prepared",
            role=role,
            database=name,
            dumpSha256=source["sha256"],
            skippedHnswCreation=True,
            embeddingSearch="exact scan permitted; no data edited",
        )
        print("Prepared unchanged source clone", role, flush=True)


def serve_api(role):
    env = live_environment()
    env.update(
        DATABASE_URL=clone_url(
            "vishue_final_knowledge" if role == "g5" else "vishue_final_catalog"
        ).render_as_string(hide_password=False),
        SKINCARE_REFRESH_ENABLED="false",
        G5_ENABLED="true" if role == "g5" else "false",
        G5_ALLOW_LOCAL_SOURCES="true",
    )
    os.environ.update(env)
    sys.path.insert(0, str(ROOT / "backend/api"))
    observe_http()
    import uvicorn

    uvicorn.run(
        "app.main:app",
        host="127.0.0.1",
        port=19838 if role == "g5" else 19834,
        log_level="warning",
        access_log=False,
    )


def start_data():
    import socket

    m = read("manifest.json")
    pids = {}
    for role, port in (("catalog", 19834), ("g5", 19838)):
        with socket.socket() as sock:
            assert sock.connect_ex(("127.0.0.1", port)) != 0, "Port already owned"
        with (OUT / "db-check.log").open("ab") as log:
            process = subprocess.Popen(
                [
                    str(ROOT / "backend/api/.venv/Scripts/python.exe"),
                    "-B",
                    str(__file__),
                    "serve-" + role,
                ],
                cwd=ROOT / "backend/api",
                env=dict(os.environ, PYTHONDONTWRITEBYTECODE="1", PYTHONUTF8="1"),
                stdout=log,
                stderr=log,
                creationflags=subprocess.CREATE_NO_WINDOW,
            )
        pids[role] = process.pid
    m["pids"] = pids
    write("manifest.json", m)
    for port in (19834, 19838):
        for _ in range(120):
            with socket.socket() as sock:
                if sock.connect_ex(("127.0.0.1", port)) == 0:
                    break
            time.sleep(0.5)
        else:
            raise AssertionError("Evaluation service not ready")
    print("Started current API source on loopback only", flush=True)


def checked(args, cwd, env, log, label):
    started = time.monotonic()
    with (OUT / log).open("a", encoding="utf-8") as stream:
        stream.write(f"\n{datetime.now(UTC).isoformat()} {label}\n")
        stream.flush()
        result = subprocess.run(args, cwd=cwd, env=env, stdout=stream, stderr=subprocess.STDOUT)
        stream.write(f"\nexit={result.returncode} seconds={time.monotonic() - started:.3f}\n")
    emit(
        "command_end",
        label=label,
        exitCode=result.returncode,
        seconds=round(time.monotonic() - started, 3),
        log=log,
    )
    print(label, "exit", result.returncode, flush=True)
    return result.returncode


def prepare():
    assert subprocess.run(["docker", "inspect", PG], capture_output=True).returncode != 0
    env = dict(os.environ, POSTGRES_PASSWORD=secrets.token_urlsafe(32))
    subprocess.run(
        [
            "docker",
            "run",
            "-d",
            "--name",
            PG,
            "--label",
            "vishue.g8-evaluation=" + LABEL,
            "-e",
            "POSTGRES_USER=g8_eval",
            "-e",
            "POSTGRES_PASSWORD",
            "-p",
            "127.0.0.1::5432",
            "pgvector/pgvector:0.8.2-pg17-bookworm",
        ],
        env=env,
        stdout=subprocess.DEVNULL,
        check=True,
    )
    for _ in range(60):
        if (
            subprocess.run(
                ["docker", "exec", PG, "pg_isready", "-U", "g8_eval"], capture_output=True
            ).returncode
            == 0
        ):
            break
        time.sleep(0.5)
    else:
        raise AssertionError("Disposable PG startup failed")
    for name in ("vishue_chat_test", "vishue_api_test", "vishue_api_g7_test"):
        subprocess.run(["docker", "exec", PG, "createdb", "-U", "g8_eval", name], check=True)
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1", PYTHONUTF8="1", **database_env())
    uv = shutil.which("uv")
    for service, url in (
        ("api", env["TEST_DATABASE_URL"]),
        ("api", env["TEST_G7_ACCOUNT_DELETION_DATABASE_URL"]),
        ("chatbot", env["TEST_CHAT_DATABASE_URL"]),
    ):
        local = dict(env, DATABASE_URL=url, CHAT_DATABASE_URL=url)
        assert (
            checked(
                [
                    uv,
                    "run",
                    "--frozen",
                    "--no-sync",
                    "python",
                    "-B",
                    "-m",
                    "alembic",
                    "upgrade",
                    "head",
                ],
                ROOT / "backend" / service,
                local,
                "db-check.log",
                service + " clean migration",
            )
            == 0
        )
    assert (
        checked(
            [
                uv,
                "run",
                "--frozen",
                "--no-sync",
                "python",
                "-B",
                "-m",
                "app.jobs.init_chat_checkpoints",
            ],
            ROOT / "backend/chatbot",
            env,
            "db-check.log",
            "chat checkpoint init",
        )
        == 0
    )
    print("Prepared only new disposable PG databases", flush=True)


def regression(group, only_failed=False):
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1", PYTHONUTF8="1", UV_NO_PROGRESS="1", CI="1")
    # Live opt-ins are intentionally absent from the full automatic regression.
    for key in list(env):
        if "LIVE" in key or key in {"G5_EXTRACTION_TEST_DATABASE_URL", "ADMIN_TEST_DATABASE_URL"}:
            env.pop(key)
    if group == "app":
        npm = shutil.which("npm.cmd") or shutil.which("npm")
        commands = [
            [npm, "run", "typecheck", "--", "--incremental", "false"],
            [npm, "run", "lint", "--", "--no-cache"],
            [npm, "test", "--", "--runInBand", "--no-cache"],
        ]
        cwd = ROOT
    else:
        env.update(database_env())
        uv = shutil.which("uv")
        prefix = [uv, "run", "--frozen", "--no-sync"]
        commands = [
            prefix + ["ruff", "check", "."],
            prefix + ["lint-imports"],
            prefix
            + ["python", "-B", "-m", "pytest", "-q", "-ra", "--tb=short", "-p", "no:cacheprovider"],
        ]
        if only_failed:
            failed = list(
                dict.fromkeys(
                    re.findall(
                        r"^(?:ERROR|FAILED) (.+?) - ",
                        (OUT / (group + "-check.log")).read_text(encoding="utf-8"),
                        re.M,
                    )
                )
            )
            assert failed, "No failed tests to retry"
            commands = [commands[-1] + failed]
        temporary = Path(os.environ["TEMP"]) / (
            "vishue-g8-final-" + group + "-" + secrets.token_hex(5)
        )
        commands[-1] += ["--basetemp", str(temporary)]
        cwd = ROOT / "backend" / group
    codes = [
        checked(command, cwd, env, group + "-check.log", group + " " + " ".join(command[1:]))
        for command in commands
    ]
    if any(codes):
        raise SystemExit(1)


def live_environment():
    spec = importlib.util.spec_from_file_location(
        "prior_environment", OUT.parent / "stage6-remediation-runtime.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.environment()


def observe_http():
    import httpx

    original_async = httpx.AsyncClient.send
    original_sync = httpx.Client.send

    def capture(request, response):
        if request.url.host == "api.openai.com":
            body, value = json.loads(request.content), response.json()
            emit(
                "model_http",
                mode="live",
                path=request.url.path,
                model=body.get("model"),
                responseId=value.get("id"),
                status=response.status_code,
                usage=value.get("usage"),
                returnedModel=value.get("model"),
            )
        elif request.url.port in (19834, 19838):
            emit(
                "tool_http",
                mode="actual migrated clone HTTP",
                path=request.url.path,
                input=json.loads(request.content) if request.content else None,
                status=response.status_code,
                result=response.json(),
            )

    async def send(client, request, *args, **kwargs):
        response = await original_async(client, request, *args, **kwargs)
        capture(request, response)
        return response

    def sync_send(client, request, *args, **kwargs):
        response = original_sync(client, request, *args, **kwargs)
        capture(request, response)
        return response

    httpx.AsyncClient.send, httpx.Client.send = send, sync_send


async def positive_probe():
    env = live_environment()
    env.update(CATALOG_API_URL="http://127.0.0.1:19838", G5_ENABLED="true")
    os.environ.update(env)
    sys.path.insert(0, str(ROOT / "backend/chatbot"))
    from app.clients.catalog_client import CatalogClient
    from app.clients.llm_client import get_llm_client
    from app.clients.skincare_recommendation_client import SkincareRecommendationClient
    from app.schemas.compound_consultation import CompoundGoal
    from app.services.compound_consultation_graph import run_compound
    from app.services.skincare_recommendation_tool import SkincareRecommendationTool

    observe_http()
    goal = CompoundGoal(
        goals=["dryness"], max_price_krw=20000, wants_knowledge=True, wants_products=True
    )
    variant = int(sys.argv[2]) if len(sys.argv) > 2 else 1
    assert variant in (1, 2), "At most two distinct diagnostic questions"
    question = (
        "건조함 관리에서 판테놀 성분을 선택하는 방법과 주의점을 설명해 주세요."
        if variant == 1
        else (
            "건조함이 고민이에요. 판테놀 함유 보습제를 선택할 때 "
            "도움이 될 관리 방법을 설명해 주세요."
        )
    )
    tasks = []
    started = time.monotonic()
    result = await run_compound(
        goal,
        question,
        SkincareRecommendationTool(SkincareRecommendationClient("http://127.0.0.1:19834")),
        CatalogClient("http://127.0.0.1:19834"),
        trace=tasks,
        llm=get_llm_client(),
    )
    emit(
        "positive_graph_result",
        mode="all live G5/extractor/Catalog; direct graph, not app/PG",
        variant=variant,
        question=question,
        goal=goal.model_dump(mode="json", by_alias=True),
        response=result.model_dump(mode="json", by_alias=True),
        tasks=tasks,
        seconds=round(time.monotonic() - started, 3),
    )
    print("Recorded one actual K1-to-V1 graph run", flush=True)


async def component_positive():
    sys.path.insert(0, str(ROOT / "backend/chatbot"))
    from app.clients.catalog_client import CatalogClient
    from app.schemas.compound_consultation import (
        CompoundGoal,
        KnowledgeSearchCondition,
        RankedOption,
    )
    from app.schemas.knowledge import KnowledgeReply
    from app.services.compound_consultation_service import validate_search_conditions, verify

    rows = [json.loads(s) for s in (OUT / "trace.jsonl").read_text().splitlines()]
    prior = next(r for r in rows if r["kind"] == "positive_graph_result")
    knowledge = KnowledgeReply.model_validate(
        next(t["result"]["knowledge"] for t in prior["tasks"] if t["task"]["taskId"] == "K1")
    )
    ref = next(e for e in knowledge.evidence if e.id == "K1.E1.2")
    proposal = KnowledgeSearchCondition(
        ingredient_name="판테놀",
        operator="includes",
        claim_index=0,
        evidence_id=ref.id,
        quote=ref.quote,
    )
    goal = CompoundGoal.model_validate(prior["goal"])
    accepted, decisions = validate_search_conditions(goal, knowledge, [proposal])
    assert len(accepted) == 1
    candidates = [
        RankedOption.model_validate(c)
        for t in prior["tasks"]
        if t["task"]["taskId"] == "P1"
        for c in t["result"]["candidates"]
    ]
    observe_http()
    options, batches, limitations = await verify(
        goal, candidates, CatalogClient("http://127.0.0.1:19834"), search_conditions=accepted
    )
    emit(
        "component_positive",
        mode="manual proposal fixture; prior real G5/P1; actual Catalog",
        newModelCalls=0,
        decisions=decisions,
        allLive=False,
        options=[o.model_dump(mode="json", by_alias=True) for o in options],
        batches=[b.model_dump(mode="json", by_alias=True) for b in batches],
        limitations=limitations,
    )
    print(
        "Component check eligible",
        sum(o.outcome == "eligible" for o in options),
        "unknown",
        sum(o.outcome == "unknown" for o in options),
        flush=True,
    )


async def skin_probe():
    os.environ.update(live_environment())
    sys.path.insert(0, str(ROOT / "backend/chatbot"))
    from app.clients.llm_client import get_llm_client
    from app.schemas.chat import ChatRequest
    from app.services.compound_consultation_graph import interpret

    llm = get_llm_client()
    original = llm.complete_with_tools
    sample = 0

    async def observed(*args, **kwargs):
        result, elapsed = await original(*args, **kwargs)
        emit(
            "skin_model_response",
            sample=sample,
            mode="live",
            ms=elapsed,
            configuredModel=llm._model,
            result=result,
        )
        return result, elapsed

    llm.complete_with_tools = observed
    for sample in range(1, 4):
        started = time.monotonic()
        req = ChatRequest(
            message="오후에 화장이 뜨는데 원인 알려주고 나한테 맞는 제품도 찾아줘",
            locale="ko",
            request_type="beauty_consultation",
        )
        try:
            plan = await interpret(req, llm, None)
            emit(
                "skin_probe",
                sample=sample,
                mode="live model; direct planner, not app/PG",
                question=req.message,
                plan=plan.model_dump(mode="json", by_alias=True) if plan else None,
                seconds=round(time.monotonic() - started, 3),
            )
            print("skin sample", sample, "accepted", plan.action if plan else None, flush=True)
        except Exception as exc:
            cause = exc.__cause__ or exc
            emit(
                "skin_probe",
                sample=sample,
                mode="live model; direct planner, not app/PG",
                question=req.message,
                errorCode=getattr(exc, "code", None),
                causeType=type(cause).__name__,
                cause=str(cause),
                seconds=round(time.monotonic() - started, 3),
            )
            print("skin sample", sample, "rejected", type(cause).__name__, flush=True)


if __name__ == "__main__":
    action = sys.argv[1]
    if action == "baseline":
        baseline()
    elif action == "prepare":
        prepare()
    elif action in {"app", "api", "chatbot"}:
        regression(action)
    elif action in {"retry-api", "retry-chatbot"}:
        regression(action.removeprefix("retry-"), only_failed=True)
    elif action == "skin-probe":
        import asyncio

        asyncio.run(skin_probe())
    elif action == "positive-probe":
        import asyncio

        asyncio.run(positive_probe())
    elif action == "component-positive":
        import asyncio

        asyncio.run(component_positive())
    elif action == "security":
        security()
    elif action == "cleanup":
        cleanup()
    elif action == "clone":
        clone_data()
    elif action == "start-data":
        start_data()
    elif action.startswith("serve-"):
        serve_api(action.removeprefix("serve-"))

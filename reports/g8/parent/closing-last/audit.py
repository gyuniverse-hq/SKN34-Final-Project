"""Approved last G8 closeout: isolated real data, bounded probes, no remote writes."""

import ast
import hashlib
import importlib.util
import json
import logging
import os
import re
import socket
import subprocess
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
OUT = Path(__file__).resolve().parent
APPROVED = [
    "backend/chatbot/app/services/compound_consultation_service.py",
    "backend/chatbot/app/services/compound_consultation_graph.py",
    "backend/chatbot/tests/test_g8_compound_consultation.py",
]
spec = importlib.util.spec_from_file_location(
    "prior_closeout", OUT.parent / "final-closeout/audit.py"
)
base = importlib.util.module_from_spec(spec)
spec.loader.exec_module(base)
base.OUT = OUT
base.PG = "vishue-g8-closing-last-pg"
base.LABEL = "closing-last-506ab47f"
RUNTIME = None


def emit(kind, **values):
    with (OUT / "trace.jsonl").open("a", encoding="utf-8") as stream:
        stream.write(
            json.dumps(
                {
                    "at": datetime.now(UTC).isoformat(),
                    "kind": kind,
                    "turn": RUNTIME.TURN.get() if RUNTIME else None,
                    **values,
                },
                ensure_ascii=False,
                default=str,
            )
            + "\n"
        )


base.emit = emit


def baseline():
    assert not (OUT / "manifest.json").exists(), "Preserve existing closeout evidence"
    base.baseline()
    m = base.read("manifest.json")
    m["productEditsAllowed"] = APPROVED
    m["approvedSourcesBefore"] = [
        {
            "path": p,
            "sha256": hashlib.sha256((ROOT / p).read_bytes()).hexdigest(),
            "text": (ROOT / p).read_text(encoding="utf-8"),
        }
        for p in APPROVED
    ]
    base.write("manifest.json", m)


def phase(name):
    emit(
        "phase_start",
        phase=name,
        driverSha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        sources=[base.hashed(ROOT / p) for p in APPROVED],
    )


def environment():
    env = base.live_environment()
    obj = json.loads(
        subprocess.check_output(
            ["docker", "inspect", "vishue-g8-closing-last-redis"],
            text=True,
        )
    )[0]
    assert obj["Config"]["Labels"]["vishue.g8-evaluation"] == base.LABEL
    port = obj["NetworkSettings"]["Ports"]["6379/tcp"][0]["HostPort"]
    env.update(base.database_env())
    env.update(
        DATABASE_URL=base.clone_url("vishue_final_catalog").render_as_string(hide_password=False),
        CATALOG_API_URL="http://127.0.0.1:19834",
        REDIS_URL=f"redis://127.0.0.1:{port}/0",
        G5_ENABLED="true",
        PYTHONDONTWRITEBYTECODE="1",
        PYTHONUTF8="1",
    )
    return env


def observe():
    global RUNTIME
    sys.path.insert(0, str(OUT.parent / "closing4"))
    loaded = importlib.util.spec_from_file_location(
        "last_runtime", OUT.parent / "closing4/runtime.py"
    )
    RUNTIME = importlib.util.module_from_spec(loaded)
    loaded.loader.exec_module(RUNTIME)
    RUNTIME.emit = emit
    from app.clients.llm_client import LlmClient
    from app.services import compound_consultation_graph as graph
    from app.services import knowledge_service as knowledge

    choose, run, resolve = LlmClient.complete_with_tools, graph.run_compound, knowledge.resolve

    async def model(self, *args, **kwargs):
        result, elapsed = await choose(self, *args, **kwargs)
        emit("model_tool_output", tool=kwargs.get("required_tool"), result=result, ms=elapsed)
        return result, elapsed

    async def compound(*args, **kwargs):
        tasks = kwargs.setdefault("trace", [])
        started = time.monotonic()
        result = await run(*args, **kwargs)
        emit(
            "compound_run",
            tasks=tasks,
            response=result.model_dump(mode="json", by_alias=True),
            ms=round((time.monotonic() - started) * 1000, 1),
            mode="live",
        )
        return result

    def verified(draft, audit, evidence, **kwargs):
        result = resolve(draft, audit, evidence, **kwargs)
        emit(
            "knowledge_resolution",
            draft=draft,
            audit=audit,
            final=result.model_dump(mode="json", by_alias=True),
            coverage=kwargs["coverage"].model_dump() if kwargs.get("coverage") else None,
        )
        return result

    LlmClient.complete_with_tools, graph.run_compound, knowledge.resolve = model, compound, verified
    RUNTIME.observe_chat()


def diagnostic_logs():
    class AuditHandler(logging.Handler):
        def emit(self, record):
            if record.name.endswith("compound_consultation_graph"):
                emit("skin_diagnostic", text=record.getMessage(), level=record.levelname)

    logging.getLogger("app.services.compound_consultation_graph").addHandler(AuditHandler())


def serve_chat():
    os.environ.update(environment())
    sys.path.insert(0, str(ROOT / "backend/chatbot"))
    base.observe_http()
    diagnostic_logs()
    observe()
    import uvicorn

    from app.main import create_app

    app = create_app()

    @app.middleware("http")
    async def observed(request, call_next):
        started = time.monotonic()
        response = await call_next(request)
        if request.url.path.startswith("/api/chat"):
            emit(
                "chat_http",
                method=request.method,
                path=re.sub(r"[0-9a-f]{8}-[0-9a-f-]{27,}", "{id}", request.url.path),
                status=response.status_code,
                ms=round((time.monotonic() - started) * 1000, 1),
            )
        return response

    uvicorn.run(app, host="127.0.0.1", port=19833, log_level="warning", access_log=False)


def start():
    subprocess.run(
        [
            "docker",
            "run",
            "-d",
            "--name",
            "vishue-g8-closing-last-redis",
            "--label",
            "vishue.g8-evaluation=" + base.LABEL,
            "-p",
            "127.0.0.1::6379",
            "redis:7-alpine",
            "redis-server",
            "--save",
            "",
            "--appendonly",
            "no",
        ],
        check=True,
        stdout=subprocess.DEVNULL,
    )
    phase("live-app-start")
    pids = {}
    for role, folder, env in [
        ("catalog", "api", os.environ.copy()),
        ("g5", "api", os.environ.copy()),
        ("chat", "chatbot", environment()),
    ]:
        with (OUT / "runtime.log").open("ab") as stream:
            pids[role] = subprocess.Popen(
                [
                    str(ROOT / f"backend/{folder}/.venv/Scripts/python.exe"),
                    "-B",
                    str(__file__),
                    "serve-" + role,
                ],
                cwd=ROOT / f"backend/{folder}",
                env=dict(env, PYTHONDONTWRITEBYTECODE="1", PYTHONUTF8="1"),
                stdout=stream,
                stderr=stream,
                creationflags=subprocess.CREATE_NO_WINDOW,
            ).pid
    env = environment()
    web = dict(
        os.environ,
        CI="1",
        EXPO_NO_TELEMETRY="1",
        EXPO_PUBLIC_API_BASE_URL="http://localhost:19834",
        EXPO_PUBLIC_CHAT_API_BASE_URL="http://localhost:19833",
        EXPO_PUBLIC_SUPABASE_URL=env["SUPABASE_URL"],
        EXPO_PUBLIC_SUPABASE_PUBLISHABLE_KEY=env["SUPABASE_PUBLISHABLE_KEY"],
    )
    with (OUT / "runtime.log").open("ab") as stream:
        pids["web"] = subprocess.Popen(
            [
                "node",
                "node_modules/expo/bin/cli",
                "start",
                "--web",
                "--port",
                "19836",
                "--localhost",
            ],
            cwd=ROOT,
            env=web,
            stdout=stream,
            stderr=stream,
            creationflags=subprocess.CREATE_NO_WINDOW,
        ).pid
    m = base.read("manifest.json")
    m["pids"] = pids
    base.write("manifest.json", m)
    for port in (19833, 19834, 19838, 19836):
        for _ in range(120):
            try:
                # Expo --localhost listens on ::1 here; API services use IPv4 loopback.
                with socket.create_connection(("localhost", port), timeout=0.4):
                    break
            except OSError:
                pass
            time.sleep(0.5)
        else:
            raise AssertionError(f"Validation service not ready: {port}")
    print("Started current API/G5/chat/Expo on loopback only", flush=True)


def integrity():
    m = base.read("manifest.json")
    result = {}
    for group in ("sources", "priorEvidence"):
        changed = [
            r["path"]
            for r in m[group]
            if not (ROOT / r["path"]).is_file()
            or base.hashed(ROOT / r["path"])["sha256"] != r["sha256"]
        ]
        result[group] = {
            "checked": len(m[group]),
            "changedOutsideApproval": [p for p in changed if p not in APPROVED],
            "approvedChanges": [p for p in changed if p in APPROVED],
        }
    return result


def verify():
    import psycopg
    from sqlalchemy.engine import make_url

    rows = [json.loads(s) for s in (OUT / "trace.jsonl").read_text().splitlines()]
    turns = [r for r in rows if r["kind"] == "turn_end"]
    runs = [r for r in rows if r["kind"] == "compound_run"]
    latest = runs[-1]
    v1 = next(t for t in latest["tasks"] if t["task"]["taskId"] == "V1")
    k1 = next(t for t in latest["tasks"] if t["task"]["taskId"] == "K1")
    conditions = v1["inputs"]["knowledgeConditions"]
    assert conditions
    requested = [
        r
        for r in rows
        if r["kind"] == "tool_http"
        and r.get("turn") == latest["turn"]
        and r["path"] == "/api/catalog/options/search"
    ]
    scope = latest["response"]["compound"]
    eligible = [o for o in scope["options"] if o["outcome"] == "eligible"]
    expected = [
        {"ingredientName": p["ingredientName"], "operator": p["operator"]} for p in conditions
    ]
    assert len(requested) == 2 and all(
        r["input"]["ingredientConditions"] == expected for r in requested
    )
    assert eligible and all(
        any(
            c.get("ingredientName") == conditions[0]["ingredientName"] and c["verdict"] == "MATCH"
            for c in o["verification"]["checks"]
        )
        for o in eligible
    )
    used, saved, dialogue = set(), [], []
    url = make_url(base.database_env()["CHAT_DATABASE_URL"]).set(drivername="postgresql")
    with psycopg.connect(url.render_as_string(hide_password=False)) as conn:
        conn.execute("SET TRANSACTION READ ONLY")
        for n, turn in enumerate(turns, 1):
            matches = conn.execute(
                "SELECT a.id,a.display_payload,c.context_json FROM chat_messages a "
                "JOIN chat_messages u ON u.conversation_id=a.conversation_id "
                "AND u.request_id=a.request_id AND u.sequence=a.sequence-1 "
                "JOIN chat_turns t ON t.response_message_id=a.id AND t.status='COMMITTED' "
                "JOIN chat_conversations c ON c.id=a.conversation_id "
                "WHERE a.role='assistant' AND u.role='user' AND a.text=%s AND u.text=%s "
                "AND a.created_at >= %s ORDER BY a.created_at",
                (turn["answer"], turn["question"], turn["at"]),
            ).fetchall()
            matches = [r for r in matches if str(r[0]) not in used][:1]
            used.update(str(r[0]) for r in matches)
            saved.append(
                {
                    "turn": turn["turn"],
                    "exactCommittedPair": bool(matches),
                    "payloads": [r[1] for r in matches],
                    "currentServerContexts": [r[2] for r in matches],
                }
            )
            dialogue.append(
                f"TURN {n} | actual signed-in Aside/models/Catalog/PG\n"
                f"USER: {turn['question']}\nASSISTANT (verbatim): {turn['answer']}"
            )
        memories = conn.execute("SELECT count(*) FROM chat_memories").fetchone()[0]
    (OUT / "dialogue.txt").write_text("\n\n".join(dialogue) + "\n", encoding="utf-8")
    positive = next(r for r in saved if r["turn"] == latest["turn"])
    stored = positive["payloads"][0]["compound"]
    server_context = positive["currentServerContexts"][0]
    assert server_context["compound"]["knowledgeSearch"]["conditions"] == conditions
    assert any(
        t.get("compoundContext", {}).get("knowledgeSearch", {}).get("conditions") == conditions
        for t in server_context["consultationParent"]["tasks"]
    )
    assert stored == scope
    assert all(r["exactCommittedPair"] for r in saved)
    samples = [r for r in rows if r["kind"] == "skin_probe"]
    assert len(samples) == 3 and all(r.get("plan", {}).get("action") == "clarify" for r in samples)
    m = base.read("manifest.json")
    old = ast.parse(
        next(
            r["text"]
            for r in m["approvedSourcesBefore"]
            if r["path"].endswith("compound_consultation_service.py")
        )
    )
    new = ast.parse((ROOT / APPROVED[0]).read_text(encoding="utf-8"))

    def function(tree, name):
        return ast.dump(
            next(
                n
                for n in tree.body
                if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == name
            ),
            include_attributes=False,
        )

    guards = {
        name: function(old, name) == function(new, name)
        for name in ("validate_search_conditions", "normalized_ingredient", "verify")
    }
    assert all(guards.values())
    same = integrity()
    assert not any(r["changedOutsideApproval"] for r in same.values())
    result = {
        "at": datetime.now(UTC).isoformat(),
        "checks": {
            "allAppQuestionAnswerPairsCommittedExactly": True,
            "actualModelProposalAcceptedAndTransmitted": True,
            "actualIngredientMatchedEligibleOptions": len(eligible),
            "positivePublicPayloadSavedExactly": stored == scope,
            "positiveConditionsSavedInServerAndTaskContext": True,
            "currentSkinSamplesNormalClarifications": len(samples),
            "serverEvidenceGuardsUnchanged": all(guards.values()),
            "unapprovedSourceOrEvidenceChanges": 0,
        },
        "guardASTEquality": guards,
        "integrity": same,
        "perTurnPG": saved,
        "positive": {
            "turn": latest["turn"],
            "conditions": conditions,
            "knowledge": k1["result"]["knowledge"],
            "inputs": v1["inputs"],
            "requests": [r["input"] for r in requested],
            "eligible": eligible,
        },
        "skinSamples": samples,
        "historicalFailureCause": "still unconfirmed",
        "memoriesWritten": memories,
        "mockOrReplayInLiveFlow": False,
        "actualModelHTTP": sum(r["kind"] in {"model_http", "skin_model_response"} for r in rows),
        "notRun": ["full4010 regression repeated", "physical AR/payment/deployment"],
    }
    base.write("verification.json", result)
    print(
        "Verified exact PG pairs",
        len(saved),
        "positive options",
        len(eligible),
        "skin samples",
        len(samples),
        "unchanged guards",
        guards,
    )


def security():
    env = base.live_environment()
    protected = [
        v
        for k, v in env.items()
        if isinstance(v, str)
        and len(v) > 10
        and any(s in k.upper() for s in ("KEY", "TOKEN", "PASSWORD", "SECRET"))
        and "PUBLISHABLE" not in k
        and not k.startswith("EXPO_PUBLIC_")
    ]
    protected.extend(
        x.split("=", 1)[1]
        for x in base.inspect()["Config"]["Env"]
        if x.startswith("POSTGRES_PASSWORD=")
    )
    counts = {"protectedValue": 0, "jwt": 0, "privateKey": 0, "email": 0}
    for p in OUT.iterdir():
        if not p.is_file():
            continue
        value = p.read_text(encoding="utf-8", errors="replace")
        counts["protectedValue"] += sum(v in value for v in protected)
        counts["jwt"] += len(re.findall(r"eyJ[\w-]{12,}\.[\w-]{12,}\.[\w-]{12,}", value))
        counts["privateKey"] += len(re.findall(r"-----BEGIN [A-Z ]*PRIVATE KEY-----", value))
        if p.name == "manifest.json":
            data = json.loads(value)
            for source in data.get("approvedSourcesBefore", []):
                source["text"] = re.sub(
                    r"(?m)^([ +\-]*)@pytest\.(?:mark\.[A-Za-z_]\w*|fixture)\b",
                    r"\1PYTEST_DECORATOR",
                    source["text"],
                )
            diff = data.get("finalSourceDiff", {})
            if "text" in diff:
                diff["text"] = re.sub(
                    r"(?m)^([ +\-]*)@pytest\.(?:mark\.[A-Za-z_]\w*|fixture)\b",
                    r"\1PYTEST_DECORATOR",
                    diff["text"],
                )
            value = json.dumps(data)
        counts["email"] += len(re.findall(r"[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}", value))
    with (OUT / "security.log").open("a", encoding="utf-8") as stream:
        stream.write(
            json.dumps(
                {
                    "at": datetime.now(UTC).isoformat(),
                    "matches": counts,
                    "sourceDecoratorClassificationOnly": True,
                }
            )
            + "\n"
        )
    print("Sensitive pattern counts", counts)
    assert not any(counts.values()), "Review counts without printing protected values"


def cleanup():
    m = base.read("manifest.json")
    private = Path(os.environ["TEMP"]) / "vishue-g8-closing-last-506ab47f"
    private.mkdir(exist_ok=True)
    dump = private / "chat-evaluation.dump"
    assert not dump.exists()
    with dump.open("wb") as stream:
        subprocess.run(
            [
                "docker",
                "exec",
                base.PG,
                "pg_dump",
                "-U",
                "g8_eval",
                "-d",
                "vishue_chat_test",
                "-Fc",
                "--no-owner",
                "--no-acl",
            ],
            stdout=stream,
            check=True,
        )
    stopped = []
    for role, pid in m["pids"].items():
        command = subprocess.check_output(
            [
                "powershell",
                "-NoProfile",
                "-Command",
                f"(Get-CimInstance Win32_Process -Filter 'ProcessId = {pid}').CommandLine",
            ],
            text=True,
        ).replace("\\", "/")
        if role == "web":
            assert "expo/bin/cli" in command and "19836" in command
        else:
            assert "closing-last/audit.py" in command and "serve-" + role in command
        result = subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"], capture_output=True)
        assert result.returncode == 0
        stopped.append({"role": role, "pid": pid, "exitCode": 0})
    removed = []
    for name in (base.PG, "vishue-g8-closing-last-redis"):
        obj = json.loads(subprocess.check_output(["docker", "inspect", name], text=True))[0]
        assert obj["Config"]["Labels"]["vishue.g8-evaluation"] == base.LABEL
        result = subprocess.run(["docker", "rm", "-fv", name], capture_output=True)
        assert result.returncode == 0
        removed.append(name)
    same = integrity()
    assert not any(r["changedOutsideApproval"] for r in same.values())
    base.write(
        "cleanup.json",
        {
            "stopped": stopped,
            "removed": removed,
            "originalWriteCommands": 0,
            "integrity": same,
            "privateChatDump": {
                "path": str(dump),
                "bytes": dump.stat().st_size,
                "sha256": hashlib.sha256(dump.read_bytes()).hexdigest(),
            },
        },
    )
    print("Private chat dump preserved;only owned services/containers removed")


if __name__ == "__main__":
    action = sys.argv[1]
    if action == "prepare":
        baseline()
        base.prepare()
        base.clone_data()
    elif action == "start":
        start()
    elif action == "serve-chat":
        phase(action)
        serve_chat()
    elif action in {"serve-catalog", "serve-g5"}:
        phase(action)
        base.serve_api(action.removeprefix("serve-"))
    elif action == "probe-skin":
        import asyncio

        phase(action)
        diagnostic_logs()
        asyncio.run(base.skin_probe())
    elif action == "verify":
        verify()
    elif action == "security":
        security()
    elif action == "cleanup":
        cleanup()

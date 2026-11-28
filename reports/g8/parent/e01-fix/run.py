"""Observe original and fixed E01 sources over a retained, isolated Catalog dump."""

import importlib.util
import json
import os
import secrets
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
OUT = Path(__file__).resolve().parent
PRIOR = OUT.parent / "closing4"
sys.path.insert(0, str(PRIOR))
import prepare_data as data  # noqa: E402 -- shared approved preparation harness

data.PG = "vishue-g8-e01-pg"
data.REDIS = "vishue-g8-e01-redis"
data.LABEL = "e01-fix-506ab47f"
data.OUT = OUT
data.DATABASES = {
    "catalog": "vishue_g8_e01_catalog",
    "g5": "vishue_g8_e01_catalog",
    "chat": "vishue_g8_e01_chat",
}
spec = importlib.util.spec_from_file_location("observed_runtime", PRIOR / "runtime.py")
legacy = importlib.util.module_from_spec(spec)
spec.loader.exec_module(legacy)
legacy.OUT = OUT


def phase():
    return json.loads((OUT / "manifest.json").read_text(encoding="utf-8")).get("phase", "before")


def emit(kind, **values):
    from datetime import UTC, datetime

    with (OUT / f"trace-{phase()}.jsonl").open("a", encoding="utf-8") as stream:
        stream.write(
            json.dumps(
                {
                    "at": datetime.now(UTC).isoformat(),
                    "kind": kind,
                    "turn": legacy.TURN.get(),
                    **values,
                },
                ensure_ascii=False,
                default=str,
            )
            + "\n"
        )


legacy.emit = emit


def environment(role="chat"):
    env = legacy.environment(role)
    # Focused E01 needs neither G5 corpus nor paid knowledge calls.
    env["G5_ENABLED"] = "false"
    env["G5_ALLOW_LOCAL_SOURCES"] = "false"
    return env


def logged(command, **kwargs):
    with (OUT / "preparation.log").open("ab") as stream:
        result = subprocess.run(command, stdout=stream, stderr=stream, **kwargs)
    assert result.returncode == 0, "Preparation failed; see scoped log"


def prepare():
    import hashlib

    source = json.loads((PRIOR / "manifest.json").read_text(encoding="utf-8"))
    dump = Path(next(d["privatePath"] for d in source["dumps"] if d["role"] == "catalog"))
    private = dump.parent / "e01-fix"
    private.mkdir(exist_ok=True)
    baseline = [
        *PRIOR.glob("*"),
        *OUT.parent.glob("stage6-investigation-*"),
        ROOT / "docs/ai-design/G8-WORKLOG.md",
        ROOT / "docs/ai-design/G8-IMPLEMENTATION-SPEC.md",
    ]
    data.record(
        sourceHead=subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True
        ).strip(),
        phase="before",
        baselineFiles=[
            {
                "path": p.relative_to(ROOT).as_posix(),
                "sha256": hashlib.sha256(p.read_bytes()).hexdigest(),
            }
            for p in baseline
            if p.is_file()
        ],
        originalWrites=0,
        sourceDump={
            "path": str(dump),
            "sha256": next(d["sha256"] for d in source["dumps"] if d["role"] == "catalog"),
        },
    )
    assert (
        subprocess.run(
            ["docker", "inspect", data.PG], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
        ).returncode
        != 0
    )
    logged(
        [
            "docker",
            "run",
            "-d",
            "--name",
            data.PG,
            "--label",
            f"vishue.g8-evaluation={data.LABEL}",
            "-e",
            "POSTGRES_USER=g8_eval",
            "-e",
            "POSTGRES_PASSWORD=" + secrets.token_urlsafe(32),
            "-p",
            "127.0.0.1::5432",
            "pgvector/pgvector:0.8.2-pg17-bookworm",
        ]
    )
    for _ in range(60):
        if (
            subprocess.run(
                ["docker", "exec", data.PG, "pg_isready", "-h", "127.0.0.1", "-U", "g8_eval"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            ).returncode
            == 0
        ):
            break
        time.sleep(0.5)
    else:
        raise AssertionError("PG readiness failed")
    logged(["docker", "cp", str(dump), data.PG + ":/tmp/catalog.dump"])
    toc = subprocess.check_output(
        ["docker", "exec", data.PG, "pg_restore", "-l", "/tmp/catalog.dump"], text=True
    )
    lines = [
        line
        for line in toc.splitlines()
        if not (" TABLE DATA " in line and " public aihub_" in line)
    ]
    listing = private / "catalog-e01.list"
    listing.write_text("\n".join(lines) + "\n", encoding="utf-8")
    logged(["docker", "cp", str(listing), data.PG + ":/tmp/catalog-e01.list"])
    for name in dict.fromkeys(data.DATABASES.values()):
        logged(["docker", "exec", data.PG, "createdb", "-U", "g8_eval", name])
    logged(
        [
            "docker",
            "exec",
            data.PG,
            "pg_restore",
            "-U",
            "g8_eval",
            "-d",
            data.DATABASES["catalog"],
            "--no-owner",
            "--no-acl",
            "--exit-on-error",
            "-L",
            "/tmp/catalog-e01.list",
            "/tmp/catalog.dump",
        ]
    )
    for role in ("api", "chat"):
        folder = ROOT / "backend" / ("chatbot" if role == "chat" else "api")
        env = dict(
            os.environ,
            PYTHONUTF8="1",
            PYTHONDONTWRITEBYTECODE="1",
            SKINCARE_REFRESH_ENABLED="false",
        )
        env["CHAT_DATABASE_URL" if role == "chat" else "DATABASE_URL"] = data.clone_url(
            data.DATABASES["chat" if role == "chat" else "catalog"]
        ).render_as_string(hide_password=False)
        py = str(folder / ".venv/Scripts/python.exe")
        logged([py, "-B", "-m", "alembic", "upgrade", "head"], cwd=folder, env=env)
        if role == "api":
            logged([py, "-B", "-m", "app.jobs.load_makeup_look_catalog"], cwd=folder, env=env)
            logged(
                [py, "-B", "-m", "app.jobs.load_makeup_look_catalog", "--write"],
                cwd=folder,
                env=env,
            )
        else:
            logged([py, "-B", "-m", "app.jobs.init_chat_checkpoints"], cwd=folder, env=env)
    logged(
        [
            "docker",
            "run",
            "-d",
            "--name",
            data.REDIS,
            "--label",
            f"vishue.g8-evaluation={data.LABEL}",
            "-p",
            "127.0.0.1::6379",
            "redis:7-alpine",
            "redis-server",
            "--save",
            "",
            "--appendonly",
            "no",
        ]
    )
    data.record(
        prepared=True,
        omittedData="aihub_* rows only; complete Catalog/option/look data retained; G5 OFF",
        sourceMetadata=data.source_metadata(),
        styleFault=True,
    )
    print("Prepared isolated E01 Catalog/chat/Redis; no original writes", flush=True)


def old_scope_components(req):
    from app.services.consultation_memory import ignores_memory

    beauty = req.chat_context
    return {
        "catalog": {
            "product": beauty.selected_product_id if beauty else None,
            "option": beauty.selected_option_id if beauty else None,
            "style": req.style_context.model_dump(mode="json") if req.style_context else None,
            "conditions": [c.model_dump(mode="json") for c in req.style_conditions or []],
            "screenProduct": req.screen_context.product_id
            if req.screen_context
            else beauty.selected_product_id
            if beauty
            else None,
            "screenOption": req.screen_context.option_id
            if req.screen_context
            else beauty.selected_option_id
            if beauty
            else None,
        },
        "memoryEpoch": req._memory_epoch,
        "memoryGeneration": req._memory_generation,
        "memoryAvailable": req._consultation_memories is not None,
        "ignoreMemory": ignores_memory(req.message),
        "memoryRefs": sorted((str(m.id), m.version) for m in req._consultation_memories or ()),
    }


def probes():
    from app.services import beauty_consultation_service as beauty
    from app.services import chat_service
    from app.services import consultation_parent_graph as parent
    from app.services import product_style_consultation_service as pair
    from app.services.consultation_task_adapter import fingerprint

    original = beauty.interpret_beauty

    async def interpreted(req, *args, **kwargs):
        plan = await original(req, *args, **kwargs)
        emit(
            "search_plan",
            message=req.message,
            parentOperation=req._product_operation,
            context=req.chat_context.model_dump(mode="json", exclude={"session"})
            if req.chat_context
            else None,
            screen=req.screen_context.model_dump(mode="json") if req.screen_context else None,
            plan=plan.model_dump(mode="json", by_alias=True),
            directComparison=beauty.direct_comparison(req, plan),
        )
        return plan

    beauty.interpret_beauty = chat_service.interpret_beauty = pair.interpret_beauty = interpreted
    scope = parent.task_scope

    def scoped(req, *args, **kwargs):
        digest = scope(req, *args, **kwargs)
        components = (
            parent.task_scope_components(req, *args, **kwargs)
            if hasattr(parent, "task_scope_components")
            else old_scope_components(req)
        )
        assert fingerprint(components) == digest
        emit("scope", digest=digest, components=components, requestType=req.request_type)
        return digest

    parent.task_scope = scoped


def start():
    import hashlib

    assert json.loads((OUT / "manifest.json").read_text(encoding="utf-8"))["prepared"]
    paths = [
        ROOT / p
        for p in (
            "backend/chatbot/app/schemas/supervisor.py",
            "backend/chatbot/app/schemas/consultation_parent.py",
            "backend/chatbot/app/services/beauty_consultation_service.py",
            "backend/chatbot/app/services/consultation_parent_graph.py",
            "backend/chatbot/app/services/consultation_intent_service.py",
        )
    ]
    sources = [
        {
            "path": p.relative_to(ROOT).as_posix(),
            "sha256": hashlib.sha256(p.read_bytes()).hexdigest(),
        }
        for p in paths
    ]
    data.record(sources=sources, **{phase() + "Sources": sources})
    pids = {}
    for role in ("api", "proxy", "chat"):
        folder = ROOT / "backend" / ("chatbot" if role == "chat" else "api")
        with (OUT / "runtime.log").open("ab") as log:
            pids[role] = subprocess.Popen(
                [
                    str(folder / ".venv/Scripts/python.exe"),
                    "-B",
                    str(Path(__file__).resolve()),
                    role,
                ],
                cwd=folder,
                env=environment(role),
                stdout=log,
                stderr=log,
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
    with (OUT / "runtime.log").open("ab") as log:
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
            stdout=log,
            stderr=log,
            creationflags=subprocess.CREATE_NO_WINDOW,
        ).pid
    data.record(pids=pids)
    print("Started focused", phase(), "services", pids)


def stop():
    manifest = json.loads((OUT / "manifest.json").read_text(encoding="utf-8"))
    outcomes = []
    for role, pid in manifest.get("pids", {}).items():
        result = subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"], capture_output=True)
        outcomes.append({"role": role, "pid": pid, "exitCode": result.returncode})
    data.record(**{phase() + "Stopped": outcomes})
    print("Stopped only evaluation services", phase())


if __name__ == "__main__":
    action = sys.argv[1]
    if action == "prepare":
        prepare()
    elif action == "start":
        start()
    elif action == "stop":
        stop()
    elif action in ("fault-on", "fault-off"):
        data.record(styleFault=action == "fault-on")
        print(action)
    else:
        os.environ.update(environment(action))
        if action == "chat":
            sys.path.insert(0, str(ROOT / "backend/chatbot"))
            probes()
        legacy.serve(action)

"""Approved closing evaluation over isolated retained dumps; no original DB writes."""

import hashlib
import importlib.util
import json
import os
import secrets
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
OUT = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("e01_harness", OUT.parent / "e01-fix/run.py")
base = importlib.util.module_from_spec(spec)
spec.loader.exec_module(base)
data, legacy = base.data, base.legacy
base.OUT = data.OUT = legacy.OUT = OUT
data.PG, data.REDIS, data.LABEL = (
    "vishue-g8-closing5-pg",
    "vishue-g8-closing5-redis",
    "closing5-506ab47f",
)
data.DATABASES = {
    "catalog": "vishue_g8_closing5_catalog",
    "chat": "vishue_g8_closing5_chat",
    "g5": "vishue_g8_closing5_knowledge",
}


def manifest():
    return json.loads((OUT / "manifest.json").read_text(encoding="utf-8"))


def emit(kind, **values):
    with (OUT / "trace.jsonl").open("a", encoding="utf-8") as stream:
        stream.write(
            json.dumps(
                {
                    "at": datetime.now(UTC).isoformat(),
                    "phase": manifest().get("phase", "diagnostic"),
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
    env["G5_ENABLED"] = "true"
    return env


def prepare():
    import time

    OUT.mkdir(exist_ok=True)
    prior = json.loads((base.PRIOR / "manifest.json").read_text(encoding="utf-8"))
    original = data.source_metadata()
    preserved = [
        *base.PRIOR.glob("*"),
        *(OUT.parent / "e01-fix").glob("*"),
        *OUT.parent.glob("stage6-investigation-*"),
    ]
    data.record(
        sourceHead=subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True
        ).strip(),
        phase="diagnostic",
        originalMetadata=original,
        originalWrites=0,
        dumps=prior["dumps"],
        baselineFiles=[
            {
                "path": p.relative_to(ROOT).as_posix(),
                "sha256": hashlib.sha256(p.read_bytes()).hexdigest(),
            }
            for p in preserved
            if p.is_file()
        ],
    )
    assert subprocess.run(["docker", "inspect", data.PG], capture_output=True).returncode != 0
    base.logged(
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
                ["docker", "exec", data.PG, "pg_isready", "-U", "g8_eval"], capture_output=True
            ).returncode
            == 0
        ):
            break
        time.sleep(0.5)
    else:
        raise AssertionError("PG not ready")
    for name in data.DATABASES.values():
        base.logged(["docker", "exec", data.PG, "createdb", "-U", "g8_eval", name])
    for role in ("catalog", "g5"):
        item = next(d for d in prior["dumps"] if d["role"] == role)
        dump = Path(item["privatePath"])
        with dump.open("rb") as stream:
            assert hashlib.file_digest(stream, "sha256").hexdigest() == item["sha256"]
        base.logged(["docker", "cp", str(dump), data.PG + f":/tmp/{role}.dump"])
        command = [
            "docker",
            "exec",
            data.PG,
            "pg_restore",
            "-U",
            "g8_eval",
            "-d",
            data.DATABASES[role],
            "--no-owner",
            "--no-acl",
            "--exit-on-error",
        ]
        if role == "catalog":
            toc = subprocess.check_output(
                ["docker", "exec", data.PG, "pg_restore", "-l", "/tmp/catalog.dump"], text=True
            )
            private = dump.parent / "closing5"
            private.mkdir(exist_ok=True)
            listing = private / "catalog.list"
            listing.write_text(
                "\n".join(
                    line
                    for line in toc.splitlines()
                    if not (" TABLE DATA " in line and " public aihub_" in line)
                )
                + "\n",
                encoding="utf-8",
            )
            base.logged(["docker", "cp", str(listing), data.PG + ":/tmp/catalog.list"])
            command += ["-L", "/tmp/catalog.list"]
        base.logged([*command, f"/tmp/{role}.dump"])
    for role, database in data.DATABASES.items():
        folder = ROOT / "backend" / ("chatbot" if role == "chat" else "api")
        py = str(folder / ".venv/Scripts/python.exe")
        env = dict(
            os.environ,
            PYTHONUTF8="1",
            PYTHONDONTWRITEBYTECODE="1",
            SKINCARE_REFRESH_ENABLED="false",
        )
        env["CHAT_DATABASE_URL" if role == "chat" else "DATABASE_URL"] = data.clone_url(
            database
        ).render_as_string(hide_password=False)
        if role == "g5":
            checks = prior["g5LegacySchemaChecks"]
            assert len(checks) == 3 and all(c["equal"] for c in checks)
            assert data.psql(data.PG, database, "SELECT version_num FROM alembic_version") == "0030"
            # Same immutable dump and migrations as the earlier exact schema comparison.
            base.logged([py, "-B", "-m", "alembic", "stamp", "0032"], cwd=folder, env=env)
            data.record(g5LegacyChecksReused=checks)
        base.logged([py, "-B", "-m", "alembic", "upgrade", "head"], cwd=folder, env=env)
        if role == "catalog":
            base.logged(
                [py, "-B", "-m", "app.jobs.load_makeup_look_catalog", "--write"],
                cwd=folder,
                env=env,
            )
        if role == "chat":
            base.logged([py, "-B", "-m", "app.jobs.init_chat_checkpoints"], cwd=folder, env=env)
    base.logged(
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
    data.record(prepared=True, styleFault=False)
    print("Prepared isolated Catalog, knowledge and chat databases", flush=True)


def probes():
    from app.clients.llm_client import LlmClient
    from app.services import consultation_intent_service as parent
    from app.services import knowledge_service as knowledge

    original_validate, original_resolve = parent.validate_intent, knowledge.resolve
    original_choose = LlmClient.complete_with_tools

    async def choose(self, *args, **kwargs):
        result, elapsed = await original_choose(self, *args, **kwargs)
        emit("model_tool_output", tool=kwargs.get("required_tool"), result=result)
        return result, elapsed

    LlmClient.complete_with_tools = choose

    def validate(proposal, req):
        try:
            result = original_validate(proposal, req)
            emit(
                "parent_validation",
                status="accepted",
                proposal=proposal.model_dump(mode="json", by_alias=True),
                result=result.model_dump(mode="json", by_alias=True),
            )
            return result
        except ValueError as exc:
            from pydantic import ValidationError

            reason = (
                [{"type": e["type"], "loc": e["loc"]} for e in exc.errors(include_input=False)]
                if isinstance(exc, ValidationError)
                else str(exc)
            )
            emit(
                "parent_validation",
                status="rejected",
                reason=reason,
                proposal=proposal.model_dump(mode="json", by_alias=True),
            )
            raise

    def resolve(draft, audit, evidence, **kwargs):
        result = original_resolve(draft, audit, evidence, **kwargs)
        emit(
            "knowledge_resolution",
            draft=draft,
            audit=audit,
            final=result.model_dump(mode="json", by_alias=True),
            coverage=kwargs["coverage"].model_dump() if kwargs.get("coverage") else None,
        )
        return result

    parent.validate_intent, knowledge.resolve = validate, resolve
    from app.services import owned_look_consultation_service as owned
    from app.services import owned_look_interpreter as interpreter

    original_interpret = interpreter.interpret

    async def interpret(message, refs, question, llm, **kwargs):
        result, audit = await original_interpret(message, refs, question, llm, **kwargs)
        emit(
            "ownership_interpretation",
            message=message,
            answeringQuestion=kwargs.get("answering_question", False),
            result=result.model_dump(mode="json", by_alias=True),
            audit=audit,
        )
        return result, audit

    interpreter.interpret = interpret
    assert owned.owned_look_interpreter is interpreter


def start():
    phase = manifest()["phase"]
    paths = [
        "backend/chatbot/app/services/" + n + ".py"
        for n in (
            "consultation_intent_service",
            "owned_look_consultation_service",
            "knowledge_service",
        )
    ]
    sources = [
        {"path": p, "sha256": hashlib.sha256((ROOT / p).read_bytes()).hexdigest()} for p in paths
    ]
    data.record(**{phase + "Sources": sources})
    pids = {}
    for role in ("api", "proxy", "g5", "chat"):
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
    print("Started", phase, "evaluation services", flush=True)


async def parent_probe():
    from app.clients.llm_client import get_llm_client
    from app.schemas.chat import ChatRequest
    from app.schemas.consultation_parent import ConsultationParent
    from app.services.consultation_intent_service import prepare_turn

    prior = [
        json.loads(line)
        for line in (OUT.parent / "e01-fix/trace-after.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
    ]
    turns = [row for row in prior if row["kind"] == "turn_end"]
    rejected = next(
        row
        for row in turns
        if any(t.get("parentIntent", {}).get("status") == "rejected_proposal" for t in row["tasks"])
    )
    plan_id = rejected["parent"]["planId"]
    context = next(row["parent"] for row in turns if row["parent"]["planId"] == plan_id)
    legacy.observe_http("parent_probe")
    results = []
    for index in range(3):
        req = ChatRequest(
            message=rejected["question"], locale="ko", request_type="beauty_consultation"
        )
        req._consultation_parent = ConsultationParent.model_validate(context)
        token = legacy.TURN.set("parent-probe-" + str(index + 1))
        result = await prepare_turn(req, get_llm_client())
        results.append(
            {
                "sample": index + 1,
                "audit": req._parent_intent_audit,
                "answer": result.answer if result else None,
            }
        )
        emit("parent_probe", **results[-1])
        legacy.TURN.reset(token)
    prior_path = OUT / "parent-rejection.json"
    history = json.loads(prior_path.read_text(encoding="utf-8")) if prior_path.exists() else {}
    runs = history.get("runs", [history] if history else [])
    runs.append(
        {
            "phase": manifest()["phase"],
            "samples": results,
            "sources": manifest().get(manifest()["phase"] + "Sources"),
        }
    )
    prior_path.write_text(
        json.dumps(
            {
                "question": rejected["question"],
                "fixedContext": context,
                "configuredMode": "live",
                "runs": runs,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    print("Recorded three fixed-context parent model samples")


async def skin_probe():
    from app.clients.llm_client import get_llm_client
    from app.schemas.chat import ChatRequest
    from app.services.compound_consultation_graph import interpret

    legacy.observe_http("skin_probe")
    llm = get_llm_client()
    original = llm.complete_with_tools

    async def observed(*args, **kwargs):
        result, elapsed = await original(*args, **kwargs)
        emit("skin_plan_output", result=result)
        return result, elapsed

    llm.complete_with_tools = observed
    req = ChatRequest(
        message="오후에 화장이 뜨는데 원인 알려주고 나한테 맞는 제품도 찾아줘",
        locale="ko",
        request_type="beauty_consultation",
    )
    try:
        result = await interpret(req, llm, None)
        emit(
            "skin_plan_probe",
            result=result.model_dump(mode="json", by_alias=True) if result else None,
        )
        print("Skin plan probe accepted")
    except Exception as exc:
        cause = exc.__cause__ or exc
        emit(
            "skin_plan_probe",
            code=getattr(exc, "code", None),
            causeType=type(cause).__name__,
            cause=str(cause),
        )
        print("Skin plan probe rejected:", type(cause).__name__)


async def knowledge_probe():
    from app.services import knowledge_service

    rows = [
        json.loads(line) for line in (OUT / "trace.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    source = [row for row in rows if row["kind"] == "knowledge_resolution"][-1]
    plan = next(
        row
        for row in rows
        if row["kind"] == "model_tool_output"
        and row.get("turn") == source["turn"]
        and row["tool"] == "plan_skin_consultation"
    )
    args = json.loads(
        plan["result"]["choices"][0]["message"]["tool_calls"][0]["function"]["arguments"]
    )
    legacy.observe_http("chat")
    legacy.observe_chat()
    token = legacy.TURN.set("knowledge-probe")
    emit(
        "knowledge_probe_start",
        question=args["question"],
        originalTurn=source["turn"],
        mode="live G5-only diagnostic; not app/PG turn",
    )
    result = await knowledge_service.consult_knowledge(
        args["question"], delegation_scope="explanation"
    )
    emit(
        "knowledge_probe_end",
        question=args["question"],
        status=result.reply.status,
        trace=result.trace,
    )
    legacy.TURN.reset(token)
    print("Recorded original G5 question diagnostic:", result.reply.status)


if __name__ == "__main__":
    action = sys.argv[1]
    if action in {"prepare", "start"}:
        globals()[action]()
    elif action == "stop":
        base.stop()
    elif action == "probe-parent":
        import asyncio

        os.environ.update(environment())
        sys.path.insert(0, str(ROOT / "backend/chatbot"))
        probes()
        asyncio.run(parent_probe())
    elif action == "probe-skin":
        import asyncio

        os.environ.update(environment())
        sys.path.insert(0, str(ROOT / "backend/chatbot"))
        asyncio.run(skin_probe())
    elif action == "probe-knowledge":
        import asyncio

        os.environ.update(environment())
        sys.path.insert(0, str(ROOT / "backend/chatbot"))
        probes()
        asyncio.run(knowledge_probe())
    else:
        os.environ.update(environment(action))
        if action == "chat":
            sys.path.insert(0, str(ROOT / "backend/chatbot"))
            probes()
        legacy.serve(action)

"""Validation-only launch/observation; production modules are imported unchanged."""

import importlib.util
import json
import os
import subprocess
import sys
import time
from contextvars import ContextVar
from datetime import UTC, datetime
from pathlib import Path

import prepare_data as data

ROOT, OUT = data.ROOT, data.OUT
PORTS = {"chat": 19833, "api": 19834, "proxy": 19835, "web": 19836, "g5": 19838}
TURN = ContextVar("closing4_turn", default=None)


def emit(kind, **values):
    with (OUT / "trace.jsonl").open("a", encoding="utf-8") as stream:
        stream.write(
            json.dumps(
                {"at": datetime.now(UTC).isoformat(), "kind": kind, "turn": TURN.get(), **values},
                ensure_ascii=False,
                default=str,
            )
            + "\n"
        )


def environment(role="chat"):
    spec = importlib.util.spec_from_file_location(
        "previous_runtime", OUT.parent / "stage6-remediation-runtime.py"
    )
    previous = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(previous)
    env = previous.environment()
    if role == "g5":
        env["G5_ALLOW_LOCAL_SOURCES"] = "true"
    env.setdefault("NEO4J_USER", "neo4j")
    if not env.get("NEO4J_PASSWORD"):
        auth = data.container_env("vishue-neo4j-1").get("NEO4J_AUTH", "")
        if "/" in auth:
            env["NEO4J_USER"], env["NEO4J_PASSWORD"] = auth.split("/", 1)
    env.update(
        DATABASE_URL=data.clone_url(
            data.DATABASES["g5" if role == "g5" else "catalog"]
        ).render_as_string(hide_password=False),
        CHAT_DATABASE_URL=data.clone_url(data.DATABASES["chat"]).render_as_string(
            hide_password=False
        ),
        CATALOG_API_URL="http://127.0.0.1:19835",
        PYTHONDONTWRITEBYTECODE="1",
    )
    redis = data.inspect(data.REDIS)
    assert redis["Config"]["Labels"]["vishue.g8-evaluation"] == data.LABEL
    port = redis["NetworkSettings"]["Ports"]["6379/tcp"][0]["HostPort"]
    env["REDIS_URL"] = f"redis://127.0.0.1:{port}/0"
    return env


def observe_http(role):
    import httpx

    original_async, original_sync = httpx.AsyncClient.send, httpx.Client.send

    def start(request):
        if request.url.host == "api.openai.com":
            body = json.loads(request.content)
            record = {
                "role": role,
                "mode": "live",
                "path": request.url.path,
                "model": body.get("model"),
            }
            emit("model_start", **record)
            return record
        return None

    async def send(self, request, *args, **kwargs):
        model = start(request)
        is_catalog = role == "chat" and request.url.port in (19834, 19835, 19838)
        try:
            response = await original_async(self, request, *args, **kwargs)
            if model:
                emit("model_end", **model, status=response.status_code)
            if is_catalog:
                await response.aread()
                emit(
                    "tool_http",
                    role=role,
                    method=request.method,
                    path=request.url.path,
                    query=dict(request.url.params),
                    input=json.loads(request.content) if request.content else None,
                    status=response.status_code,
                    result=response.json(),
                )
            return response
        except Exception as exc:
            emit("http_error", role=role, path=request.url.path, error=type(exc).__name__)
            raise

    def sync(self, request, *args, **kwargs):
        model = start(request)
        response = original_sync(self, request, *args, **kwargs)
        if model:
            emit("model_end", **model, status=response.status_code)
        return response

    httpx.AsyncClient.send, httpx.Client.send = send, sync


def observe_chat():
    import hashlib

    import httpx
    from app.clients.knowledge_client import KnowledgeClient
    from app.services.chat_service import ChatService

    original_init = KnowledgeClient.__init__

    def knowledge_init(self, http):
        http.base_url = httpx.URL("http://127.0.0.1:19838/internal/knowledge/")
        original_init(self, http)

    KnowledgeClient.__init__ = knowledge_init
    original = ChatService.answer

    async def answer(self, req, *args, **kwargs):
        import traceback

        started = time.monotonic()
        alias = hashlib.sha256((req.message + str(time.time_ns())).encode()).hexdigest()[:12]
        token = TURN.set(alias)
        emit(
            "turn_start",
            question=req.message,
            requestType=req.request_type,
            hasStyleContext=req.style_context is not None,
            configuredMode="live",
        )
        try:
            response = await original(self, req, *args, **kwargs)
            emit(
                "turn_end",
                question=req.message,
                answer=response.answer,
                ms=round((time.monotonic() - started) * 1000, 1),
                products=[p.model_dump(mode="json", by_alias=True) for p in response.products],
                consultation=response.consultation.model_dump(mode="json", by_alias=True)
                if response.consultation
                else None,
                parent=response._consultation_parent.model_dump(mode="json", by_alias=True)
                if response._consultation_parent
                else None,
                tasks=response._parent_trace,
                ownedLookContext=response._owned_look_context.model_dump(mode="json", by_alias=True)
                if response._owned_look_context
                else None,
                options=response.owned_look_options.model_dump(mode="json", by_alias=True)
                if response.owned_look_options
                else None,
                styleCandidates=[
                    c.model_dump(mode="json", by_alias=True)
                    for c in response.style_candidates or []
                ],
                sessionStatus=response.session_status,
            )
            return response
        except Exception as exc:
            emit(
                "turn_error",
                question=req.message,
                code=getattr(exc, "code", type(exc).__name__),
                frames=[
                    {"file": Path(f.filename).name, "line": f.lineno, "function": f.name}
                    for f in traceback.extract_tb(exc.__traceback__)
                ],
            )
            raise
        finally:
            TURN.reset(token)

    ChatService.answer = answer


def serve(role):
    import httpx
    import uvicorn

    if role == "proxy":
        from fastapi import FastAPI, Request
        from fastapi.responses import JSONResponse, Response

        app = FastAPI()

        @app.api_route("/{path:path}", methods=["GET", "POST", "DELETE", "PATCH"])
        async def forward(path: str, request: Request):
            manifest = json.loads((OUT / "manifest.json").read_text(encoding="utf-8"))
            if manifest.get("styleFault") and request.url.path == "/api/style-looks":
                emit(
                    "injected_fault",
                    method=request.method,
                    path=request.url.path,
                    status=503,
                    mode="controlled HTTP; not spontaneous service failure",
                )
                return JSONResponse(
                    {"error": "Validation-only Style unavailable", "code": "upstream_unavailable"},
                    status_code=503,
                )
            async with httpx.AsyncClient(timeout=60) as client:
                response = await client.request(
                    request.method,
                    "http://127.0.0.1:19834/" + path,
                    params=request.query_params,
                    content=await request.body(),
                    headers={
                        k: v
                        for k, v in request.headers.items()
                        if k.lower() not in ("host", "content-length")
                    },
                )
            return Response(
                response.content,
                status_code=response.status_code,
                headers={"content-type": response.headers.get("content-type", "application/json")},
            )
    else:
        directory = ROOT / "backend" / ("chatbot" if role == "chat" else "api")
        sys.path.insert(0, str(directory))
        observe_http(role)
        if role == "chat":
            observe_chat()
        from app.main import create_app

        app = create_app()
        if role == "chat":
            from fastapi import Request

            replay = {}

            @app.middleware("http")
            async def observe(request: Request, call_next):
                started = time.monotonic()
                path = request.url.path
                if request.method == "POST" and path == "/api/chat":
                    body = await request.body()
                    if "지금 바로 얼굴에 발라주고 내 기억에도 저장해" in body.decode():
                        replay.update(
                            path=path,
                            body=body,
                            headers={
                                "authorization": request.headers.get("authorization", ""),
                                "content-type": "application/json",
                            },
                        )
                response = await call_next(request)
                if path.startswith("/api/chat"):
                    import re

                    emit(
                        "chat_http",
                        method=request.method,
                        path=re.sub(r"[0-9a-f]{8}-[0-9a-f-]{27,}", "{id}", path),
                        status=response.status_code,
                        ms=round((time.monotonic() - started) * 1000, 1),
                    )
                return response

            @app.post("/__eval/replay")
            async def same_request_replay():
                assert replay, "No approved synthetic B01 message observed"
                async with httpx.AsyncClient(timeout=90) as client:
                    response = await client.post(
                        "http://127.0.0.1:19833" + replay["path"],
                        content=replay["body"],
                        headers=replay["headers"],
                    )
                emit("same_request_replay", status=response.status_code, result=response.json())
                return {"status": response.status_code, "result": response.json()}

    uvicorn.run(app, host="127.0.0.1", port=PORTS[role], access_log=False, log_level="warning")


def start():
    import hashlib
    import socket

    assert json.loads((OUT / "manifest.json").read_text(encoding="utf-8"))["prepared"]
    for port in PORTS.values():
        with socket.socket() as sock:
            assert sock.connect_ex(("127.0.0.1", port)) != 0, "Existing listener left untouched"
    env = environment()
    sources = []
    for pattern in (
        "backend/api/app/**/*.py",
        "backend/chatbot/app/**/*.py",
        "app/**/*.tsx",
        "hooks/*.ts",
        "lib/api.ts",
    ):
        for path in ROOT.glob(pattern):
            sources.append(
                {
                    "path": path.relative_to(ROOT).as_posix(),
                    "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                }
            )
    pids = {}
    for role in ("api", "g5", "proxy", "chat"):
        folder = ROOT / "backend" / ("chatbot" if role == "chat" else "api")
        with (OUT / "runtime.log").open("ab") as log:
            proc = subprocess.Popen(
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
            )
        pids[role] = proc.pid
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
    data.record(
        pids=pids,
        ports=PORTS,
        sources=sources,
        styleFault=False,
        configuredModel=env["LLM_MODEL"],
        configuredMode="live",
        startedAt=datetime.now(UTC).isoformat(),
    )
    print("Started scoped services", pids)


if __name__ == "__main__":
    action = sys.argv[1]
    if action == "start":
        start()
    elif action in ("fault-on", "fault-off"):
        data.record(styleFault=action == "fault-on")
        print("Controlled Style HTTP fault", action)
    else:
        serve(action)

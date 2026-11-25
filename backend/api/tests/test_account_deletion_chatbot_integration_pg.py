"""Run with disposable migrated API and chatbot databases and a dedicated local Redis."""

import asyncio
import json
import os
import sys
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from pathlib import Path
from secrets import token_hex
from urllib.parse import urlsplit
from uuid import uuid4

import httpx
import pytest
from pydantic import SecretStr
from sqlalchemy import delete, select, update
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.clients.chatbot_deletion_client import delete_chatbot_account
from app.core.config import get_settings
from app.core.errors import ApiError
from app.models.account_deletion import AccountDeletionJobRow
from app.models.member import MemberRow
from app.repositories.account_deletion_repository import AccountDeletionRepository
from app.services.account_deletion_service import (
    AccountDeletionService,
    build_local_deletion_worker,
)
from app.services.member_service import TERMS_VERSION
from tests.test_account_deletion_public_api_pg import member_app

API_DB = os.environ.get("TEST_G7_ACCOUNT_DELETION_DATABASE_URL")
CHAT_DB = os.environ.get("TEST_CHAT_DATABASE_URL")
CHAT_REDIS = os.environ.get("TEST_CHAT_REDIS_URL")
LOCAL_HOSTS = {"127.0.0.1", "localhost", "::1"}
CHATBOT_ROOT = Path(__file__).resolve().parents[2] / "chatbot"
DELETION_PATH = "/internal/g7/account-deletion"
pytestmark = pytest.mark.anyio


async def test_worker_refuses_a_nonlocal_database(monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "env", "test")
    monkeypatch.setattr(settings, "database_url", "postgresql+asyncpg://192.0.2.10/vishue")
    monkeypatch.setattr(settings, "g7_local_supabase_url", "http://127.0.0.1:8000")
    monkeypatch.setattr(settings, "g7_local_supabase_secret_key", SecretStr(token_hex(32)))
    with pytest.raises(ApiError) as failed:
        build_local_deletion_worker()
    assert failed.value.code == "account_deletion_unavailable"


# Both services use an `app` package. Serve the chatbot on loopback in its own process.
CHATBOT_SCRIPT = """
import asyncio
import json
import os
import socket
import sys
from uuid import UUID, uuid4

import psycopg
import uvicorn
from sqlalchemy.engine import make_url

sys.path.insert(0, sys.argv[1])

from app.core.db import get_chat_sessionmaker
from app.core.ratelimit import get_redis
from app.main import app
from app.models.conversation import ChatConversation, ChatMemory, ChatMessage, ChatOwnerStatus
from app.repositories.chat_session_repository import get_chat_sessions
from app.services.chat_service import ChatService
from tests.test_beauty_consultation import PlanLlm
from tests.test_chat_sessions import SessionCatalog, request
from tests.test_g7_owner_deletion_pg import checkpoint_exists, seed_owner


async def seed(owner_id):
    ids = [str(value) for value in await seed_owner(owner_id)]
    repo = get_chat_sessions()
    service = ChatService(
        None, PlanLlm(intent="search", category="lip"), SessionCatalog(), sessions=repo
    )
    principal, request_id = f"user:{owner_id}", uuid4()
    result = await service.answer(request(rid=request_id), principal)
    redis_keys = [
        repo.key(result.chat_context.session.session_id),
        repo.request_key(principal, request_id),
        f"vishue:chat:rl:{principal}:123",
    ]
    await get_redis().set(redis_keys[-1], "1", ex=600)
    return {"ids": ids, "redis_keys": redis_keys}


async def snapshot(fixtures):
    result = {}
    async with get_chat_sessionmaker()() as db:
        for owner_id, data in fixtures.items():
            room, thread, message, memory = map(UUID, data["ids"])
            status = await db.get(ChatOwnerStatus, owner_id)
            records = (
                await db.get(ChatConversation, room),
                await db.get(ChatMessage, message),
                await db.get(ChatMemory, memory),
            )
            result[owner_id] = {
                "status": status.status,
                "postgres_records": sum(row is not None for row in records),
                "checkpoint": await checkpoint_exists(thread),
                "redis_keys": await get_redis().exists(*data["redis_keys"]),
            }
    return result


def reply(payload):
    print(json.dumps(payload), flush=True)


async def run(owner, other):
    fixtures = {owner_id: await seed(owner_id) for owner_id in (owner, other)}
    url = make_url(os.environ["CHAT_DATABASE_URL"]).set(drivername="postgresql")
    lock_key = f"g7:checkpoint:{fixtures[owner]['ids'][1]}"
    async with await psycopg.AsyncConnection.connect(
        url.render_as_string(hide_password=False), autocommit=True
    ) as conn:
        await conn.execute("SELECT pg_advisory_lock(hashtextextended(%s, 0))", (lock_key,))
        with socket.socket() as listener:
            listener.bind(("127.0.0.1", 0))
            port = listener.getsockname()[1]
            server = uvicorn.Server(uvicorn.Config(
                app, access_log=False, log_config=None, proxy_headers=False,
                timeout_graceful_shutdown=2,
            ))
            serving = asyncio.create_task(server.serve(sockets=[listener]))
            try:
                while not server.started:
                    if serving.done():
                        serving.result()
                        raise RuntimeError("Chatbot server did not start")
                    await asyncio.sleep(0.01)
                reply({"origin": f"http://127.0.0.1:{port}", "state": await snapshot(fixtures)})
                while command := (await asyncio.to_thread(sys.stdin.readline)).strip():
                    if command == "unlock":
                        await conn.execute(
                            "SELECT pg_advisory_unlock(hashtextextended(%s, 0))", (lock_key,)
                        )
                    elif command != "snapshot":
                        raise ValueError("Unknown test command")
                    reply(await snapshot(fixtures))
            finally:
                server.should_exit = True
                await serving


asyncio.run(run(*sys.argv[2:]), loop_factory=asyncio.SelectorEventLoop)
"""


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.fixture
def chatbot_python():
    default_python = "Scripts/python.exe" if os.name == "nt" else "bin/python"
    python = Path(
        os.environ.get("VISHUE_CHATBOT_TEST_PYTHON") or CHATBOT_ROOT / ".venv" / default_python
    ).resolve()
    if not python.is_file():
        pytest.fail("Set VISHUE_CHATBOT_TEST_PYTHON to the chatbot test interpreter")
    return python


def disposable_postgres(raw_url, database):
    url = make_url(raw_url)
    if (
        url.drivername != "postgresql+asyncpg"
        or url.host not in LOCAL_HOSTS
        or url.database != database
        or url.query
    ):
        pytest.fail(f"Configure a disposable local PostgreSQL database named {database}")
    return url


@asynccontextmanager
async def serve_chatbot(tmp_path, chatbot_python, owner, other, key):
    child_env = {name: os.environ[name] for name in ("PATH", "SYSTEMROOT") if name in os.environ}
    child_env.update(
        ENV="test",
        LOG_LEVEL="WARNING",
        CHAT_DATABASE_URL=CHAT_DB,
        TEST_CHAT_DATABASE_URL=CHAT_DB,
        REDIS_URL=CHAT_REDIS,
        G7_PERSISTENCE_ENABLED="true",
        G7_MEMORY_ENABLED="true",
        G7_INTERNAL_DELETION_ENABLED="true",
        G7_INTERNAL_DELETION_KEY=key,
        PGCONNECT_TIMEOUT="5",
    )
    process = await asyncio.create_subprocess_exec(
        str(chatbot_python),
        "-E",
        "-s",
        "-B",
        "-X",
        "utf8",
        "-c",
        CHATBOT_SCRIPT,
        str(CHATBOT_ROOT),
        owner,
        other,
        cwd=tmp_path,
        env=child_env,
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stderr = asyncio.create_task(process.stderr.read())

    async def receive():
        line = await asyncio.wait_for(process.stdout.readline(), timeout=60)
        if not line:
            output = (await stderr).decode("utf-8", errors="replace")
            pytest.fail(f"Chatbot test server closed its output:\n{output}")
        return json.loads(line)

    async def command(action):
        process.stdin.write(f"{action}\n".encode())
        await process.stdin.drain()
        return await receive()

    try:
        yield await receive(), command
    finally:
        process.stdin.close()
        try:
            await asyncio.wait_for(process.wait(), timeout=10)
        except TimeoutError:
            process.kill()
            await process.wait()
        await stderr


@pytest.mark.parametrize(
    ("env", "origin"),
    [("production", "http://127.0.0.1:8000"), ("test", "http://192.0.2.10:8000")],
)
async def test_deletion_client_rejects_configuration_outside_local_http(monkeypatch, env, origin):
    settings = get_settings()
    monkeypatch.setattr(settings, "env", env)
    monkeypatch.setattr(settings, "g7_chatbot_deletion_base_url", origin)
    monkeypatch.setattr(settings, "g7_internal_deletion_key", SecretStr(token_hex(32)))

    async def unexpected_send(*_args, **_kwargs):
        pytest.fail("Deletion client attempted to send a request outside the local test scope")

    monkeypatch.setattr(httpx.AsyncClient, "send", unexpected_send)
    with pytest.raises(ApiError) as error:
        await delete_chatbot_account(uuid4(), str(uuid4()))
    assert error.value.code == "account_deletion_unavailable"


@pytest.mark.integration
@pytest.mark.skipif(
    not (API_DB and CHAT_DB and CHAT_REDIS), reason="disposable G7 databases and Redis required"
)
async def test_deletion_job_retries_real_chatbot_http_cleanup(
    tmp_path, chatbot_python, monkeypatch
):
    if os.environ.get("G7_ALLOW_DESTRUCTIVE_TESTS") != "1":
        pytest.fail("Set G7_ALLOW_DESTRUCTIVE_TESTS=1 for the disposable G7 stores")
    api_db = disposable_postgres(API_DB, "vishue_api_g7_test")
    disposable_postgres(CHAT_DB, "vishue_chat_test")
    redis_url = urlsplit(CHAT_REDIS)
    if redis_url.scheme != "redis" or redis_url.hostname not in LOCAL_HOSTS or redis_url.query:
        pytest.fail("Configure a dedicated local Redis for the G7 test")

    owner, other = str(uuid4()), str(uuid4())
    key = token_hex(32)
    calls, requests, statuses = [], [], []

    class Steps:
        replay_safe = True

        async def execute(self, current_job, current_owner, phase):
            if (current_job, current_owner) != (job_id, owner):
                pytest.fail("The disposable deletion queue returned an unrelated job")
            calls.append(phase)
            if phase == "PURGING_CHAT":
                await delete_chatbot_account(current_job, current_owner)

    send = httpx.AsyncClient.send

    async def record_response(self, request, **kwargs):
        response = await send(self, request, **kwargs)
        if request.url.path == DELETION_PATH:
            requests.append(request)
            statuses.append(response.status_code)
            if statuses == [503, 204]:
                # Simulate the API losing the first successful reply.
                await response.aclose()
                raise httpx.ReadTimeout("simulated response loss", request=request)
        return response

    monkeypatch.setattr(httpx.AsyncClient, "send", record_response)

    engine = create_async_engine(api_db)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with sessions.begin() as db:
            job_id = (await AccountDeletionRepository(db).get_or_create(owner)).id
        service = AccountDeletionService(
            sessions, Steps(), lease_seconds=120, retry_delay_seconds=0
        )
        async with serve_chatbot(tmp_path, chatbot_python, owner, other, key) as (ready, command):
            settings = get_settings()
            monkeypatch.setattr(settings, "env", "test")
            monkeypatch.setattr(settings, "g7_chatbot_deletion_base_url", ready["origin"])
            monkeypatch.setattr(settings, "g7_internal_deletion_key", SecretStr(key))
            present = {
                "status": "ACTIVE",
                "postgres_records": 3,
                "checkpoint": True,
                "redis_keys": 3,
            }
            assert ready["state"] == {owner: present, other: present}

            first = await service.run_once()
            assert (first.status, first.job_id, first.phase) == ("RETRY", job_id, "PURGING_CHAT")
            assert statuses == [503]
            assert calls == ["BLOCKING", "PURGING_CHAT"]
            assert await command("unlock") == {
                owner: {**present, "status": "DELETING", "redis_keys": 0},
                other: present,
            }
            async with sessions() as db:
                job = await db.get(AccountDeletionJobRow, job_id)
                assert (job.status, job.phase, job.error_code) == (
                    "RETRY_REQUIRED",
                    "PURGING_CHAT",
                    "step_failed",
                )

            second = await service.run_once()
            assert (second.status, second.job_id, second.phase) == ("RETRY", job_id, "PURGING_CHAT")
            assert statuses == [503, 204]
            assert calls == ["BLOCKING", "PURGING_CHAT", "PURGING_CHAT"]
            cleaned = {
                owner: {
                    "status": "DELETED",
                    "postgres_records": 0,
                    "checkpoint": False,
                    "redis_keys": 0,
                },
                other: present,
            }
            assert await command("snapshot") == cleaned

            third = await service.run_once()
            assert (third.status, third.job_id, third.phase) == ("DONE", job_id, "DONE")
            assert statuses == [503, 204, 204]
            assert calls == [
                "BLOCKING",
                "PURGING_CHAT",
                "PURGING_CHAT",
                "PURGING_CHAT",
                "DELETING_AUTH",
                "DELETING_MEMBER",
            ]
            assert all(
                json.loads(r.content) == {"jobId": str(job_id), "ownerId": owner} for r in requests
            )
            assert len({r.headers["x-g7-deletion-nonce"] for r in requests}) == 3

            signed = requests[-1]
            async with httpx.AsyncClient(trust_env=False) as client:
                replay = await client.post(
                    signed.url, headers=signed.headers, content=signed.content
                )
            assert (replay.status_code, replay.json()["code"]) == (
                403,
                "account_deletion_forbidden",
            )
            assert await command("snapshot") == cleaned

        async with sessions() as db:
            job = await db.get(AccountDeletionJobRow, job_id)
            assert (job.status, job.phase, job.attempt_count) == ("DONE", "DONE", 3)
    finally:
        try:
            async with sessions.begin() as db:
                await db.execute(
                    delete(AccountDeletionJobRow).where(AccountDeletionJobRow.owner_id == owner)
                )
        finally:
            await engine.dispose()


@asynccontextmanager
async def local_supabase_stub(owner, key) -> AsyncIterator:
    calls = []

    async def handle(reader, writer):
        try:
            head = await asyncio.wait_for(reader.readuntil(b"\r\n\r\n"), 5)
            request, *headers = head.decode("ascii").split("\r\n")
            calls.append(request)
            if (
                request != f"DELETE /auth/v1/admin/users/{owner} HTTP/1.1"
                or f"apikey: {key}" not in headers
            ):
                status = "403 Forbidden"
            else:
                # First report acceptance, then model a user already removed before retry.
                status = "202 Accepted" if len(calls) == 1 else "404 Not Found"
            writer.write(
                f"HTTP/1.1 {status}\r\nContent-Length: 0\r\nConnection: close\r\n\r\n".encode()
            )
            await writer.drain()
        finally:
            writer.close()
            await writer.wait_closed()

    async with await asyncio.start_server(handle, "127.0.0.1", 0) as server:
        port = server.sockets[0].getsockname()[1]
        yield f"http://127.0.0.1:{port}", calls


async def run_worker_process(tmp_path, *, chat_origin, chat_key, auth_origin, auth_key):
    env = {name: os.environ[name] for name in ("PATH", "SYSTEMROOT") if name in os.environ}
    env.update(
        ENV="test",
        PYTHONPATH=str(CHATBOT_ROOT.parent / "api"),
        DATABASE_URL=API_DB,
        G7_CHATBOT_DELETION_BASE_URL=chat_origin,
        G7_INTERNAL_DELETION_KEY=chat_key,
        G7_LOCAL_SUPABASE_URL=auth_origin,
        G7_LOCAL_SUPABASE_SECRET_KEY=auth_key,
    )
    worker = await asyncio.create_subprocess_exec(
        sys.executable,
        "-B",
        "-m",
        "app.jobs.process_account_deletions",
        "--once",
        cwd=tmp_path,
        env=env,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        _, stderr = await asyncio.wait_for(worker.communicate(), 40)
    finally:
        if worker.returncode is None:
            worker.kill()
            await worker.wait()
    assert worker.returncode == 0, stderr.decode(errors="replace")


@pytest.mark.integration
@pytest.mark.skipif(not (API_DB and CHAT_DB and CHAT_REDIS), reason="disposable G7 stores required")
async def test_public_delete_finishes_through_an_independent_worker(
    tmp_path, chatbot_python, monkeypatch
):
    if os.environ.get("G7_ALLOW_DESTRUCTIVE_TESTS") != "1":
        pytest.fail("Set G7_ALLOW_DESTRUCTIVE_TESTS=1 for the disposable G7 stores")
    api_db = disposable_postgres(API_DB, "vishue_api_g7_test")
    disposable_postgres(CHAT_DB, "vishue_chat_test")
    redis = urlsplit(CHAT_REDIS)
    if redis.scheme != "redis" or redis.hostname not in LOCAL_HOSTS or redis.query:
        pytest.fail("Configure a dedicated local Redis for the G7 test")

    owner, other = str(uuid4()), str(uuid4())
    chat_key, auth_key = token_hex(32), token_hex(32)
    bearer = {"Authorization": f"Bearer {owner}"}
    engine = create_async_engine(api_db)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    app = member_app(sessions, monkeypatch, owner, other)

    async def verify_stage(status, phase, attempts, *, member_present):
        async with sessions() as session:
            job = await session.scalar(
                select(AccountDeletionJobRow).where(AccountDeletionJobRow.owner_id == owner)
            )
            assert (job.status, job.phase, job.attempt_count) == (status, phase, attempts)
            assert (await session.get(MemberRow, owner) is not None) == member_present
            assert await session.get(MemberRow, other) is not None
            return job.id

    async def make_retry_due(job_id):
        async with sessions.begin() as session:
            await session.execute(
                update(AccountDeletionJobRow)
                .where(AccountDeletionJobRow.id == job_id)
                .values(next_attempt_at=datetime.now(UTC))
            )

    try:
        async with sessions.begin() as session:
            session.add_all(
                [
                    MemberRow(
                        id=member, terms_version=TERMS_VERSION, terms_agreed_at=datetime.now(UTC)
                    )
                    for member in (owner, other)
                ]
            )
        async with (
            serve_chatbot(tmp_path, chatbot_python, owner, other, chat_key) as (ready, command),
            local_supabase_stub(owner, auth_key) as (auth_origin, auth_calls),
            httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app), base_url="http://test"
            ) as api,
        ):
            worker_args = {
                "chat_origin": ready["origin"],
                "chat_key": chat_key,
                "auth_origin": auth_origin,
                "auth_key": auth_key,
            }
            pending = await api.delete("/api/me", headers=bearer)
            assert (pending.status_code, pending.json()["code"]) == (
                409,
                "account_deletion_in_progress",
            )
            job_id = await verify_stage("PENDING", "BLOCKING", 0, member_present=True)

            await run_worker_process(tmp_path, **worker_args)
            assert (
                await verify_stage("RETRY_REQUIRED", "PURGING_CHAT", 1, member_present=True)
                == job_id
            )
            assert auth_calls == []
            blocked = await command("unlock")
            assert blocked[owner]["status"] == "DELETING"
            await make_retry_due(job_id)

            await run_worker_process(tmp_path, **worker_args)
            assert (
                await verify_stage("RETRY_REQUIRED", "DELETING_AUTH", 2, member_present=True)
                == job_id
            )
            assert len(auth_calls) == 1
            cleaned = await command("snapshot")
            assert cleaned[owner] == {
                "status": "DELETED",
                "postgres_records": 0,
                "checkpoint": False,
                "redis_keys": 0,
            }
            assert cleaned[other] == ready["state"][other]
            await make_retry_due(job_id)

            # The worker can finish accepted jobs while the API's intake is paused.
            monkeypatch.setattr(get_settings(), "g7_account_deletion_enabled", False)
            await run_worker_process(tmp_path, **worker_args)
            assert await verify_stage("DONE", "DONE", 3, member_present=False) == job_id
            assert len(auth_calls) == 2
            assert (await api.delete("/api/me", headers=bearer)).status_code == 204
            assert (
                await api.post("/api/me/terms", headers=bearer, json={"version": TERMS_VERSION})
            ).status_code == 403
    finally:
        try:
            async with sessions.begin() as session:
                await session.execute(
                    delete(AccountDeletionJobRow).where(AccountDeletionJobRow.owner_id == owner)
                )
                await session.execute(delete(MemberRow).where(MemberRow.id.in_((owner, other))))
        finally:
            await engine.dispose()

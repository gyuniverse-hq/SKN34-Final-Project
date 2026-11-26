"""Exercise the member API against a disposable local API database."""

import asyncio
import os
from uuid import uuid4

import httpx
import pytest
from pydantic import SecretStr
from sqlalchemy import delete, select, update
from sqlalchemy.engine import make_url
from sqlalchemy.exc import OperationalError
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.core import auth
from app.core.config import get_settings
from app.core.db import get_session
from app.main import create_app
from app.models.account_deletion import AccountDeletionJobRow
from app.models.member import MemberRow
from app.repositories.account_deletion_repository import AccountDeletionRepository
from app.services.member_service import TERMS_VERSION

API_DB = os.environ.get("TEST_G7_ACCOUNT_DELETION_DATABASE_URL")
pytestmark = [
    pytest.mark.anyio,
    pytest.mark.integration,
    pytest.mark.skipif(not API_DB, reason="disposable API DB required"),
]


def member_app(sessions, monkeypatch, *owners):
    settings = get_settings()
    monkeypatch.setattr(settings, "env", "test")
    url = sessions.kw["bind"].url.render_as_string(hide_password=False)
    monkeypatch.setattr(settings, "database_url", url)
    monkeypatch.setattr(settings, "g7_account_deletion_enabled", True)
    monkeypatch.setattr(settings, "supabase_url", None)
    monkeypatch.setattr(settings, "supabase_secret_key", None)

    class FakeVerifier:
        async def verify(self, token):
            return {"role": "authenticated", "sub": token} if token in owners else None

    async def session_override():
        async with sessions() as session:
            yield session

    monkeypatch.setattr(auth, "get_verifier", lambda: FakeVerifier())
    app = create_app()
    app.dependency_overrides[get_session] = session_override
    return app


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.fixture
async def member_api(monkeypatch):
    url = make_url(API_DB)
    if (
        url.drivername != "postgresql+asyncpg"
        or url.host not in {"127.0.0.1", "localhost", "::1"}
        or url.database != "vishue_api_g7_test"
        or url.query
        or os.environ.get("G7_ALLOW_DESTRUCTIVE_TESTS") != "1"
    ):
        pytest.fail("Use an authorized disposable local API test database")
    engine = create_async_engine(url)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    owner, other = str(uuid4()), str(uuid4())
    app = member_app(sessions, monkeypatch, owner, other)
    try:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            yield client, sessions, owner, other
    finally:
        async with sessions.begin() as session:
            await session.execute(
                delete(AccountDeletionJobRow).where(
                    AccountDeletionJobRow.owner_id.in_((owner, other))
                )
            )
            await session.execute(delete(MemberRow).where(MemberRow.id.in_((owner, other))))
        await engine.dispose()


async def test_duplicate_intake_and_pausing_preserve_the_member_fence(member_api, monkeypatch):
    client, sessions, owner, other = member_api
    headers = {"Authorization": f"Bearer {owner}"}
    other_headers = {"Authorization": f"Bearer {other}"}
    assert (await client.delete("/api/me")).status_code == 401
    replies = await asyncio.gather(*(client.delete("/api/me", headers=headers) for _ in range(3)))
    assert all(
        (res.status_code, res.json()["code"]) == (409, "account_deletion_in_progress")
        for res in replies
    )
    async with sessions() as session:
        jobs = list(
            await session.scalars(
                select(AccountDeletionJobRow).where(
                    AccountDeletionJobRow.owner_id.in_((owner, other))
                )
            )
        )
        assert len(jobs) == 1 and (jobs[0].owner_id, jobs[0].status) == (owner, "PENDING")

    monkeypatch.setattr(get_settings(), "g7_account_deletion_enabled", False)
    assert (await client.get("/api/me", headers=headers)).status_code == 403
    assert (await client.get("/api/me/skin-access", headers=headers)).status_code == 403
    assert (await client.get("/api/me/rewards", headers=headers)).status_code == 403
    assert (await client.post("/api/me/rewards/attendance", headers=headers)).status_code == 403
    assert (await client.delete("/api/me", headers=headers)).json()[
        "code"
    ] == "account_deletion_in_progress"
    assert (await client.get("/api/me", headers=other_headers)).status_code == 200
    assert (await client.delete("/api/me", headers=other_headers)).status_code == 503


async def test_signed_receipt_confirms_deletion_after_auth_is_gone(member_api, monkeypatch):
    client, sessions, owner, _ = member_api
    monkeypatch.setattr(get_settings(), "g7_internal_deletion_key", SecretStr("test-receipt-key"))
    intake = await client.delete("/api/me", headers={"Authorization": f"Bearer {owner}"})
    assert intake.status_code == 409
    receipt = intake.json()["deletionReceipt"]
    path = "/api/me/deletion-status"
    assert (await client.post(path, json={"receipt": receipt})).json() == {"status": "pending"}
    forged = receipt[:-1] + ("0" if receipt[-1] != "0" else "1")
    assert (await client.post(path, json={"receipt": forged})).status_code == 404
    monkeypatch.setattr(auth, "get_verifier", lambda: None)
    async with sessions.begin() as session:
        await session.execute(
            update(AccountDeletionJobRow)
            .where(AccountDeletionJobRow.owner_id == owner)
            .values(status="DONE", phase="DONE")
        )
    complete = await client.post(path, json={"receipt": receipt})
    assert complete.status_code == 200 and complete.json() == {"status": "complete"}
    assert complete.headers["Cache-Control"] == "no-store"


async def test_member_write_waits_for_intake_and_cannot_recreate_member(member_api, monkeypatch):
    client, sessions, owner, _ = member_api
    headers = {"Authorization": f"Bearer {owner}"}
    inserted, release, writing = asyncio.Event(), asyncio.Event(), asyncio.Event()
    create, lock = AccountDeletionRepository.get_or_create, AccountDeletionRepository.lock_owner

    async def hold_receipt(self, owner_id):
        job = await create(self, owner_id)
        inserted.set()
        await release.wait()
        return job

    async def signal_lock(self, owner_id):
        if inserted.is_set():
            writing.set()
        await lock(self, owner_id)

    monkeypatch.setattr(AccountDeletionRepository, "get_or_create", hold_receipt)
    monkeypatch.setattr(AccountDeletionRepository, "lock_owner", signal_lock)
    receipt = asyncio.create_task(client.delete("/api/me", headers=headers))
    try:
        await asyncio.wait_for(inserted.wait(), 5)
        terms = asyncio.create_task(
            client.post("/api/me/terms", headers=headers, json={"version": TERMS_VERSION})
        )
        await asyncio.wait_for(writing.wait(), 5)
        assert not terms.done()
    finally:
        release.set()
    assert (await asyncio.wait_for(receipt, 5)).status_code == 409
    denied = await asyncio.wait_for(terms, 5)
    assert (denied.status_code, denied.json()["code"]) == (403, "account_unavailable")
    async with sessions() as session:
        assert await session.get(MemberRow, owner) is None


async def test_failed_intake_is_not_reported_as_pending(member_api, monkeypatch):
    client, sessions, owner, _ = member_api
    create = AccountDeletionRepository.get_or_create

    async def fail_after_insert(self, owner_id):
        await create(self, owner_id)
        raise OperationalError(None, None, OSError("test transaction failure"))

    monkeypatch.setattr(AccountDeletionRepository, "get_or_create", fail_after_insert)
    res = await client.delete("/api/me", headers={"Authorization": f"Bearer {owner}"})
    assert (res.status_code, res.json()["code"]) == (503, "account_deletion_unavailable")
    async with sessions() as session:
        assert await AccountDeletionRepository(session).status(owner) is None

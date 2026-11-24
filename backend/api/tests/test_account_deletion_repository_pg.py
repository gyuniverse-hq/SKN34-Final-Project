"""Deletion job tests use only a disposable local PostgreSQL database."""

import asyncio
import os
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy import delete, func, select, update
from sqlalchemy.engine import make_url
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.models.account_deletion import AccountDeletionJobRow
from app.models.member import MemberRow
from app.repositories.account_deletion_repository import AccountDeletionRepository

URL = os.environ.get("TEST_G7_ACCOUNT_DELETION_DATABASE_URL")
pytestmark = [
    pytest.mark.integration,
    pytest.mark.anyio,
    pytest.mark.skipif(not URL, reason="disposable deletion test database not configured"),
]


@pytest.fixture
def anyio_backend():
    if os.name == "nt":
        return "asyncio", {"loop_factory": asyncio.SelectorEventLoop}
    return "asyncio"


@pytest.fixture
async def database():
    url = make_url(URL)
    if (
        url.host not in {"127.0.0.1", "localhost", "::1"}
        or url.database != "vishue_api_g7_test"
        or os.environ.get("G7_ALLOW_DESTRUCTIVE_TESTS") != "1"
    ):
        raise RuntimeError("Deletion jobs require an authorized disposable local test database")
    engine = create_async_engine(URL)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    prefix = "g7-test-" + uuid4().hex
    try:
        yield sessions, prefix
    finally:
        async with sessions.begin() as session:
            await session.execute(
                delete(AccountDeletionJobRow).where(
                    AccountDeletionJobRow.owner_id.startswith(prefix)
                )
            )
            await session.execute(delete(MemberRow).where(MemberRow.id.startswith(prefix)))
        await engine.dispose()


async def test_concurrent_requests_share_one_job(database):
    sessions, owner = database

    async def create_job():
        async with sessions.begin() as session:
            job = await AccountDeletionRepository(session).get_or_create(owner)
            return job.id

    job_ids = await asyncio.gather(*(create_job() for _ in range(5)))
    assert len(set(job_ids)) == 1
    async with sessions() as session:
        jobs = list(await session.scalars(select(AccountDeletionJobRow)))
        matching = [job for job in jobs if job.owner_id == owner]
        assert len(matching) == 1
        assert (matching[0].status, matching[0].phase) == ("PENDING", "BLOCKING")


async def test_skipped_locked_rows_allow_independent_workers(database):
    sessions, prefix = database
    async with sessions.begin() as session:
        repo = AccountDeletionRepository(session)
        await repo.get_or_create(prefix + "-a")
        await repo.get_or_create(prefix + "-b")

    async with sessions.begin() as first, sessions.begin() as second:
        job_a = await AccountDeletionRepository(first).claim_next(60)
        job_b = await AccountDeletionRepository(second).claim_next(60)
        assert job_a and job_b and job_a.id != job_b.id
        assert job_a.lease_token != job_b.lease_token


async def test_expired_worker_is_fenced_and_retry_keeps_its_phase(database):
    sessions, owner = database
    async with sessions.begin() as session:
        job_id = (await AccountDeletionRepository(session).get_or_create(owner)).id
    async with sessions.begin() as session:
        claimed = await AccountDeletionRepository(session).claim_next(60)
        assert claimed and claimed.id == job_id
        old_token = claimed.lease_token
        assert await AccountDeletionRepository(session).advance(job_id, old_token, "BLOCKING")
    async with sessions.begin() as session:
        await session.execute(
            update(AccountDeletionJobRow)
            .where(AccountDeletionJobRow.id == job_id)
            .values(lease_until=func.clock_timestamp() - timedelta(seconds=1))
        )
    async with sessions.begin() as session:
        repo = AccountDeletionRepository(session)
        assert not await repo.advance(job_id, old_token, "PURGING_CHAT")
        claimed = await repo.claim_next(60)
        assert claimed and claimed.id == job_id and claimed.phase == "PURGING_CHAT"
        new_token = claimed.lease_token
        assert new_token != old_token and claimed.attempt_count == 2
        assert not await repo.advance(job_id, old_token, "PURGING_CHAT")
        assert await repo.retry(job_id, new_token, "PURGING_CHAT", "redis_unavailable", 60)
    async with sessions.begin() as session:
        repo = AccountDeletionRepository(session)
        assert await repo.claim_next(60) is None
        row = await session.get(AccountDeletionJobRow, job_id)
        assert row.status == "RETRY_REQUIRED" and row.phase == "PURGING_CHAT"
        assert row.error_code == "redis_unavailable" and row.lease_token is None
        await session.execute(
            update(AccountDeletionJobRow)
            .where(AccountDeletionJobRow.id == job_id)
            .values(next_attempt_at=func.clock_timestamp() - timedelta(seconds=1))
        )
    async with sessions.begin() as session:
        repo = AccountDeletionRepository(session)
        claimed = await repo.claim_next(60)
        assert claimed and claimed.phase == "PURGING_CHAT" and claimed.attempt_count == 3
        for phase in ("PURGING_CHAT", "DELETING_AUTH", "DELETING_MEMBER"):
            assert await repo.advance(job_id, claimed.lease_token, phase)
    async with sessions() as session:
        row = await session.get(AccountDeletionJobRow, job_id)
        assert (row.status, row.phase) == ("DONE", "DONE")
        assert row.lease_token is None and row.lease_until is None and row.error_code is None
        assert (await AccountDeletionRepository(session).get_or_create(owner)).id == job_id


async def test_job_survives_member_removal(database):
    sessions, owner = database
    async with sessions.begin() as session:
        session.add(MemberRow(id=owner, terms_version="test", terms_agreed_at=datetime.now(UTC)))
        job_id = (await AccountDeletionRepository(session).get_or_create(owner)).id
    async with sessions.begin() as session:
        await session.execute(delete(MemberRow).where(MemberRow.id == owner))
    async with sessions() as session:
        assert await session.get(MemberRow, owner) is None
        assert (await session.get(AccountDeletionJobRow, job_id)).owner_id == owner


async def test_invalid_state_is_rejected_by_database(database):
    sessions, owner = database
    async with sessions.begin() as session:
        job_id = (await AccountDeletionRepository(session).get_or_create(owner)).id
    with pytest.raises(IntegrityError):
        async with sessions.begin() as session:
            await session.execute(
                update(AccountDeletionJobRow)
                .where(AccountDeletionJobRow.id == job_id)
                .values(status="DONE")
            )
    with pytest.raises(IntegrityError):
        async with sessions.begin() as session:
            await session.execute(
                update(AccountDeletionJobRow)
                .where(AccountDeletionJobRow.id == job_id)
                .values(status="IN_PROGRESS")
            )

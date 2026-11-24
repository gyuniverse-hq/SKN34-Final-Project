"""Deletion workflow tests use disposable PostgreSQL and replay-safe fake steps only."""

import asyncio
import os
from datetime import timedelta
from uuid import uuid4

import pytest
from sqlalchemy import delete, func, update
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.models.account_deletion import AccountDeletionJobRow
from app.repositories.account_deletion_repository import AccountDeletionRepository
from app.services.account_deletion_service import AccountDeletionService

pytestmark = [
    pytest.mark.integration,
    pytest.mark.anyio,
    pytest.mark.skipif(
        not os.environ.get("TEST_G7_ACCOUNT_DELETION_DATABASE_URL"),
        reason="disposable deletion test database not configured",
    ),
]

PHASES = ("BLOCKING", "PURGING_CHAT", "DELETING_AUTH", "DELETING_MEMBER")


@pytest.fixture
def anyio_backend():
    if os.name == "nt":
        return "asyncio", {"loop_factory": asyncio.SelectorEventLoop}
    return "asyncio"


@pytest.fixture
async def database():
    url = make_url(os.environ["TEST_G7_ACCOUNT_DELETION_DATABASE_URL"])
    if (
        url.host not in {"127.0.0.1", "localhost", "::1"}
        or url.database != "vishue_api_g7_test"
        or os.environ.get("G7_ALLOW_DESTRUCTIVE_TESTS") != "1"
    ):
        raise RuntimeError(
            "Deletion workflow requires an authorized disposable local test database"
        )
    engine = create_async_engine(url)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    owner = "g7-workflow-" + uuid4().hex
    try:
        yield sessions, owner
    finally:
        async with sessions.begin() as session:
            await session.execute(
                delete(AccountDeletionJobRow).where(AccountDeletionJobRow.owner_id == owner)
            )
        await engine.dispose()


class FakeSteps:
    replay_safe = True

    def __init__(self, *, fail_before=None, fail_after=None):
        self.fail_before = fail_before
        self.fail_after = fail_after
        self.calls = []
        self.effects = []
        self._effect_keys = set()

    async def execute(self, job_id, owner_id, phase):
        self.calls.append((job_id, owner_id, phase))
        if self.fail_before == phase:
            self.fail_before = None
            raise RuntimeError("synthetic failure before step")
        key = (job_id, phase)
        if key not in self._effect_keys:
            self._effect_keys.add(key)
            self.effects.append((job_id, owner_id, phase))
        if self.fail_after == phase:
            self.fail_after = None
            raise RuntimeError("synthetic lost response after step")


async def create_job(sessions, owner):
    async with sessions.begin() as session:
        return (await AccountDeletionRepository(session).get_or_create(owner)).id


async def job_state(sessions, job_id):
    async with sessions() as session:
        job = await session.get(AccountDeletionJobRow, job_id)
        return job.status, job.phase, job.error_code, job.attempt_count


async def expire_lease(sessions, job_id):
    async with sessions.begin() as session:
        await session.execute(
            update(AccountDeletionJobRow)
            .where(AccountDeletionJobRow.id == job_id)
            .values(lease_until=func.clock_timestamp() - timedelta(seconds=1))
        )


async def test_workflow_runs_each_step_in_order_and_reports_no_work(database):
    sessions, owner = database
    job_id = await create_job(sessions, owner)
    steps = FakeSteps()
    service = AccountDeletionService(sessions, steps, retry_delay_seconds=0)
    result = await service.run_once()
    assert (result.status, result.job_id, result.phase) == ("DONE", job_id, "DONE")
    assert steps.effects == [(job_id, owner, phase) for phase in PHASES]
    assert await job_state(sessions, job_id) == ("DONE", "DONE", None, 1)
    assert (await service.run_once()).status == "NO_WORK"


@pytest.mark.parametrize("failed_phase", PHASES)
async def test_failed_step_keeps_phase_and_retries_without_repeating_previous_steps(
    database, failed_phase
):
    sessions, owner = database
    job_id = await create_job(sessions, owner)
    steps = FakeSteps(fail_before=failed_phase)
    service = AccountDeletionService(sessions, steps, retry_delay_seconds=0)
    first = await service.run_once()
    assert (first.status, first.phase) == ("RETRY", failed_phase)
    assert await job_state(sessions, job_id) == ("RETRY_REQUIRED", failed_phase, "step_failed", 1)
    assert (await service.run_once()).status == "DONE"
    assert steps.effects == [(job_id, owner, phase) for phase in PHASES]
    assert [phase for _, _, phase in steps.calls].count(failed_phase) == 2
    assert await job_state(sessions, job_id) == ("DONE", "DONE", None, 2)


async def test_lost_step_response_retries_same_replay_safe_effect(database):
    sessions, owner = database
    job_id = await create_job(sessions, owner)
    steps = FakeSteps(fail_after="DELETING_AUTH")
    service = AccountDeletionService(sessions, steps, retry_delay_seconds=0)
    assert (await service.run_once()).status == "RETRY"
    assert await job_state(sessions, job_id) == (
        "RETRY_REQUIRED",
        "DELETING_AUTH",
        "step_failed",
        1,
    )
    assert (await service.run_once()).status == "DONE"
    assert steps.effects == [(job_id, owner, phase) for phase in PHASES]
    assert [phase for _, _, phase in steps.calls].count("DELETING_AUTH") == 2


async def test_expired_worker_cannot_commit_its_late_result(database):
    sessions, owner = database
    job_id = await create_job(sessions, owner)
    started, release = asyncio.Event(), asyncio.Event()

    class WaitingSteps(FakeSteps):
        async def execute(self, current_job, current_owner, phase):
            await super().execute(current_job, current_owner, phase)
            if phase == "BLOCKING" and not started.is_set():
                started.set()
                await release.wait()

    steps = WaitingSteps()
    service = AccountDeletionService(sessions, steps, retry_delay_seconds=0)
    first = asyncio.create_task(service.run_once())
    try:
        await asyncio.wait_for(started.wait(), timeout=10)
        await expire_lease(sessions, job_id)
        assert (await service.run_once()).status == "DONE"
    finally:
        release.set()
    assert (await asyncio.wait_for(first, timeout=10)).status == "LEASE_LOST"
    assert steps.effects == [(job_id, owner, phase) for phase in PHASES]
    assert await job_state(sessions, job_id) == ("DONE", "DONE", None, 2)


async def test_database_failure_after_step_is_recovered_with_safe_replay(database, monkeypatch):
    sessions, owner = database
    job_id = await create_job(sessions, owner)
    steps = FakeSteps()
    service = AccountDeletionService(sessions, steps, retry_delay_seconds=0)
    original = AccountDeletionRepository.advance

    async def fail_advance(self, job_id, lease_token, phase):
        raise OSError("synthetic database failure")

    monkeypatch.setattr(AccountDeletionRepository, "advance", fail_advance)
    with pytest.raises(OSError):
        await service.run_once()
    assert await job_state(sessions, job_id) == ("IN_PROGRESS", "BLOCKING", None, 1)
    monkeypatch.setattr(AccountDeletionRepository, "advance", original)
    await expire_lease(sessions, job_id)
    assert (await service.run_once()).status == "DONE"
    assert steps.effects == [(job_id, owner, phase) for phase in PHASES]
    assert [phase for _, _, phase in steps.calls].count("BLOCKING") == 2


def test_non_replay_safe_adapter_is_rejected():
    steps = FakeSteps()
    steps.replay_safe = False
    with pytest.raises(ValueError, match="replay-safe"):
        AccountDeletionService(None, steps)

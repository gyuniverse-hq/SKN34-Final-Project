"""Needs a migrated PostgreSQL: CI sets TEST_DATABASE_URL after `alembic upgrade head`."""

import os
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from app.core.auth import AuthUser
from app.core.config import get_settings
from app.repositories.member_repository import MemberRepository
from app.services.member_service import MemberService
from tests.conftest import FakeAccounts

DATABASE_URL = os.environ.get("TEST_DATABASE_URL")

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(not DATABASE_URL, reason="TEST_DATABASE_URL not set"),
]


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.mark.anyio
async def test_terms_are_upserted_and_deleted():
    engine = create_async_engine(DATABASE_URL)
    first = datetime(2026, 1, 1, tzinfo=UTC)
    later = datetime(2026, 6, 1, tzinfo=UTC)
    try:
        async with AsyncSession(engine, expire_on_commit=False) as session:
            repo = MemberRepository(session)
            await repo.delete("pg-member")
            assert await repo.get("pg-member") is None
            await repo.save_terms("pg-member", "v1", first)
            updated = await repo.save_terms("pg-member", "v2", later)
            assert (updated.terms_version, updated.terms_agreed_at) == ("v2", later)

        async with AsyncSession(engine) as session:
            repo = MemberRepository(session)
            assert (await repo.get("pg-member")).terms_version == "v2"
            await repo.delete("pg-member")
            assert await repo.get("pg-member") is None
    finally:
        await engine.dispose()


@pytest.mark.anyio
async def test_skin_trial_is_idempotent_and_subscription_expiry_is_enforced(monkeypatch):
    monkeypatch.setattr(get_settings(), "env", "local")
    engine = create_async_engine(DATABASE_URL)
    now = datetime.now(UTC)
    member_id = "pg-skin-trial"
    try:
        async with AsyncSession(engine, expire_on_commit=False) as session:
            repo = MemberRepository(session)
            await repo.delete(member_id)
            await repo.save_terms(member_id, "v1", now)
            assert await repo.claim_first_ar_visit(member_id)
            assert not await repo.claim_first_ar_visit(member_id)
            assert (await repo.complete_analysis(member_id, "first")).skin_trial_run == "first"
            assert await repo.complete_analysis(member_id, "first")
            assert await repo.complete_analysis(member_id, "second") is None
            service = MemberService(repo, FakeAccounts())
            user = AuthUser(id=member_id, email=None)
            access = await service.start_dev_subscription(user)
            assert access.trial_used and access.subscribed and access.expires_at > now
            assert await repo.complete_analysis(member_id, "second")
            await repo.set_skin_subscription(member_id, now - timedelta(days=1))
            assert await repo.complete_analysis(member_id, "third") is None
            assert not (await service.skin_access(user)).subscribed
            await repo.delete(member_id)
            await repo.save_terms(member_id, "v1", now)
            assert await repo.complete_analysis(member_id, "before-ar")
            assert not await repo.claim_first_ar_visit(member_id)
            await repo.delete(member_id)
    finally:
        await engine.dispose()

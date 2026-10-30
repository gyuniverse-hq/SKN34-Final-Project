"""Needs a migrated PostgreSQL: CI sets TEST_DATABASE_URL after `alembic upgrade head`."""

import os
from datetime import UTC, datetime

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from app.repositories.member_repository import MemberRepository

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

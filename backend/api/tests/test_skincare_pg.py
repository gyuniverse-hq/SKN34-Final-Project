"""Requires migrated disposable TEST_DATABASE_URL; never touches production."""

import os

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from app.repositories.skincare_repository import SkincareRepository
from app.schemas.skincare import SkincareSnapshot
from tests.test_skincare import snapshot

URL = os.environ.get("TEST_DATABASE_URL")
pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(not URL, reason="TEST_DATABASE_URL not set"),
]


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.mark.anyio
async def test_publish_read_and_failed_transaction_preserves_snapshot():
    engine = create_async_engine(URL)
    try:
        old = snapshot()
        async with AsyncSession(engine) as session:
            await SkincareRepository(session).publish(old)
        # Raising inside the transaction rolls back both snapshot and catalog updates.
        async with AsyncSession(engine) as session:
            with pytest.raises(RuntimeError):
                async with session.begin():
                    from app.models.skincare import SkincareServingRow

                    row = await session.get(SkincareServingRow, 1)
                    row.data_version = "invalid"
                    raise RuntimeError("publish failed")
        async with AsyncSession(engine) as session:
            loaded = await SkincareRepository(session).read()
            assert isinstance(loaded, SkincareSnapshot)
            assert loaded == old
    finally:
        await engine.dispose()

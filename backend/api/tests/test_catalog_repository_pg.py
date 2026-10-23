"""Needs a migrated PostgreSQL: CI sets TEST_DATABASE_URL after `alembic upgrade head`."""

import os

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from app.repositories.catalog_repository import CatalogRepository
from tests.conftest import SAMPLE

DATABASE_URL = os.environ.get("TEST_DATABASE_URL")

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(not DATABASE_URL, reason="TEST_DATABASE_URL not set"),
]


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.mark.anyio
async def test_replace_and_search_round_trip():
    engine = create_async_engine(DATABASE_URL)
    try:
        async with AsyncSession(engine, expire_on_commit=False) as session:
            await CatalogRepository(session).replace_catalog(SAMPLE)

        async with AsyncSession(engine) as session:
            repo = CatalogRepository(session)
            assert [p.id for p in await repo.search_products([], "base")] == ["base-1", "base-2"]
            assert [p.id for p in await repo.search_products(["제품", "lip-1"])] == ["lip-1"]
            assert await repo.search_products(["100%"]) == []
            product = await repo.get_product("base-1")
            assert product == SAMPLE.products[1]
            assert await repo.get_look("look-1") == SAMPLE.looks[0]
            assert await repo.list_stores() == SAMPLE.stores
    finally:
        await engine.dispose()

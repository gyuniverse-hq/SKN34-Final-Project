"""Needs a migrated PostgreSQL: CI sets TEST_DATABASE_URL after `alembic upgrade head`."""

import os
from datetime import datetime
from types import SimpleNamespace

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from app.models.admin import ProductAdminStateRow
from app.models.catalog import ProductRow
from app.models.raw_oliveyoung import RawOyProductRow, RawOyReviewSummaryRow
from app.repositories.catalog_repository import CatalogRepository, build_search_text
from tests.conftest import SAMPLE, make_product

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
            assert len(await repo.search_products([], tags=["bestseller", "x"])) == 3
            assert await repo.search_products([], tags=["x"]) == []
            assert await repo.search_products([], tags=[]) == []
            product = await repo.get_product("base-1")
            assert product == SAMPLE.products[1]
            assert await repo.get_look("look-1") == SAMPLE.looks[0]
            assert await repo.list_stores() == SAMPLE.stores
    finally:
        await engine.dispose()


@pytest.mark.anyio
async def test_discovery_candidates_use_the_latest_review_and_active_visible_catalog(monkeypatch):
    monkeypatch.setattr(
        "app.repositories.catalog_repository.get_settings",
        lambda: SimpleNamespace(admin_enabled=True),
    )
    engine = create_async_engine(DATABASE_URL)
    registered = datetime(2026, 11, 10)
    collected = datetime(2026, 11, 17, 14, 30)
    goods_prefix = "DISCOVERY-TEST-"
    product_prefix = f"oy-{goods_prefix.lower()}"
    try:
        async with AsyncSession(engine) as session:
            for suffix in ("REVIEWED", "UNREVIEWED", "DELISTED", "HIDDEN", "SOURCE-ONLY"):
                session.add(
                    RawOyProductRow(
                        goods_no=f"{goods_prefix}{suffix}",
                        registered_at=registered,
                        is_new=True,
                        delisted_at=collected if suffix == "DELISTED" else None,
                    )
                )
            for suffix in ("reviewed", "unreviewed", "delisted", "hidden", "catalog-only"):
                product = make_product(f"{product_prefix}{suffix}", "base", [])
                session.add(
                    ProductRow(
                        **product.model_dump(by_alias=False, exclude={"shades"}),
                        search_text=build_search_text(product),
                    )
                )
            await session.flush()
            session.add(
                ProductAdminStateRow(product_id=f"{product_prefix}hidden", is_visible=False)
            )
            session.add_all(
                [
                    RawOyReviewSummaryRow(
                        goods_no=f"{goods_prefix}REVIEWED",
                        is_latest=False,
                        review_count=9,
                        rating_avg=3.5,
                        collected_at=registered,
                    ),
                    RawOyReviewSummaryRow(
                        goods_no=f"{goods_prefix}REVIEWED",
                        is_latest=True,
                        review_count=80,
                        rating_avg=4.5,
                        collected_at=collected,
                    ),
                ]
            )
            await session.flush()

            candidates = {
                row.product_id.removeprefix(product_prefix): row
                for row in await CatalogRepository(session).discovery_candidates()
                if row.product_id.startswith(product_prefix)
            }

            assert set(candidates) == {"reviewed", "unreviewed"}
            reviewed = candidates["reviewed"]
            assert (reviewed.rating_avg, reviewed.review_count) == (4.5, 80)
            assert reviewed.registered_on == registered.date()
            assert reviewed.review_collected_on == collected.date()
            assert candidates["unreviewed"].review_count is None
            assert candidates["unreviewed"].is_new is True
    finally:
        await engine.dispose()

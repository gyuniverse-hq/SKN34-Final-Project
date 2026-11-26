from datetime import date, datetime, timedelta
from unittest.mock import AsyncMock

from app.core.cache import Cache, NullCache
from app.repositories.catalog_repository import ProductDiscoveryCandidate
from app.services.catalog_service import (
    KOREA_TIMEZONE,
    CatalogService,
    rank_discovery_products,
)
from tests.conftest import SAMPLE, FakeCatalogStore, client_for

TODAY = date(2026, 11, 25)


def candidate(
    product_id,
    *,
    category="lip",
    registered_days_ago=14,
    collected_days_ago=0,
    rating=4.8,
    count=28,
    is_new=False,
):
    return ProductDiscoveryCandidate(
        product_id=product_id,
        category=category,
        registered_on=(
            TODAY - timedelta(days=registered_days_ago) if registered_days_ago is not None else None
        ),
        is_new=is_new,
        rating_avg=rating,
        review_count=count,
        review_collected_on=(
            TODAY - timedelta(days=collected_days_ago) if collected_days_ago is not None else None
        ),
    )


def test_hot_uses_observed_review_age_with_a_seven_day_floor_and_recent_registration():
    products = [
        candidate("missing-date", registered_days_ago=None),
        candidate("missing-collection", collected_days_ago=None),
        candidate("wrong-date-order", registered_days_ago=0, collected_days_ago=1),
        candidate("future-collection", collected_days_ago=-1),
        candidate("no-reviews", count=0),
        candidate("outside-window", registered_days_ago=60, count=6000),
        candidate("window-edge", registered_days_ago=59, count=59),
        candidate("rate-tie-unrated", registered_days_ago=7, count=14, rating=None),
        candidate("rate-tie-z", registered_days_ago=7, count=14),
        candidate("same-day", registered_days_ago=0, count=14),
        candidate("earlier-snapshot", registered_days_ago=21, collected_days_ago=14, count=35),
    ]

    order = rank_discovery_products(products, TODAY)

    assert order.hot == [
        "earlier-snapshot",
        "rate-tie-z",
        "same-day",
        "rate-tie-unrated",
        "window-edge",
    ]


def test_charts_use_rating_confidence_and_include_only_valid_reviews_in_each_group():
    products = [
        candidate("few-perfect-reviews", rating=5, count=3),
        candidate("tie-z", category="base", count=800),
        candidate("tie-a", category="eye", count=800),
        candidate("invalid-rating", category="cheek", rating=6),
        candidate("zero-reviews", category="cheek", count=0),
        candidate("missing-rating", category="lip", rating=None),
        candidate("sunscreen", category="suncare", rating=4.9),
        candidate("cream", category="skincare", rating=4.7),
        candidate("brush", category="tool", rating=5),
    ]

    order = rank_discovery_products(products, TODAY)

    assert order.makeup == ["tie-a", "tie-z", "few-perfect-reviews"]
    assert order.skincare == ["sunscreen", "cream"]


def test_new_arrivals_prioritize_registration_date_then_review_score():
    products = [
        candidate("unflagged", registered_days_ago=0),
        candidate("future-date", registered_days_ago=-1, is_new=True),
        candidate("missing-date", registered_days_ago=None, is_new=True),
        candidate("old-unrated", rating=None, is_new=True),
        candidate("old-lower-rated", rating=4.6, is_new=True),
        candidate("old-higher-rated", rating=4.9, is_new=True),
        candidate("newest-unrated", registered_days_ago=0, rating=None, count=None, is_new=True),
    ]

    assert rank_discovery_products(products, TODAY).new_arrivals == [
        "newest-unrated",
        "old-higher-rated",
        "old-lower-rated",
        "old-unrated",
    ]


def test_discovery_preview_and_full_responses_share_one_cached_order():
    today = datetime.now(KOREA_TIMEZONE).date()
    products = [
        ProductDiscoveryCandidate(
            f"oy-{category}-{index:02}", category, today, True, 4.8, index + 1, today
        )
        for category in ("lip", "skincare")
        for index in range(10)
    ]
    store = FakeCatalogStore(SAMPLE)
    store.discovery_candidates = AsyncMock(return_value=products)
    cache = AsyncMock(spec=Cache)
    cache.get_json.return_value = None
    client = client_for(CatalogService(store, cache, 300))

    preview = client.get("/api/discovery/product-order?preview=true")
    assert preview.status_code == 200
    assert preview.headers["cache-control"] == "public, max-age=300, s-maxage=300"
    key, cached_order, ttl = cache.set_json.await_args.args
    assert key.startswith("products:discovery:")
    assert ttl == 300

    cache.get_json.return_value = cached_order
    full = client.get("/api/discovery/product-order")
    assert full.status_code == 200
    assert set(full.json()) == {"hot", "makeup", "skincare", "newArrivals"}
    assert all(len(ids) > 8 for ids in full.json().values())
    assert preview.json() == {name: ids[:8] for name, ids in full.json().items()}
    cache.get_json.assert_awaited_with(key)
    store.discovery_candidates.assert_awaited_once()


def test_chart_pages_only_fetch_selected_product_ids_in_rank_order():
    today = datetime.now(KOREA_TIMEZONE).date()
    store = FakeCatalogStore(SAMPLE)
    store.discovery_candidates = AsyncMock(
        return_value=[
            ProductDiscoveryCandidate("base-1", "base", today, True, 4.0, 200, today),
            ProductDiscoveryCandidate("base-2", "base", today, True, 4.9, 200, today),
            ProductDiscoveryCandidate("lip-1", "lip", today, True, 4.7, 200, today),
            ProductDiscoveryCandidate("cream", "skincare", today, True, 4.9, 200, today),
        ]
    )
    store.search_products = AsyncMock(wraps=store.search_products)
    client = client_for(CatalogService(store, NullCache(), 300))

    path = "/api/discovery/charts/makeup?limit=2"
    first = client.get(path).json()
    last = client.get(f"{path}&offset=2").json()
    assert [p["id"] for p in first["products"]] == ["base-2", "lip-1"]
    assert first["hasMore"] is True
    assert [p["id"] for p in last["products"]] == ["base-1"]
    assert last["hasMore"] is False
    assert [call.args[2] for call in store.search_products.await_args_list] == [
        ["base-2", "lip-1"],
        ["base-1"],
    ]

from unittest.mock import AsyncMock

import pytest

from app.core.cache import NullCache
from app.schemas.catalog import CatalogBundle
from app.services.catalog_service import CONCERN_TAGS, CatalogService
from tests.conftest import FakeCatalogStore, client_for, make_product


def recommendation_client(products):
    service = CatalogService(FakeCatalogStore(CatalogBundle(products=products)), NullCache(), 60)
    return client_for(service)


def test_ranks_by_distinct_matching_concerns_and_returns_reasons():
    products = [
        make_product("one", "skincare", [], tags=["hydrating", "hydrating", "bestseller"]),
        make_product("both", "skincare", [], tags=["hydrating", "soothing", "firming"]),
        make_product("other", "skincare", [], tags=["pore-care"]),
        make_product("makeup", "base", [], tags=["hydrating", "soothing"]),
    ]
    response = recommendation_client(products).post(
        "/api/recommendations/skin", json={"concerns": ["sensitivity", "dryness", "dryness"]}
    )
    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    body = response.json()
    assert body["strategyVersion"] == "skin-concern-v1"
    assert body["concerns"] == ["dryness", "sensitivity"]
    assert body["status"] == "ok"
    assert [m["product"]["id"] for m in body["matches"]] == ["both", "one"]
    assert [m["score"] for m in body["matches"]] == [2, 1]
    assert body["matches"][0]["matchedConcerns"] == ["dryness", "sensitivity"]
    assert body["matches"][0]["product"]["priceKRW"] == 18000


def test_ties_are_stable_and_limit_is_applied_after_ranking():
    products = [
        make_product("z", "skincare", [], tags=["soothing"]),
        make_product("b", "suncare", [], tags=["soothing"]),
        make_product("a", "skincare", [], tags=["soothing", "hydrating"]),
    ]
    for ordered in (products, list(reversed(products))):
        body = recommendation_client(ordered).post(
            "/api/recommendations/skin", json={"concerns": ["sensitivity"], "limit": 2}
        ).json()
        assert [m["product"]["id"] for m in body["matches"]] == ["a", "b"]


@pytest.mark.parametrize("concern,tags", CONCERN_TAGS.items())
def test_each_supported_concern_uses_the_existing_catalog_tags(concern, tags):
    client = recommendation_client([make_product("care", "skincare", [], tags=list(tags))])
    body = client.post("/api/recommendations/skin", json={"concerns": [concern]}).json()
    assert body["matches"][0]["matchedConcerns"] == [concern]
    assert body["matches"][0]["score"] == 1


def test_empty_catalog_is_explicit_and_does_not_invent_products():
    body = recommendation_client([]).post(
        "/api/recommendations/skin", json={"concerns": ["pores"]}
    ).json()
    assert body["status"] == "empty_catalog"
    assert body["matches"] == []


def test_no_matches_does_not_fall_back_to_unrelated_products():
    client = recommendation_client([make_product("unrelated", "skincare", [], tags=["demo"])])
    body = client.post("/api/recommendations/skin", json={"concerns": ["pores"]}).json()
    assert body["status"] == "no_matches"
    assert body["matches"] == []


def test_no_concerns_does_not_read_the_catalog(catalog_service):
    catalog_service.list_products = AsyncMock(side_effect=AssertionError("unexpected catalog read"))
    body = client_for(catalog_service).post(
        "/api/recommendations/skin", json={"concerns": []}
    ).json()
    assert body["status"] == "no_concerns"
    assert body["matches"] == []
    catalog_service.list_products.assert_not_called()


def test_ranking_does_not_call_external_image_providers():
    images = AsyncMock()
    store = FakeCatalogStore(
        CatalogBundle(products=[make_product("care", "skincare", [], tags=["hydrating"])])
    )
    service = CatalogService(store, NullCache(), 60, images=images)
    response = client_for(service).post(
        "/api/recommendations/skin", json={"concerns": ["dryness"]}
    )
    assert response.status_code == 200
    assert response.json()["status"] == "ok"
    images.with_live_images.assert_not_called()


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"concerns": ["unknown"]},
        {"concerns": "dryness"},
        {"concerns": [None]},
        {"concerns": ["dryness"] * 8},
        {"concerns": ["dryness"], "limit": 0},
        {"concerns": ["dryness"], "limit": 21},
        {"concerns": ["dryness"], "limit": True},
        {"concerns": ["dryness"], "limit": 1.5},
        {"concerns": ["dryness"], "analysis": {"acne": 1}},
        {"concerns": ["dryness"], "questionnaire": {"tightness": 2}},
        {"concerns": ["dryness"], "photo": "data:image/jpeg;base64,placeholder"},
    ],
)
def test_invalid_or_extraneous_inputs_are_rejected(client, payload):
    response = client.post("/api/recommendations/skin", json=payload)
    assert response.status_code == 400
    assert response.json() == {"error": "Invalid request", "code": "invalid_request"}

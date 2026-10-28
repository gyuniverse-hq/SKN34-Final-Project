import pytest

from app.core.cache import NullCache
from app.schemas.catalog import CatalogBundle
from app.services.catalog_service import CatalogService
from tests.conftest import FakeCatalogStore, client_for, make_product

BUNDLE = CatalogBundle(
    products=[
        make_product("lip-a", "lip", [("01", "Rose", "#c0485a"), ("02", "Coral", "#e0705a")]),
        make_product("lip-b", "lip", [("10", "Near rose", "#c24a5c"), ("11", "Plum", "#6b2a3e")]),
        make_product("lip-c", "lip", [("20", "Rose glossy", "#c0485b")], texture="glossy"),
        make_product("cheek-a", "cheek", [("c1", "Rose blush", "#c0485a")], makeupZone="blush"),
        make_product("base-a", "base", [("21", "Light", "#f1d3b9")]),
    ]
)


@pytest.fixture
def client():
    return client_for(CatalogService(FakeCatalogStore(BUNDLE), NullCache(), 60))


def test_similar_ranks_same_zone_shades_by_delta_e_and_excludes_source(client):
    res = client.get("/api/shades/similar?productId=lip-a&shadeId=01&limit=10")
    assert res.status_code == 200
    body = res.json()
    assert body["source"] == {
        "productId": "lip-a", "shadeId": "01", "hex": "#c0485a", "makeupZone": "lip"
    }  # fmt: skip
    pairs = [(m["productId"], m["shadeId"]) for m in body["matches"]]
    assert ("lip-a", "01") not in pairs
    assert all(pid.startswith("lip-") for pid, _ in pairs)
    assert [m["deltaE"] for m in body["matches"]] == sorted(m["deltaE"] for m in body["matches"])
    assert {p["id"] for p in body["products"]} == {pid for pid, _ in pairs}


def test_similar_explains_matches_with_reason_codes(client):
    matches = client.get("/api/shades/similar?productId=lip-a&shadeId=01").json()["matches"]
    by_key = {(m["productId"], m["shadeId"]): m["reasons"] for m in matches}
    assert by_key[("lip-b", "10")] == ["close_color", "same_texture", "same_category"]
    assert by_key[("lip-c", "20")] == ["close_color", "same_category"]
    assert "close_color" not in by_key[("lip-b", "11")]


def test_similar_respects_limit(client):
    res = client.get("/api/shades/similar?productId=lip-a&shadeId=01&limit=2")
    assert len(res.json()["matches"]) == 2


@pytest.mark.parametrize(
    ("query", "status", "code"),
    [
        ("productId=nope&shadeId=01", 404, "not_found"),
        ("productId=lip-a&shadeId=99", 404, "shade_not_found"),
        ("productId=base-a&shadeId=21", 400, "not_try_on"),
        ("productId=lip-a", 400, "invalid_request"),
        ("productId=lip-a&shadeId=01&limit=0", 400, "invalid_request"),
    ],
)
def test_similar_errors_use_error_body(client, query, status, code):
    res = client.get(f"/api/shades/similar?{query}")
    assert res.status_code == status
    assert res.json()["code"] == code

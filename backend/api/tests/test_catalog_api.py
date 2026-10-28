import pytest

from app.schemas.catalog import CatalogBundle
from app.services.catalog_service import validate_catalog
from tests.conftest import SAMPLE


def test_products_use_the_app_json_contract(client):
    res = client.get("/api/products")
    assert res.status_code == 200
    assert res.headers["cache-control"] == "public, max-age=300, s-maxage=300"
    product = res.json()["products"][0]
    assert {"nameKo", "priceKRW", "makeupZone", "keyIngredients", "imageUrl"} <= product.keys()
    assert "price_krw" not in product


def test_products_filter_by_category_ids_and_query(client):
    assert [p["id"] for p in client.get("/api/products?category=base").json()["products"]] == [
        "base-1",
        "base-2",
    ]
    assert [p["id"] for p in client.get("/api/products?ids=lip-1,base-2").json()["products"]] == [
        "lip-1",
        "base-2",
    ]
    assert len(client.get("/api/products?q=BESTSELLER").json()["products"]) == 3


def test_unknown_category_is_rejected(client):
    res = client.get("/api/products?category=perfume")
    assert res.status_code == 400
    assert res.json() == {"error": "Unknown category", "code": "invalid_category"}


def test_missing_product_returns_error_body(client):
    res = client.get("/api/products/nope")
    assert res.status_code == 404
    assert res.json() == {"error": "Product not found", "code": "not_found"}


def test_look_detail_includes_its_products_and_omits_absent_optionals(client):
    body = client.get("/api/looks/look-1").json()
    assert body["look"]["items"] == [{"productId": "lip-1", "shadeId": "r1", "step": "lips"}]
    assert [p["id"] for p in body["products"]] == ["lip-1"]


def test_look_key_zones_round_trip_in_camel_case_and_reject_unknown_zones():
    from pydantic import ValidationError

    from app.schemas.catalog import CelebLook

    base = {
        "id": "l", "title": "t", "inspiration": "i", "description": "d", "thumbnailUrl": "u",
        "tutorialQuery": "q", "items": [], "tags": [],
        "makeup": {"lip": None, "blush": None, "eyeshadow": None},
    }  # fmt: skip
    look = CelebLook.model_validate({**base, "heroZones": ["lip", "eyeshadow"]})
    assert look.model_dump(by_alias=True, exclude_none=True)["heroZones"] == ["lip", "eyeshadow"]
    assert "heroZones" not in CelebLook.model_validate(base).model_dump(
        by_alias=True, exclude_none=True
    )
    with pytest.raises(ValidationError):
        CelebLook.model_validate({**base, "heroZones": ["tanning"]})


def test_stores_only_lists_pickup_stores_without_null_phone(client):
    stores = client.get("/api/stores").json()["stores"]
    assert [s["id"] for s in stores] == ["s1"]
    assert "phone" not in stores[0]


def test_unknown_route_uses_error_body(client):
    res = client.get("/api/unknown")
    assert res.status_code == 404
    assert res.json()["code"] == "not_found"


def test_responses_carry_request_id(client):
    res = client.get("/healthz", headers={"X-Request-ID": "abc123"})
    assert res.headers["x-request-id"] == "abc123"
    assert res.headers["cache-control"] == "no-store"


def _broken(mutate) -> CatalogBundle:
    bundle = SAMPLE.model_copy(deep=True)
    mutate(bundle)
    return bundle


@pytest.mark.parametrize(
    ("mutate", "message"),
    [
        (lambda b: setattr(b.looks[0].items[0], "product_id", "missing"), "unknown product"),
        (lambda b: setattr(b.looks[0].items[0], "shade_id", "nope"), "unknown shade"),
        (lambda b: setattr(b.products[1], "id", "lip-1"), "duplicate product"),
        (lambda b: setattr(b.products[0], "name_ko", " "), "Korean name"),
        (lambda b: setattr(b.products[0], "price_krw", 0), "price"),
        (lambda b: b.products[0].shades.clear(), "at least one shade"),
        (lambda b: setattr(b.stores[0], "lat", 126.98), "outside Korea"),
    ],
)
def test_catalog_integrity_rules(mutate, message):
    with pytest.raises(ValueError, match=message):
        validate_catalog(_broken(mutate))


def test_valid_catalogs_pass():
    validate_catalog(SAMPLE)
    validate_catalog(CatalogBundle())

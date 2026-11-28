import asyncio
import json

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.repositories import style_look_repository
from app.repositories.style_look_repository import StyleLookRepository
from app.schemas.style_look import StyleProduct

PRODUCT = {
    "number": 1,
    "brand": "스킨푸드",
    "name": "캐롯 카로틴 워터패드",
    "option": "원문에 명시 정보 없음",
    "category": "스킨케어",
    "zone": "피부",
    "reviewStatus": "검토 필요",
}
LOOK = {
    "id": "1qj6SactPVM",
    "catalog_title": "뉴트럴 바닐라 메이크업",
    "style_group": "컬러·톤 스타일",
    "style_tag": "#뉴트럴바닐라",
    "video_id": "1qj6SactPVM",
}


@pytest.fixture(autouse=True)
def catalog_rows(monkeypatch):
    # Adapt the existing fixture catalog to the new DB row contract; no production fallback.
    def rows():
        path = style_look_repository._DATA / "style_looks.json"
        return json.loads(path.read_text(encoding="utf-8"))

    async def published(session, source):
        assert source == "style"
        return [
            {
                "video_id": r["id"],
                "catalog_title": r["title"],
                "style_group": r["group"],
                "style_tag": r["tag"],
            }
            for r in rows()
        ]

    async def mentions(session, source):
        assert source == "style"
        return {r["id"]: r["products"] for r in rows()}

    monkeypatch.setattr(style_look_repository, "published_looks", published)
    monkeypatch.setattr(style_look_repository, "mention_payloads", mentions)


def recipe():
    # Test-only fabricated review; never added to the serving registry.
    return {
        "lookId": "fixture-look",
        "kind": "video",
        "version": "fixture-v1",
        "reviewStatus": "verified",
        "reviewerId": "fixture-reviewer",
        "source": "fixture:source",
        "evidenceId": "fixture:evidence",
        "synthetic": False,
        "productUsages": [
            {
                "stepOrder": 1,
                "productId": "blush-b",
                "shadeId": "blush-b-shade",
                "evidenceId": "fixture:usage",
                "source": "fixture:segment",
            }
        ],
        "steps": [{"order": 1, "zone": "blush", "title": "블러셔", "description": "합성 볼 단계"}],
    }


@pytest.fixture
def recipe_registry(tmp_path, monkeypatch):
    from app.repositories import style_look_repository as repository

    row = {
        "id": "fixture-look",
        "title": "Synthetic look",
        "group": "fixture",
        "tag": "fixture",
        "videoUrl": "https://www.youtube.com/watch?v=fixture-look",
        "products": [
            {
                "number": 1,
                "brand": "Fixture",
                "name": "blush-b",
                "option": "Fixture shade",
                "category": "cheek",
                "zone": "베이스 블러셔",
                "reviewStatus": "검토 완료",
                "mappingVerified": True,
                "catalogProductId": "blush-b",
                "catalogShadeId": "blush-b-shade",
            }
        ],
    }
    (tmp_path / "style_looks.json").write_text(json.dumps([row]), encoding="utf-8")
    monkeypatch.setattr(repository, "_DATA", tmp_path)
    repository._reviewed_recipes.cache_clear()
    yield tmp_path
    repository._reviewed_recipes.cache_clear()


def test_reviewed_recipe_serves_through_real_api_route(recipe_registry, record_property):
    from app.services.style_look_service import StyleLookService, get_style_look_service

    (recipe_registry / "reviewed_style_recipes.json").write_text(
        json.dumps([recipe()]), encoding="utf-8"
    )
    app.dependency_overrides[get_style_look_service] = lambda: StyleLookService(
        StyleLookRepository(session=None)
    )
    try:
        with TestClient(app) as client:
            response = client.get("/api/style-looks")
        assert response.status_code == 200
        payload = response.json()
        assert payload["looks"][0]["recipe"]["evidenceId"] == "fixture:evidence"
        assert payload["looks"][0]["products"][0]["catalogShadeId"] == "blush-b-shade"
        record_property("recipe_delivery_payload", json.dumps(payload, ensure_ascii=False))
    finally:
        app.dependency_overrides.pop(get_style_look_service, None)


@pytest.mark.parametrize(
    "change",
    [
        {"reviewStatus": "unreviewed"},
        {"reviewerId": " "},
        {"evidenceId": ""},
        {"lookId": "another-look"},
        {"synthetic": True},
        {"kind": "catalog"},
        {"steps": [{"order": 2, "zone": "blush", "title": "x", "description": "x"}]},
    ],
)
def test_unapproved_mismatched_or_synthetic_recipe_is_withheld(recipe_registry, change):
    (recipe_registry / "reviewed_style_recipes.json").write_text(
        json.dumps([{**recipe(), **change}]), encoding="utf-8"
    )
    (look,) = asyncio.run(StyleLookRepository(session=None).list_looks())
    assert "recipe" not in look.model_dump(mode="json", by_alias=True)
    assert len(look.products) == 1


def test_duplicate_recipe_versions_are_not_arbitrarily_selected(recipe_registry):
    (recipe_registry / "reviewed_style_recipes.json").write_text(
        json.dumps([recipe(), {**recipe(), "version": "v2"}]), encoding="utf-8"
    )
    assert asyncio.run(StyleLookRepository(session=None).list_looks())[0].recipe is None


def test_style_look_data_preserves_video_and_product_links():
    looks = asyncio.run(StyleLookRepository(session=None).list_looks())
    assert len(looks) == 73
    assert len({look.id for look in looks}) == len(looks)
    assert sum(len(look.products) for look in looks) == 906
    for look in looks:
        assert look.recipe is None
        assert look.video_url == f"https://www.youtube.com/watch?v={look.id}"
        assert len({product.number for product in look.products}) == len(look.products)
        assert all(product.review_status == "검토 필요" for product in look.products)


def test_style_looks_endpoint_uses_client_field_names(monkeypatch):
    from app.services.style_look_service import StyleLookService, get_style_look_service

    monkeypatch.setitem(
        app.dependency_overrides,
        get_style_look_service,
        lambda: StyleLookService(StyleLookRepository(session=None)),
    )
    with TestClient(app) as client:
        response = client.get("/api/style-looks")
    assert response.status_code == 200
    look = response.json()["looks"][0]
    assert look["videoUrl"].endswith(look["id"])
    assert look["products"][0]["reviewStatus"] == "검토 필요"


def test_verified_product_mapping_is_retained_in_api_contract():
    item = StyleProduct.model_validate(
        {
            "number": 1,
            "brand": "A",
            "name": "B",
            "option": "C",
            "category": "lip",
            "zone": "립",
            "reviewStatus": "검토 완료",
            "mappingVerified": True,
            "catalogProductId": "p1",
            "catalogShadeId": "s1",
        }
    )
    result = item.model_dump(mode="json", by_alias=True)
    assert result["mappingVerified"] is True
    assert result["catalogProductId"] == "p1"
    assert result["catalogShadeId"] == "s1"


@pytest.mark.parametrize(
    "change", [{"stepOrder": 2}, {"evidenceId": " "}, {"shadeId": ""}, {"unexpected": True}]
)
def test_invalid_usage_withheld(recipe_registry, change):
    row = recipe()
    row["productUsages"][0].update(change)
    (recipe_registry / "reviewed_style_recipes.json").write_text(
        json.dumps([row]), encoding="utf-8"
    )
    assert asyncio.run(StyleLookRepository(session=None).list_looks())[0].recipe is None


def test_legacy_recipe_without_usages_still_serves(recipe_registry):
    row = recipe()
    del row["productUsages"]
    (recipe_registry / "reviewed_style_recipes.json").write_text(
        json.dumps([row]), encoding="utf-8"
    )
    result = asyncio.run(StyleLookRepository(session=None).list_looks())[0].recipe
    assert result is not None and "productUsages" not in result.model_dump(by_alias=True)


def test_repository_builds_looks_from_catalog_rows_and_payloads(monkeypatch):
    calls = []

    async def published_looks(session, look_type):
        calls.append(look_type)
        return [LOOK, {**LOOK, "video_id": "empty", "catalog_title": "No products"}]

    async def mention_payloads(session, source):
        calls.append(source)
        return {"1qj6SactPVM": [PRODUCT]}

    monkeypatch.setattr(style_look_repository, "published_looks", published_looks)
    monkeypatch.setattr(style_look_repository, "mention_payloads", mention_payloads)
    looks = asyncio.run(StyleLookRepository(session=None).list_looks())
    assert calls == ["style", "style"]
    assert [look.model_dump(by_alias=True) for look in looks] == [
        {
            "id": "1qj6SactPVM",
            "title": "뉴트럴 바닐라 메이크업",
            "group": "컬러·톤 스타일",
            "tag": "#뉴트럴바닐라",
            "videoUrl": "https://www.youtube.com/watch?v=1qj6SactPVM",
            "products": [PRODUCT],
        },
        {
            "id": "empty",
            "title": "No products",
            "group": "컬러·톤 스타일",
            "tag": "#뉴트럴바닐라",
            "videoUrl": "https://www.youtube.com/watch?v=empty",
            "products": [],
        },
    ]

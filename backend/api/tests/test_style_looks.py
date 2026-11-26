import asyncio

from fastapi.testclient import TestClient

from app.main import app
from app.repositories import style_look_repository
from app.repositories.style_look_repository import StyleLookRepository
from app.schemas.style_look import StyleProduct
from app.services.style_look_service import StyleLookService, get_style_look_service

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


def test_style_looks_endpoint_uses_client_field_names(monkeypatch):
    async def published_looks(session, look_type):
        return [LOOK]

    async def mention_payloads(session, source):
        return {"1qj6SactPVM": [PRODUCT]}

    monkeypatch.setattr(style_look_repository, "published_looks", published_looks)
    monkeypatch.setattr(style_look_repository, "mention_payloads", mention_payloads)
    app.dependency_overrides[get_style_look_service] = lambda: StyleLookService(
        StyleLookRepository(session=None)
    )
    try:
        with TestClient(app) as client:
            response = client.get("/api/style-looks")
    finally:
        app.dependency_overrides.pop(get_style_look_service, None)
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

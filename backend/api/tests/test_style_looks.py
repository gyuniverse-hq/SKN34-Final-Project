import asyncio

from fastapi.testclient import TestClient

from app.main import app
from app.repositories.style_look_repository import StyleLookRepository


def test_style_look_data_preserves_video_and_product_links():
    looks = asyncio.run(StyleLookRepository().list_looks())
    assert len(looks) == 73
    assert len({look.id for look in looks}) == len(looks)
    assert sum(len(look.products) for look in looks) == 906
    for look in looks:
        assert look.video_url == f"https://www.youtube.com/watch?v={look.id}"
        assert len({product.number for product in look.products}) == len(look.products)
        assert all(product.review_status == "검토 필요" for product in look.products)


def test_style_looks_endpoint_uses_client_field_names():
    with TestClient(app) as client:
        response = client.get("/api/style-looks")
    assert response.status_code == 200
    look = response.json()["looks"][0]
    assert look["videoUrl"].endswith(look["id"])
    assert look["products"][0]["reviewStatus"] == "검토 필요"

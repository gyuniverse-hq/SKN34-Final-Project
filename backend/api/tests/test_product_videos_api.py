from app.schemas.celebrity_video import CelebrityVideo
from app.schemas.style_look import StyleLook
from app.services.product_video_service import ProductVideoService, get_product_video_service


class FakeCelebrities:
    async def list_videos(self):
        return [
            CelebrityVideo.model_validate(
                {
                    "id": "celeb",
                    "celebrityId": "karina",
                    "number": 1,
                    "startSeconds": 0,
                    "linkStatus": "metadata_available",
                    "title": "Title",
                    "channelName": "Channel",
                    "products": [
                        {
                            "number": 1,
                            "category": "립",
                            "zone": "입술",
                            "brand": "a",
                            "name": "b",
                            "option": "c",
                            "reviewStatus": "ok",
                            "sourceType": "미기재",
                            "mappingVerified": True,
                            "catalogProductId": "lip-1",
                            "catalogShadeId": "r1",
                        },
                        {
                            "number": 2,
                            "category": "립",
                            "zone": "입술",
                            "brand": "a",
                            "name": "b",
                            "option": "c",
                            "reviewStatus": "ok",
                            "sourceType": "미기재",
                            "catalogProductId": "lip-1",
                        },
                    ],
                }
            )
        ]


class FakeStyles:
    async def list_looks(self):
        return [
            StyleLook.model_validate(
                {
                    "id": "style",
                    "title": "Style",
                    "group": "group",
                    "tag": "tag",
                    "videoUrl": "url",
                    "products": [
                        {
                            "number": 1,
                            "category": "립",
                            "zone": "립",
                            "brand": "a",
                            "name": "b",
                            "option": "c",
                            "reviewStatus": "ok",
                            "mappingVerified": True,
                            "catalogProductId": "lip-1",
                        }
                    ],
                }
            )
        ]


def test_product_videos_verified_only_and_missing_product(client):
    client.app.dependency_overrides[get_product_video_service] = lambda: ProductVideoService(
        FakeCelebrities(), FakeStyles()
    )
    try:
        response = client.get("/api/products/lip-1/videos")
        assert response.status_code == 200
        assert response.headers["cache-control"] == "public, max-age=300, s-maxage=300"
        assert response.json() == {
            "videos": [
                {
                    "source": "celebrity",
                    "id": "celeb",
                    "title": "Title",
                    "channelName": "Channel",
                    "celebrityId": "karina",
                    "shadeId": "r1",
                },
                {"source": "style", "id": "style", "title": "Style", "channelName": ""},
            ]
        }
        assert client.get("/api/products/base-1/videos").json() == {"videos": []}
        missing = client.get("/api/products/nope/videos")
        assert missing.status_code == 404 and missing.json()["code"] == "not_found"
    finally:
        client.app.dependency_overrides.pop(get_product_video_service, None)

import asyncio

from app.repositories.verified_video_product_repository import VerifiedVideoProductLink
from app.schemas.celebrity_video import CelebrityVideo
from app.schemas.style_look import StyleLook
from app.services.product_video_service import ProductVideoService
from app.services.verified_video_product_links import attach_verified_links


def celebrity_video() -> CelebrityVideo:
    return CelebrityVideo.model_validate(
        {
            "id": "video-1",
            "celebrityId": "karina",
            "number": 1,
            "startSeconds": 0,
            "linkStatus": "metadata_available",
            "title": "Video",
            "channelName": "Channel",
            "products": [
                {
                    "number": 1,
                    "category": "립",
                    "zone": "입술",
                    "brand": "Brand",
                    "name": "Product",
                    "option": "01",
                    "reviewStatus": "ok",
                    "sourceType": "미기재",
                },
                {
                    "number": 2,
                    "category": "립",
                    "zone": "입술",
                    "brand": "Brand",
                    "name": "Other",
                    "option": "",
                    "reviewStatus": "ok",
                    "sourceType": "미기재",
                },
            ],
        }
    )


def test_confirmed_links_attach_only_to_the_matching_video_mention():
    video = celebrity_video()
    links = [
        VerifiedVideoProductLink("celebrity", "video-1", 1, "oy-a1", "A1-001"),
        VerifiedVideoProductLink("celebrity", "video-1", 2, "oy-a2", None),
        VerifiedVideoProductLink("style", "video-1", 1, "oy-other", None),
    ]
    [mapped] = attach_verified_links([video], links, "celebrity")
    assert mapped.products[0].mapping_verified is True
    assert mapped.products[0].catalog_product_id == "oy-a1"
    assert mapped.products[0].catalog_shade_id == "A1-001"
    assert mapped.products[1].catalog_product_id == "oy-a2"
    assert mapped.products[1].catalog_shade_id is None
    assert video.products[0].catalog_product_id is None


def test_ambiguous_mention_does_not_become_verified():
    [mapped] = attach_verified_links(
        [celebrity_video()],
        [
            VerifiedVideoProductLink("celebrity", "video-1", 1, "oy-a1", None),
            VerifiedVideoProductLink("celebrity", "video-1", 1, "oy-a2", None),
        ],
        "celebrity",
    )
    assert mapped.products[0].mapping_verified is None
    assert mapped.products[0].catalog_product_id is None


class FakeCelebrities:
    async def list_videos(self):
        return [celebrity_video()]


class FakeStyles:
    async def list_looks(self):
        return [
            StyleLook.model_validate(
                {
                    "id": "look-1",
                    "title": "Look",
                    "group": "group",
                    "tag": "tag",
                    "videoUrl": "https://www.youtube.com/watch?v=look-1",
                    "products": [
                        {
                            "number": 1,
                            "category": "립",
                            "zone": "입술",
                            "brand": "Brand",
                            "name": "Product",
                            "option": "",
                            "reviewStatus": "ok",
                        }
                    ],
                }
            )
        ]


class FakeMatches:
    async def links(self, *, source=None, product_id=None):
        links = [
            VerifiedVideoProductLink("celebrity", "video-1", 1, "oy-a1", "A1-001"),
            VerifiedVideoProductLink("style", "look-1", 1, "oy-a1", None),
        ]
        return [link for link in links if product_id is None or link.product_id == product_id]


def test_product_video_lookup_includes_confirmed_database_matches():
    service = ProductVideoService(FakeCelebrities(), FakeStyles(), FakeMatches())
    videos = asyncio.run(service.videos_for_product("oy-a1"))
    assert [(video.source, video.id, video.shade_id) for video in videos] == [
        ("celebrity", "video-1", "A1-001"),
        ("style", "look-1", None),
    ]

from fastapi.testclient import TestClient

from app.main import create_app
from app.schemas.idol_look import IdolLook
from app.services.idol_look_service import get_idol_look_service

PRESETS = {
    "LOOK-001": {
        "lip": {"hex": "#C96B72", "intensity": 0.52, "texture": "satin"},
        "blush": {"hex": "#E8A0A6", "intensity": 0.30, "texture": "sheer"},
        "eyeshadow": {"hex": "#B98A78", "intensity": 0.24, "texture": "satin"},
    },
    "LOOK-002": {
        "lip": {"hex": "#B45F6B", "intensity": 0.58, "texture": "velvet"},
        "blush": {"hex": "#C98B92", "intensity": 0.34, "texture": "sheer"},
        "eyeshadow": {"hex": "#8F6B66", "intensity": 0.30, "texture": "matte"},
    },
    "LOOK-003": {
        "lip": {"hex": "#D45B7A", "intensity": 0.62, "texture": "glossy"},
        "blush": {"hex": "#E69AAF", "intensity": 0.36, "texture": "cream"},
        "eyeshadow": {"hex": "#A97891", "intensity": 0.32, "texture": "shimmer"},
    },
}


def make_look(look_id: str, number: int) -> IdolLook:
    video_id = f"video-{number}"
    return IdolLook.model_validate(
        {
            "id": look_id,
            "displayName": f"Look {number}",
            "styleDescription": "Approximate AR recreation",
            "isPublished": True,
            "video": {
                "id": f"VIDEO-{number:03}",
                "videoId": video_id,
                "youtubeUrl": f"https://www.youtube.com/watch?v={video_id}",
                "startSeconds": 0,
                "title": f"Look {number}",
                "channelName": "Channel",
                "thumbnailUrl": f"https://i.ytimg.com/vi/{video_id}/hqdefault.jpg",
                "description": "Official description",
                "publishedAt": "2026-10-27T00:00:00Z",
                "makeupLookId": look_id,
                "analysisStatus": "metadata_ready",
                "productMappingStatus": "no_verified_products",
            },
            "products": [],
            "arSettings": PRESETS[look_id],
        }
    )


LOOKS = [make_look(f"LOOK-{number:03}", number) for number in range(1, 4)]


class FakeIdolLookService:
    async def list_looks(self):
        return LOOKS

    async def detail(self, look_id: str):
        look = next((item for item in LOOKS if item.id == look_id), None)
        return (look, []) if look else None


def test_all_registered_looks_return_three_valid_ar_zones():
    app = create_app()
    app.dependency_overrides[get_idol_look_service] = FakeIdolLookService

    with TestClient(app) as client:
        response = client.get("/api/idol-looks")

    assert response.status_code == 200
    looks = response.json()["looks"]
    assert len(looks) == 3
    for look in looks:
        assert set(look["arSettings"]) == {"lip", "blush", "eyeshadow"}
        for setting in look["arSettings"].values():
            assert setting["hex"].startswith("#")
            assert 0 <= setting["intensity"] <= 1


def test_idol_look_detail_uses_camel_case_contract():
    app = create_app()
    app.dependency_overrides[get_idol_look_service] = FakeIdolLookService

    with TestClient(app) as client:
        response = client.get("/api/idol-looks/LOOK-002")

    assert response.status_code == 200
    body = response.json()
    assert body["look"]["video"]["analysisStatus"] == "metadata_ready"
    assert body["look"]["arSettings"]["lip"]["texture"] == "velvet"
    assert body["products"] == []

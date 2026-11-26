import asyncio

from fastapi.testclient import TestClient

from app.main import app
from app.repositories import celebrity_video_repository
from app.repositories.celebrity_video_repository import CelebrityVideoRepository
from app.services.celebrity_video_service import (
    CelebrityVideoService,
    get_celebrity_video_service,
)

PRODUCT = {
    "number": 1,
    "category": "베이스",
    "zone": "얼굴",
    "brand": "클리오",
    "name": "킬커버 파운웨어 쿠션 21C 란제리",
    "option": "21C 란제리",
    "reviewStatus": "원본 기준 정리",
    "sourceType": "미기재",
}


def row(video_id, celebrity_id, position, **extra):
    return {
        "video_id": video_id,
        "celebrity_id": celebrity_id,
        "catalog_position": position,
        "catalog_start_seconds": 0,
        "catalog_link_status": "metadata_available",
        "catalog_title": f"{celebrity_id} {position}",
        "channel_name": "channel",
        **extra,
    }


def patch_rows(monkeypatch, rows, payloads):
    async def published_looks(session, look_type):
        assert look_type == "celebrity"
        return rows

    async def mention_payloads(session, source):
        assert source == "celebrity"
        return payloads

    monkeypatch.setattr(celebrity_video_repository, "published_looks", published_looks)
    monkeypatch.setattr(celebrity_video_repository, "mention_payloads", mention_payloads)


def test_videos_follow_app_profile_order_then_catalog_position(monkeypatch):
    # Rows arrive ordered by catalog_position; the profile order must win across celebrities.
    rows = [
        row("w1", "wony", 1),
        row("k1", "karina", 1),
        row("new1", "goyounjung", 1),
        row("k2", "karina", 2),
        row("j1", "jennie", 1, catalog_start_seconds=None, channel_name=None),
    ]
    patch_rows(monkeypatch, sorted(rows, key=lambda r: r["catalog_position"]), {"k1": [PRODUCT]})
    videos = asyncio.run(CelebrityVideoRepository(session=None).list_videos())
    assert [video.id for video in videos] == ["k1", "k2", "j1", "w1", "new1"]
    assert videos[0].products[0].brand == "클리오"
    assert videos[1].products == []
    assert videos[2].start_seconds == 0 and videos[2].channel_name == ""


def test_celebrity_videos_endpoint_uses_client_contract(monkeypatch):
    patch_rows(monkeypatch, [row("k1", "karina", 1)], {"k1": [PRODUCT]})
    app.dependency_overrides[get_celebrity_video_service] = lambda: CelebrityVideoService(
        CelebrityVideoRepository(session=None)
    )
    try:
        with TestClient(app) as client:
            response = client.get("/api/celebrity-videos")
    finally:
        app.dependency_overrides.pop(get_celebrity_video_service, None)
    assert response.status_code == 200
    video = response.json()["videos"][0]
    assert video["celebrityId"] == "karina"
    assert video["linkStatus"] == "metadata_available"
    assert video["products"][0]["reviewStatus"] == "원본 기준 정리"

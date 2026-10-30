import asyncio

from fastapi.testclient import TestClient

from app.main import app
from app.repositories.celebrity_video_repository import CelebrityVideoRepository


def test_celebrity_videos_preserve_associations():
    videos = asyncio.run(CelebrityVideoRepository().list_videos())
    assert len(videos) == 34
    assert len({video.id for video in videos}) == 34
    assert {video.celebrity_id for video in videos} == {
        "karina", "wonyoung", "sullyoon", "winter", "jennie", "haerin", "wony"
    }
    assert sum(len(video.products) for video in videos) == 711
    for video in videos:
        assert len({product.number for product in video.products}) == len(video.products)
    needs_review = sum(
        product.review_status == "브랜드 확인 필요"
        for video in videos
        for product in video.products
    )
    assert needs_review == 2
    assert sorted(video.start_seconds for video in videos if video.start_seconds) == [1, 1582]


def test_celebrity_videos_endpoint_uses_client_contract():
    with TestClient(app) as client:
        response = client.get("/api/celebrity-videos")
    assert response.status_code == 200
    video = response.json()["videos"][0]
    assert video["celebrityId"] == "karina"
    assert video["linkStatus"] == "metadata_available"
    assert "reviewStatus" in video["products"][0]

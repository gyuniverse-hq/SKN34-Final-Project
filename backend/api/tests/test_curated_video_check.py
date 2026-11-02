import asyncio
from types import SimpleNamespace

from app.core.errors import UpstreamError
from app.services.curated_video_check_service import CuratedVideoCheckService


class FakeVideos:
    async def list_videos(self):
        return [SimpleNamespace(id="public"), SimpleNamespace(id="deleted")]

    async def list_looks(self):
        return [SimpleNamespace(id="blocked")]


class FakeYoutube:
    async def get_video_details(self, ids):
        return [
            SimpleNamespace(video_id="public", privacy_status="public", embeddable=True),
            SimpleNamespace(video_id="blocked", privacy_status="public", embeddable=False),
        ]


def test_check_reports_status_and_resumes_from_offset():
    result = asyncio.run(
        CuratedVideoCheckService(FakeYoutube(), FakeVideos(), FakeVideos()).check(1)
    )
    assert [(r["videoId"], r["status"]) for r in result] == [
        ("deleted", "unavailable"),
        ("blocked", "not_embeddable"),
    ]


def test_quota_error_marks_remaining_without_leaking_error():
    class Quota:
        async def get_video_details(self, ids):
            raise UpstreamError("YouTube video lookup failed (403)")

    result = asyncio.run(CuratedVideoCheckService(Quota(), FakeVideos(), FakeVideos()).check())
    assert len(result) == 3 and all(row["status"] == "lookup_failed" for row in result)

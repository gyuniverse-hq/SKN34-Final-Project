import anyio

from app.core.errors import UpstreamError
from app.jobs.refresh_youtube_metadata import refresh_registered_metadata
from app.schemas.external import YoutubeVideoMetadata
from app.services.idol_look_service import IdolLookService


def metadata(video_id: str) -> YoutubeVideoMetadata:
    return YoutubeVideoMetadata(
        video_id=video_id,
        title=f"Title {video_id}",
        channel_title="Channel",
        thumbnail_url=f"https://i.ytimg.com/vi/{video_id}/hqdefault.jpg",
        published_at="2026-10-27T00:00:00Z",
        description="Official YouTube description",
    )


class FakeStore:
    def __init__(self) -> None:
        self.updated: list[YoutubeVideoMetadata] = []

    async def update_video_metadata(self, value: YoutubeVideoMetadata) -> None:
        self.updated.append(value)


class RecordingCache:
    def __init__(self) -> None:
        self.deleted: list[str] = []

    async def get_json(self, key):
        return None

    async def set_json(self, key, value, ttl_seconds):
        return None

    async def delete_prefix(self, prefix):
        self.deleted.append(prefix)


class FakeYoutube:
    def __init__(self, configured: bool = True) -> None:
        self.configured = configured
        self.calls: list[str] = []

    async def get_video_metadata(self, video_id: str):
        self.calls.append(video_id)
        return metadata(video_id)


def test_metadata_refresh_persists_and_invalidates_list_cache():
    store = FakeStore()
    cache = RecordingCache()
    youtube = FakeYoutube()
    service = IdolLookService(store, cache, youtube)  # type: ignore[arg-type]

    assert anyio.run(service.refresh_metadata, "video-1")
    assert [item.video_id for item in store.updated] == ["video-1"]
    assert cache.deleted == ["idol-looks"]


def test_metadata_refresh_without_key_keeps_fallback_and_skips_request():
    store = FakeStore()
    cache = RecordingCache()
    youtube = FakeYoutube(configured=False)
    service = IdolLookService(store, cache, youtube)  # type: ignore[arg-type]

    assert not anyio.run(service.refresh_metadata, "video-1")
    assert youtube.calls == []
    assert store.updated == []
    assert cache.deleted == []


class PartiallyFailingService:
    async def refresh_metadata(self, video_id: str) -> bool:
        if video_id == "bad":
            raise UpstreamError("YouTube lookup failed (403)")
        return video_id == "updated"


def test_refresh_job_continues_after_one_video_fails(capsys):
    summary = anyio.run(
        refresh_registered_metadata,
        PartiallyFailingService(),  # type: ignore[arg-type]
        ("updated", "bad", "missing"),
    )

    assert summary.updated == ("updated",)
    assert summary.failed == ("bad",)
    assert summary.unchanged == ("missing",)
    assert "YouTube metadata failed: bad" in capsys.readouterr().out

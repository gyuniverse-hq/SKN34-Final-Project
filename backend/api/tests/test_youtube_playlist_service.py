import anyio

from app.schemas.external import YoutubePlaylistItem, YoutubeVideoDetails
from app.services.youtube_playlist_service import YoutubePlaylistService


def playlist_item(position: int, video_id: str) -> YoutubePlaylistItem:
    return YoutubePlaylistItem(
        playlist_id="playlist",
        playlist_item_id=f"item-{position}",
        position=position,
        video_id=video_id,
        title=f"Playlist title {video_id}",
        channel_title="Channel",
        thumbnail_url="",
    )


def details(
    video_id: str, *, embeddable: bool = True, privacy_status: str = "public"
) -> YoutubeVideoDetails:
    return YoutubeVideoDetails(
        video_id=video_id,
        title=f"Official title {video_id}",
        channel_title="Official channel",
        thumbnail_url=f"https://i/{video_id}.jpg",
        published_at="2026-01-01",
        description="Official description",
        duration_iso8601="PT3M",
        duration_seconds=180,
        embeddable=embeddable,
        privacy_status=privacy_status,
    )


class FakeSource:
    configured = True

    async def list_playlist_items(self, playlist_id: str):
        return [
            playlist_item(0, "accepted"),
            playlist_item(1, "duplicate"),
            playlist_item(2, "duplicate"),
            playlist_item(3, "private"),
            playlist_item(4, "blocked"),
            playlist_item(5, "missing"),
        ]

    async def get_video_details(self, video_ids: list[str]):
        return [
            details("accepted"),
            details("duplicate"),
            details("private", privacy_status="private"),
            details("blocked", embeddable=False),
        ]


def test_playlist_collection_deduplicates_and_reports_every_exclusion():
    result = anyio.run(YoutubePlaylistService(FakeSource()).collect, "playlist")

    assert result.playlist_items == 6
    assert [candidate.video_id for candidate in result.candidates] == [
        "accepted",
        "duplicate",
    ]
    assert [candidate.playlist_position for candidate in result.candidates] == [0, 1]
    assert all(candidate.subject_name == "" for candidate in result.candidates)
    assert all(candidate.look_style == "" for candidate in result.candidates)
    assert all(candidate.review_status == "candidate" for candidate in result.candidates)
    assert [(item.video_id, item.reason) for item in result.excluded] == [
        ("duplicate", "duplicate_video_id"),
        ("private", "privacy_private"),
        ("blocked", "embedding_disabled"),
        ("missing", "unavailable_private_or_deleted"),
    ]

from dataclasses import dataclass
from typing import Protocol

from app.clients.youtube_client import get_youtube_client
from app.schemas.external import YoutubePlaylistItem, YoutubeVideoDetails


class YoutubePlaylistSource(Protocol):
    configured: bool

    async def list_playlist_items(self, playlist_id: str) -> list[YoutubePlaylistItem]: ...

    async def get_video_details(self, video_ids: list[str]) -> list[YoutubeVideoDetails]: ...


@dataclass(frozen=True)
class YoutubeCandidate:
    playlist_id: str
    playlist_item_id: str
    playlist_position: int
    video_id: str
    youtube_url: str
    title: str
    channel_name: str
    description: str
    thumbnail_url: str
    published_at: str
    duration_iso8601: str
    duration_seconds: int
    subject_name: str = ""
    look_style: str = ""
    review_status: str = "candidate"


@dataclass(frozen=True)
class ExcludedPlaylistItem:
    playlist_position: int
    video_id: str
    reason: str


@dataclass(frozen=True)
class PlaylistCollection:
    playlist_items: int
    candidates: tuple[YoutubeCandidate, ...]
    excluded: tuple[ExcludedPlaylistItem, ...]


class YoutubePlaylistService:
    def __init__(self, source: YoutubePlaylistSource) -> None:
        self._source = source

    @property
    def configured(self) -> bool:
        return self._source.configured

    async def collect(self, playlist_id: str) -> PlaylistCollection:
        items = await self._source.list_playlist_items(playlist_id)
        first_items: list[YoutubePlaylistItem] = []
        excluded: list[ExcludedPlaylistItem] = []
        seen: set[str] = set()
        for item in items:
            if item.video_id in seen:
                excluded.append(
                    ExcludedPlaylistItem(item.position, item.video_id, "duplicate_video_id")
                )
                continue
            seen.add(item.video_id)
            first_items.append(item)

        details = {
            video.video_id: video
            for video in await self._source.get_video_details(
                [item.video_id for item in first_items]
            )
        }
        candidates: list[YoutubeCandidate] = []
        for item in first_items:
            video = details.get(item.video_id)
            if video is None:
                excluded.append(
                    ExcludedPlaylistItem(
                        item.position, item.video_id, "unavailable_private_or_deleted"
                    )
                )
                continue
            if video.privacy_status != "public":
                excluded.append(
                    ExcludedPlaylistItem(
                        item.position, item.video_id, f"privacy_{video.privacy_status or 'unknown'}"
                    )
                )
                continue
            if not video.embeddable:
                excluded.append(
                    ExcludedPlaylistItem(item.position, item.video_id, "embedding_disabled")
                )
                continue
            candidates.append(
                YoutubeCandidate(
                    playlist_id=playlist_id,
                    playlist_item_id=item.playlist_item_id,
                    playlist_position=item.position,
                    video_id=video.video_id,
                    youtube_url=f"https://www.youtube.com/watch?v={video.video_id}",
                    title=video.title,
                    channel_name=video.channel_title,
                    description=video.description,
                    thumbnail_url=video.thumbnail_url,
                    published_at=video.published_at,
                    duration_iso8601=video.duration_iso8601,
                    duration_seconds=video.duration_seconds,
                )
            )
        return PlaylistCollection(
            playlist_items=len(items),
            candidates=tuple(candidates),
            excluded=tuple(sorted(excluded, key=lambda item: item.playlist_position)),
        )


def get_youtube_playlist_service() -> YoutubePlaylistService:
    return YoutubePlaylistService(get_youtube_client())

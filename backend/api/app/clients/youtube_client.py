import html
import re
from functools import lru_cache

import httpx

from app.core.config import get_settings
from app.core.errors import UpstreamError
from app.schemas.external import (
    YoutubePlaylistItem,
    YoutubeVideo,
    YoutubeVideoDetails,
    YoutubeVideoMetadata,
)

SEARCH_URL = "https://www.googleapis.com/youtube/v3/search"
VIDEOS_URL = "https://www.googleapis.com/youtube/v3/videos"
PLAYLIST_ITEMS_URL = "https://www.googleapis.com/youtube/v3/playlistItems"
YOUTUBE_DURATION = re.compile(
    r"^P(?:(?P<days>\d+)D)?T"
    r"(?:(?P<hours>\d+)H)?"
    r"(?:(?P<minutes>\d+)M)?"
    r"(?:(?P<seconds>\d+)S)?$"
)


def youtube_duration_seconds(value: str) -> int:
    match = YOUTUBE_DURATION.fullmatch(value)
    if match is None:
        return 0
    parts = {name: int(number or 0) for name, number in match.groupdict().items()}
    return parts["days"] * 86400 + parts["hours"] * 3600 + parts["minutes"] * 60 + parts["seconds"]


def _thumbnail(snippet: dict) -> str:
    thumbnails = snippet.get("thumbnails") or {}
    return next(
        (
            thumbnails[key]["url"]
            for key in ("maxres", "standard", "high", "medium", "default")
            if (thumbnails.get(key) or {}).get("url")
        ),
        "",
    )


class YoutubeClient:
    """YouTube Data API v3. The only place the YouTube key is used."""

    def __init__(
        self,
        api_key: str | None,
        timeout: float = 5,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._key = api_key
        self._timeout = timeout
        self._transport = transport

    @property
    def configured(self) -> bool:
        return bool(self._key)

    async def search_videos(self, query: str, max_results: int = 8) -> list[YoutubeVideo]:
        if not self._key:
            return []
        params = {
            "part": "snippet",
            "type": "video",
            "q": query,
            "maxResults": max_results,
            "safeSearch": "strict",
            "videoEmbeddable": "true",
            "key": self._key,
        }
        try:
            async with httpx.AsyncClient(timeout=self._timeout, transport=self._transport) as c:
                res = await c.get(SEARCH_URL, params=params)
        except httpx.HTTPError as exc:
            raise UpstreamError("YouTube request failed") from exc
        if res.status_code != 200:
            raise UpstreamError(f"YouTube search failed ({res.status_code})")

        videos = []
        for item in res.json().get("items", []):
            video_id = (item.get("id") or {}).get("videoId")
            snippet = item.get("snippet")
            if not video_id or not snippet:
                continue
            videos.append(
                YoutubeVideo(
                    video_id=video_id,
                    title=html.unescape(snippet.get("title") or ""),
                    channel_title=html.unescape(snippet.get("channelTitle") or ""),
                    thumbnail_url=_thumbnail(snippet),
                    published_at=snippet.get("publishedAt") or "",
                )
            )
        return videos

    async def get_video_metadata(self, video_id: str) -> YoutubeVideoMetadata | None:
        """Fetch registered-video metadata through the official Data API, never by scraping."""
        if not self._key:
            return None
        try:
            async with httpx.AsyncClient(
                timeout=self._timeout, transport=self._transport
            ) as client:
                response = await client.get(
                    VIDEOS_URL,
                    params={"part": "snippet", "id": video_id, "key": self._key},
                )
        except httpx.HTTPError as exc:
            raise UpstreamError("YouTube request failed") from exc
        if response.status_code != 200:
            raise UpstreamError(f"YouTube video lookup failed ({response.status_code})")
        items = response.json().get("items") or []
        if not items or not (snippet := items[0].get("snippet")):
            return None
        return YoutubeVideoMetadata(
            video_id=video_id,
            title=html.unescape(snippet.get("title") or ""),
            channel_title=html.unescape(snippet.get("channelTitle") or ""),
            thumbnail_url=_thumbnail(snippet),
            published_at=snippet.get("publishedAt") or "",
            description=snippet.get("description") or "",
        )

    async def list_playlist_items(self, playlist_id: str) -> list[YoutubePlaylistItem]:
        """Read every page of a playlist while preserving its declared position."""
        if not self._key:
            return []
        try:
            async with httpx.AsyncClient(
                timeout=self._timeout, transport=self._transport
            ) as client:
                page_token: str | None = None
                items: list[dict] = []
                while True:
                    params = {
                        "part": "snippet,contentDetails",
                        "playlistId": playlist_id,
                        "maxResults": 50,
                        "key": self._key,
                    }
                    if page_token:
                        params["pageToken"] = page_token
                    response = await client.get(PLAYLIST_ITEMS_URL, params=params)
                    if response.status_code != 200:
                        raise UpstreamError(
                            f"YouTube playlist lookup failed ({response.status_code})"
                        )
                    payload = response.json()
                    items.extend(payload.get("items") or [])
                    page_token = payload.get("nextPageToken")
                    if not page_token:
                        break
        except httpx.HTTPError as exc:
            raise UpstreamError("YouTube playlist request failed") from exc
        results = []
        for item in items:
            snippet = item.get("snippet") or {}
            content = item.get("contentDetails") or {}
            resource = snippet.get("resourceId") or {}
            video_id = content.get("videoId") or resource.get("videoId")
            if not video_id:
                continue
            results.append(
                YoutubePlaylistItem(
                    playlist_id=playlist_id,
                    playlist_item_id=item.get("id") or "",
                    position=snippet.get("position") or 0,
                    video_id=video_id,
                    title=html.unescape(snippet.get("title") or ""),
                    channel_title=html.unescape(snippet.get("videoOwnerChannelTitle") or ""),
                    thumbnail_url=_thumbnail(snippet),
                    added_at=snippet.get("publishedAt") or None,
                )
            )
        return sorted(results, key=lambda item: item.position)

    async def get_video_details(self, video_ids: list[str]) -> list[YoutubeVideoDetails]:
        """Fetch official metadata, status, and duration in API-sized batches."""
        if not self._key or not video_ids:
            return []
        unique_ids = list(dict.fromkeys(video_ids))
        responses: list[dict] = []
        try:
            async with httpx.AsyncClient(
                timeout=self._timeout, transport=self._transport
            ) as client:
                for start in range(0, len(unique_ids), 50):
                    response = await client.get(
                        VIDEOS_URL,
                        params={
                            "part": "snippet,status,contentDetails",
                            "id": ",".join(unique_ids[start : start + 50]),
                            "key": self._key,
                        },
                    )
                    if response.status_code != 200:
                        raise UpstreamError(f"YouTube video lookup failed ({response.status_code})")
                    responses.extend(response.json().get("items") or [])
        except httpx.HTTPError as exc:
            raise UpstreamError("YouTube request failed") from exc

        details = []
        for item in responses:
            snippet = item.get("snippet") or {}
            status = item.get("status") or {}
            content = item.get("contentDetails") or {}
            video_id = item.get("id")
            if not video_id or not snippet:
                continue
            duration = content.get("duration") or ""
            details.append(
                YoutubeVideoDetails(
                    video_id=video_id,
                    title=html.unescape(snippet.get("title") or ""),
                    channel_title=html.unescape(snippet.get("channelTitle") or ""),
                    thumbnail_url=_thumbnail(snippet),
                    published_at=snippet.get("publishedAt") or "",
                    description=snippet.get("description") or "",
                    duration_iso8601=duration,
                    duration_seconds=youtube_duration_seconds(duration),
                    embeddable=bool(status.get("embeddable")),
                    privacy_status=status.get("privacyStatus") or "",
                )
            )
        return details


@lru_cache
def get_youtube_client() -> YoutubeClient:
    return YoutubeClient(get_settings().youtube_api_key)

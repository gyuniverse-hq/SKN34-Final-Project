import html
from functools import lru_cache

import httpx

from app.core.config import get_settings
from app.core.errors import UpstreamError
from app.schemas.external import YoutubeVideo

SEARCH_URL = "https://www.googleapis.com/youtube/v3/search"


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
            thumbs = snippet.get("thumbnails") or {}
            thumbnail = next(
                (
                    thumbs[k]["url"]
                    for k in ("high", "medium", "default")
                    if (thumbs.get(k) or {}).get("url")
                ),
                "",
            )
            videos.append(
                YoutubeVideo(
                    video_id=video_id,
                    title=html.unescape(snippet.get("title") or ""),
                    channel_title=html.unescape(snippet.get("channelTitle") or ""),
                    thumbnail_url=thumbnail,
                    published_at=snippet.get("publishedAt") or "",
                )
            )
        return videos


@lru_cache
def get_youtube_client() -> YoutubeClient:
    return YoutubeClient(get_settings().youtube_api_key)

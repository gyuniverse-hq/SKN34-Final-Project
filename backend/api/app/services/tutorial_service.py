import re
from functools import lru_cache
from typing import Protocol

from app.clients.youtube_client import get_youtube_client
from app.core.cache import Cache, get_cache
from app.schemas.external import YoutubeVideo

# search.list costs 100 quota units (10,000/day by default), so cache aggressively.
TUTORIAL_CACHE_SECONDS = 12 * 60 * 60
_HAS_TUTORIAL_WORD = re.compile(r"makeup|tutorial|메이크업", re.IGNORECASE)


class VideoSource(Protocol):
    @property
    def configured(self) -> bool: ...
    async def search_videos(self, query: str, max_results: int = 8) -> list[YoutubeVideo]: ...


def build_tutorial_query(query: str) -> str:
    q = query.strip()
    return q if _HAS_TUTORIAL_WORD.search(q) else f"{q} makeup tutorial"


class TutorialService:
    """Makeup tutorial videos for a look (YouTube)."""

    def __init__(self, source: VideoSource, cache: Cache) -> None:
        self._source = source
        self._cache = cache

    @property
    def configured(self) -> bool:
        return self._source.configured

    async def search(self, query: str, max_results: int = 8) -> list[YoutubeVideo]:
        q = build_tutorial_query(query)
        key = f"tutorials:{q.lower()}:{max_results}"
        if (hit := await self._cache.get_json(key)) is not None:
            return [YoutubeVideo.model_validate(v) for v in hit]
        videos = await self._source.search_videos(q, max_results)
        await self._cache.set_json(
            key, [v.model_dump(mode="json") for v in videos], TUTORIAL_CACHE_SECONDS
        )
        return videos


@lru_cache
def get_tutorial_service() -> TutorialService:
    return TutorialService(get_youtube_client(), get_cache())

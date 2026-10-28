from typing import Protocol

from fastapi import Depends

from app.clients.youtube_client import YoutubeClient, get_youtube_client
from app.core.cache import Cache, get_cache
from app.core.db import get_session
from app.repositories.idol_look_repository import IdolLookRepository
from app.schemas.external import YoutubeVideoMetadata
from app.schemas.idol_look import IdolLook


class IdolLookStore(Protocol):
    async def list_published(self) -> list[IdolLook]: ...
    async def get_published(self, look_id: str) -> IdolLook | None: ...
    async def products_for(self, look: IdolLook): ...
    async def update_video_metadata(self, metadata: YoutubeVideoMetadata) -> None: ...


class IdolLookService:
    def __init__(self, store: IdolLookStore, cache: Cache, youtube: YoutubeClient) -> None:
        self._store = store
        self._cache = cache
        self._youtube = youtube

    async def list_looks(self) -> list[IdolLook]:
        if (hit := await self._cache.get_json('idol-looks')) is not None:
            return [IdolLook.model_validate(item) for item in hit]
        looks = await self._store.list_published()
        await self._cache.set_json(
            'idol-looks', [look.model_dump(mode='json') for look in looks], 300
        )
        return looks

    async def detail(self, look_id: str):
        look = await self._store.get_published(look_id)
        return (look, await self._store.products_for(look)) if look else None

    async def refresh_metadata(self, video_id: str) -> bool:
        """Persist official metadata; unavailable keys/videos leave fallback fields intact."""
        if not self._youtube.configured:
            return False
        metadata = await self._youtube.get_video_metadata(video_id)
        if metadata is None:
            return False
        await self._store.update_video_metadata(metadata)
        await self._cache.delete_prefix('idol-looks')
        return True


def idol_look_service_for(session) -> IdolLookService:
    return IdolLookService(IdolLookRepository(session), get_cache(), get_youtube_client())


def get_idol_look_service(session=Depends(get_session)) -> IdolLookService:
    return idol_look_service_for(session)

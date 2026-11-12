from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_session
from app.repositories.celebrity_video_repository import CelebrityVideoRepository
from app.repositories.verified_video_product_repository import VerifiedVideoProductRepository
from app.schemas.celebrity_video import CelebrityVideo
from app.services.verified_video_product_links import attach_verified_links


class CelebrityVideoService:
    def __init__(
        self,
        repository: CelebrityVideoRepository,
        matches: VerifiedVideoProductRepository | None = None,
    ) -> None:
        self._repository = repository
        self._matches = matches

    async def list_videos(self) -> list[CelebrityVideo]:
        videos = await self._repository.list_videos()
        if self._matches is None:
            return videos
        return attach_verified_links(
            videos, await self._matches.links(source="celebrity"), "celebrity"
        )


def get_celebrity_video_service(
    session: AsyncSession = Depends(get_session),
) -> CelebrityVideoService:
    return CelebrityVideoService(
        CelebrityVideoRepository(), VerifiedVideoProductRepository(session)
    )

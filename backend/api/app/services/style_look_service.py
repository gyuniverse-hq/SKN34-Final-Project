from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_session
from app.repositories.style_look_repository import StyleLookRepository
from app.repositories.verified_video_product_repository import VerifiedVideoProductRepository
from app.schemas.style_look import StyleLook
from app.services.verified_video_product_links import attach_verified_links


class StyleLookService:
    def __init__(
        self,
        repository: StyleLookRepository,
        matches: VerifiedVideoProductRepository | None = None,
    ) -> None:
        self._repository = repository
        self._matches = matches

    async def list_looks(self) -> list[StyleLook]:
        looks = await self._repository.list_looks()
        if self._matches is None:
            return looks
        return attach_verified_links(looks, await self._matches.links(source="style"), "style")


def get_style_look_service(session: AsyncSession = Depends(get_session)) -> StyleLookService:
    return StyleLookService(StyleLookRepository(), VerifiedVideoProductRepository(session))

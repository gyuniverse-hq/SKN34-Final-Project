from sqlalchemy.ext.asyncio import AsyncSession

from app.repositories.curated_video_rows import mention_payloads, published_looks
from app.schemas.style_look import StyleLook


class StyleLookRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def list_looks(self) -> list[StyleLook]:
        looks = await published_looks(self._session, "style")
        products = await mention_payloads(self._session, "style")
        return [
            StyleLook.model_validate(
                {
                    "id": look["video_id"],
                    "title": look["catalog_title"],
                    "group": look["style_group"],
                    "tag": look["style_tag"],
                    "videoUrl": f"https://www.youtube.com/watch?v={look['video_id']}",
                    "products": products.get(look["video_id"], []),
                }
            )
            for look in looks
        ]

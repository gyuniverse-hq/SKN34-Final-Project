from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_session
from app.repositories.celebrity_video_repository import CelebrityVideoRepository
from app.repositories.style_look_repository import StyleLookRepository
from app.repositories.verified_video_product_repository import VerifiedVideoProductRepository
from app.schemas.product_video import ProductVideo
from app.services.verified_video_product_links import attach_verified_links


class ProductVideoService:
    def __init__(
        self,
        celebrities: CelebrityVideoRepository,
        styles: StyleLookRepository,
        matches: VerifiedVideoProductRepository | None = None,
    ):
        self.celebrities = celebrities
        self.styles = styles
        self.matches = matches

    async def videos_for_product(self, product_id: str) -> list[ProductVideo]:
        results = []
        seen = set()
        links = await self.matches.links(product_id=product_id) if self.matches else []
        for source, videos in (
            ("celebrity", await self.celebrities.list_videos()),
            ("style", await self.styles.list_looks()),
        ):
            videos = attach_verified_links(videos, links, source)
            for video in videos:
                for item in video.products:
                    if item.mapping_verified is not True or item.catalog_product_id != product_id:
                        continue
                    identity = (source, video.id, item.catalog_shade_id)
                    if identity in seen:
                        continue
                    seen.add(identity)
                    results.append(
                        ProductVideo(
                            source=source,
                            id=video.id,
                            title=video.title,
                            channel_name=getattr(video, "channel_name", ""),
                            celebrity_id=getattr(video, "celebrity_id", None),
                            shade_id=item.catalog_shade_id,
                        )
                    )
        return results


def get_product_video_service(
    session: AsyncSession = Depends(get_session),
) -> ProductVideoService:
    return ProductVideoService(
        CelebrityVideoRepository(), StyleLookRepository(), VerifiedVideoProductRepository(session)
    )

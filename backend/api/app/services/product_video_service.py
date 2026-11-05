from app.repositories.celebrity_video_repository import CelebrityVideoRepository
from app.repositories.style_look_repository import StyleLookRepository
from app.schemas.product_video import ProductVideo


class ProductVideoService:
    def __init__(self, celebrities: CelebrityVideoRepository, styles: StyleLookRepository):
        self.celebrities = celebrities
        self.styles = styles

    async def videos_for_product(self, product_id: str) -> list[ProductVideo]:
        results = []
        seen = set()
        for source, videos in (
            ("celebrity", await self.celebrities.list_videos()),
            ("style", await self.styles.list_looks()),
        ):
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


def get_product_video_service() -> ProductVideoService:
    return ProductVideoService(CelebrityVideoRepository(), StyleLookRepository())

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.idol_look import MakeupLookRow, YoutubeVideoRow
from app.repositories.catalog_repository import CatalogRepository
from app.schemas.catalog import MakeupState, ZoneSetting
from app.schemas.external import YoutubeVideoMetadata
from app.schemas.idol_look import IdolLook, IdolLookProduct, IdolVideo


def _look(row: MakeupLookRow) -> IdolLook:
    video = row.video
    settings = {
        setting.makeup_zone: ZoneSetting(
            hex=setting.hex, intensity=setting.intensity, texture=setting.texture
        )
        for setting in row.ar_settings
    }
    return IdolLook(
        id=row.id,
        display_name=row.display_name,
        style_description=row.style_description,
        is_published=row.is_published,
        video=IdolVideo(
            id=video.id,
            video_id=video.video_id,
            youtube_url=video.youtube_url,
            start_seconds=video.start_seconds,
            title=video.title,
            channel_name=video.channel_name,
            thumbnail_url=video.thumbnail_url,
            description=video.description,
            published_at=video.published_at,
            makeup_look_id=row.id,
            analysis_status=video.analysis_status,
            product_mapping_status=video.product_mapping_status,
        ),
        products=[
            IdolLookProduct(
                id=item.id,
                makeup_zone=item.makeup_zone,
                status=item.status,
                product_id=item.product_id,
                shade_id=item.shade_id,
                source_type=item.source_type,
                source_url=item.source_url,
                evidence_text=item.evidence_text,
                verified=item.verified,
                similarity_score=item.similarity_score,
                recommendation_reason=item.recommendation_reason,
            )
            for item in row.products
        ],
        ar_settings=MakeupState(
            lip=settings.get("lip"),
            blush=settings.get("blush"),
            eyeshadow=settings.get("eyeshadow"),
        ),
    )


class IdolLookRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._catalog = CatalogRepository(session)

    async def list_published(self) -> list[IdolLook]:
        stmt = select(MakeupLookRow).where(MakeupLookRow.is_published).order_by(MakeupLookRow.id)
        rows = (await self._session.scalars(stmt)).all()
        return [_look(row) for row in rows]

    async def get_published(self, look_id: str) -> IdolLook | None:
        row = await self._session.get(MakeupLookRow, look_id)
        return _look(row) if row and row.is_published else None

    async def products_for(self, look: IdolLook):
        ids = [product.product_id for product in look.products if product.product_id]
        return await self._catalog.search_products([], ids=ids) if ids else []

    async def update_video_metadata(self, metadata: YoutubeVideoMetadata) -> None:
        row = await self._session.scalar(
            select(YoutubeVideoRow).where(YoutubeVideoRow.video_id == metadata.video_id)
        )
        if row is None:
            return
        row.title = metadata.title or row.title
        row.channel_name = metadata.channel_title
        row.thumbnail_url = metadata.thumbnail_url or row.thumbnail_url
        row.description = metadata.description
        row.published_at = metadata.published_at or None
        row.analysis_status = "metadata_ready"
        look = await self._session.scalar(
            select(MakeupLookRow).where(MakeupLookRow.video_id == row.id)
        )
        if look:
            look.display_name = row.title
        await self._session.commit()

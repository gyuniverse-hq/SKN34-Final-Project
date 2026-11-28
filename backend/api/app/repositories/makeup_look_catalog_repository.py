"""Read and write the catalog classification of makeup looks (0040)."""

from collections.abc import Iterable, Mapping
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.idol_look import MakeupLookRow, YoutubeVideoRow
from app.models.raw_youtube_product import RawYtProductMentionRow

CATALOG_FIELDS = (
    "look_type",
    "style_group",
    "style_tag",
    "celebrity_id",
    "catalog_title",
    "catalog_position",
    "catalog_start_seconds",
    "catalog_link_status",
    "is_catalog_published",
)
CURATED_SOURCES = ("style", "celebrity")


class MakeupLookCatalogRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def looks(self) -> list[dict[str, Any]]:
        """Every look with its YouTube id, video title and current catalog values."""
        columns = [getattr(MakeupLookRow, name) for name in CATALOG_FIELDS]
        stmt = (
            select(MakeupLookRow.id, YoutubeVideoRow.video_id, YoutubeVideoRow.title, *columns)
            .join(YoutubeVideoRow, YoutubeVideoRow.id == MakeupLookRow.video_id)
            .order_by(MakeupLookRow.id)
        )
        rows = (await self._session.execute(stmt)).mappings()
        return [
            {"look_id": r["id"], "youtube_id": r["video_id"], "video_title": r["title"], **r}
            for r in rows
        ]

    async def curated_mentions(self) -> dict[tuple[str, str, int], dict[str, Any]]:
        """(source, YouTube id, mention number) -> row id and current curated payload."""
        stmt = select(
            RawYtProductMentionRow.source_row_id,
            RawYtProductMentionRow.source,
            RawYtProductMentionRow.video_id,
            RawYtProductMentionRow.mention_number,
            RawYtProductMentionRow.source_payload,
        ).where(RawYtProductMentionRow.source.in_(CURATED_SOURCES))
        rows = (await self._session.execute(stmt)).all()
        return {
            (r.source, r.video_id, r.mention_number): {
                "source_row_id": r.source_row_id,
                "source_payload": r.source_payload,
            }
            for r in rows
        }

    async def apply(
        self,
        looks: Mapping[str, Mapping[str, Any]],
        payloads: Iterable[tuple[str, dict[str, Any]]],
    ) -> None:
        """Write look catalog values and mention payloads in one transaction."""
        for look_id, values in looks.items():
            await self._session.execute(
                update(MakeupLookRow).where(MakeupLookRow.id == look_id).values(**values)
            )
        for source_row_id, payload in payloads:
            await self._session.execute(
                update(RawYtProductMentionRow)
                .where(RawYtProductMentionRow.source_row_id == source_row_id)
                .values(source_payload=payload)
            )
        await self._session.commit()

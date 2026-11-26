"""Database access for registering look videos and linking their products."""

from collections.abc import Iterable, Mapping, Sequence
from typing import Any

from sqlalchemy import delete, insert, select, text, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.idol_look import (
    LookProductRow,
    LookVideoTagRow,
    MakeupLookRow,
    YoutubeVideoRow,
)
from app.schemas.look_video import PlannedVideo

STYLE_PLACEHOLDER = "Video is registered. Makeup style has not been verified."

# A mention reaches a serving product only through a reviewed path: a YouTube-only catalog
# link, or a confirmed Olive Young match whose serving id is oy-<goods_no>.
REVIEWED_MENTIONS_SQL = text(
    """
    SELECT l.id AS look_id, m.mention_number, m.video_url, m.video_use_evidence,
           x.product_id, x.path, x.oy_goods_no, x.oy_option_id, x.similarity, p.makeup_zone
    FROM raw_yt_product_mention m
    JOIN youtube_videos v ON v.video_id = m.video_id
    JOIN makeup_looks l ON l.video_id = v.id
    JOIN (
        SELECT source_yt_product_id AS yt_product_id, serving_product_id AS product_id,
               'catalog_link' AS path, NULL::text AS oy_goods_no, NULL::text AS oy_option_id,
               NULL::float AS similarity
        FROM yt_catalog_product_link
        UNION ALL
        SELECT o.yt_product_id, s.id, 'oy_confirmed', o.oy_goods_no, o.oy_option_id,
               o.similarity_score
        FROM yt_oy_product_match o
        JOIN products s ON s.id = left('oy-' || lower(o.oy_goods_no), 64)
        WHERE o.decision_status = 'confirmed'
    ) x ON x.yt_product_id = m.yt_product_id
    JOIN products p ON p.id = x.product_id
    ORDER BY l.id, m.mention_number
    """
)
OPTIONS_SQL = text(
    "SELECT option_id, goods_no, shade_code FROM raw_oy_product_option WHERE goods_no = ANY(:goods)"
)
SHADES_SQL = text("SELECT product_id, id FROM shades WHERE product_id = ANY(:products)")


class LookVideoRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def registered_ids(self) -> tuple[dict[str, str], list[str]]:
        """YouTube id -> youtube_videos.id, and every video and look id already used."""
        pairs = await self._session.execute(select(YoutubeVideoRow.video_id, YoutubeVideoRow.id))
        existing = dict(pairs.all())
        used = list(existing.values())
        used += list(await self._session.scalars(select(MakeupLookRow.id)))
        return existing, used

    async def register(self, planned: Sequence[PlannedVideo], write: bool) -> dict[str, int]:
        """Insert new videos and unpublished looks; refresh start times of known ones."""
        rows = {
            row.video_id: row
            for row in await self._session.scalars(
                select(YoutubeVideoRow).where(
                    YoutubeVideoRow.video_id.in_([item.video_id for item in planned])
                )
            )
        }
        look_ids = set(await self._session.scalars(select(MakeupLookRow.id)))
        counts = {"videos_added": 0, "looks_added": 0, "start_updated": 0}
        for item in planned:
            row = rows.get(item.video_id)
            if row is None:
                self._session.add(
                    YoutubeVideoRow(
                        id=item.id,
                        video_id=item.video_id,
                        youtube_url=item.youtube_url,
                        start_seconds=item.start_seconds,
                        title=item.title,
                        channel_name=item.channel_name,
                        thumbnail_url=item.thumbnail_url,
                        description=item.description,
                        published_at=None,
                        analysis_status=item.analysis_status,
                        product_mapping_status="unreviewed",
                    )
                )
                counts["videos_added"] += 1
            elif item.start_seconds and row.start_seconds != item.start_seconds:
                row.start_seconds = item.start_seconds
                counts["start_updated"] += 1
            if item.look_id not in look_ids:
                self._session.add(
                    MakeupLookRow(
                        id=item.look_id,
                        video_id=item.id,
                        display_name=item.title,
                        style_description=STYLE_PLACEHOLDER,
                        is_published=False,
                    )
                )
                counts["looks_added"] += 1
        if write:
            await self._session.commit()
        else:
            await self._session.rollback()
        return counts

    async def reviewed_mentions(self) -> list[dict[str, Any]]:
        result = await self._session.execute(REVIEWED_MENTIONS_SQL)
        return [dict(row) for row in result.mappings()]

    async def shade_sources(
        self, goods: Iterable[str], products: Iterable[str]
    ) -> tuple[list[dict[str, Any]], list[tuple[str, str]]]:
        """Olive Young options of the matched goods and the serving shades of the products."""
        options = await self._session.execute(OPTIONS_SQL, {"goods": sorted(goods)})
        shades = await self._session.execute(SHADES_SQL, {"products": sorted(products)})
        return [dict(row) for row in options.mappings()], [(r.product_id, r.id) for r in shades]

    async def look_videos(self) -> dict[str, str]:
        """makeup_looks.id -> youtube_videos.id for every look."""
        result = await self._session.execute(select(MakeupLookRow.id, MakeupLookRow.video_id))
        return dict(result.all())

    async def replace_look_products(
        self,
        source_type: str,
        look_ids: Iterable[str],
        rows: Sequence[Mapping[str, Any]],
        statuses: Mapping[str, Sequence[str]],
    ) -> None:
        """Swap this source's rows and video mapping statuses in one transaction."""
        await self._session.execute(
            delete(LookProductRow).where(
                LookProductRow.source_type == source_type,
                LookProductRow.look_id.in_(list(look_ids)),
            )
        )
        if rows:
            await self._session.execute(insert(LookProductRow), list(rows))
        for status, videos in statuses.items():
            if videos:
                await self._session.execute(
                    update(YoutubeVideoRow)
                    .where(YoutubeVideoRow.id.in_(list(videos)))
                    .values(product_mapping_status=status)
                )
        await self._session.commit()

    async def reviewed_tag_video_ids(self) -> set[str]:
        """Videos whose tags a person has confirmed; batch loads never overwrite them."""
        result = await self._session.scalars(
            select(LookVideoTagRow.video_id).where(LookVideoTagRow.review_status == "user_reviewed")
        )
        return set(result)

    async def replace_video_tags(self, rows: Sequence[Mapping[str, Any]]) -> None:
        """Swap the given videos' tag rows in one transaction."""
        if not rows:
            return
        await self._session.execute(
            delete(LookVideoTagRow).where(
                LookVideoTagRow.video_id.in_([row["video_id"] for row in rows])
            )
        )
        await self._session.execute(insert(LookVideoTagRow), list(rows))
        await self._session.commit()

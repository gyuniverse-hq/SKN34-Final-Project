"""Shared reads for the curated style/celebrity screens (makeup_looks catalog columns, 0040)."""

from collections import defaultdict
from typing import Any

from sqlalchemy import RowMapping, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.idol_look import MakeupLookRow, YoutubeVideoRow
from app.models.raw_youtube_product import RawYtProductMentionRow


async def published_looks(session: AsyncSession, look_type: str) -> list[RowMapping]:
    """Looks shown on the general screens, in catalog order, with their YouTube video."""
    stmt = (
        select(
            MakeupLookRow.id,
            MakeupLookRow.style_group,
            MakeupLookRow.style_tag,
            MakeupLookRow.celebrity_id,
            MakeupLookRow.catalog_title,
            MakeupLookRow.catalog_position,
            MakeupLookRow.catalog_start_seconds,
            MakeupLookRow.catalog_link_status,
            YoutubeVideoRow.video_id,
            YoutubeVideoRow.channel_name,
        )
        .join(YoutubeVideoRow, YoutubeVideoRow.id == MakeupLookRow.video_id)
        .where(MakeupLookRow.look_type == look_type, MakeupLookRow.is_catalog_published)
        .order_by(MakeupLookRow.catalog_position, MakeupLookRow.id)
    )
    return list((await session.execute(stmt)).mappings())


async def mention_payloads(session: AsyncSession, source: str) -> dict[str, list[dict[str, Any]]]:
    """YouTube id -> curated product display values, in mention order.

    Mentions without a payload (not curated) are left out.
    """
    mention = RawYtProductMentionRow
    stmt = (
        select(mention.video_id, mention.source_payload)
        .where(mention.source == source, mention.source_payload.is_not(None))
        .order_by(mention.video_id, mention.mention_number)
    )
    payloads: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for video_id, payload in (await session.execute(stmt)).all():
        payloads[video_id].append(payload)
    return payloads

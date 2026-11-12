"""Confirmed researched-video product links that resolve to serving products."""

from dataclasses import dataclass

from sqlalchemy import and_, func, literal, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.catalog import ProductRow, ShadeRow
from app.models.raw_youtube_product import (
    RawYtProductMentionRow,
    YtCatalogProductLinkRow,
    YtOyProductMatchRow,
)


@dataclass(frozen=True)
class VerifiedVideoProductLink:
    source: str
    video_id: str
    mention_number: int
    product_id: str
    shade_id: str | None
    link_type: str = "confirmed_oy"
    display_brand: str | None = None
    display_name: str | None = None


class VerifiedVideoProductRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def links(
        self, *, source: str | None = None, product_id: str | None = None
    ) -> list[VerifiedVideoProductLink]:
        mention = RawYtProductMentionRow
        match = YtOyProductMatchRow
        stmt = (
            select(
                mention.source,
                mention.video_id,
                mention.mention_number,
                ProductRow.id,
                ShadeRow.id,
            )
            .join(match, match.yt_product_id == mention.yt_product_id)
            .join(ProductRow, ProductRow.id == literal("oy-") + func.lower(match.oy_goods_no))
            .outerjoin(
                ShadeRow,
                and_(
                    ShadeRow.product_id == ProductRow.id,
                    ShadeRow.id == match.oy_option_id,
                ),
            )
            .where(match.decision_status == "confirmed")
        )
        if source is not None:
            stmt = stmt.where(mention.source == source)
        if product_id is not None:
            stmt = stmt.where(ProductRow.id == product_id)
        rows = (await self._session.execute(stmt)).all()
        links = [VerifiedVideoProductLink(*row, "confirmed_oy") for row in rows]

        curated = (
            select(
                mention.source,
                mention.video_id,
                mention.mention_number,
                ProductRow.id,
                literal(None),
                YtCatalogProductLinkRow.link_type,
                ProductRow.brand,
                ProductRow.name,
            )
            .join(
                YtCatalogProductLinkRow,
                YtCatalogProductLinkRow.source_yt_product_id == mention.yt_product_id,
            )
            .join(ProductRow, ProductRow.id == YtCatalogProductLinkRow.serving_product_id)
        )
        if source is not None:
            curated = curated.where(mention.source == source)
        if product_id is not None:
            curated = curated.where(ProductRow.id == product_id)
        links.extend(
            VerifiedVideoProductLink(*row) for row in (await self._session.execute(curated)).all()
        )

        # A verified YouTube-only item uses its raw research ID as its serving ID.
        # It has no Olive Young decision or shade unless separately verified.
        direct = (
            select(
                mention.source,
                mention.video_id,
                mention.mention_number,
                ProductRow.id,
            )
            .join(ProductRow, ProductRow.id == mention.yt_product_id)
            .where(ProductRow.id.like("yt-%"), ProductRow.tags.contains(["youtube"]))
            .where(
                ~select(YtCatalogProductLinkRow.source_yt_product_id)
                .where(YtCatalogProductLinkRow.source_yt_product_id == mention.yt_product_id)
                .exists()
            )
            .where(
                ~select(match.match_id)
                .where(
                    match.yt_product_id == mention.yt_product_id,
                    match.decision_status == "confirmed",
                )
                .exists()
            )
        )
        if source is not None:
            direct = direct.where(mention.source == source)
        if product_id is not None:
            direct = direct.where(ProductRow.id == product_id)
        for row in (await self._session.execute(direct)).all():
            links.append(VerifiedVideoProductLink(*row, None, "direct"))
        unique = {
            (link.source, link.video_id, link.mention_number, link.product_id, link.shade_id): link
            for link in links
        }
        return sorted(
            unique.values(),
            key=lambda link: (
                link.source,
                link.video_id,
                link.mention_number,
                link.product_id,
                link.shade_id or "",
            ),
        )

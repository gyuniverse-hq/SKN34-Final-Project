"""Confirmed researched-video product links that resolve to serving products."""

from collections import defaultdict
from dataclasses import dataclass

from sqlalchemy import and_, func, literal, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.video_shade_resolution import (
    RawShadeColor,
    RawShadeOption,
    ServingShade,
    resolve_confirmed_shade_fallback,
)
from app.models.catalog import ProductRow, ShadeRow
from app.models.raw_oliveyoung import RawOyOptionColorRow, RawOyProductOptionRow
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
    option_id: str | None = None


class VerifiedVideoProductRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def _resolve_missing_shades(
        self, pending: set[tuple[str, str, str]]
    ) -> dict[tuple[str, str, str], str]:
        """Batch read source-option evidence only for confirmed, unresolved rows."""
        if not pending:
            return {}
        goods = {g for _, g, _ in pending}
        products = {p for p, _, _ in pending}
        option_ids = {o for _, _, o in pending}
        # All options for the matched goods are necessary to detect shared color codes.
        # Do not filter delisted or unreferenced options: the old builder also considered them.
        option = RawOyProductOptionRow
        option_rows = (
            await self._session.execute(
                select(
                    option.option_id, option.goods_no, option.shade_code, option.shade_name
                ).where(option.goods_no.in_(goods))
            )
        ).all()
        options_by_goods: dict[str, list[RawShadeOption]] = defaultdict(list)
        for row in option_rows:
            source_option = RawShadeOption(*row)
            options_by_goods[source_option.goods_no].append(source_option)

        color = RawOyOptionColorRow
        color_rows = (
            await self._session.execute(
                select(color.option_id, color.hex_code, color.color_method)
                .where(color.option_id.in_(option_ids))
                .order_by(color.option_id, color.collected_at.desc())
            )
        ).all()
        latest_color: dict[str, RawShadeColor] = {}
        for option_id, hex_code, color_method in color_rows:
            # Match the builder's latest-color semantics: a newer NULL must not be
            # silently replaced with an older valid hex.
            latest_color.setdefault(option_id, RawShadeColor(hex_code, color_method))

        shade_rows = (
            await self._session.execute(
                select(
                    ShadeRow.product_id,
                    ShadeRow.id,
                    ShadeRow.name,
                    ShadeRow.hex,
                    ShadeRow.measure_method,
                    ShadeRow.color_source,
                ).where(ShadeRow.product_id.in_(products))
            )
        ).all()
        shades_by_product: dict[str, list[ServingShade]] = defaultdict(list)
        for row in shade_rows:
            shade = ServingShade(*row)
            shades_by_product[shade.product_id].append(shade)

        resolved: dict[tuple[str, str, str], str] = {}
        for key in pending:
            product_id, goods_no, option_id = key
            shade_id = resolve_confirmed_shade_fallback(
                product_id=product_id,
                raw_option_id=option_id,
                options=options_by_goods[goods_no],
                shades=shades_by_product[product_id],
                color=latest_color.get(option_id),
            )
            if shade_id is not None:
                resolved[key] = shade_id
        return resolved

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
                match.oy_goods_no,
                select(RawOyProductOptionRow.option_id)
                .where(
                    RawOyProductOptionRow.option_id == match.oy_option_id,
                    RawOyProductOptionRow.goods_no == match.oy_goods_no,
                    RawOyProductOptionRow.delisted_at.is_(None),
                )
                .scalar_subquery(),
            )
            .select_from(mention)
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
        resolved = await self._resolve_missing_shades(
            {
                (pid, goods_no, option_id)
                for _, _, _, pid, exact_shade, goods_no, option_id in rows
                if exact_shade is None and option_id is not None
            }
        )
        links = [
            VerifiedVideoProductLink(
                src,
                video,
                number,
                pid,
                exact_shade
                if exact_shade is not None
                else resolved.get((pid, goods_no, option_id)),
                "confirmed_oy",
                option_id=option_id,
            )
            for src, video, number, pid, exact_shade, goods_no, option_id in rows
        ]

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

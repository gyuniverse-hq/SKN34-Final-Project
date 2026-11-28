"""Read Olive Young raw tables for the serving-catalog export."""

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.video_shade_resolution import (
    RawShadeColor,
    RawShadeOption,
    ServingShade,
    resolve_confirmed_shade_fallback,
)
from app.models.catalog import ShadeRow
from app.models.raw_oliveyoung import (
    RawOyBrandRow,
    RawOyCategoryRow,
    RawOyImageRow,
    RawOyOptionColorRow,
    RawOyPriceSnapshotRow,
    RawOyProductNoticeRow,
    RawOyProductOptionRow,
    RawOyProductRow,
    RawOyProductTextureRow,
)
from app.schemas.oy_catalog import (
    CARE_PATH_TOKENS,
    ZONE_BY_CATEGORY,
    OyProductInput,
    OyShadeInput,
    catalog_category,
    derive_care_tags,
)


class OyCatalogRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def option_identity(self, option_id: str, product_id: str):
        if not product_id.startswith("oy-"):
            return None
        row = (
            await self._session.execute(
                select(
                    RawOyProductOptionRow.option_id,
                    RawOyProductOptionRow.option_name,
                    RawOyProductOptionRow.collected_at,
                    RawOyProductRow.product_url,
                )
                .join(RawOyProductRow, RawOyProductRow.goods_no == RawOyProductOptionRow.goods_no)
                .where(
                    RawOyProductOptionRow.option_id == option_id,
                    RawOyProductOptionRow.goods_no == product_id.removeprefix("oy-").upper(),
                    RawOyProductOptionRow.delisted_at.is_(None),
                    RawOyProductRow.delisted_at.is_(None),
                )
            )
        ).one_or_none()
        return tuple(row) if row else None

    async def option_image(self, option_id: str, product_id: str):
        rows = (
            await self._session.execute(
                select(RawOyImageRow.image_url, RawOyImageRow.image_type)
                .where(
                    RawOyImageRow.option_id == option_id,
                    RawOyImageRow.goods_no == product_id.removeprefix("oy-").upper(),
                    RawOyImageRow.image_type.in_(["option", "color_chip", "color_compare"]),
                )
                .order_by(RawOyImageRow.sort_seq, RawOyImageRow.image_id)
            )
        ).all()
        for kind in ("option", "color_chip", "color_compare"):
            for url, image_type in rows:
                if image_type == kind and url and url.startswith("https://"):
                    return url, kind
        return None

    async def option_ar_shade(self, option_id: str, product_id: str):
        # Reuse the existing conservative raw-to-serving mapping, never route shade input.
        options = (
            (
                await self._session.execute(
                    select(RawOyProductOptionRow).where(
                        RawOyProductOptionRow.goods_no == product_id.removeprefix("oy-").upper(),
                        RawOyProductOptionRow.delisted_at.is_(None),
                    )
                )
            )
            .scalars()
            .all()
        )
        shades = (
            (
                await self._session.execute(
                    select(ShadeRow).where(
                        ShadeRow.product_id == product_id,
                    )
                )
            )
            .scalars()
            .all()
        )
        color = (
            await self._session.execute(
                select(RawOyOptionColorRow)
                .where(
                    RawOyOptionColorRow.option_id == option_id,
                )
                .order_by(RawOyOptionColorRow.collected_at.desc())
                .limit(1)
            )
        ).scalar_one_or_none()
        return resolve_confirmed_shade_fallback(
            product_id=product_id,
            raw_option_id=option_id,
            options=[
                RawShadeOption(o.option_id, o.goods_no, o.shade_code, o.shade_name) for o in options
            ],
            shades=[
                ServingShade(s.product_id, s.id, s.name, s.hex, s.measure_method, s.color_source)
                for s in shades
            ],
            color=RawShadeColor(color.hex_code, color.color_method) if color else None,
        )

    async def option_price(self, option_id: str, product_id: str):
        if not product_id.startswith("oy-"):
            return None
        row = (
            await self._session.execute(
                select(
                    RawOyPriceSnapshotRow.snapshot_id,
                    RawOyPriceSnapshotRow.sale_price,
                    RawOyPriceSnapshotRow.collected_at,
                    RawOyProductRow.product_url,
                )
                .join(
                    RawOyProductOptionRow,
                    RawOyProductOptionRow.option_id == RawOyPriceSnapshotRow.option_id,
                )
                .join(RawOyProductRow, RawOyProductRow.goods_no == RawOyProductOptionRow.goods_no)
                .where(
                    RawOyPriceSnapshotRow.option_id == option_id,
                    RawOyProductOptionRow.goods_no == product_id.removeprefix("oy-").upper(),
                    RawOyPriceSnapshotRow.is_latest.is_(True),
                    RawOyProductOptionRow.delisted_at.is_(None),
                    RawOyProductRow.delisted_at.is_(None),
                )
            )
        ).one_or_none()
        return tuple(row) if row else None

    async def product_texture(self, product_id: str):
        if not product_id.startswith("oy-"):
            return None
        row = (
            await self._session.execute(
                select(
                    RawOyProductTextureRow.texture_code,
                    RawOyProductTextureRow.judge_step,
                    RawOyProductTextureRow.collected_at,
                    RawOyProductRow.product_url,
                )
                .join(RawOyProductRow, RawOyProductRow.goods_no == RawOyProductTextureRow.goods_no)
                .where(
                    RawOyProductTextureRow.goods_no == product_id.removeprefix("oy-").upper(),
                    RawOyProductRow.delisted_at.is_(None),
                )
                .order_by(RawOyProductTextureRow.collected_at.desc())
                .limit(1)
            )
        ).one_or_none()
        return tuple(row) if row else None

    async def load_products(self) -> list[OyProductInput]:
        product_rows = (
            await self._session.execute(
                select(
                    RawOyProductRow,
                    RawOyBrandRow.brand_name_ko,
                    RawOyCategoryRow.category_name,
                    RawOyCategoryRow.category_path,
                    RawOyProductNoticeRow.volume,
                )
                .join(RawOyCategoryRow, RawOyCategoryRow.category_no == RawOyProductRow.category_no)
                .outerjoin(RawOyBrandRow, RawOyBrandRow.brand_code == RawOyProductRow.brand_code)
                .outerjoin(
                    RawOyProductNoticeRow,
                    RawOyProductNoticeRow.goods_no == RawOyProductRow.goods_no,
                )
                .where(
                    # Prefilter only. ``catalog_category`` decides the group, so the
                    # path tokens come from the same constant it reads.
                    or_(
                        RawOyCategoryRow.category_name.in_(tuple(ZONE_BY_CATEGORY)),
                        *(
                            RawOyCategoryRow.category_path.contains(token, autoescape=True)
                            for token, _ in CARE_PATH_TOKENS
                        ),
                    ),
                    RawOyProductRow.delisted_at.is_(None),
                )
            )
        ).all()
        goods = [row[0].goods_no for row in product_rows]
        if not goods:
            return []

        options = list(
            (
                await self._session.scalars(
                    select(RawOyProductOptionRow).where(
                        RawOyProductOptionRow.goods_no.in_(goods),
                        RawOyProductOptionRow.delisted_at.is_(None),
                    )
                )
            ).all()
        )
        option_ids = [option.option_id for option in options]
        colors = (
            list(
                (
                    await self._session.scalars(
                        select(RawOyOptionColorRow).where(
                            RawOyOptionColorRow.option_id.in_(option_ids)
                        )
                    )
                ).all()
            )
            if option_ids
            else []
        )
        prices = (
            list(
                (
                    await self._session.scalars(
                        select(RawOyPriceSnapshotRow).where(
                            RawOyPriceSnapshotRow.option_id.in_(option_ids),
                            RawOyPriceSnapshotRow.is_latest.is_(True),
                        )
                    )
                ).all()
            )
            if option_ids
            else []
        )
        images = list(
            (
                await self._session.scalars(
                    select(RawOyImageRow).where(
                        RawOyImageRow.goods_no.in_(goods),
                        RawOyImageRow.image_type == "thumbnail",
                    )
                )
            ).all()
        )
        textures = list(
            (
                await self._session.scalars(
                    select(RawOyProductTextureRow).where(RawOyProductTextureRow.goods_no.in_(goods))
                )
            ).all()
        )

        latest_color: dict[str, RawOyOptionColorRow] = {}
        for color in colors:
            current = latest_color.get(color.option_id)
            if current is None or (
                color.collected_at
                and current.collected_at
                and color.collected_at >= current.collected_at
            ):
                latest_color[color.option_id] = color
        price_by_option = {price.option_id: price for price in prices if price.option_id}
        image_by_goods: dict[str, str] = {}
        for image in images:
            if image.goods_no and image.image_url and image.goods_no not in image_by_goods:
                image_by_goods[image.goods_no] = image.image_url
        texture_by_goods: dict[str, RawOyProductTextureRow] = {}
        for texture in textures:
            current = texture_by_goods.get(texture.goods_no)
            if current is None or texture.collected_at >= current.collected_at:
                texture_by_goods[texture.goods_no] = texture
        options_by_goods: dict[str, list[RawOyProductOptionRow]] = {}
        for option in options:
            if option.goods_no:
                options_by_goods.setdefault(option.goods_no, []).append(option)

        built: list[OyProductInput] = []
        for product, brand_name, category_name, category_path, volume in product_rows:
            group = catalog_category(category_name or "", category_path or "")
            if group is None:
                continue
            shades: list[OyShadeInput] = []
            for option in options_by_goods.get(product.goods_no, []):
                color = latest_color.get(option.option_id)
                price = price_by_option.get(option.option_id)
                shades.append(
                    OyShadeInput(
                        option_id=option.option_id,
                        shade_name=(option.shade_name or option.option_name or option.option_id),
                        shade_code=option.shade_code,
                        hex_code=color.hex_code if color else None,
                        sale_price=price.sale_price if price else None,
                        list_price=price.list_price if price else None,
                    )
                )
            texture = texture_by_goods.get(product.goods_no)
            built.append(
                OyProductInput(
                    goods_no=product.goods_no,
                    brand_name=brand_name or "",
                    goods_name=product.goods_name or "",
                    category_name=group,
                    product_url=product.product_url,
                    image_url=image_by_goods.get(product.goods_no),
                    texture_code=texture.texture_code if texture else None,
                    volume=volume,
                    shades=tuple(shades),
                    care_tags=derive_care_tags(product.goods_name or "", group),
                )
            )
        return built

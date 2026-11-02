"""Read Olive Young raw tables for the serving-catalog export."""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

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
from app.schemas.oy_catalog import ZONE_BY_CATEGORY, OyProductInput, OyShadeInput


class OyCatalogRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def load_products(self) -> list[OyProductInput]:
        product_rows = (
            await self._session.execute(
                select(
                    RawOyProductRow,
                    RawOyBrandRow.brand_name_ko,
                    RawOyCategoryRow.category_name,
                    RawOyProductNoticeRow.volume,
                )
                .join(RawOyCategoryRow, RawOyCategoryRow.category_no == RawOyProductRow.category_no)
                .outerjoin(RawOyBrandRow, RawOyBrandRow.brand_code == RawOyProductRow.brand_code)
                .outerjoin(
                    RawOyProductNoticeRow,
                    RawOyProductNoticeRow.goods_no == RawOyProductRow.goods_no,
                )
                .where(
                    RawOyCategoryRow.category_name.in_(tuple(ZONE_BY_CATEGORY)),
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
        for product, brand_name, category_name, volume in product_rows:
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
                    category_name=category_name or "",
                    product_url=product.product_url,
                    image_url=image_by_goods.get(product.goods_no),
                    texture_code=texture.texture_code if texture else None,
                    volume=volume,
                    shades=tuple(shades),
                )
            )
        return built

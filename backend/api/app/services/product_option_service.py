"""Read one active sale option; no order, ingredient or AR approval side effects."""

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_session
from app.core.errors import ApiError
from app.repositories.oy_catalog_repository import OyCatalogRepository
from app.schemas.product_option import ProductOption, ProductOptionImage


class ProductOptionService:
    def __init__(self, repository: OyCatalogRepository):
        self.repository = repository

    async def get_option(self, product_id: str, option_id: str) -> ProductOption:
        identity = await self.repository.option_identity(option_id, product_id)
        if identity is None:
            raise ApiError(404, "Sale option not found", "option_not_found")
        price = await self.repository.option_price(option_id, product_id)
        image = await self.repository.option_image(option_id, product_id)
        return ProductOption(
            product_id=product_id,
            option_id=identity[0],
            name=identity[1] or identity[0],
            price_krw=price[1] if price and price[1] is not None and price[1] >= 0 else None,
            observed_at=price[2].isoformat() if price and price[2] else None,
            source_url=identity[3],
            image=ProductOptionImage(url=image[0], kind=image[1]) if image else None,
            ar_shade_id=await self.repository.option_ar_shade(option_id, product_id),
        )


def get_product_option_service(
    session: AsyncSession = Depends(get_session),
) -> ProductOptionService:
    return ProductOptionService(OyCatalogRepository(session))

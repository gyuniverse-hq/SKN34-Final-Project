from typing import Protocol

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.clients.naver_client import get_naver_client
from app.core.cache import Cache, get_cache
from app.core.db import get_session
from app.repositories.catalog_repository import CatalogRepository
from app.schemas.catalog import Product
from app.schemas.external import ProductOffers, ShoppingOffer

OFFER_CACHE_SECONDS = 6 * 60 * 60
OFFERS_PER_PRODUCT = 5
MAX_QUERY_LENGTH = 80


class ProductLookup(Protocol):
    async def get_product(self, product_id: str) -> Product | None: ...


class OfferSource(Protocol):
    @property
    def configured(self) -> bool: ...
    async def search_offers(self, query: str, display: int = 5) -> list[ShoppingOffer]: ...


class OfferService:
    """Online sellers and lowest prices for a product (Naver Shopping)."""

    def __init__(self, products: ProductLookup, source: OfferSource, cache: Cache) -> None:
        self._products = products
        self._source = source
        self._cache = cache

    async def get_product_offers(self, product_id: str) -> ProductOffers | None:
        """`None` when the product does not exist. Raises UpstreamError when Naver fails."""
        product = await self._products.get_product(product_id)
        if product is None:
            return None
        if not self._source.configured:
            return ProductOffers(configured=False, offers=[])
        key = f"offers:{product.search_keyword}:{OFFERS_PER_PRODUCT}"
        if (hit := await self._cache.get_json(key)) is not None:
            return ProductOffers(configured=True, offers=hit)
        offers = await self._source.search_offers(product.search_keyword, OFFERS_PER_PRODUCT)
        await self._cache.set_json(
            key, [o.model_dump(mode="json") for o in offers], OFFER_CACHE_SECONDS
        )
        return ProductOffers(configured=True, offers=offers)

    async def search_offers(self, query: str) -> ProductOffers:
        """Sellers for free text (a look color the catalog lacks). Raises UpstreamError."""
        if not self._source.configured:
            return ProductOffers(configured=False, offers=[])
        q = " ".join(query.split())[:MAX_QUERY_LENGTH]
        key = f"offers:q:{q.lower()}:{OFFERS_PER_PRODUCT}"
        if (hit := await self._cache.get_json(key)) is not None:
            return ProductOffers(configured=True, offers=hit)
        offers = await self._source.search_offers(q, OFFERS_PER_PRODUCT)
        await self._cache.set_json(
            key, [o.model_dump(mode="json") for o in offers], OFFER_CACHE_SECONDS
        )
        return ProductOffers(configured=True, offers=offers)


def get_offer_service(session: AsyncSession = Depends(get_session)) -> OfferService:
    return OfferService(CatalogRepository(session), get_naver_client(), get_cache())

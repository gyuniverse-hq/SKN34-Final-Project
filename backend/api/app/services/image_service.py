import asyncio
import logging
from functools import lru_cache
from typing import Protocol

from app.clients.naver_client import get_naver_client
from app.core.cache import Cache, get_cache
from app.schemas.catalog import Product
from app.schemas.external import ShoppingOffer

logger = logging.getLogger(__name__)

IMAGE_CACHE_SECONDS = 24 * 60 * 60
# Naver rejects bursts (HTTP 429), so cap concurrent upstream lookups.
LOOKUP_CONCURRENCY = 3
# A full catalog listing can contain thousands of products; do not make one external
# shopping request per row. Product detail and small result sets still get live photos.
MAX_LIST_IMAGE_LOOKUPS = 20


class ImageSource(Protocol):
    @property
    def configured(self) -> bool: ...
    async def search_offers(self, query: str, display: int = 5) -> list[ShoppingOffer]: ...
    async def search_product_images(self, query: str) -> list[str]: ...


class ProductImageService:
    """Replaces placeholder product images with real Naver Shopping photos when configured."""

    def __init__(self, source: ImageSource, cache: Cache) -> None:
        self._source = source
        self._cache = cache

    async def find_image(self, query: str) -> str | None:
        key = f"image:{query}"
        if (hit := await self._cache.get_json(key)) is not None:
            return hit["url"]
        url = None
        try:
            offers = await self._source.search_offers(query, 1)
            if offers and offers[0].image_url.startswith("https://"):
                url = offers[0].image_url
        except Exception:
            logger.info("shopping image lookup failed, trying image search")
        if url is None:
            urls = await self._source.search_product_images(query)
            url = next((u for u in urls if u.startswith("https://shopping-phinf.")), None)
            url = url or (urls[0] if urls else None)
        await self._cache.set_json(key, {"url": url}, IMAGE_CACHE_SECONDS)
        return url

    async def with_live_images(self, products: list[Product]) -> list[Product]:
        if not self._source.configured or not products or len(products) > MAX_LIST_IMAGE_LOOKUPS:
            return products
        gate = asyncio.Semaphore(LOOKUP_CONCURRENCY)

        async def enrich(p: Product) -> Product:
            async with gate:
                try:
                    url = await self.find_image(p.search_keyword)
                except Exception:
                    return p
            return p.model_copy(update={"image_url": url}) if url else p

        return list(await asyncio.gather(*(enrich(p) for p in products)))


@lru_cache
def get_image_service() -> ProductImageService:
    return ProductImageService(get_naver_client(), get_cache())

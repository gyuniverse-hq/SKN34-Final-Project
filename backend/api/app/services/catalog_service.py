from typing import Protocol

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.cache import Cache, get_cache
from app.core.config import get_settings
from app.core.db import get_session
from app.repositories.catalog_repository import CatalogRepository
from app.schemas.catalog import CatalogBundle, CelebLook, Product, Store
from app.services.image_service import get_image_service

# Rough bounding box of South Korea; catches swapped lat/lng and missing coordinates.
KOREA_LAT = (33.0, 39.0)
KOREA_LNG = (124.0, 132.0)


class CatalogStore(Protocol):
    async def search_products(
        self, terms: list[str], category: str | None = None, ids: list[str] | None = None
    ) -> list[Product]: ...
    async def get_product(self, product_id: str) -> Product | None: ...
    async def list_looks(self) -> list[CelebLook]: ...
    async def get_look(self, look_id: str) -> CelebLook | None: ...
    async def list_stores(self) -> list[Store]: ...
    async def replace_catalog(self, bundle: CatalogBundle) -> None: ...


class ProductImages(Protocol):
    async def with_live_images(self, products: list[Product]) -> list[Product]: ...


class CatalogService:
    def __init__(
        self,
        store: CatalogStore,
        cache: Cache,
        cache_seconds: int,
        images: ProductImages | None = None,
    ) -> None:
        self._store = store
        self._cache = cache
        self._ttl = cache_seconds
        self._images = images

    async def _with_images(self, products: list[Product]) -> list[Product]:
        return await self._images.with_live_images(products) if self._images else products

    async def list_products(
        self,
        q: str | None = None,
        category: str | None = None,
        ids: list[str] | None = None,
        with_images: bool = True,
    ) -> list[Product]:
        terms = q.lower().split() if q else []
        id_key = ",".join(ids) if ids is not None else "*"
        key = f"products:{category or ''}:{id_key}:{' '.join(terms)}"
        if (hit := await self._cache.get_json(key)) is not None:
            products = [Product.model_validate(p) for p in hit]
        else:
            products = await self._store.search_products(terms, category, ids)
            await self._cache.set_json(
                key, [p.model_dump(mode="json") for p in products], self._ttl
            )
        return await self._with_images(products) if with_images else products

    async def get_product(self, product_id: str) -> Product | None:
        product = await self._store.get_product(product_id)
        if product is None:
            return None
        [enriched] = await self._with_images([product])
        return enriched

    async def list_looks(self) -> list[CelebLook]:
        if (hit := await self._cache.get_json("looks")) is not None:
            return [CelebLook.model_validate(look) for look in hit]
        looks = await self._store.list_looks()
        await self._cache.set_json("looks", [lk.model_dump(mode="json") for lk in looks], self._ttl)
        return looks

    async def get_look_with_products(self, look_id: str) -> tuple[CelebLook, list[Product]] | None:
        look = await self._store.get_look(look_id)
        if look is None:
            return None
        products = await self.list_products(ids=[i.product_id for i in look.items])
        return look, products

    async def list_pickup_stores(self) -> list[Store]:
        return [s for s in await self._store.list_stores() if s.pickup_available]

    async def import_catalog(self, bundle: CatalogBundle) -> None:
        validate_catalog(bundle)
        await self._store.replace_catalog(bundle)


def _unique(ids: list[str], what: str) -> None:
    seen: set[str] = set()
    for i in ids:
        if i in seen:
            raise ValueError(f"duplicate {what} id: {i}")
        seen.add(i)


def validate_catalog(bundle: CatalogBundle) -> None:
    """Integrity rules for imported catalog data (seed files now, crawled data later).

    Hex colors and intensity ranges are already enforced by the schemas.
    """
    _unique([p.id for p in bundle.products], "product")
    _unique([lk.id for lk in bundle.looks], "look")
    _unique([s.id for s in bundle.stores], "store")
    for p in bundle.products:
        if not p.name_ko.strip():
            raise ValueError(f"product {p.id}: Korean name is empty")
        if p.price_krw <= 0:
            raise ValueError(f"product {p.id}: price must be positive")
        _unique([s.id for s in p.shades], f"product {p.id} shade")
        if p.makeup_zone and not p.shades:
            raise ValueError(f"product {p.id}: try-on products need at least one shade")

    shades = {p.id: {s.id for s in p.shades} for p in bundle.products}
    for look in bundle.looks:
        for item in look.items:
            if item.product_id not in shades:
                raise ValueError(f"look {look.id}: unknown product {item.product_id}")
            if item.shade_id and item.shade_id not in shades[item.product_id]:
                raise ValueError(f"look {look.id}: unknown shade {item.shade_id}")

    for s in bundle.stores:
        if not (KOREA_LAT[0] < s.lat < KOREA_LAT[1] and KOREA_LNG[0] < s.lng < KOREA_LNG[1]):
            raise ValueError(f"store {s.id}: coordinates are outside Korea")


def catalog_service_for(session: AsyncSession) -> CatalogService:
    return CatalogService(
        CatalogRepository(session),
        get_cache(),
        get_settings().catalog_cache_seconds,
        get_image_service(),
    )


def get_catalog_service(session: AsyncSession = Depends(get_session)) -> CatalogService:
    return catalog_service_for(session)

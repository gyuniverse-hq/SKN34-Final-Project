from typing import Protocol

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.cache import Cache, get_cache
from app.core.config import get_settings
from app.core.db import get_session
from app.repositories.catalog_repository import CatalogRepository
from app.schemas.catalog import CatalogBundle, CelebLook, Product, Store


class CatalogStore(Protocol):
    async def search_products(
        self, terms: list[str], category: str | None = None, ids: list[str] | None = None
    ) -> list[Product]: ...
    async def get_product(self, product_id: str) -> Product | None: ...
    async def list_looks(self) -> list[CelebLook]: ...
    async def get_look(self, look_id: str) -> CelebLook | None: ...
    async def list_stores(self) -> list[Store]: ...
    async def replace_catalog(self, bundle: CatalogBundle) -> None: ...


class CatalogService:
    def __init__(self, store: CatalogStore, cache: Cache, cache_seconds: int) -> None:
        self._store = store
        self._cache = cache
        self._ttl = cache_seconds

    async def list_products(
        self, q: str | None = None, category: str | None = None, ids: list[str] | None = None
    ) -> list[Product]:
        terms = q.lower().split() if q else []
        id_key = ",".join(ids) if ids is not None else "*"
        key = f"products:{category or ''}:{id_key}:{' '.join(terms)}"
        if (hit := await self._cache.get_json(key)) is not None:
            return [Product.model_validate(p) for p in hit]
        products = await self._store.search_products(terms, category, ids)
        await self._cache.set_json(key, [p.model_dump(mode="json") for p in products], self._ttl)
        return products

    async def get_product(self, product_id: str) -> Product | None:
        return await self._store.get_product(product_id)

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
        validate_references(bundle)
        await self._store.replace_catalog(bundle)


def validate_references(bundle: CatalogBundle) -> None:
    """Look items must point at existing products and shades (same rule as the app's data tests)."""
    shades = {p.id: {s.id for s in p.shades} for p in bundle.products}
    for look in bundle.looks:
        for item in look.items:
            if item.product_id not in shades:
                raise ValueError(f"look {look.id}: unknown product {item.product_id}")
            if item.shade_id and item.shade_id not in shades[item.product_id]:
                raise ValueError(f"look {look.id}: unknown shade {item.shade_id}")


def catalog_service_for(session: AsyncSession) -> CatalogService:
    return CatalogService(
        CatalogRepository(session), get_cache(), get_settings().catalog_cache_seconds
    )


def get_catalog_service(session: AsyncSession = Depends(get_session)) -> CatalogService:
    return catalog_service_for(session)

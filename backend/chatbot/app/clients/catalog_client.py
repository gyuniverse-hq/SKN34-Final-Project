from functools import lru_cache

import httpx

from app.core.config import get_settings
from app.core.errors import UpstreamError
from app.schemas.catalog import CatalogLook, CatalogProduct


class CatalogClient:
    """Reads the catalog from the api service, which owns PostgreSQL."""

    def __init__(self, base_url: str, timeout: float = 15) -> None:
        self._base = base_url.rstrip("/")
        self._timeout = timeout

    async def _get(self, path: str, key: str) -> list[dict]:
        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                res = await client.get(self._base + path)
            res.raise_for_status()
            return res.json()[key]
        except (httpx.HTTPError, KeyError, ValueError) as exc:
            raise UpstreamError(f"catalog request failed: {path}") from exc

    async def fetch_products(self) -> list[CatalogProduct]:
        return [
            CatalogProduct.model_validate(p) for p in await self._get("/api/products", "products")
        ]

    async def fetch_looks(self) -> list[CatalogLook]:
        return [CatalogLook.model_validate(lk) for lk in await self._get("/api/looks", "looks")]


@lru_cache
def get_catalog_client() -> CatalogClient:
    return CatalogClient(get_settings().catalog_api_url)

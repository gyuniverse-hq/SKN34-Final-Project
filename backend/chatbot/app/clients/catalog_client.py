import asyncio
import re
from functools import lru_cache
from urllib.parse import quote, urlencode

import httpx
from pydantic import ValidationError

from app.core.config import get_settings
from app.core.errors import UpstreamError
from app.schemas.catalog import CatalogLook, CatalogProduct


class CatalogClient:
    """Reads the catalog from the api service, which owns PostgreSQL."""

    def __init__(self, base_url: str, timeout: float = 15) -> None:
        self._base = base_url.rstrip("/")
        self._timeout = timeout

    async def _get(self, path: str, key: str, *, search: bool = False) -> list[dict]:
        try:
            async with httpx.AsyncClient(
                timeout=max(40, self._timeout) if search else self._timeout
            ) as client:
                res = await client.get(self._base + path)
            res.raise_for_status()
            return res.json()[key]
        except (httpx.HTTPError, KeyError, ValueError) as exc:
            raise UpstreamError(f"catalog request failed: {path}") from exc

    async def fetch_products(self) -> list[CatalogProduct]:
        return [
            CatalogProduct.model_validate(p) for p in await self._get("/api/products", "products")
        ]

    async def search_products(
        self, *, category: str | None = None, q: str = "", ids: list[str] | None = None
    ) -> list[CatalogProduct]:
        params = {}
        if category:
            params["category"] = category
        if q:
            params["q"] = q
        if ids is not None:
            if not ids:
                return []
            params["ids"] = ",".join(ids[:6])
        suffix = "?" + urlencode(params) if params else ""
        try:
            # A hosted development Catalog cold start exceeded 30 seconds during validation.
            async with asyncio.timeout(max(40, self._timeout)):
                rows = await self._get("/api/products" + suffix, "products", search=True)
            products = [CatalogProduct.model_validate(row) for row in rows]
        except (ValidationError, TypeError, TimeoutError) as exc:
            raise UpstreamError("Invalid catalog search response") from exc
        # Never trust an upstream response to have applied the requested ID restriction.
        return [p for p in products if ids is None or p.id in ids]

    async def fetch_looks(self) -> list[CatalogLook]:
        return [CatalogLook.model_validate(lk) for lk in await self._get("/api/looks", "looks")]

    async def get_product(self, product_id: str) -> CatalogProduct | None:
        # Catalog IDs use URL-safe characters; never send path delimiters upstream.
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,63}", product_id):
            return None
        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                res = await client.get(self._base + "/api/products/" + quote(product_id, safe=""))
            if res.status_code == 404:
                return None
            res.raise_for_status()
            return CatalogProduct.model_validate(res.json()["product"])
        except (httpx.HTTPError, KeyError, ValueError, ValidationError, TypeError) as exc:
            raise UpstreamError("catalog product request failed") from exc


@lru_cache
def get_catalog_client() -> CatalogClient:
    return CatalogClient(get_settings().catalog_api_url)

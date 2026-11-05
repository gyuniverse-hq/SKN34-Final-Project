import asyncio
import re
import unicodedata
from functools import lru_cache
from urllib.parse import quote, urlencode

import httpx
from pydantic import ValidationError

from app.core.config import get_settings
from app.core.errors import UpstreamError
from app.schemas.catalog import CatalogIngredients, CatalogLook, CatalogProduct, CatalogStyleLook


class IngredientLookupError(UpstreamError):
    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


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

    async def get_style_look(self, kind: str, look_id: str):
        pattern = r"[A-Za-z0-9_-]{1,64}" if kind == "video" else r"[A-Za-z0-9][A-Za-z0-9._-]{0,63}"
        if not re.fullmatch(pattern, look_id):
            return None
        if kind not in {"video", "catalog"}:
            return None
        path = "/api/style-looks" if kind == "video" else "/api/looks"
        model = CatalogStyleLook if kind == "video" else CatalogLook
        try:
            looks = [model.model_validate(row) for row in await self._get(path, "looks")]
            matches = [look for look in looks if look.id == look_id]
            if len(matches) > 1:
                raise ValueError("Duplicate look ID")
            return matches[0] if matches else None
        except (ValueError, TypeError) as exc:
            raise UpstreamError("Invalid style catalog response") from exc

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

    async def get_ingredients(
        self,
        product_id: str,
        shade_id: str,
        *,
        ingredient_name: str | None = None,
        operator: str = "includes",
    ) -> CatalogIngredients:
        params = {"shadeId": shade_id}
        if ingredient_name:
            params.update(ingredientName=ingredient_name, operator=operator)
        path = "/api/products/" + quote(product_id, safe="") + "/ingredients"
        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                res = await client.get(self._base + path, params=params)
            if res.status_code == 404:
                code = res.json().get("code")
                if code not in {"not_found", "shade_not_found"}:
                    raise ValueError("Unknown not-found response")
                raise IngredientLookupError(
                    "shade_not_found" if code == "shade_not_found" else "product_not_found"
                )
            if res.status_code == 503:
                raise IngredientLookupError("source_unavailable")
            res.raise_for_status()
            result = CatalogIngredients.model_validate(res.json())
            if (result.product_id, result.shade_id) != (product_id, shade_id):
                raise ValueError("Ingredient selection mismatch")
            if any(
                (c.product_id, c.shade_id, c.option_id, c.ingredient_name, c.operator)
                != (product_id, shade_id, result.option_id, ingredient_name, operator)
                or c.verdict != result.verdict
                or c.evidence_id != result.evidence_id
                or c.synthetic != result.synthetic
                for c in result.conditions
            ):
                raise ValueError("Ingredient condition mismatch")
            if ingredient_name and len(result.conditions) != 1:
                raise ValueError("Ingredient condition required")
            if not ingredient_name and (result.conditions or result.verdict != "UNKNOWN"):
                raise ValueError("Unexpected ingredient condition")
            if result.verdict in {"MATCH", "NOT_MATCH"}:
                if not result.verified:
                    raise ValueError("Unverified ingredient verdict")
                absent = (operator == "includes" and result.verdict == "NOT_MATCH") or (
                    operator == "excludes" and result.verdict == "MATCH"
                )
                if absent and not result.complete:
                    raise ValueError("Incomplete absence evidence")

                def normalize(value):
                    return " ".join(unicodedata.normalize("NFKC", value).casefold().split())

                present = normalize(ingredient_name) in {
                    normalize(i.name) for i in result.ingredients
                }
                expected = "MATCH" if present == (operator == "includes") else "NOT_MATCH"
                if result.verdict != expected:
                    raise ValueError("Verdict contradicts ingredient evidence")
                if absent:
                    # A legacy API's name-only absence cannot establish ingredient identity.
                    result.verdict = "UNKNOWN"
                    result.reason = "ingredient_identity_unresolved"
                    for condition in result.conditions:
                        condition.verdict = "UNKNOWN"
                        condition.reason = result.reason
            # Unreviewed upstream rows must not accidentally become public ingredient facts.
            if result.ingredients and not result.verified:
                raise ValueError("Unverified ingredient list")
            return result
        except IngredientLookupError:
            raise
        except httpx.TimeoutException as exc:
            raise IngredientLookupError("timeout") from exc
        except httpx.HTTPStatusError as exc:
            raise IngredientLookupError("http_error") from exc
        except httpx.RequestError as exc:
            raise IngredientLookupError("network_error") from exc
        except (ValueError, TypeError, KeyError) as exc:
            raise IngredientLookupError("invalid_response") from exc


@lru_cache
def get_catalog_client() -> CatalogClient:
    return CatalogClient(get_settings().catalog_api_url)

import asyncio
import logging
import re
import unicodedata
from functools import lru_cache
from urllib.parse import quote, urlencode

import httpx
from pydantic import ValidationError

from app.core.config import get_settings
from app.core.errors import UpstreamError
from app.core.observability import catalog_tool_call_id
from app.schemas.catalog import (
    CatalogIngredients,
    CatalogLook,
    CatalogProduct,
    CatalogStyleLook,
    OptionSearchRequest,
    OptionSearchResponse,
)

logger = logging.getLogger(__name__)


def _log_catalog_http(path: str, status: int | None, *, error: str | None = None) -> None:
    logger.info(
        "catalog_http",
        extra={
            "path": path,
            "status": status,
            "method": "GET",
            "tool_call_id": catalog_tool_call_id.get(),
            "error_type": error,
        },
    )


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
            if search:
                _log_catalog_http("/api/products", res.status_code)
            res.raise_for_status()
            return res.json()[key]
        except (httpx.HTTPError, KeyError, ValueError) as exc:
            if search and not isinstance(exc, httpx.HTTPStatusError):
                _log_catalog_http("/api/products", None, error=type(exc).__name__)
            raise UpstreamError(f"catalog request failed: {path.partition('?')[0]}") from exc

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
            _log_catalog_http("/api/products/{productId}", res.status_code)
            if res.status_code == 404:
                return None
            res.raise_for_status()
            return CatalogProduct.model_validate(res.json()["product"])
        except (httpx.HTTPError, KeyError, ValueError, ValidationError, TypeError) as exc:
            if not isinstance(exc, httpx.HTTPStatusError):
                _log_catalog_http("/api/products/{productId}", None, error=type(exc).__name__)
            raise UpstreamError("catalog product request failed") from exc

    async def search_options(self, request: OptionSearchRequest) -> OptionSearchResponse:
        try:
            async with httpx.AsyncClient(timeout=max(40, self._timeout)) as client:
                response = await client.post(
                    self._base + "/api/catalog/options/search",
                    json=request.model_dump(mode="json", by_alias=True),
                )
            response.raise_for_status()
            result = OptionSearchResponse.model_validate(response.json())
            products = {p.id: p for p in result.products}
            if len(products) != len(result.products):
                raise ValueError("Duplicate products")
            keys = [(i.product_id, i.shade_id, i.option_id) for i in result.items]
            if len(set(keys)) != len(keys):
                raise ValueError("Duplicate options")
            allowed = (
                None
                if request.option_scope is None
                else {(r.product_id, r.shade_id, r.option_id) for r in request.option_scope}
            )
            if result.effective_request != request or result.checked_at is None:
                raise ValueError("Missing or changed effective search request")
            resolutions = result.ingredient_resolutions
            if resolutions and [(r.ingredient_name, r.operator) for r in resolutions] != [
                (c.ingredient_name, c.operator) for c in request.ingredient_conditions
            ]:
                raise ValueError("Missing or changed ingredient name resolutions")
            if any(
                r.status == "resolved" and not (r.canonical_name or "").strip() for r in resolutions
            ):
                raise ValueError("Missing canonical ingredient name")
            blocking = any(r.status not in {"resolved", "literal"} for r in resolutions)
            confirming = result.checked_scope.stopped_reason == "INGREDIENT_CONFIRMATION"
            if blocking != confirming or (
                confirming
                and (
                    result.status != "PARTIAL"
                    or result.items
                    or result.products
                    or result.checked_scope.checked_options
                    or result.checked_scope.exhaustive
                )
            ):
                raise ValueError("Invalid ingredient confirmation state")
            for item in result.items:
                if request.product_type and item.product_type != request.product_type:
                    raise ValueError("Option outside requested product type")
                if request.product_ids is not None and item.product_id not in request.product_ids:
                    raise ValueError("Product outside requested scope")
                if (
                    allowed is not None
                    and (item.product_id, item.shade_id, item.option_id) not in allowed
                ):
                    raise ValueError("Option outside requested scope")
                if item.group != "EXCLUDED":
                    product = products.get(item.product_id)
                    if product is None or (
                        item.shade_id not in {s.id for s in product.shades}
                        if product.shades
                        else item.shade_id is not None
                    ):
                        raise ValueError("Option outside Catalog product")
                conditions = [
                    (c.ingredient_name, c.operator)
                    for c in item.checks
                    if c.condition == "ingredient"
                ]
                if conditions != [
                    (c.ingredient_name, c.operator) for c in request.ingredient_conditions
                ]:
                    raise ValueError("Missing or changed ingredient conditions")
                required = {"identity"}
                if request.texture:
                    required.add("texture")
                if request.max_price_krw is not None:
                    required.add("price")
                if request.fragrance_free:
                    required.add("fragrance_free")
                if request.moisturizing:
                    required.add("moisturizing")
                required.update(
                    f"unsupported:{i}" for i, _ in enumerate(request.unsupported_conditions)
                )
                if {
                    c.condition for c in item.checks if c.condition != "ingredient"
                } != required or len(item.checks) != len(required) + len(
                    request.ingredient_conditions
                ):
                    raise ValueError("Missing or unexpected predicates")
                for check in item.checks:
                    if check.condition == "identity" and (
                        check.verdict != "MATCH" or check.source_version != item.source_version
                    ):
                        raise ValueError("Unverified option identity")
                    if (
                        check.condition == "texture"
                        and (
                            check.verdict in {"MATCH", "NOT_MATCH"}
                            or check.texture_basis == "official_reviewed"
                        )
                        and (
                            check.texture_basis != "official_reviewed"
                            or check.reason != "official_option_texture_reviewed"
                            or check.review_status != "verified"
                            or not check.reviewed_at
                            or not check.review_ref
                            or not (check.source_ref or "").startswith("https://")
                            or not check.source_version
                            or check.evidence_id
                            != f"texture:{item.option_id}:{check.source_version}"
                            or check.texture_code != request.texture
                            or check.verdict != "MATCH"
                        )
                    ):
                        raise ValueError("Option texture lacks option-specific evidence")
                    if (
                        check.condition == "moisturizing"
                        or check.condition.startswith("unsupported:")
                    ) and check.verdict != "UNKNOWN":
                        raise ValueError("Unsupported claim")
                    if (
                        check.condition == "fragrance_free"
                        and check.verdict in {"MATCH", "NOT_MATCH"}
                        and (check.verdict, check.reason, check.ingredient_name, check.operator)
                        != ("NOT_MATCH", "ingredient_present", "향료", "excludes")
                    ):
                        raise ValueError("Unverified fragrance-free claim")
                    if (
                        check.condition in {"ingredient", "fragrance_free"}
                        and check.verdict in {"MATCH", "NOT_MATCH"}
                        and (not check.evidence_id or check.source_version != item.source_version)
                    ):
                        raise ValueError("Missing ingredient provenance")
                    if check.condition in {"ingredient", "fragrance_free"} and check.verdict in {
                        "MATCH",
                        "NOT_MATCH",
                    }:
                        if (
                            check.review_status != "verified"
                            or not check.source_ref
                            or not (check.observed_at or (check.reviewed_at and check.review_ref))
                            or check.ingredient_coverage not in {"full", "partial"}
                        ):
                            raise ValueError("Missing ingredient review or observation")
                        if check.reason == "ingredient_absent" and (
                            check.ingredient_coverage != "full"
                            or check.normalization_status != "verified"
                        ):
                            raise ValueError("Unverifiable absence")
                        expected = {
                            "ingredient_present": "MATCH"
                            if check.operator == "includes"
                            else "NOT_MATCH",
                            "ingredient_absent": "NOT_MATCH"
                            if check.operator == "includes"
                            else "MATCH",
                        }.get(check.reason)
                        if check.verdict != expected:
                            raise ValueError("Ingredient predicate mismatch")
                    if check.condition == "price" and check.verdict in {"MATCH", "NOT_MATCH"}:
                        price = item.price
                        if (
                            not price
                            or request.price_basis == "current_offer"
                            or price.requested_basis != request.price_basis
                            or price.observed_basis != request.price_basis
                        ):
                            raise ValueError("Price basis mismatch")
                        if price.observed_basis == "collected_snapshot" and (
                            (not price.observed_at and not price.observed_at_raw)
                            or (
                                price.observed_at is not None
                                and price.observed_at > price.checked_at
                            )
                            or (
                                price.observed_at_raw is not None
                                and "timezone_unknown" not in price.limitations
                            )
                        ):
                            raise ValueError("Missing observation time")
                        expected = (
                            "MATCH" if price.amount_krw <= request.max_price_krw else "NOT_MATCH"
                        )
                        if check.verdict != expected:
                            raise ValueError("Price verdict mismatch")
            if set(products) != {i.product_id for i in result.items if i.group != "EXCLUDED"}:
                raise ValueError("Products without option results")
            if request.texture and any(p.texture != request.texture for p in result.products):
                raise ValueError("Product outside texture candidate filter")
            if any(request.category and p.category != request.category for p in result.products):
                raise ValueError("Unexpected category")
            scope = result.checked_scope
            if (
                scope.checked_options > scope.candidate_options
                or scope.unidentified_options > scope.checked_options
                or (
                    scope.exhaustive
                    and (
                        scope.checked_options != scope.candidate_options
                        or scope.stopped_reason != "COMPLETE"
                    )
                )
            ):
                raise ValueError("Invalid checked scope")
            if (
                len(result.items) + result.omitted_count + scope.unidentified_options
                != scope.checked_options
            ):
                raise ValueError("Missing checked options")
            if result.status == "SUCCESS" and (
                not scope.exhaustive
                or scope.unidentified_options
                or scope.errors
                or any(i.group == "REFERENCE_ONLY" for i in result.items)
            ):
                raise ValueError("Partial result declared successful")
            if result.excluded_count != sum(i.group == "EXCLUDED" for i in result.items):
                raise ValueError("Invalid excluded count")
            return result
        except (httpx.HTTPError, ValueError, TypeError) as exc:
            raise UpstreamError("Invalid or unavailable Catalog option search") from exc

    async def get_ingredients(
        self,
        product_id: str,
        shade_id: str | None,
        *,
        ingredient_name: str | None = None,
        operator: str = "includes",
    ) -> CatalogIngredients:
        params = {"shadeId": shade_id} if shade_id is not None else {}
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
                identity = result.conditions[0].query_identity
                canonical_present = identity is not None and any(
                    i.identity is not None
                    and i.identity.mfds_ingredient_id == identity.mfds_ingredient_id
                    and i.identity.source_hash == identity.source_hash
                    for i in result.ingredients
                )
                present = present or canonical_present
                expected = "MATCH" if present == (operator == "includes") else "NOT_MATCH"
                if result.verdict != expected:
                    raise ValueError("Verdict contradicts ingredient evidence")
                if absent:
                    unresolved = identity is None or any(
                        i.identity is None for i in result.ingredients
                    )
                    version_mismatch = identity is not None and any(
                        i.identity is not None
                        and i.identity.mfds_ingredient_id == identity.mfds_ingredient_id
                        for i in result.ingredients
                    )
                    if unresolved or version_mismatch:
                        result.verdict = "UNKNOWN"
                        result.reason = (
                            "ingredient_identity_unresolved"
                            if unresolved
                            else "ingredient_identity_version_mismatch"
                        )
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

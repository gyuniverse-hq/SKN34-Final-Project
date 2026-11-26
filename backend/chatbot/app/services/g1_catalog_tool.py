import re
import unicodedata

from app.clients.catalog_client import CatalogClient
from app.core.errors import UpstreamError
from app.schemas.catalog import CatalogProduct


def _normalize(value: str) -> str:
    return " ".join(unicodedata.normalize("NFKC", value).casefold().split())


def validate_catalog_product(product: CatalogProduct) -> None:
    shade_ids = [shade.id for shade in product.shades]
    if (
        not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,63}", product.id)
        or any(not sid.strip() or len(sid) > 128 for sid in shade_ids)
        or len(shade_ids) != len(set(shade_ids))
        or any(shade.product_id not in {None, product.id} for shade in product.shades)
    ):
        raise UpstreamError("Invalid Catalog product or shade identity")


class InvalidShadeSelection(Exception):
    """A requested shade was not found on the verified Catalog product."""


class G1CatalogTool:
    """Validate Catalog HTTP facts before they reach the G1 response builder."""

    def __init__(self, client: CatalogClient, query: str = "") -> None:
        self._client = client
        self._query = query

    async def search_products(
        self, *, category: str | None = None, q: str = "", ids: list[str] | None = None
    ) -> list[CatalogProduct]:
        q = q or self._query
        products = await self._client.search_products(category=category, q=q, ids=ids)
        if len({p.id for p in products}) != len(products):
            raise UpstreamError("Duplicate Catalog product identity")
        for product in products:
            validate_catalog_product(product)

        query = _normalize(q)
        brand_query = bool(query) and any(_normalize(p.brand) == query for p in products)
        return [
            p
            for p in products
            if (not category or p.category == category)
            and (ids is None or p.id in ids[:6])
            and (
                not query
                or (_normalize(p.brand) == query if brand_query else self._matches_name(p, query))
            )
        ]

    @staticmethod
    def _matches_name(product: CatalogProduct, query: str) -> bool:
        identity = _normalize(f"{product.brand} {product.name} {product.name_ko}")
        return all(word in identity for word in query.split())

    async def search_options(self, request):
        result = await self._client.search_options(request)
        for product in result.products:
            validate_catalog_product(product)
            if request.query and not self._matches_name(product, _normalize(request.query)):
                raise UpstreamError("Catalog option search identity does not match request")
        return result

    async def get_product(self, product_id: str) -> CatalogProduct | None:
        product = await self._client.get_product(product_id)
        if product is not None:
            validate_catalog_product(product)
            if product.id != product_id:
                raise UpstreamError("Catalog detail identity does not match request")
        return product

    async def get_product_detail(
        self, product_id: str, shade_id: str | None
    ) -> CatalogProduct | None:
        product = await self.get_product(product_id)
        if product and shade_id and all(shade.id != shade_id for shade in product.shades):
            raise InvalidShadeSelection
        return product

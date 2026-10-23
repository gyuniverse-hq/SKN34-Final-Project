from typing import Any, Protocol

from app.clients.catalog_client import CatalogClient, get_catalog_client
from app.core.graph import get_driver
from app.repositories.graph_repository import GraphRepository
from app.schemas.catalog import CatalogLook, CatalogProduct


class CatalogSource(Protocol):
    async def fetch_products(self) -> list[CatalogProduct]: ...
    async def fetch_looks(self) -> list[CatalogLook]: ...


class GraphWriter(Protocol):
    async def ensure_schema(self) -> None: ...
    async def replace_catalog(
        self, products: list[dict[str, Any]], looks: list[dict[str, Any]]
    ) -> None: ...


def product_row(p: CatalogProduct) -> dict[str, Any]:
    search = " ".join([p.brand, p.name, p.name_ko, p.description, *p.tags, *p.key_ingredients])
    return {
        "id": p.id,
        "brand": p.brand,
        "name": p.name,
        "nameKo": p.name_ko,
        "category": p.category,
        "texture": p.texture,
        "priceKRW": p.price_krw,
        "searchText": search.lower(),
        "shades": [s.model_dump() for s in p.shades],
        "ingredients": p.key_ingredients,
        "tags": p.tags,
    }


def look_row(look: CatalogLook) -> dict[str, Any]:
    return {
        "id": look.id,
        "title": look.title,
        "tags": look.tags,
        "items": [
            {"productId": i.product_id, "shadeId": i.shade_id, "step": i.step} for i in look.items
        ],
    }


class GraphSyncService:
    """PostgreSQL (via the api service) -> Neo4j, one direction only. Never edit Neo4j by hand."""

    def __init__(self, source: CatalogSource, graph: GraphWriter) -> None:
        self._source = source
        self._graph = graph

    async def sync(self) -> dict[str, int]:
        products = await self._source.fetch_products()
        looks = await self._source.fetch_looks()
        await self._graph.ensure_schema()
        await self._graph.replace_catalog(
            [product_row(p) for p in products], [look_row(lk) for lk in looks]
        )
        return {"products": len(products), "looks": len(looks)}


def create_graph_sync_service(source: CatalogClient | None = None) -> GraphSyncService:
    return GraphSyncService(source or get_catalog_client(), GraphRepository(get_driver()))

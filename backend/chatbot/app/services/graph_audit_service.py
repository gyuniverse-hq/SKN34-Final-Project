"""Read-only comparison of the deployed Catalog API and the *legacy* Neo4j copy.

This checks projection parity; it never certifies full ingredient/option evidence.
No write methods, arbitrary Cypher, LLM requests, or hidden live DB credentials.
"""

from collections import Counter
from typing import Any, Protocol


class CatalogSource(Protocol):
    async def fetch_products(self) -> list[Any]: ...
    async def fetch_looks(self) -> list[Any]: ...


class GraphSource(Protocol):
    async def audit_catalog_products(self) -> list[dict[str, Any]]: ...
    async def audit_catalog_looks(self) -> list[dict[str, Any]]: ...


def _counts(values: list[str]) -> Counter[str]:
    return Counter(values)


def _product_fields(product: Any) -> dict[str, Any]:
    return {
        "brand": product.brand,
        "name": product.name,
        "nameKo": product.name_ko,
        "category": product.category,
        "texture": product.texture,
        "priceKRW": product.price_krw,
        "searchText": " ".join(
            [
                product.brand,
                product.name,
                product.name_ko,
                product.description,
                *product.tags,
                *product.key_ingredients,
            ]
        ).lower(),
    }


def _source_shades(product: Any) -> Counter[tuple[str, str, str]]:
    return Counter((shade.id, shade.name, shade.hex.lower()) for shade in product.shades)


def _graph_shades(row: dict) -> Counter[tuple[str, str, str]]:
    return Counter(
        (str(s.get("id")), str(s.get("name")), str(s.get("hex", "")).lower())
        for s in (row.get("shades") or [])
    )


def _look_items(look: Any) -> Counter[tuple[str, str | None, str]]:
    return Counter((item.product_id, item.shade_id, item.step) for item in look.items)


def _graph_look_items(row: dict) -> Counter[tuple[str, str | None, str]]:
    return Counter(
        (item.get("productId"), item.get("shadeId"), item.get("step"))
        for item in (row.get("items") or [])
    )


def _report_diff(
    expected: dict[str, Any],
    actual: dict[str, Any],
    *,
    item_kind: str,
    max_samples: int,
) -> dict[str, Any]:
    source_ids, graph_ids = set(expected), set(actual)
    missing = sorted(source_ids - graph_ids)
    unexpected = sorted(graph_ids - source_ids)
    mismatched: list[str] = []
    mismatch_count = 0
    for identifier in sorted(source_ids & graph_ids):
        if expected[identifier] != actual[identifier]:
            mismatch_count += 1
            if len(mismatched) < max_samples:
                mismatched.append(identifier)
    return {
        "kind": item_kind,
        "sourceCount": len(expected),
        "graphCount": len(actual),
        "missingCount": len(missing),
        "unexpectedCount": len(unexpected),
        "differentCount": mismatch_count,
        "missingSample": missing[:max_samples],
        "unexpectedSample": unexpected[:max_samples],
        "differentSample": mismatched,
        "matched": not missing and not unexpected and not mismatch_count,
    }


def compare_catalog_projection(
    products: list[Any],
    looks: list[Any],
    graph_products: list[dict[str, Any]],
    graph_looks: list[dict[str, Any]],
    *,
    max_samples: int = 10,
) -> dict[str, Any]:
    """Pure comparison. Duplicate IDs are detected, never silently overwritten."""
    if max_samples < 1:
        raise ValueError("max_samples must be positive")

    source_product_ids = [p.id for p in products]
    graph_product_ids = [r.get("id") for r in graph_products]
    source_look_ids = [l.id for l in looks]
    graph_look_ids = [r.get("id") for r in graph_looks]
    duplicates = {
        "catalogProducts": sorted(k for k, n in _counts(source_product_ids).items() if n > 1),
        "graphProducts": sorted(k for k, n in _counts(graph_product_ids).items() if n > 1),
        "catalogLooks": sorted(k for k, n in _counts(source_look_ids).items() if n > 1),
        "graphLooks": sorted(k for k, n in _counts(graph_look_ids).items() if n > 1),
    }
    source_p = {
        p.id: (
            _product_fields(p),
            _source_shades(p),
            _counts(p.key_ingredients),
            _counts(p.tags),
        )
        for p in products
    }
    graph_p = {
        r["id"]: (
            {key: r.get(key) for key in ("brand", "name", "nameKo", "category", "texture", "priceKRW", "searchText")},
            _graph_shades(r),
            _counts(r.get("keyIngredients") or []),
            _counts(r.get("tags") or []),
        )
        for r in graph_products
        if r.get("id") is not None
    }
    source_l = {
        l.id: (l.title, _look_items(l), _counts(l.tags)) for l in looks
    }
    graph_l = {
        r["id"]: (
            r.get("title"),
            _graph_look_items(r),
            _counts(r.get("tags") or []),
        )
        for r in graph_looks
        if r.get("id") is not None
    }
    product_diff = _report_diff(source_p, graph_p, item_kind="products", max_samples=max_samples)
    look_diff = _report_diff(source_l, graph_l, item_kind="looks", max_samples=max_samples)
    expected_shades = sum(len(p.shades) for p in products)
    actual_shades = sum(len(r.get("shades") or []) for r in graph_products)
    expected_key_edges = sum(len(p.key_ingredients) for p in products)
    actual_key_edges = sum(len(r.get("keyIngredients") or []) for r in graph_products)
    expected_tag_edges = sum(len(p.tags) for p in products)
    actual_tag_edges = sum(len(r.get("tags") or []) for r in graph_products)
    look_usage_count = sum(len(l.items) for l in looks)
    graph_look_usage_count = sum(len(r.get("items") or []) for r in graph_looks)
    edge_counts = {
        "shadeEdges": {"source": expected_shades, "graph": actual_shades},
        "keyIngredientEdges": {"source": expected_key_edges, "graph": actual_key_edges},
        "tagEdgesFromProducts": {"source": expected_tag_edges, "graph": actual_tag_edges},
        "lookUsageEdges": {"source": look_usage_count, "graph": graph_look_usage_count},
    }
    edge_counts_match = all(v["source"] == v["graph"] for v in edge_counts.values())
    duplicates_present = any(duplicates.values())
    # Empty source is not evidence of successful synchronization.
    comparison_ok = bool(products) and product_diff["matched"] and look_diff["matched"]
    comparison_ok = comparison_ok and edge_counts_match and not duplicates_present
    return {
        "status": "PASS" if comparison_ok else "FAIL",
        "projection": "legacy_catalog_only",
        "fullIngredientEvidenceVerified": False,
        "recommendationEvidenceVerified": False,
        "catalogContainsAnyKeyIngredients": expected_key_edges > 0,
        "dataSource": "catalog_api",
        "products": product_diff,
        "looks": look_diff,
        "edges": edge_counts,
        "duplicates": {k: v[:max_samples] for k, v in duplicates.items()},
        "duplicateCounts": {k: len(v) for k, v in duplicates.items()},
        "limitations": [
            "Neo4j keyIngredients are not verified complete ingredient inventories",
            "option/ingredient coverage and rec_* approvals are not in this projection",
            "this command compares with live Catalog API data, not direct PostgreSQL snapshots",
            "PASS means legacy projection parity only, not approval for GraphRAG recommendations",
        ],
    }


class GraphAuditService:
    def __init__(self, source: CatalogSource, graph: GraphSource) -> None:
        self._source = source
        self._graph = graph

    async def audit(self) -> dict[str, Any]:
        # Read the source and copy separately; a concurrent source update can
        # cause a transient mismatch. Re-audit against a pinned version after
        # versioned export is introduced.
        products = await self._source.fetch_products()
        looks = await self._source.fetch_looks()
        graph_products = await self._graph.audit_catalog_products()
        graph_looks = await self._graph.audit_catalog_looks()
        return compare_catalog_projection(products, looks, graph_products, graph_looks)


def create_graph_audit_service() -> GraphAuditService:
    from app.clients.catalog_client import get_catalog_client
    from app.core.graph import get_driver
    from app.repositories.graph_repository import GraphRepository

    return GraphAuditService(get_catalog_client(), GraphRepository(get_driver()))

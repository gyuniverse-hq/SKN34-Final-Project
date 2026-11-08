"""Legacy graph parity tests; synthetic, offline, no writes or paid APIs."""

from copy import deepcopy

import pytest

from app.services.graph_audit_service import GraphAuditService, compare_catalog_projection
from tests.test_graph_sync import LOOK, PRODUCT


def catalog_rows():
    product = PRODUCT
    look = LOOK
    gp = {
        "id": product.id,
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
        "shades": [{"id": s.id, "name": s.name, "hex": s.hex} for s in product.shades],
        "keyIngredients": list(product.key_ingredients),
        "tags": list(product.tags),
    }
    gl = {
        "id": look.id,
        "title": look.title,
        "tags": list(look.tags),
        "items": [
            {"productId": i.product_id, "shadeId": i.shade_id, "step": i.step}
            for i in look.items
        ],
    }
    return [product], [look], [gp], [gl]


def report(*, graph_products=None, graph_looks=None, source_products=None, source_looks=None):
    ps, ls, gps, gls = catalog_rows()
    return compare_catalog_projection(
        ps if source_products is None else source_products,
        ls if source_looks is None else source_looks,
        gps if graph_products is None else graph_products,
        gls if graph_looks is None else graph_looks,
    )


def test_exact_projection_only_passes_as_legacy_copy():
    result = report()
    assert result["status"] == "PASS"
    assert result["products"]["matched"] and result["looks"]["matched"]
    assert result["edges"]["keyIngredientEdges"] == {"source": 1, "graph": 1}
    assert result["fullIngredientEvidenceVerified"] is False
    assert result["recommendationEvidenceVerified"] is False


@pytest.mark.parametrize(
    "path,new_value",
    [
        (("name",), "Invented product"),
        (("priceKRW",), 99999),
        (("searchText",), "wrong search corpus"),
        (("shades", 0, "name"), "wrong shade"),
        (("shades", 0, "hex"), "#FFFFFF"),
        (("keyIngredients", 0), "Fragrance"),
        (("tags", 0), "fake-trend"),
    ],
)
def test_rejects_wrong_graph_product_facts(path, new_value):
    _, _, gps, _ = catalog_rows()
    changed = deepcopy(gps)
    field = changed[0]
    for part in path[:-1]:
        field = field[part]
    field[path[-1]] = new_value
    result = report(graph_products=changed)
    assert result["status"] == "FAIL"
    assert result["products"]["differentSample"] == [PRODUCT.id]


@pytest.mark.parametrize(
    "field,value",
    [
        ("title", "different look"),
        ("items", []),
        ("tags", ["different"]),
    ],
)
def test_rejects_wrong_graph_look_facts(field, value):
    _, _, _, gls = catalog_rows()
    gls[0][field] = value
    result = report(graph_looks=gls)
    assert result["status"] == "FAIL"
    assert result["looks"]["differentSample"] == [LOOK.id]


def test_missing_and_extra_products_are_reported_without_silent_replacement():
    _, _, gps, _ = catalog_rows()
    assert report(graph_products=[])["products"]["missingSample"] == [PRODUCT.id]
    gps.append({**gps[0], "id": "extra-item"})
    result = report(graph_products=gps)
    assert result["products"]["unexpectedSample"] == ["extra-item"]
    assert result["status"] == "FAIL"


def test_duplicate_graph_ids_fail_even_when_mapped_payload_matches():
    _, _, gps, _ = catalog_rows()
    result = report(graph_products=[gps[0], dict(gps[0])])
    assert result["status"] == "FAIL"
    assert result["duplicateCounts"]["graphProducts"] == 1


def test_empty_source_and_graph_cannot_claim_sync_success():
    result = compare_catalog_projection([], [], [], [])
    assert result["status"] == "FAIL"
    assert result["products"]["sourceCount"] == 0


def test_key_ingredients_empty_stays_unverified_even_when_parity_passes():
    product = PRODUCT.model_copy(update={"key_ingredients": []})
    _, looks, rows, gls = catalog_rows()
    rows[0]["keyIngredients"] = []
    result = report(source_products=[product], source_looks=looks, graph_products=rows, graph_looks=gls)
    assert result["status"] == "PASS"
    assert result["catalogContainsAnyKeyIngredients"] is False
    assert result["fullIngredientEvidenceVerified"] is False


@pytest.mark.anyio
async def test_audit_reads_only_without_mutation_methods():
    ps, ls, gps, gls = catalog_rows()
    calls = []

    class Source:
        async def fetch_products(self):
            calls.append("products")
            return ps

        async def fetch_looks(self):
            calls.append("looks")
            return ls

    class Graph:
        async def audit_catalog_products(self):
            calls.append("graph_products")
            return gps

        async def audit_catalog_looks(self):
            calls.append("graph_looks")
            return gls

    result = await GraphAuditService(Source(), Graph()).audit()
    assert result["status"] == "PASS"
    assert calls == ["products", "looks", "graph_products", "graph_looks"]

"""Preference ranking is independent of ingredient filtering and upstream order."""

import time

import pytest

from app.schemas.catalog import CatalogIngredients
from app.schemas.chat import BeautyContext, BeautyFilters, ChatRequest
from app.schemas.supervisor import SearchPlan
from app.services.beauty_consultation_service import execute_beauty
from tests.test_beauty_consultation import Catalog, product
from tests.test_ingredient_consultation import evidence


@pytest.fixture
def anyio_backend():
    return "asyncio"


class PreferenceCatalog(Catalog):
    def __init__(self, ids, reverse):
        self.products = [product(pid, 15000) for pid in ids]
        for p in self.products:
            p.shades = [p.shades[0].model_copy(update={"id": p.id + "-03", "name": "03"})]
        self.preferred = ids[-1]
        self.products[-1].tags = ["moisturizing"]
        if reverse:
            self.products.reverse()

    async def get_ingredients(self, pid, shade, *, ingredient_name=None, operator="includes"):
        return CatalogIngredients.model_validate(
            evidence(
                pid=pid,
                shade=shade,
                name=ingredient_name,
                operator=operator,
                ingredients=[{"name": "Panthenol", "sequence": 1}],
            )
        )


@pytest.mark.anyio
@pytest.mark.parametrize("ids", [["a", "b", "z"], ["sku-91", "sku-03", "sku-72"]])
@pytest.mark.parametrize("reverse", [False, True])
@pytest.mark.parametrize("scope", ["catalog", "previous"])
async def test_ingredient_search_keeps_same_preference_as_general_search(ids, reverse, scope):
    catalog = PreferenceCatalog(ids, reverse)
    context = (
        BeautyContext(
            issued_at=int(time.time()),
            filters=BeautyFilters(category="lip"),
            candidate_ids=ids,
            scope_ids=ids,
        )
        if scope == "previous"
        else None
    )
    request = ChatRequest(
        message="lip 03 Panthenol",
        locale="en",
        request_type="beauty_consultation",
        chat_context=context,
    )
    plan = SearchPlan(
        intent="search" if scope == "catalog" else "refine",
        scope=scope,
        category="lip",
        moisturizing=True,
    )
    general = await execute_beauty(request, plan, catalog)
    ingredient = await execute_beauty(
        request,
        plan.model_copy(
            update={"ingredient_lookup": True, "ingredient_name": "Panthenol", "shade_name": "03"}
        ),
        catalog,
    )
    assert general.chat_context.candidate_ids[0] == catalog.preferred
    assert ingredient.chat_context.candidate_ids == general.chat_context.candidate_ids
    assert [p.id for p in ingredient.products] == ingredient.chat_context.candidate_ids
    assert all(r.verdict == "MATCH" for r in ingredient.ingredient_results)


@pytest.mark.anyio
async def test_preference_applies_before_display_limit_without_assuming_api_order():
    ids = [f"sku-{i:02d}" for i in range(7)]
    catalog = PreferenceCatalog(ids, reverse=True)
    request = ChatRequest(
        message="lip 03 Panthenol", locale="en", request_type="beauty_consultation"
    )
    plan = SearchPlan(
        intent="search",
        category="lip",
        moisturizing=True,
        ingredient_lookup=True,
        ingredient_name="Panthenol",
        shade_name="03",
    )
    response = await execute_beauty(request, plan, catalog)
    assert response.chat_context.candidate_ids == [ids[-1], *ids[:5]]
    assert len(response.products) == 6

"""Clearing prior conditions must preserve explicit replacements from the same turn."""

import pytest

from app.schemas.chat import BeautyContext, BeautyFilters, IngredientFilter
from app.schemas.supervisor import SearchPlan
from app.services.beauty_consultation_service import _effective_filters, answer_beauty
from tests.test_beauty_consultation import Catalog, PlanLlm, product, request

CLEAR_ALL = [
    "category",
    "maxPriceKRW",
    "fragranceFree",
    "moisturizing",
    "query",
    "ingredientConditions",
]


@pytest.fixture
def anyio_backend():
    return "asyncio"


def prior_context():
    return BeautyContext(
        issued_at=1000,
        candidate_ids=["old"],
        selected_product_id="old",
        filters=BeautyFilters(
            category="base",
            maxPriceKRW=30000,
            fragranceFree=True,
            moisturizing=True,
            query="Old Brand",
            ingredientConditions=[IngredientFilter(ingredientName="retinol", operator="excludes")],
        ),
    )


@pytest.mark.parametrize("intent", ["search", "refine"])
@pytest.mark.parametrize("category,budget", [("lip", 1000), ("eye", 0), ("skincare", 17000)])
def test_clear_all_then_replace_preserves_new_conditions(intent, category, budget):
    context = prior_context()
    plan = SearchPlan(intent=intent, category=category, maxPriceKRW=budget, clearFilters=CLEAR_ALL)
    result = _effective_filters(context, plan)
    assert result.category == category and result.max_price_krw == budget
    assert not result.fragrance_free and not result.moisturizing
    assert result.query == "" and not result.ingredient_conditions
    assert context.filters.category == "base" and context.filters.fragrance_free


@pytest.mark.anyio
@pytest.mark.parametrize(
    "message",
    [
        "이전 조건을 모두 해제하고 1천원 이하 립 추천해줘",
        "Start over: lip products at most 1000 won, with none of the old conditions",
        "앞의 요청은 잊고 립만 새로 찾아줘. 예산은 1000원이야",
    ],
)
async def test_reset_and_new_search_returns_empty_not_missing_category(monkeypatch, message):
    monkeypatch.setattr("app.services.beauty_consultation_service.time.time", lambda: 1000)
    catalog = Catalog()
    catalog.products = [product("lip-expensive", 5000), product("other", 800, category="eye")]
    result = await answer_beauty(
        request(message, prior_context()),
        PlanLlm(
            intent="search",
            scope="catalog",
            category="lip",
            maxPriceKRW=1000,
            clearFilters=CLEAR_ALL,
        ),
        catalog,
    )
    assert result.result_type == "empty" and not result.products
    assert result.chat_context.filters.category == "lip"
    assert result.chat_context.filters.max_price_krw == 1000
    assert result.chat_context.selected_product_id is None


def test_partial_clear_preserves_unmentioned_prior_conditions():
    result = _effective_filters(
        prior_context(), SearchPlan(intent="refine", clearFilters=["fragranceFree"])
    )
    assert not result.fragrance_free
    assert result.category == "base" and result.max_price_krw == 30000
    assert result.moisturizing and result.query == "Old Brand" and result.ingredient_conditions


def test_clear_all_then_add_new_ingredient_and_false_zero_values():
    result = _effective_filters(
        prior_context(),
        SearchPlan(
            intent="refine",
            clearFilters=CLEAR_ALL,
            category="eye",
            maxPriceKRW=0,
            fragranceFree=False,
            moisturizing=False,
            ingredientName="panthenol",
        ),
    )
    assert result.category == "eye" and result.max_price_krw == 0
    assert result.fragrance_free is False and result.moisturizing is False
    assert result.ingredient_conditions == [
        IngredientFilter(ingredientName="panthenol", operator="includes")
    ]


@pytest.mark.parametrize(
    "context", [None, BeautyContext(issued_at=1, filters=BeautyFilters(category="base"))]
)
@pytest.mark.anyio
async def test_complete_reset_search_does_not_require_valid_prior_session(monkeypatch, context):
    monkeypatch.setattr("app.services.beauty_consultation_service.time.time", lambda: 1000)
    result = await answer_beauty(
        request("New search with all prior conditions removed", context),
        PlanLlm(
            intent="search",
            scope="catalog",
            category="lip",
            maxPriceKRW=1000,
            clearFilters=CLEAR_ALL,
        ),
        Catalog(),
    )
    assert result.result_type == "empty" and result.chat_context.filters.category == "lip"

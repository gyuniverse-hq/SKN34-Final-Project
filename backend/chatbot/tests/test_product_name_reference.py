"""Explicit product identities must not silently reuse another selected product."""

import pytest

from app.core.errors import UpstreamError
from app.schemas.chat import BeautyContext, BeautyFilters
from app.services.beauty_consultation_service import answer_beauty
from tests.test_beauty_consultation import Catalog, PlanLlm, product, request


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.mark.anyio
@pytest.mark.parametrize("intent", ["price", "detail"])
@pytest.mark.parametrize("reverse", [False, True])
@pytest.mark.parametrize(
    "name,query,message",
    [
        ("Beta Velvet Foundation", "Beta Velvet", "What does Beta Velvet cost?"),
        ("새봄 벨벳 파운데이션", "새봄 벨벳", "새봄 벨벳 파운데이션 가격 알려줘"),
        ("Ｂｅｔａ Velvet", "beta velvet", "Tell me about beta velvet instead"),
    ],
)
async def test_named_product_overrides_previous_selection(
    monkeypatch, intent, reverse, name, query, message
):
    monkeypatch.setattr("app.services.beauty_consultation_service.time.time", lambda: 1000)
    catalog = Catalog()
    first = product("selected", 22400, category="base")
    target = product("named", 31500, category="base")
    target.name = target.name_ko = name
    catalog.products = [target, first] if reverse else [first, target]
    context = BeautyContext(
        issued_at=1000,
        filters=BeautyFilters(category="base"),
        candidate_ids=[p.id for p in catalog.products],
        selected_product_id=first.id,
    )
    result = await answer_beauty(
        request(message, context), PlanLlm(intent=intent, scope="previous", query=query), catalog
    )
    assert [p.id for p in result.products] == [target.id]
    assert result.chat_context.selected_product_id == target.id
    assert context.selected_product_id == first.id
    if intent == "price":
        assert "31,500" in result.answer and "22,400" not in result.answer


@pytest.mark.anyio
@pytest.mark.parametrize(
    "query,ordinal", [("Other Product", None), ("shared", None), ("unique", 1)]
)
async def test_unresolved_or_conflicting_name_never_falls_back(monkeypatch, query, ordinal):
    monkeypatch.setattr("app.services.beauty_consultation_service.time.time", lambda: 1000)
    catalog = Catalog()
    catalog.products = [product("old", 22400), product("target", 31500)]
    catalog.products[0].name = catalog.products[0].name_ko = "Shared First"
    catalog.products[1].name = catalog.products[1].name_ko = "Shared Unique"
    context = BeautyContext(
        issued_at=1000,
        filters=BeautyFilters(),
        candidate_ids=["old", "target"],
        selected_product_id="old",
    )
    result = await answer_beauty(
        request("An explicitly named product's price", context),
        PlanLlm(intent="price", scope="previous", query=query, ordinal=ordinal),
        catalog,
    )
    assert result.result_type == "clarification" and not result.products
    assert "22,400" not in result.answer and "31,500" not in result.answer


@pytest.mark.anyio
async def test_description_does_not_establish_product_identity(monkeypatch):
    monkeypatch.setattr("app.services.beauty_consultation_service.time.time", lambda: 1000)
    catalog = Catalog()
    catalog.products = [product("old", 22400, description="Other Product")]
    context = BeautyContext(
        issued_at=1000, filters=BeautyFilters(), candidate_ids=["old"], selected_product_id="old"
    )
    result = await answer_beauty(
        request("Other Product price", context),
        PlanLlm(intent="price", scope="previous", query="Other Product"),
        catalog,
    )
    assert result.result_type == "clarification" and not result.products


@pytest.mark.anyio
async def test_name_reference_preserves_search_query_and_ingredient_target(monkeypatch):
    monkeypatch.setattr("app.services.beauty_consultation_service.time.time", lambda: 1000)
    catalog = Catalog()
    catalog.products = [product("old", 22400), product("target", 31500)]
    catalog.products[1].name = catalog.products[1].name_ko = "Target Velvet"
    context = BeautyContext(
        issued_at=1000,
        filters=BeautyFilters(query="Catalog Brand"),
        candidate_ids=["old", "target"],
        selected_product_id="old",
    )
    response = await answer_beauty(
        request("Target Velvet ingredients?", context),
        PlanLlm(intent="detail", scope="previous", query="Target Velvet", ingredientLookup=True),
        catalog,
    )
    assert [p.id for p in response.products] == ["target"]
    assert response.chat_context.filters.query == "Catalog Brand"
    assert response.ingredient_results[0].product_id == "target"
    assert response.ingredient_results[0].reason == "shade_required"


@pytest.mark.anyio
@pytest.mark.parametrize("ordinal", [None, 2])
async def test_name_lookup_restricts_untrusted_catalog_to_prior_ids(monkeypatch, ordinal):
    monkeypatch.setattr("app.services.beauty_consultation_service.time.time", lambda: 1000)
    catalog = Catalog()
    catalog.products = [product("old", 22400), product("target", 31500), product("outsider", 100)]
    for p in catalog.products[1:]:
        p.name = p.name_ko = "Target Velvet"
    context = BeautyContext(
        issued_at=1000,
        filters=BeautyFilters(query="Catalog Brand"),
        candidate_ids=["old", "target"],
        selected_product_id="old",
    )
    response = await answer_beauty(
        request("Target Velvet price", context),
        PlanLlm(intent="price", scope="previous", query="Target Velvet", ordinal=ordinal),
        catalog,
    )
    assert [p.id for p in response.products] == ["target"]
    assert response.chat_context.filters.query == "Catalog Brand"


@pytest.mark.anyio
async def test_name_catalog_error_remains_error(monkeypatch):
    monkeypatch.setattr("app.services.beauty_consultation_service.time.time", lambda: 1000)
    catalog = Catalog()

    async def fail(**kwargs):
        raise UpstreamError("unavailable")

    catalog.search_products = fail
    context = BeautyContext(
        issued_at=1000, filters=BeautyFilters(), candidate_ids=["a"], selected_product_id="a"
    )
    from app.core.errors import ApiError

    with pytest.raises(ApiError) as caught:
        await answer_beauty(
            request("Target price", context),
            PlanLlm(intent="price", scope="previous", query="Target"),
            catalog,
        )
    assert caught.value.code == "upstream_error"


@pytest.mark.anyio
async def test_named_reference_cannot_be_bypassed_by_lowest_price_selection(monkeypatch):
    monkeypatch.setattr("app.services.beauty_consultation_service.time.time", lambda: 1000)
    context = BeautyContext(
        issued_at=1000, filters=BeautyFilters(), candidate_ids=["a", "b"], selected_product_id="a"
    )
    response = await answer_beauty(
        request("A named product detail", context),
        PlanLlm(intent="detail", scope="previous", selection="lowest_price", query="b"),
        Catalog(),
    )
    assert response.result_type == "clarification" and not response.products

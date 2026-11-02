import json

import httpx
import pytest

from app.clients.catalog_client import CatalogClient
from app.core.errors import ApiError, UpstreamError
from app.schemas.catalog import CatalogProduct
from app.schemas.chat import BeautyContext, BeautyFilters, ChatRequest
from app.services import beauty_consultation_service as beauty
from app.services.chat_service import ChatService, get_chat_service
from tests.conftest import FakeLlm


class PlanLlm(FakeLlm):
    def __init__(self, **plan):
        super().__init__()
        self.plan = plan
        self.calls = 0

    async def complete(self, messages):
        self.calls += 1
        self.messages = messages
        return json.dumps(self.plan)


def product(pid, price, *, category="lip", description="", ingredients=None):
    return CatalogProduct(
        id=pid,
        brand="Catalog Brand",
        name=pid,
        name_ko=pid,
        category=category,
        makeup_zone="lip" if category == "lip" else None,
        texture="matte",
        priceKRW=price,
        description=description,
        key_ingredients=ingredients or [],
        tags=[],
        shades=[{"id": "real-shade", "name": "Catalog Shade", "hex": "#BB3344"}],
    )


class Catalog:
    def __init__(self):
        self.products = [
            product("a", 15000, ingredients=["히알루론산"]),
            product("b", 19000, description="촉촉한 립", ingredients=["시어버터"]),
            product("c", 25000),
            product("base", 10000, category="base"),
        ]
        self.ids = None

    async def search_products(self, *, category=None, q="", ids=None):
        self.ids = ids
        return list(self.products)  # Deliberately ignores filters; the service must enforce them.

    async def get_product(self, pid):
        return next((p for p in self.products if p.id == pid), None)


def request(message="2만원 이하 촉촉한 립 추천", context=None):
    return ChatRequest(
        message=message, locale="ko", request_type="beauty_consultation", chat_context=context
    )


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.fixture
def setup(monkeypatch):
    monkeypatch.setattr(beauty.time, "time", lambda: 1000)
    return Catalog()


@pytest.mark.anyio
async def test_combines_category_budget_and_preference_from_catalog_only(setup):
    llm = PlanLlm(intent="search", category="lip", maxPriceKRW=20000, moisturizing=True)
    response = await beauty.answer_beauty(request(), llm, setup)
    assert [p.id for p in response.products] == ["b", "a"]
    assert response.chat_context.filters.max_price_krw == 20000
    assert response.chat_context.candidate_ids == ["b", "a"]
    assert all(e.ingredient_coverage == "key_only" for e in response.evidence)
    assert llm.calls == 1


@pytest.mark.anyio
async def test_second_product_and_selected_product_followup_keep_order_and_filters(setup):
    first = await beauty.answer_beauty(
        request(), PlanLlm(intent="search", category="lip", maxPriceKRW=20000), setup
    )
    response = await beauty.answer_beauty(
        request("두 번째 제품 자세히", first.chat_context),
        PlanLlm(intent="detail", scope="previous", ordinal=2),
        setup,
    )
    assert [p.id for p in response.products] == ["b"]
    assert response.chat_context.candidate_ids == ["a", "b"]
    assert response.chat_context.selected_product_id == "b"
    assert response.chat_context.filters.max_price_krw == 20000
    assert "전성분" in response.answer and "미확인" in response.answer
    more = await beauty.answer_beauty(
        request("그 제품 성분은?", response.chat_context),
        PlanLlm(intent="detail", scope="previous"),
        setup,
    )
    assert [p.id for p in more.products] == ["b"]


@pytest.mark.anyio
async def test_fragrance_requires_full_ingredients_and_can_be_removed_explicitly(setup):
    first = await beauty.answer_beauty(
        request(), PlanLlm(intent="search", category="lip", maxPriceKRW=20000), setup
    )
    refined = await beauty.answer_beauty(
        request("아까 추천 중 향료 없는 것만", first.chat_context),
        PlanLlm(intent="refine", scope="previous", fragranceFree=True),
        setup,
    )
    assert refined.products == []
    assert refined.result_type == "empty"
    assert "주요 성분만으로 무향료라고 판단하지 않습니다" in refined.answer
    assert refined.chat_context.scope_ids == ["a", "b"]
    assert refined.chat_context.filters.max_price_krw == 20000
    relaxed = await beauty.answer_beauty(
        request("향료 조건만 빼줘", refined.chat_context),
        PlanLlm(intent="refine", scope="previous", clearFilters=["fragranceFree"]),
        setup,
    )
    assert [p.id for p in relaxed.products] == ["a", "b"]
    assert setup.ids == ["a", "b"]


@pytest.mark.anyio
async def test_ingredient_query_checks_actual_key_ingredients_even_if_api_q_is_name_only(setup):
    response = await beauty.answer_beauty(
        request("히알루론산 있는 제품 찾아줘"),
        PlanLlm(intent="search", query="히알루론산"),
        setup,
    )
    assert [p.id for p in response.products] == ["a"]
    assert response.evidence[0].fragrance_status == "unknown"


@pytest.mark.anyio
@pytest.mark.parametrize("age", [601, -30])
async def test_expired_or_future_candidate_reference_is_not_guessed(setup, age):
    context = BeautyContext(issued_at=1000 - age, filters=BeautyFilters(), candidate_ids=["a", "b"])
    response = await beauty.answer_beauty(
        request("두 번째 제품", context), PlanLlm(intent="detail", ordinal=2), setup
    )
    assert response.result_type == "clarification"
    assert not response.products


@pytest.mark.anyio
async def test_removed_product_does_not_shift_ordinal_to_another_candidate(setup):
    context = BeautyContext(issued_at=1000, filters=BeautyFilters(), candidate_ids=["missing", "b"])
    response = await beauty.answer_beauty(
        request("첫 번째 제품", context), PlanLlm(intent="detail", ordinal=1), setup
    )
    assert not response.products
    assert "현재 카탈로그에서 확인할 수 없어요" in response.answer


@pytest.mark.anyio
@pytest.mark.parametrize("ordinal", [None, 3])
async def test_ambiguous_or_out_of_range_reference_clarifies(setup, ordinal):
    context = BeautyContext(issued_at=1000, filters=BeautyFilters(), candidate_ids=["a", "b"])
    plan = {"intent": "detail"}
    if ordinal is not None:
        plan["ordinal"] = ordinal
    result = await beauty.answer_beauty(request("그 제품", context), PlanLlm(**plan), setup)
    assert result.result_type == "clarification"
    assert result.products == []


@pytest.mark.anyio
async def test_new_category_search_resets_old_budget_and_candidates(setup):
    context = BeautyContext(
        issued_at=1000, filters=BeautyFilters(category="lip", maxPriceKRW=100), candidate_ids=["a"]
    )
    result = await beauty.answer_beauty(
        request("파운데이션 추천", context), PlanLlm(intent="search", category="base"), setup
    )
    assert [p.id for p in result.products] == ["base"]
    assert result.chat_context.filters.max_price_krw is None


@pytest.mark.anyio
async def test_model_cannot_supply_product_ids(setup):
    with pytest.raises(ApiError) as error:
        await beauty.answer_beauty(
            request(), PlanLlm(intent="search", productIds=["invented"]), setup
        )
    assert error.value.code == "invalid_chat_plan"


@pytest.mark.anyio
async def test_catalog_failure_is_not_an_empty_result(setup):
    async def broken(**kwargs):
        raise UpstreamError("unavailable")

    setup.search_products = broken
    with pytest.raises(ApiError) as error:
        await beauty.answer_beauty(request(), PlanLlm(intent="search", category="lip"), setup)
    assert error.value.code == "upstream_error"


def test_new_route_works_without_neo4j_and_keeps_legacy_response(client, setup, monkeypatch):
    service = ChatService(None, PlanLlm(intent="search", category="lip"), setup)
    client.app.dependency_overrides[get_chat_service] = lambda: service

    def forbidden():
        pytest.fail("shopping must use Catalog, not initialize Neo4j")

    monkeypatch.setattr("app.services.chat_service.get_driver", forbidden)
    payload = request().model_dump(mode="json")
    response = client.post(
        "/api/chat",
        json=payload,
        headers={"X-Vishue-Anonymous-Id": "guest-session-0123456789-abcdefghijk"},
    )
    assert response.status_code == 200
    data = response.json()
    assert "answer" in data and "products" in data and "chatContext" in data
    assert data["evidence"][0]["source"] == "catalog_api"


def test_legacy_chat_ignores_unrecognized_context(client):
    result = client.post(
        "/api/chat",
        json={"message": "hi", "chatContext": {"invalid": True}},
        headers={"X-Vishue-Anonymous-Id": "guest-session-0123456789-abcdefghijk"},
    )
    assert result.status_code == 200
    assert set(result.json()) == {"answer", "products"}


@pytest.mark.anyio
async def test_catalog_search_http_contract_encodes_filters_and_checks_returned_ids(monkeypatch):
    calls = []
    original = httpx.AsyncClient

    def respond(req):
        calls.append(req)
        return httpx.Response(
            200,
            json={
                "products": [
                    product("a", 10000).model_dump(mode="json", by_alias=True),
                    product("foreign", 10000).model_dump(mode="json", by_alias=True),
                ]
            },
        )

    monkeypatch.setattr(
        httpx,
        "AsyncClient",
        lambda **kwargs: original(transport=httpx.MockTransport(respond), **kwargs),
    )
    result = await CatalogClient("http://catalog.test").search_products(
        category="lip", q="립 & 보습", ids=["a"]
    )
    assert [p.id for p in result] == ["a"]
    assert calls[0].url.params["category"] == "lip"
    assert calls[0].url.params["q"] == "립 & 보습"
    assert calls[0].url.params["ids"] == "a"


@pytest.mark.anyio
async def test_general_advice_keeps_existing_grounded_chat_path(graph, setup):
    class GeneralLlm(FakeLlm):
        calls = 0

        async def complete(self, messages):
            self.calls += 1
            return '{"intent":"general"}' if self.calls == 1 else "General explanation"

    llm = GeneralLlm()
    result = await ChatService(graph, llm, setup).answer(request("바르는 방법 알려줘"))
    assert result.answer == "General explanation"
    assert result.chat_context is None
    assert llm.calls == 2


@pytest.mark.anyio
async def test_cheapest_after_fragrance_removal_uses_real_prices_and_keeps_context(setup):
    first = await beauty.answer_beauty(
        request(),
        PlanLlm(intent="search", category="lip", maxPriceKRW=20000, moisturizing=True),
        setup,
    )
    refined = await beauty.answer_beauty(
        request("아까 추천한 제품 중 향료 없는 제품만 보여줘.", first.chat_context),
        PlanLlm(intent="refine", scope="previous", fragranceFree=True),
        setup,
    )
    restored = await beauty.answer_beauty(
        request("향료 조건만 빼줘.", refined.chat_context),
        PlanLlm(intent="refine", scope="previous", clearFilters=["fragranceFree"]),
        setup,
    )
    llm = PlanLlm(intent="detail", scope="previous", selection="lowest_price")
    result = await beauty.answer_beauty(
        request("그중 가장 저렴한 제품 알려줘.", restored.chat_context),
        llm,
        setup,
    )
    assert first.chat_context.candidate_ids == ["b", "a"]
    assert [p.id for p in result.products] == ["a"]  # Cheaper than first/moisture-ranked b.
    assert result.result_type == "product_detail"
    assert "15,000" in result.answer
    assert result.chat_context.candidate_ids == restored.chat_context.candidate_ids
    assert result.chat_context.scope_ids == restored.chat_context.scope_ids
    assert result.chat_context.filters == restored.chat_context.filters
    assert result.chat_context.selected_product_id == "a"
    assert llm.calls == 1
    followup = await beauty.answer_beauty(
        request("그 제품 성분", result.chat_context),
        PlanLlm(intent="detail", scope="previous"),
        setup,
    )
    assert [p.id for p in followup.products] == ["a"]


@pytest.mark.anyio
async def test_cheapest_excludes_unlisted_missing_unpriced_and_changed_conditions(setup):
    setup.products = [
        product("foreign", 1),
        product("a", 0),
        product("b", -1),
        product("c", 25000),
        product("base", 1000, category="base"),
        product("valid", 18000),
    ]
    context = BeautyContext(
        issued_at=1000,
        filters=BeautyFilters(category="lip", maxPriceKRW=20000),
        candidate_ids=["a", "b", "c", "base", "missing", "valid"],
    )
    result = await beauty.answer_beauty(
        request("그중 최저가", context),
        PlanLlm(intent="detail", scope="previous", selection="lowest_price"),
        setup,
    )
    assert [p.id for p in result.products] == ["valid"]
    assert "18,000" in result.answer
    assert setup.ids == context.candidate_ids


@pytest.mark.anyio
async def test_cheapest_ties_keep_original_order_and_do_not_guess_singular_followup(setup):
    setup.products = [product("a", 5000), product("b", 5000)]
    context = BeautyContext(
        issued_at=1000, filters=BeautyFilters(category="lip"), candidate_ids=["b", "a"]
    )
    result = await beauty.answer_beauty(
        request("그중 최저가", context),
        PlanLlm(intent="detail", scope="previous", selection="lowest_price"),
        setup,
    )
    assert [p.id for p in result.products] == ["b", "a"]
    assert result.chat_context.selected_product_id is None
    assert "5,000" in result.answer and "2개" in result.answer
    ambiguous = await beauty.answer_beauty(
        request("그 제품", result.chat_context),
        PlanLlm(intent="detail", scope="previous"),
        setup,
    )
    assert ambiguous.result_type == "clarification"


@pytest.mark.anyio
@pytest.mark.parametrize("ids", [[], ["missing"], ["zero"]])
async def test_cheapest_without_verified_prices_returns_empty_without_expanding_scope(setup, ids):
    setup.products = [product("zero", 0), product("unlisted", 1)]
    context = BeautyContext(
        issued_at=1000,
        filters=BeautyFilters(category="lip"),
        candidate_ids=ids,
        scope_ids=["unlisted"],
    )
    result = await beauty.answer_beauty(
        request("그중 최저가", context),
        PlanLlm(intent="detail", scope="previous", selection="lowest_price"),
        setup,
    )
    assert result.result_type == "empty"
    assert result.products == []
    assert result.chat_context == context
    assert "유효한 가격" in result.answer


@pytest.mark.anyio
@pytest.mark.parametrize("age", [601, -30])
async def test_cheapest_rejects_expired_and_future_context(setup, age):
    context = BeautyContext(issued_at=1000 - age, filters=BeautyFilters(), candidate_ids=["a", "b"])
    result = await beauty.answer_beauty(
        request("그중 최저가", context),
        PlanLlm(intent="detail", scope="previous", selection="lowest_price"),
        setup,
    )
    assert result.result_type == "clarification"
    assert not result.products
    assert setup.ids is None


@pytest.mark.anyio
async def test_cheapest_catalog_failure_remains_error(setup):
    async def broken(**kwargs):
        raise UpstreamError("unavailable")

    setup.search_products = broken
    context = BeautyContext(issued_at=1000, filters=BeautyFilters(), candidate_ids=["a"])
    with pytest.raises(ApiError) as error:
        await beauty.answer_beauty(
            request("그중 최저가", context),
            PlanLlm(intent="detail", scope="previous", selection="lowest_price"),
            setup,
        )
    assert error.value.code == "upstream_error"


@pytest.mark.anyio
@pytest.mark.parametrize(
    "plan",
    [
        {"intent": "search", "selection": "lowest_price"},
        {"intent": "detail", "scope": "catalog", "selection": "lowest_price"},
        {"intent": "detail", "scope": "previous", "selection": "lowest_price", "ordinal": 2},
    ],
)
async def test_inconsistent_price_selection_is_rejected(setup, plan):
    with pytest.raises(ApiError) as error:
        await beauty.answer_beauty(request(), PlanLlm(**plan), setup)
    assert error.value.code == "invalid_chat_plan"


@pytest.mark.anyio
async def test_cheapest_does_not_silently_relax_existing_filters(setup):
    context = BeautyContext(
        issued_at=1000,
        filters=BeautyFilters(category="lip", maxPriceKRW=20000, fragranceFree=True),
        candidate_ids=[],
        scope_ids=["a", "b"],
    )
    result = await beauty.answer_beauty(
        request("그중 가장 저렴한 제품", context),
        PlanLlm(intent="detail", scope="previous", selection="lowest_price", fragranceFree=False),
        setup,
    )
    assert result.result_type == "clarification"
    assert result.chat_context == context
    assert result.products == []
    assert setup.ids is None


@pytest.mark.anyio
@pytest.mark.parametrize("source", [None, "synthetic-price", "unverified-url"])
async def test_single_price_is_reference_not_live_and_source_optional(setup, source):
    setup.products[0].price_evidence = source
    context = BeautyContext(
        issued_at=1000, candidate_ids=["a", "b"], selected_product_id="a", filters=BeautyFilters()
    )
    response = await beauty.answer_beauty(
        request("이 제품 오늘 얼마야?", context), PlanLlm(intent="price", scope="previous"), setup
    )
    assert response.result_type == "product_detail"
    assert [p.id for p in response.products] == ["a"]
    assert (
        "15,000" in response.answer
        and "오늘의 실제 판매가·판매처·확인 시각은 미확인" in response.answer
    )
    assert ("합성 가격" in response.answer) == (source == "synthetic-price")
    assert "주요 성분:" not in response.answer
    assert "unverified-url" not in response.answer


@pytest.mark.anyio
@pytest.mark.parametrize(
    "selected,ordinal,expected",
    [(None, None, None), ("missing", None, None), ("a", 2, "b"), ("b", None, "b")],
)
async def test_single_price_resolves_current_selection_without_cheapest(
    setup, selected, ordinal, expected
):
    context = BeautyContext(
        issued_at=1000,
        candidate_ids=["a", "b"],
        selected_product_id=selected,
        filters=BeautyFilters(),
    )
    plan = {"intent": "price", "scope": "previous"}
    if ordinal is not None:
        plan["ordinal"] = ordinal
    response = await beauty.answer_beauty(request("가격은?", context), PlanLlm(**plan), setup)
    assert [p.id for p in response.products] == ([expected] if expected else [])
    if expected:
        assert "19,000" in response.answer
    else:
        assert response.result_type == "clarification"


@pytest.mark.anyio
async def test_single_price_unavailable_and_product_removed(setup):
    context = BeautyContext(
        issued_at=1000, candidate_ids=["a"], selected_product_id="a", filters=BeautyFilters()
    )
    setup.products[0].price_krw = 0
    response = await beauty.answer_beauty(
        request(context=context), PlanLlm(intent="price", scope="previous"), setup
    )
    assert "기준가격을 확인할 수 없습니다" in response.answer
    setup.products.clear()
    response = await beauty.answer_beauty(
        request(context=context), PlanLlm(intent="price", scope="previous"), setup
    )
    assert response.products == [] and response.result_type == "clarification"


def test_missing_price_field_is_not_invented():
    from pydantic import ValidationError

    raw = product("a", 100).model_dump()
    del raw["price_krw"]
    with pytest.raises(ValidationError):
        CatalogProduct.model_validate(raw)


@pytest.mark.anyio
async def test_price_missing_upstream_field_is_502_without_fabrication(monkeypatch):
    raw = product("a", 100).model_dump(by_alias=True)
    del raw["priceKRW"]
    transport = httpx.MockTransport(lambda req: httpx.Response(200, json={"product": raw}))
    client_class = httpx.AsyncClient
    monkeypatch.setattr(
        httpx, "AsyncClient", lambda **kwargs: client_class(transport=transport, **kwargs)
    )
    context = BeautyContext(
        issued_at=1000, candidate_ids=["a"], selected_product_id="a", filters=BeautyFilters()
    )
    monkeypatch.setattr(beauty.time, "time", lambda: 1000)
    with pytest.raises(ApiError) as error:
        await beauty.answer_beauty(
            request(context=context),
            PlanLlm(intent="price", scope="previous"),
            CatalogClient("http://fixture.local"),
        )
    assert error.value.status == 502
    assert error.value.code == "upstream_error"

"""Synthetic ingredient-search coverage; standalone pytest, no private harness dependency."""

import asyncio
import time
from uuid import uuid4

import pytest

from app.clients.catalog_client import IngredientLookupError
from app.repositories.chat_session_repository import ChatSessionRepository
from app.schemas.catalog import CatalogIngredients
from app.schemas.chat import BeautyContext, BeautyFilters, ChatRequest, IngredientFilter
from app.schemas.supervisor import SearchPlan
from app.services import beauty_consultation_service as beauty
from app.services.chat_service import ChatService
from tests.test_beauty_consultation import Catalog, PlanLlm, product
from tests.test_chat_sessions import RedisDouble
from tests.test_ingredient_consultation import evidence


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.fixture(autouse=True)
def fixed_clock(monkeypatch):
    monkeypatch.setattr(time, "time", lambda: 1000)


class SearchCatalog(Catalog):
    def __init__(self, count, *, marker="Niacinamide", matches=(), reverse=False):
        self.products = [product(f"item-{i:03d}", 15000) for i in range(count)]
        self.ingredients = {
            p.id: [marker] if i in matches else ["Water"] for i, p in enumerate(self.products)
        }
        for p in self.products:
            p.shades = [p.shades[0].model_copy(update={"id": f"{p.id}-shade", "name": "03"})]
        if reverse:
            self.products.reverse()
        self.product_calls, self.ingredient_calls = [], []
        self.states = {}
        self.delay = 1
        self.slow_product = None
        self.slow_condition = None

    async def get_product(self, pid):
        self.product_calls.append(pid)
        if pid == self.slow_product:
            await asyncio.sleep(self.delay)
        return await super().get_product(pid)

    async def get_ingredients(self, pid, shade, *, ingredient_name=None, operator="includes"):
        self.ingredient_calls.append((pid, ingredient_name))
        if ingredient_name == self.slow_condition:
            await asyncio.sleep(self.delay)
        state = self.states.get(pid)
        if state == "ERROR":
            raise IngredientLookupError("network_error")
        changes = {
            "ingredients": [
                {"name": name, "sequence": i + 1} for i, name in enumerate(self.ingredients[pid])
            ]
        }
        if state == "UNKNOWN":
            changes.update(
                status="unknown",
                verdict="UNKNOWN",
                mappingStatus="candidate",
                reviewStatus="unreviewed",
                ingredients=[],
            )
        return CatalogIngredients.model_validate(
            evidence(pid=pid, shade=shade, name=ingredient_name, operator=operator, **changes)
        )


def search_request(context=None, *, marker="Niacinamide", locale="ko"):
    return ChatRequest(
        message=f"03 {marker} lip",
        locale=locale,
        request_type="beauty_consultation",
        chat_context=context,
        request_id=uuid4(),
    )


def search_plan(marker="Niacinamide", *, scope="catalog"):
    return SearchPlan(
        intent="search" if scope == "catalog" else "refine",
        scope=scope,
        category="lip",
        ingredientName=marker,
        ingredientLookup=True,
        shadeName="03",
    )


@pytest.mark.anyio
@pytest.mark.parametrize("marker", ["Niacinamide", "판테놀"])
@pytest.mark.parametrize("reverse", [False, True])
@pytest.mark.parametrize("count", [0, 1, 6, 7, 13])
async def test_search_finds_late_match_without_depending_on_api_order(count, reverse, marker):
    catalog = SearchCatalog(count, marker=marker, matches=[count - 1], reverse=reverse)
    response = await beauty.execute_beauty(
        search_request(marker=marker), search_plan(marker), catalog
    )
    expected = [f"item-{count - 1:03d}"] if count else []
    assert [p.id for p in response.products] == expected
    assert response.chat_context.candidate_ids == expected
    assert response.chat_context.scope_ids == expected
    assert set(response.chat_context.shade_selections) == set(expected)
    assert response.result_type == ("recommendations" if count else "empty")
    assert all(r.verdict == "MATCH" for r in response.ingredient_results)


@pytest.mark.anyio
@pytest.mark.parametrize("count", [6, 7, 13])
async def test_display_stops_at_six_and_never_stores_the_scan_pool(count):
    catalog = SearchCatalog(count, matches=range(count))
    response = await beauty.execute_beauty(search_request(), search_plan(), catalog)
    expected = [f"item-{i:03d}" for i in range(6)]
    assert [p.id for p in response.products] == expected
    assert response.chat_context.candidate_ids == response.chat_context.scope_ids == expected
    assert len(response.ingredient_results) == len(response.evidence) == 6
    assert set(response.chat_context.shade_selections) == set(expected)
    assert len(catalog.product_calls) == len(catalog.ingredient_calls) == 6
    assert response.tool_result.status == ("success" if count == 6 else "partial")
    response.model_validate(response.model_dump())


@pytest.mark.anyio
@pytest.mark.parametrize("count", [20, 21, 22])
async def test_scan_request_budget_is_bounded_and_unsearched_is_not_empty(count):
    catalog = SearchCatalog(count, matches=[count - 1])
    response = await beauty.execute_beauty(search_request(), search_plan(), catalog)
    assert len(catalog.product_calls) + len(catalog.ingredient_calls) <= 42
    if count <= 21:
        assert [p.id for p in response.products] == [f"item-{count - 1:03d}"]
        assert response.result_type == "recommendations"
    else:
        assert not response.products
        assert response.result_type == "clarification"
        assert response.tool_result.status == "partial"
        assert "21/22" in response.answer and "1" in response.answer
        assert "찾지 못했어요" not in response.answer


@pytest.mark.anyio
async def test_six_conditions_keep_the_old_worst_case_budget():
    names = [f"component-{i}" for i in range(6)]
    catalog = SearchCatalog(7, marker=names[0], matches=[6])
    catalog.ingredients["item-006"] = names
    context = BeautyContext(
        issued_at=1000,
        filters=BeautyFilters(
            ingredient_conditions=[
                IngredientFilter(ingredient_name=n, operator="includes") for n in names
            ]
        ),
    )
    response = await beauty.execute_beauty(
        search_request(context, marker=names[0]), search_plan(names[0]), catalog
    )
    assert len(catalog.product_calls) + len(catalog.ingredient_calls) == 42
    assert "item-006" not in catalog.product_calls
    assert response.result_type == "clarification"
    assert response.tool_result.status == "partial"
    assert "6/7" in response.answer


@pytest.mark.anyio
async def test_unknown_and_error_are_retained_without_becoming_non_matches():
    catalog = SearchCatalog(7, matches=[6])
    catalog.states = {"item-000": "ERROR", "item-001": "UNKNOWN"}
    response = await beauty.execute_beauty(search_request(), search_plan(), catalog)
    assert [p.id for p in response.products] == ["item-000", "item-001", "item-006"]
    assert [r.verdict for r in response.ingredient_results] == ["ERROR", "UNKNOWN", "MATCH"]
    assert response.tool_result.status == "error"
    assert response.result_type == "clarification"


@pytest.mark.anyio
async def test_previous_scope_never_expands_to_the_seventh_product():
    catalog = SearchCatalog(7, matches=[6])
    ids = [f"item-{i:03d}" for i in range(6)]
    context = BeautyContext(
        issued_at=1000,
        filters=BeautyFilters(category="lip"),
        candidate_ids=ids,
        scope_ids=ids,
        shade_selections={pid: f"{pid}-shade" for pid in ids},
    )
    response = await beauty.execute_beauty(
        search_request(context), search_plan(scope="previous"), catalog
    )
    assert not response.products and response.result_type == "empty"
    assert "item-006" not in catalog.product_calls
    assert not response.chat_context.shade_selections


@pytest.mark.anyio
@pytest.mark.parametrize("locale", ["ko", "en", "ja", "zh"])
async def test_partial_scan_scope_is_visible_in_all_locales(locale):
    catalog = SearchCatalog(7, matches=range(7))
    response = await beauty.execute_beauty(search_request(locale=locale), search_plan(), catalog)
    assert "6/7" in response.answer
    assert response.tool_result.status == "partial"
    assert "tool_result" not in response.model_dump()
    assert "toolResult" not in response.model_dump(by_alias=True)


@pytest.mark.anyio
async def test_deadline_keeps_only_finished_products(monkeypatch):
    monkeypatch.setattr(beauty, "INGREDIENT_SEARCH_TIMEOUT_SECONDS", 0.01, raising=False)
    catalog = SearchCatalog(3, matches=[0, 1, 2])
    catalog.slow_product = "item-001"
    response = await beauty.execute_beauty(search_request(), search_plan(), catalog)
    assert [p.id for p in response.products] == ["item-000"]
    assert len(response.ingredient_results) == 1
    assert response.chat_context.shade_selections == {"item-000": "item-000-shade"}
    assert "1/3" in response.answer and response.tool_result.status == "partial"


@pytest.mark.anyio
async def test_deadline_mid_condition_does_not_publish_half_verified_product(monkeypatch):
    monkeypatch.setattr(beauty, "INGREDIENT_SEARCH_TIMEOUT_SECONDS", 0.01, raising=False)
    catalog = SearchCatalog(2)
    catalog.ingredients["item-000"] = ["Niacinamide", "Panthenol"]
    catalog.slow_condition = "Panthenol"
    context = BeautyContext(
        issued_at=1000,
        filters=BeautyFilters(
            ingredient_conditions=[
                IngredientFilter(ingredient_name="Panthenol", operator="includes")
            ]
        ),
    )
    response = await beauty.execute_beauty(search_request(context), search_plan(), catalog)
    assert not response.products and not response.ingredient_results
    assert not response.chat_context.shade_selections
    assert response.result_type == "clarification"
    assert response.tool_result.status == "partial"
    assert "0/2" in response.answer


@pytest.mark.anyio
async def test_error_before_deadline_stays_error(monkeypatch):
    monkeypatch.setattr(beauty, "INGREDIENT_SEARCH_TIMEOUT_SECONDS", 0.01, raising=False)
    catalog = SearchCatalog(3)
    catalog.states["item-000"] = "ERROR"
    catalog.slow_product = "item-001"
    response = await beauty.execute_beauty(search_request(), search_plan(), catalog)
    assert [r.verdict for r in response.ingredient_results] == ["ERROR"]
    assert response.tool_result.status == "error"


@pytest.mark.anyio
async def test_seventh_result_session_ordinal_and_retry():
    catalog = SearchCatalog(7, matches=[6])
    llm = PlanLlm(**search_plan().model_dump(by_alias=True, exclude_none=True))
    redis = RedisDouble()
    service = ChatService(None, llm, catalog, sessions=ChatSessionRepository(redis))
    response = await service.answer(search_request(), "guest:coverage")
    assert response.chat_context.session is not None
    assert response.chat_context.candidate_ids == ["item-006"]
    saved = await service._sessions.load("guest:coverage", response.chat_context.session)
    assert saved.context.scope_ids == ["item-006"]
    llm.plan = {"intent": "price", "scope": "previous", "ordinal": 1}
    followup = search_request(response.chat_context)
    price = await service.answer(followup, "guest:coverage")
    assert price.chat_context.selected_product_id == "item-006"
    assert "15,000" in price.answer
    calls, writes = llm.calls, redis.writes
    retry = await service.answer(followup, "guest:coverage")
    assert retry.model_dump(mode="json") == price.model_dump(mode="json")
    assert (llm.calls, redis.writes) == (calls, writes)


@pytest.mark.anyio
async def test_fragrance_unknown_keeps_public_scope_bounded():
    catalog = SearchCatalog(13)
    catalog.states = {p.id: "UNKNOWN" for p in catalog.products}
    context = BeautyContext(
        issued_at=1000, filters=BeautyFilters(category="lip", fragrance_free=True)
    )
    response = await beauty.execute_beauty(
        search_request(context), search_plan().model_copy(update={"fragrance_free": True}), catalog
    )
    assert len(response.products) == len(response.ingredient_results) == 6
    assert len(response.chat_context.candidate_ids) == len(response.chat_context.scope_ids) == 6
    assert response.chat_context.filters.fragrance_free
    assert response.result_type == "clarification"
    assert response.tool_result.status == "partial"


@pytest.mark.anyio
async def test_unknown_slots_do_not_hide_a_later_match_or_claim_complete_certainty():
    catalog = SearchCatalog(7, matches=[6])
    catalog.states = {f"item-{i:03d}": "UNKNOWN" for i in range(6)}
    response = await beauty.execute_beauty(search_request(), search_plan(), catalog)
    assert len(response.products) == 6
    assert [r.verdict for r in response.ingredient_results] == ["UNKNOWN"] * 5 + ["MATCH"]
    assert "item-006" in catalog.product_calls
    assert response.result_type == "clarification"
    assert response.tool_result.status == "clarification"
    assert "7/7" in response.answer


@pytest.mark.anyio
async def test_fragrance_unknown_candidates_do_not_hide_later_verified_match():
    catalog = SearchCatalog(7, matches=[6])
    catalog.states = {f"item-{i:03d}": "UNKNOWN" for i in range(6)}
    plan = search_plan().model_copy(update={"fragrance_free": True})
    response = await beauty.execute_beauty(search_request(), plan, catalog)
    assert "item-006" in catalog.product_calls
    assert len(response.products) == len(response.ingredient_results) == 6
    assert response.ingredient_results[-1].verdict == "MATCH"
    assert "item-006" in response.chat_context.candidate_ids
    assert response.tool_result.status == "partial"
    assert response.chat_context.filters.fragrance_free


@pytest.mark.anyio
async def test_search_never_selects_a_first_shade_without_an_explicit_label():
    catalog = SearchCatalog(7, matches=[6])
    plan = search_plan().model_copy(update={"shade_name": None})
    response = await beauty.execute_beauty(search_request(), plan, catalog)
    assert not catalog.ingredient_calls
    assert not response.chat_context.shade_selections
    assert all(r.reason == "shade_required" for r in response.ingredient_results)
    assert len(response.products) == 6 and "7/7" in response.answer


@pytest.mark.anyio
async def test_scan_deadline_does_not_change_ingredient_detail(monkeypatch):
    monkeypatch.setattr(beauty, "INGREDIENT_SEARCH_TIMEOUT_SECONDS", 0.001, raising=False)
    catalog = SearchCatalog(1, matches=[0])
    catalog.slow_product, catalog.delay = "item-000", 0.02
    context = BeautyContext(
        issued_at=1000,
        filters=BeautyFilters(),
        candidate_ids=["item-000"],
        scope_ids=["item-000"],
        selected_product_id="item-000",
        shade_selections={"item-000": "item-000-shade"},
    )
    plan = search_plan().model_copy(update={"intent": "detail", "scope": "previous"})
    response = await beauty.execute_beauty(search_request(context), plan, catalog)
    assert response.result_type == "product_detail"
    assert response.ingredient_results[0].verdict == "MATCH"
    assert response.tool_result.status == "success"


@pytest.mark.anyio
async def test_unfinished_empty_scan_keeps_last_server_session(monkeypatch):
    catalog = SearchCatalog(22)
    llm = PlanLlm(intent="search", category="lip")
    redis = RedisDouble()
    repo = ChatSessionRepository(redis)
    service = ChatService(None, llm, catalog, sessions=repo)
    initial = await service.answer(search_request(), "guest:coverage")
    before = await repo.load("guest:coverage", initial.chat_context.session)
    llm.plan = search_plan().model_dump(by_alias=True, exclude_none=True)
    catalog.slow_product = "item-000"
    monkeypatch.setattr(beauty, "INGREDIENT_SEARCH_TIMEOUT_SECONDS", 0.01, raising=False)
    response = await service.answer(search_request(initial.chat_context), "guest:coverage")
    assert response.result_type == "clarification" and not response.products
    assert response.session_status == "unchanged"
    after = await repo.load("guest:coverage", response.chat_context.session)
    assert before.model_dump() == after.model_dump()
    assert "0/22" in response.answer and redis.writes == 1


@pytest.mark.anyio
@pytest.mark.parametrize("count", [1, 6])
async def test_empty_verified_scope_can_be_reused_after_explicit_condition_clear(count):
    catalog = SearchCatalog(count)
    llm = PlanLlm(**search_plan().model_dump(by_alias=True, exclude_none=True))
    redis = RedisDouble()
    repo = ChatSessionRepository(redis)
    service = ChatService(None, llm, catalog, sessions=repo)
    empty = await service.answer(search_request(), "guest:coverage")
    ids = [f"item-{i:03d}" for i in range(count)]
    assert empty.result_type == "empty" and not empty.products
    assert empty.chat_context.scope_ids == ids
    assert not empty.chat_context.shade_selections
    saved = await repo.load("guest:coverage", empty.chat_context.session)
    assert saved.context.scope_ids == ids
    llm.plan = {"intent": "refine", "scope": "previous", "clearFilters": ["ingredientConditions"]}
    restored = await service.answer(search_request(empty.chat_context), "guest:coverage")
    assert [p.id for p in restored.products] == ids
    assert not restored.chat_context.filters.ingredient_conditions


@pytest.mark.anyio
@pytest.mark.parametrize("reverse", [False, True])
async def test_confirmed_ingredient_failure_survives_other_condition_timeout(reverse):
    class MixedCatalog(SearchCatalog):
        async def get_ingredients(self, pid, shade, *, ingredient_name=None, operator="includes"):
            if pid == "item-001" and ingredient_name == "Glycerin":
                raise IngredientLookupError("timeout")
            return await super().get_ingredients(
                pid, shade, ingredient_name=ingredient_name, operator=operator
            )

    catalog = MixedCatalog(3, matches=[1])
    conditions = [
        {"ingredientName": "Niacinamide", "operator": "excludes"},
        {"ingredientName": "Glycerin", "operator": "excludes"},
    ]
    if reverse:
        conditions.reverse()
    llm = PlanLlm(intent="search", category="lip", shadeName="03", ingredientConditions=conditions)
    service = ChatService(None, llm, catalog, sessions=ChatSessionRepository(RedisDouble()))
    owner = "guest:compound-condition-search"
    response = await service.answer(search_request(), owner)
    expected = ["item-000", "item-002"]
    assert [p.id for p in response.products] == expected
    assert [r.product_id for r in response.ingredient_results] == expected
    assert response.chat_context.candidate_ids == expected
    stored = await service._sessions.load(owner, response.chat_context.session)
    assert stored.context.candidate_ids == expected
    assert stored.last_tool_result.status == "success"
    assert "3/3" in response.answer
    llm.plan = {"intent": "price", "scope": "previous", "ordinal": 2}
    followup = await service.answer(search_request(response.chat_context), owner)
    assert followup.chat_context.selected_product_id == "item-002"


@pytest.mark.anyio
@pytest.mark.parametrize("persist", [True, False])
async def test_detail_filter_update_survives_saved_session_and_retry(persist):
    catalog = SearchCatalog(2)
    llm = PlanLlm(
        intent="search",
        category="lip",
        shadeName="03",
        ingredientName="A",
        ingredientOperator="excludes",
    )
    redis = RedisDouble()
    service = ChatService(None, llm, catalog, sessions=ChatSessionRepository(redis))
    owner = "guest:detail-ingredient-update"
    first = await service.answer(search_request(), owner)
    llm.plan = dict(
        intent="detail",
        scope="previous",
        ordinal=2,
        ingredientName="B",
        ingredientOperator="excludes" if persist else "includes",
        persistIngredientConditions=persist,
    )
    req = search_request(first.chat_context)
    detail = await service.answer(req, owner)
    expected = ["A", "B"] if persist else ["A"]
    assert [
        c.ingredient_name for c in detail.chat_context.filters.ingredient_conditions
    ] == expected
    assert detail.chat_context.selected_product_id == "item-001"
    calls, writes = llm.calls, redis.writes
    await service.answer(req, owner)
    assert (llm.calls, redis.writes) == (calls, writes)
    llm.plan = dict(intent="refine", scope="previous", maxPriceKRW=20000)
    catalog.ingredient_calls.clear()
    result = await service.answer(search_request(detail.chat_context), owner)
    assert [
        c.ingredient_name for c in result.chat_context.filters.ingredient_conditions
    ] == expected
    assert {name for _, name in catalog.ingredient_calls} == set(expected)
    assert result.chat_context.filters.max_price_krw == 20000


@pytest.mark.anyio
@pytest.mark.parametrize(
    "first,second,expected",
    [
        ("MATCH", "MATCH", "MATCH"),
        ("NOT_MATCH", "ERROR", "NOT_MATCH"),
        ("ERROR", "NOT_MATCH", "NOT_MATCH"),
        ("NOT_MATCH", "UNKNOWN", "NOT_MATCH"),
        ("MATCH", "ERROR", "ERROR"),
        ("MATCH", "UNKNOWN", "UNKNOWN"),
        ("UNKNOWN", "ERROR", "ERROR"),
        ("FOREIGN", "MATCH", "ERROR"),
    ],
)
async def test_compound_condition_preserves_checks(first, second, expected):
    catalog = SearchCatalog(1)
    pid, shade = "item-000", "item-000-shade"

    async def lookup(pid, shade, *, ingredient_name, operator):
        state = first if ingredient_name == "A" else second
        if state == "ERROR":
            raise IngredientLookupError("timeout")
        catalog.states[pid] = state
        catalog.ingredients[pid] = [ingredient_name] if state == "NOT_MATCH" else ["Water"]
        result = await SearchCatalog.get_ingredients(
            catalog, pid, shade, ingredient_name=ingredient_name, operator=operator
        )
        return result.model_copy(update={"product_id": "foreign"}) if state == "FOREIGN" else result

    catalog.get_ingredients = lookup
    conditions = [IngredientFilter(ingredient_name=n, operator="excludes") for n in ("A", "B")]
    results = [
        await beauty._lookup_ingredient_condition(catalog, pid, shade, c) for c in conditions
    ]
    combined = beauty._combine_ingredient_results(results)
    assert combined.verdict == expected
    assert [c.ingredient_name for c in combined.conditions] == ["A", "B"]
    assert all(c.product_id == pid and c.shade_id == shade for c in combined.conditions)
    for check, state in zip(combined.conditions, (first, second), strict=True):
        if state in {"MATCH", "NOT_MATCH"}:
            assert check.evidence_id == f"synthetic-{pid}"
        elif state in {"ERROR", "FOREIGN"}:
            assert check.reason == ("timeout" if state == "ERROR" else "invalid_response")


@pytest.mark.anyio
async def test_scan_deadline_preserves_completed_exclusion(monkeypatch):
    monkeypatch.setattr(beauty, "INGREDIENT_SEARCH_TIMEOUT_SECONDS", 0.01)
    catalog = SearchCatalog(2, matches=[0])
    catalog.slow_condition = "Panthenol"
    plan = SearchPlan(
        intent="search",
        category="lip",
        shadeName="03",
        ingredientConditions=[
            {"ingredientName": name, "operator": "excludes"}
            for name in ("Niacinamide", "Panthenol")
        ],
    )
    response = await beauty.execute_beauty(search_request(), plan, catalog)
    assert response.chat_context.candidate_ids == []
    assert response.tool_result.status == "partial"
    assert "1/2" in response.answer


@pytest.mark.anyio
@pytest.mark.parametrize(
    "first,second,verdict",
    [
        ("NOT_MATCH", "ERROR", "NOT_MATCH"),
        ("ERROR", "NOT_MATCH", "NOT_MATCH"),
        ("NOT_MATCH", "UNKNOWN", "NOT_MATCH"),
        ("MATCH", "ERROR", "ERROR"),
        ("MATCH", "UNKNOWN", "UNKNOWN"),
        ("MATCH", "MATCH", "MATCH"),
    ],
)
async def test_detail_reports_each_condition_verdict_and_failure(first, second, verdict):
    catalog = SearchCatalog(1)
    pid = "item-000"

    async def get_ingredients(pid, shade, *, ingredient_name, operator):
        state = first if ingredient_name == "A" else second
        if state == "ERROR":
            raise IngredientLookupError("timeout")
        catalog.states[pid] = state if state == "UNKNOWN" else None
        catalog.ingredients[pid] = [ingredient_name] if state == "NOT_MATCH" else ["Water"]
        return await SearchCatalog.get_ingredients(
            catalog, pid, shade, ingredient_name=ingredient_name, operator=operator
        )

    catalog.get_ingredients = get_ingredients
    context = BeautyContext(
        issuedAt=1000,
        filters={},
        candidateIds=[pid],
        selectedProductId=pid,
        shadeSelections={pid: "item-000-shade"},
    )
    plan = SearchPlan(
        intent="detail",
        scope="previous",
        ordinal=1,
        ingredientConditions=[
            {"ingredientName": "A", "operator": "excludes"},
            {"ingredientName": "B", "operator": "excludes"},
        ],
    )
    response = await beauty.execute_beauty(search_request(context), plan, catalog)
    result = response.ingredient_results[0]
    assert result.verdict == verdict
    assert "A:" in response.answer and "B:" in response.answer
    for name, state in (("A", first), ("B", second)):
        check = next(c for c in result.conditions if c.ingredient_name == name)
        assert check.verdict == state
        if state == "ERROR":
            assert check.reason == "timeout"
            assert "조회 시간이 초과됐습니다." in response.answer
            assert check.option_id is None and check.evidence_id is None
    if verdict in {"ERROR", "UNKNOWN"} and "MATCH" in (first, second):
        assert result.option_id == "option-item-000"
        assert result.evidence_id == "synthetic-item-000"
        assert result.ingredients


@pytest.mark.anyio
@pytest.mark.parametrize("locale,index", [("ko", 0), ("en", 1), ("ja", 2), ("zh", 3)])
@pytest.mark.parametrize("reason", ["timeout", "source_unavailable"])
async def test_detail_failure_reason_is_localized(locale, index, reason):
    catalog = SearchCatalog(1)
    pid = "item-000"

    async def lookup(pid, shade, *, ingredient_name, operator):
        if ingredient_name == "B":
            raise IngredientLookupError(reason)
        catalog.ingredients[pid] = ["A"]
        return await SearchCatalog.get_ingredients(
            catalog, pid, shade, ingredient_name=ingredient_name, operator=operator
        )

    catalog.get_ingredients = lookup
    context = BeautyContext(
        issuedAt=1000,
        filters={},
        candidateIds=[pid],
        selectedProductId=pid,
        shadeSelections={pid: "item-000-shade"},
    )
    plan = SearchPlan(
        intent="detail",
        scope="previous",
        ordinal=1,
        ingredientConditions=[
            {"ingredientName": "A", "operator": "excludes"},
            {"ingredientName": "B", "operator": "excludes"},
        ],
    )
    response = await beauty.execute_beauty(search_request(context, locale=locale), plan, catalog)
    assert response.ingredient_results[0].verdict == "NOT_MATCH"
    assert "A:" in response.answer and "B:" in response.answer
    assert beauty.INGREDIENT_ISSUES[reason][index] in response.answer


@pytest.mark.anyio
async def test_compound_conflicting_verified_options_do_not_share_evidence():
    catalog = SearchCatalog(1)
    pid, shade = "item-000", "item-000-shade"
    conditions = [IngredientFilter(ingredient_name=n, operator="excludes") for n in ("A", "B")]
    results = [
        await beauty._lookup_ingredient_condition(catalog, pid, shade, c) for c in conditions
    ]
    results[1].option_id = "foreign-option"
    results[1].conditions[0].option_id = "foreign-option"
    combined = beauty._combine_ingredient_results(results)
    assert combined.verdict == "UNKNOWN"
    assert all(c.verdict == "UNKNOWN" for c in combined.conditions)
    assert all(c.evidence_id is None for c in combined.conditions)


@pytest.mark.anyio
async def test_unverified_assertion_is_converted_to_named_unknown():
    catalog = SearchCatalog(1)
    pid, shade = "item-000", "item-000-shade"

    async def lookup(pid, shade, *, ingredient_name, operator):
        result = await SearchCatalog.get_ingredients(
            catalog, pid, shade, ingredient_name=ingredient_name, operator=operator
        )
        return result.model_copy(update={"review_status": "unreviewed"})

    catalog.get_ingredients = lookup
    condition = IngredientFilter(ingredient_name="A", operator="excludes")
    result = await beauty._lookup_ingredient_condition(catalog, pid, shade, condition)
    assert result.verdict == "UNKNOWN"
    assert len(result.conditions) == 1
    assert result.conditions[0].ingredient_name == "A"
    assert result.conditions[0].verdict == "UNKNOWN"
    assert result.conditions[0].evidence_id is None

"""Evidence-search retention: uncertainty must not mask later verified candidates."""

import re
from uuid import NAMESPACE_URL, uuid4, uuid5

import pytest

from app.repositories.chat_session_repository import ChatSessionRepository
from app.services import beauty_consultation_service as beauty
from app.services.chat_service import ChatService
from tests.test_beauty_consultation import PlanLlm
from tests.test_chat_sessions import RedisDouble
from tests.test_ingredient_search_coverage import (
    SearchCatalog,
    search_plan,
    search_request,
)
from tests.test_ingredient_search_coverage import (
    fixed_clock as fixed_clock,
)


@pytest.fixture
def anyio_backend():
    return "asyncio"


def uncertain_prefix(prefix, matches=1, state="UNKNOWN", reverse=False, marker="Niacinamide"):
    catalog = SearchCatalog(
        prefix + matches, matches=range(prefix, prefix + matches), reverse=reverse, marker=marker
    )
    for p in catalog.products:
        index = int(p.id.rsplit("-", 1)[1])
        if index < prefix:
            if state == "shade_required":
                p.shades[0].name = "04"
            else:
                catalog.states[p.id] = state
    return catalog


@pytest.mark.anyio
@pytest.mark.parametrize("prefix", [0, 1, 6, 9, 20, 21])
@pytest.mark.parametrize("state", ["UNKNOWN", "ERROR", "shade_required"])
@pytest.mark.parametrize("reverse", [False, True])
async def test_verified_candidate_is_found_after_uncertainty_within_budget(prefix, state, reverse):
    catalog = uncertain_prefix(prefix, state=state, reverse=reverse)
    response = await beauty.execute_beauty(search_request(), search_plan(), catalog)
    verified = {r.product_id for r in response.ingredient_results if r.verdict == "MATCH"}
    expected = {f"item-{prefix:03d}"} if prefix < 21 else set()
    assert verified == expected
    assert len(response.products) <= 6
    assert len(catalog.product_calls) + len(catalog.ingredient_calls) <= 42
    assert len(catalog.product_calls) == min(prefix + 1, 21)
    assert set(response.chat_context.candidate_ids) == {p.id for p in response.products}
    assert set(response.chat_context.scope_ids) == set(response.chat_context.candidate_ids)
    assert set(response.chat_context.shade_selections) <= set(response.chat_context.candidate_ids)
    assert len(response.products) == len(response.ingredient_results) == len(response.evidence)
    if prefix:
        assert response.result_type == "clarification"
    if prefix >= 21:
        assert "21/22" in response.answer
        assert response.tool_result.status == ("error" if state == "ERROR" else "partial")
    if state == "shade_required":
        assert all(pid in expected for pid, _ in catalog.ingredient_calls)
    response.model_validate(response.model_dump())


@pytest.mark.anyio
@pytest.mark.parametrize("state", ["UNKNOWN", "ERROR"])
async def test_six_verified_results_can_replace_displayed_uncertainty_without_erasing_it(state):
    catalog = uncertain_prefix(6, matches=6, state=state)
    response = await beauty.execute_beauty(search_request(), search_plan(), catalog)
    assert [p.id for p in response.products] == [f"item-{i:03d}" for i in range(6, 12)]
    assert all(r.verdict == "MATCH" for r in response.ingredient_results)
    assert response.result_type == "clarification"
    assert response.tool_result.status == ("error" if state == "ERROR" else "clarification")
    assert "12/12" in response.answer
    assert len(response.answer.splitlines()) > len(response.products) + 1
    assert len(catalog.product_calls) + len(catalog.ingredient_calls) == 24


@pytest.mark.anyio
@pytest.mark.parametrize("count", [0, 1, 6, 22])
async def test_all_uncertain_remains_bounded_without_becoming_an_empty_search(count):
    catalog = uncertain_prefix(count, matches=0)
    response = await beauty.execute_beauty(search_request(), search_plan(), catalog)
    assert len(catalog.product_calls) == min(count, 21)
    assert len(response.products) == min(count, 6)
    assert all(r.verdict == "UNKNOWN" for r in response.ingredient_results)
    assert response.result_type == ("clarification" if count else "empty")
    assert f"{min(count, 21)}/{count}" in response.answer


@pytest.mark.anyio
async def test_retained_late_verified_candidate_has_consistent_session_ordinal_and_retry():
    catalog = uncertain_prefix(6)
    llm = PlanLlm(**search_plan().model_dump(by_alias=True, exclude_none=True))
    redis = RedisDouble()
    repo = ChatSessionRepository(redis)
    service = ChatService(None, llm, catalog, sessions=repo)
    response = await service.answer(search_request(), "guest:verified-retention")
    target = next(
        p.id
        for p, r in zip(response.products, response.ingredient_results, strict=True)
        if r.verdict == "MATCH"
    )
    saved = await repo.load("guest:verified-retention", response.chat_context.session)
    assert saved.context.candidate_ids == [p.id for p in response.products]
    llm.plan = {
        "intent": "price",
        "scope": "previous",
        "ordinal": saved.context.candidate_ids.index(target) + 1,
    }
    request = search_request(response.chat_context).model_copy(update={"request_id": uuid4()})
    price = await service.answer(request, "guest:verified-retention")
    assert price.chat_context.selected_product_id == target and "15,000" in price.answer
    calls, writes = llm.calls, redis.writes
    retry = await service.answer(request, "guest:verified-retention")
    assert retry.model_dump(mode="json") == price.model_dump(mode="json")
    assert (llm.calls, redis.writes) == (calls, writes)


@pytest.mark.anyio
@pytest.mark.parametrize("locale", ["ko", "en", "ja", "zh"])
async def test_hidden_uncertainty_counts_are_public_in_each_locale(locale):
    catalog = uncertain_prefix(6, matches=6)
    response = await beauty.execute_beauty(search_request(locale=locale), search_plan(), catalog)
    assert re.findall(r"\d+", response.answer.splitlines()[-2])[:4] == ["6", "0", "6", "0"]
    assert "toolResult" not in response.model_dump(by_alias=True)
    assert response.result_type == "clarification"


@pytest.mark.anyio
@pytest.mark.parametrize("marker", ["Component-A", "Component-B"])
async def test_changed_ids_names_and_api_order_do_not_change_retention(marker):
    catalog = uncertain_prefix(9, marker=marker, reverse=True)
    mapping = {
        p.id: f"candidate-{i:02d}-{uuid5(NAMESPACE_URL, marker + p.id).hex[:8]}"
        for i, p in enumerate(sorted(catalog.products, key=lambda p: p.id))
    }
    catalog.ingredients = {mapping[pid]: names for pid, names in catalog.ingredients.items()}
    catalog.states = {mapping[pid]: state for pid, state in catalog.states.items()}
    expected = mapping["item-009"]
    for p in catalog.products:
        p.id = mapping[p.id]
        p.name = str(uuid5(NAMESPACE_URL, p.id))
        p.shades[0].id = p.id + "-option"
    response = await beauty.execute_beauty(
        search_request(marker=marker), search_plan(marker), catalog
    )
    assert [r.product_id for r in response.ingredient_results if r.verdict == "MATCH"] == [expected]
    assert len(response.products) == 6 and len(catalog.product_calls) == 10

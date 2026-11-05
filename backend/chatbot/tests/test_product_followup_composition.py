"""Search evidence, named references and reset must compose across session turns."""

from uuid import uuid4

import pytest

from app.repositories.chat_session_repository import ChatSessionRepository
from app.services.chat_service import ChatService
from tests.test_beauty_consultation import PlanLlm
from tests.test_chat_sessions import RedisDouble
from tests.test_ingredient_search_coverage import fixed_clock as fixed_clock
from tests.test_ingredient_search_coverage import search_plan, search_request
from tests.test_ingredient_verified_candidates import uncertain_prefix
from tests.test_search_filter_reset import CLEAR_ALL


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.mark.anyio
@pytest.mark.parametrize("prefix", [6, 9])
@pytest.mark.parametrize("reverse", [False, True])
@pytest.mark.parametrize("marker", ["Component-A", "판테놀"])
@pytest.mark.parametrize("new_ingredient", [False, True])
async def test_late_verified_named_reference_then_full_reset(
    prefix, reverse, marker, new_ingredient
):
    catalog = uncertain_prefix(prefix, marker=marker, reverse=reverse)
    target = next(p for p in catalog.products if p.id == f"item-{prefix:03d}")
    target.name = target.name_ko = f"Unique Target {marker}"
    catalog.ingredients[target.id].append("Panthenol-New")
    initial_plan = search_plan(marker).model_dump(by_alias=True, exclude_none=True)
    initial_plan["query"] = "Catalog Brand"
    llm = PlanLlm(**initial_plan)
    redis = RedisDouble()
    service = ChatService(None, llm, catalog, sessions=ChatSessionRepository(redis))
    owner = "guest:composition"
    first = await service.answer(search_request(marker=marker), owner)
    assert len(first.products) == 6
    assert [r.product_id for r in first.ingredient_results if r.verdict == "MATCH"] == [target.id]

    llm.plan = {"intent": "price", "scope": "previous", "ordinal": 1}
    selected = await service.answer(search_request(first.chat_context), owner)
    assert selected.chat_context.selected_product_id != target.id

    llm.plan = {"intent": "price", "scope": "previous", "query": target.name}
    named = await service.answer(search_request(selected.chat_context), owner)
    assert [p.id for p in named.products] == [target.id]
    assert "15,000" in named.answer
    assert named.chat_context.filters.query == "Catalog Brand"
    assert named.chat_context.filters.ingredient_conditions[0].ingredient_name == marker
    assert named.chat_context.candidate_ids == first.chat_context.candidate_ids

    llm.plan = {
        "intent": "search",
        "scope": "catalog",
        "category": "lip",
        "maxPriceKRW": 20000 if new_ingredient else 1000,
        "clearFilters": CLEAR_ALL,
    }
    if new_ingredient:
        llm.plan.update(ingredientName="Panthenol-New", ingredientLookup=True, shadeName="03")
    request = search_request(named.chat_context).model_copy(
        update={"message": "03 Panthenol-New lip", "request_id": uuid4()}
    )
    reset = await service.answer(request, owner)
    assert reset.chat_context.filters.category == "lip"
    assert reset.chat_context.filters.query == ""
    assert reset.chat_context.selected_product_id is None
    conditions = reset.chat_context.filters.ingredient_conditions
    if new_ingredient:
        assert [c.ingredient_name for c in conditions] == ["Panthenol-New"]
        assert [r.product_id for r in reset.ingredient_results if r.verdict == "MATCH"] == [
            target.id
        ]
    else:
        assert not conditions and reset.result_type == "empty" and not reset.products
    calls, writes = llm.calls, redis.writes
    retry = await service.answer(request, owner)
    assert retry.model_dump(mode="json") == reset.model_dump(mode="json")
    assert (llm.calls, redis.writes) == (calls, writes)

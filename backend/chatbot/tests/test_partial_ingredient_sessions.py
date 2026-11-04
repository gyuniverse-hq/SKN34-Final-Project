"""Partial evidence must commit one consistent, retryable result set."""

import asyncio
from uuid import uuid4

import pytest

from app.core.errors import ApiError
from app.repositories.chat_session_repository import ChatSessionRepository
from app.schemas.chat import ChatResponse
from app.schemas.supervisor import ScreenContext
from app.services import beauty_consultation_service as beauty
from app.services.chat_service import ChatService
from tests.test_beauty_consultation import PlanLlm
from tests.test_chat_sessions import RedisDouble
from tests.test_ingredient_search_coverage import SearchCatalog, search_plan, search_request


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.fixture
def redis_client():
    return RedisDouble()


async def mixed_setup(client, *, count=7, good="MATCH"):
    owner = "guest:partial-" + uuid4().hex
    catalog = SearchCatalog(count, matches=[count - 1])
    catalog.states["item-001"] = "ERROR"
    if good == "UNKNOWN":
        catalog.states[f"item-{count - 1:03d}"] = "UNKNOWN"
    llm = PlanLlm(intent="search", scope="catalog", category="lip")
    repo = ChatSessionRepository(client)
    service = ChatService(None, llm, catalog, sessions=repo)
    first = await service.answer(search_request(), owner)
    llm.plan = search_plan().model_dump(by_alias=True, exclude_none=True) | {"intent": "refine"}
    req = search_request(first.chat_context)
    return owner, catalog, llm, repo, service, first, req


@pytest.mark.anyio
@pytest.mark.parametrize("count", [6, 7])
@pytest.mark.parametrize("good", ["MATCH", "UNKNOWN"])
async def test_partial_error_stores_displayed_order_and_caches_retry(redis_client, count, good):
    owner, catalog, llm, repo, service, first, req = await mixed_setup(
        redis_client, count=count, good=good
    )
    result = await service.answer(req, owner)
    assert result.tool_result.status == "error" and result.session_status == "stored"
    ids = [p.id for p in result.products]
    saved = await repo.load(owner, result.chat_context.session)
    assert saved.context.candidate_ids == saved.context.scope_ids == ids
    assert saved.context.filters == result.chat_context.filters
    assert saved.context.shade_selections == result.chat_context.shade_selections
    assert saved.state_version == 2 and saved.last_request_id == req.request_id
    calls = llm.calls
    catalog.states.clear()
    catalog.ingredients["item-001"] = ["Niacinamide"]
    retry = await service.answer(req, owner)
    assert retry.model_dump(mode="json") == result.model_dump(mode="json")
    assert llm.calls == calls
    llm.plan = {"intent": "price", "scope": "previous", "ordinal": 1}
    follow = await service.answer(search_request(result.chat_context), owner)
    assert [p.id for p in follow.products] == ids[:1]


@pytest.mark.anyio
async def test_initial_mixed_error_is_referenceable(redis_client):
    catalog = SearchCatalog(7, matches=[6])
    catalog.states["item-001"] = "ERROR"
    llm = PlanLlm(**search_plan().model_dump(by_alias=True, exclude_none=True))
    service = ChatService(None, llm, catalog, sessions=ChatSessionRepository(redis_client))
    owner = "guest:initial-" + uuid4().hex
    first = await service.answer(search_request(), owner)
    assert first.session_status == "stored" and first.chat_context.session is not None
    llm.plan = {"intent": "price", "scope": "previous", "ordinal": 1}
    follow = await service.answer(search_request(first.chat_context), owner)
    assert follow.products[0].id == first.products[0].id


@pytest.mark.anyio
async def test_all_error_new_result_preserves_old_state_without_reusing_its_reference(redis_client):
    owner, catalog, llm, repo, service, first, req = await mixed_setup(redis_client)
    catalog.states = {p.id: "ERROR" for p in catalog.products}
    failed = await service.answer(req, owner)
    assert failed.tool_result.status == "error"
    assert failed.chat_context.session is None and failed.session_status == "unavailable"
    ChatResponse.model_validate(failed.model_dump(mode="json"))
    saved = await repo.load(owner, first.chat_context.session)
    assert saved.state_version == 1 and saved.context == first.chat_context.model_copy(
        update={"session": None}
    )
    llm.plan = {"intent": "price", "scope": "previous", "ordinal": 1}
    with pytest.raises(ApiError) as exc:
        await service.answer(search_request(failed.chat_context), owner)
    assert exc.value.code == "chat_session_required"


@pytest.mark.anyio
async def test_same_uuid_partial_error_concurrent_commit_is_identical(redis_client):
    owner, _, _, repo, service, _, req = await mixed_setup(redis_client)
    a, b = await asyncio.gather(service.answer(req, owner), service.answer(req, owner))
    assert a.session_status == b.session_status == "stored"
    assert a.model_dump(mode="json") == b.model_dump(mode="json")
    saved = await repo.load(owner, a.chat_context.session)
    assert saved.state_version == 2


@pytest.mark.anyio
@pytest.mark.parametrize("changed", ["UNKNOWN", "ERROR", "NOT_MATCH", "MATCH"])
@pytest.mark.parametrize("middle_price", [False, True])
async def test_lowest_rechecks_current_ingredient_eligibility(redis_client, changed, middle_price):
    catalog = SearchCatalog(2, matches=[0, 1])
    catalog.products[0].price_krw = 1000
    catalog.products[1].price_krw = 20000
    llm = PlanLlm(**search_plan().model_dump(by_alias=True, exclude_none=True))
    repo = ChatSessionRepository(redis_client)
    service = ChatService(None, llm, catalog, sessions=repo)
    owner = "guest:lowest-" + uuid4().hex
    first = await service.answer(search_request(), owner)
    context = first.chat_context
    if middle_price:
        llm.plan = {"intent": "price", "scope": "previous", "ordinal": 1}
        context = (await service.answer(search_request(context), owner)).chat_context
    if changed in {"UNKNOWN", "ERROR"}:
        catalog.states["item-000"] = changed
    elif changed == "NOT_MATCH":
        catalog.ingredients["item-000"] = ["Water"]
    before = len(catalog.ingredient_calls)
    llm.plan = {"intent": "detail", "scope": "previous", "selection": "lowest_price"}
    result = await service.answer(search_request(context), owner)
    assert len(catalog.ingredient_calls) > before
    assert result.chat_context.filters.ingredient_conditions
    if changed in {"UNKNOWN", "ERROR"}:
        assert result.result_type == "clarification" and "1,000" not in result.answer
    else:
        expected = "item-001" if changed == "NOT_MATCH" else "item-000"
        assert [p.id for p in result.products] == [expected]
        assert result.result_type == "product_detail"
        assert all(r.verified and r.verdict == "MATCH" for r in result.ingredient_results)


@pytest.mark.anyio
@pytest.mark.parametrize("state", ["no_matches", "missing_shade", "tie", "unpriced"])
async def test_ingredient_lowest_edge_cases(redis_client, state):
    catalog = SearchCatalog(2, matches=[0, 1])
    llm = PlanLlm(**search_plan().model_dump(by_alias=True, exclude_none=True))
    service = ChatService(None, llm, catalog, sessions=ChatSessionRepository(redis_client))
    owner = "guest:lowest-edge-" + uuid4().hex
    first = await service.answer(search_request(), owner)
    if state == "no_matches":
        catalog.ingredients = {p.id: ["Water"] for p in catalog.products}
    elif state == "missing_shade":
        first.chat_context.shade_selections.clear()
        # A new condition search without a supplied shade produces unresolved evidence.
        llm.plan = {
            "intent": "search",
            "scope": "catalog",
            "category": "lip",
            "ingredientName": "Niacinamide",
        }
        first = await service.answer(search_request(first.chat_context), owner)
    elif state == "unpriced":
        for p in catalog.products:
            p.price_krw = 0
    llm.plan = {"intent": "detail", "scope": "previous", "selection": "lowest_price"}
    result = await service.answer(search_request(first.chat_context), owner)
    if state in {"no_matches", "unpriced"}:
        assert result.result_type == "empty" and not result.products
    elif state == "missing_shade":
        assert result.result_type == "clarification"
    else:
        assert [p.id for p in result.products] == ["item-000", "item-001"]
        assert result.chat_context.selected_product_id is None


@pytest.mark.anyio
async def test_initial_all_error_is_not_committed(redis_client):
    catalog = SearchCatalog(2)
    catalog.states = {p.id: "ERROR" for p in catalog.products}
    llm = PlanLlm(**search_plan().model_dump(by_alias=True, exclude_none=True))
    service = ChatService(None, llm, catalog, sessions=ChatSessionRepository(redis_client))
    owner = "guest:all-error-" + uuid4().hex
    result = await service.answer(search_request(), owner)
    assert result.tool_result.status == "error" and result.session_status == "unavailable"
    assert result.chat_context.session is None
    assert all(r.verdict == "ERROR" for r in result.ingredient_results)


@pytest.mark.anyio
async def test_partial_error_different_requests_have_one_winner(redis_client):
    owner, _, _, repo, service, _, req = await mixed_setup(redis_client)
    other = req.model_copy(update={"request_id": uuid4()})
    results = await asyncio.gather(
        service.answer(req, owner), service.answer(other, owner), return_exceptions=True
    )
    winner = next(r for r in results if not isinstance(r, Exception))
    loser = next(r for r in results if isinstance(r, Exception))
    assert isinstance(loser, ApiError) and loser.status == 409
    assert (await repo.load(owner, winner.chat_context.session)).state_version == 2


@pytest.mark.anyio
async def test_lowest_ignores_outside_screen_product(redis_client):
    catalog = SearchCatalog(3, matches=[0, 1, 2])
    catalog.products[2].category = "base"
    llm = PlanLlm(**search_plan().model_dump(by_alias=True, exclude_none=True))
    service = ChatService(None, llm, catalog, sessions=ChatSessionRepository(redis_client))
    owner = "guest:screen-lowest-" + uuid4().hex
    first = await service.answer(search_request(), owner)
    llm.plan = {"intent": "detail", "scope": "previous", "selection": "lowest_price"}
    req = search_request(first.chat_context).model_copy(
        update={"screen_context": ScreenContext(product_id="item-002", shade_id="item-002-shade")}
    )
    before = len(catalog.ingredient_calls)
    result = await service.answer(req, owner)
    assert {p.id for p in result.products} == {"item-000", "item-001"}
    assert all(pid != "item-002" for pid, _ in catalog.ingredient_calls[before:])


@pytest.mark.anyio
async def test_lowest_uses_prices_after_evidence_recheck(redis_client):
    class RepricedCatalog(SearchCatalog):
        reprice = False

        async def search_products(self, **kwargs):
            return [p.model_copy(deep=True) for p in await super().search_products(**kwargs)]

        async def get_product(self, pid):
            if self.reprice and pid == "item-000":
                self.products[0].price_krw = 50000
            return await super().get_product(pid)

    catalog = RepricedCatalog(2, matches=[0, 1])
    catalog.products[0].price_krw, catalog.products[1].price_krw = 1000, 20000
    llm = PlanLlm(**search_plan().model_dump(by_alias=True, exclude_none=True))
    service = ChatService(None, llm, catalog, sessions=ChatSessionRepository(redis_client))
    owner = "guest:repriced-" + uuid4().hex
    first = await service.answer(search_request(), owner)
    catalog.reprice = True
    llm.plan = {"intent": "detail", "scope": "previous", "selection": "lowest_price"}
    result = await service.answer(search_request(first.chat_context), owner)
    assert [p.id for p in result.products] == ["item-001"] and "20,000" in result.answer


@pytest.mark.anyio
async def test_partial_ingredient_verification_cannot_claim_lowest(redis_client, monkeypatch):
    catalog = SearchCatalog(2, matches=[0, 1])
    llm = PlanLlm(**search_plan().model_dump(by_alias=True, exclude_none=True))
    service = ChatService(None, llm, catalog, sessions=ChatSessionRepository(redis_client))
    owner = "guest:timeout-lowest-" + uuid4().hex
    first = await service.answer(search_request(), owner)
    catalog.slow_product = "item-001"
    monkeypatch.setattr(beauty, "INGREDIENT_SEARCH_TIMEOUT_SECONDS", 0.01)
    llm.plan = {"intent": "detail", "scope": "previous", "selection": "lowest_price"}
    result = await service.answer(search_request(first.chat_context), owner)
    assert result.result_type == "clarification" and "15,000" not in result.answer

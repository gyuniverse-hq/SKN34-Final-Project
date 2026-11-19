"""Synthetic G4 contracts; no live model, Catalog or Redis."""

import json
from copy import deepcopy
from uuid import uuid4

import httpx
import pytest

from app.clients.catalog_client import CatalogClient
from app.core.config import get_settings
from app.core.errors import ApiError, UpstreamError
from app.repositories.chat_session_repository import ChatSessionRepository
from app.schemas.catalog import CatalogIngredients, OptionSearchRequest, OptionSearchResponse
from app.schemas.supervisor import ScreenContext
from app.services.chat_service import ChatService
from tests.test_chat_sessions import RedisDouble, SessionCatalog
from tests.test_g2_multiturn import G2Llm, request
from tests.test_ingredient_consultation import evidence


@pytest.fixture
def anyio_backend():
    return "asyncio"


class OptionLlm(G2Llm):
    search_arguments = {"category": "lip", "optionSearch": True, "maxPriceKRW": 10000}

    async def complete_with_tools(self, *args, **kwargs):
        result, elapsed = await super().complete_with_tools(*args, **kwargs)
        result["choices"][0]["message"]["tool_calls"][0]["function"]["arguments"] = json.dumps(
            self.search_arguments
        )
        return result, elapsed


class OptionCatalog(SessionCatalog):
    def __init__(self):
        super().__init__()
        self.calls = []
        self.fail = False

    async def search_options(self, req):
        self.calls.append(req)
        if self.fail:
            raise UpstreamError("synthetic outage")
        product = self.products[0].model_copy(update={"category": req.category or "lip"})
        item = {
            "productType": req.product_type,
            "productId": product.id,
            "shadeId": product.shades[0].id,
            "optionId": "synthetic-option",
            "sourceVersion": "synthetic-v1",
            "synthetic": True,
            "group": "REFERENCE_ONLY",
            "checks": [
                {
                    "condition": "identity",
                    "verdict": "MATCH",
                    "reason": "verified_option",
                    "sourceVersion": "synthetic-v1",
                },
                {"condition": "price", "verdict": "UNKNOWN", "reason": "current_price_unverified"},
            ],
        }
        return OptionSearchResponse.model_validate(
            {
                "effectiveRequest": req.model_dump(mode="json", by_alias=True),
                "checkedAt": "2026-11-17T00:00:00Z",
                "status": "PARTIAL",
                "items": [item],
                "products": [product.model_dump(by_alias=True)],
                "excludedCount": 0,
                "omittedCount": 0,
                "checkedScope": {
                    "candidateProducts": 1,
                    "candidateOptions": 1,
                    "checkedOptions": 1,
                    "unidentifiedOptions": 0,
                    "exhaustive": True,
                    "stoppedReason": "COMPLETE",
                    "errors": 0,
                },
            }
        )


@pytest.fixture
def setup(monkeypatch):
    monkeypatch.setattr(get_settings(), "g1_supervisor_enabled", True)
    redis = RedisDouble()
    repo = ChatSessionRepository(redis)
    return ChatService(None, OptionLlm(), OptionCatalog(), sessions=repo), redis, repo


@pytest.mark.anyio
async def test_model_tool_session_replay_and_authoritative_option_scope(setup):
    service, redis, repo = setup
    req = request(message="현재 만원 이하 립 옵션 찾아줘")
    first = await service.answer(req, "user:a")
    assert first.option_search.status == "PARTIAL"
    assert first.chat_context.filters.option_search
    assert first.chat_context.option_scope[0].option_id == "synthetic-option"
    assert all(c.verdict != "NOT_MATCH" for c in first.tool_result.conditions)
    with pytest.raises(ApiError) as conflict:
        await service.answer(req, "user:a")
    assert conflict.value.code == "chat_request_conflict"
    assert len(service._catalog.calls) == 1 and redis.writes == 1
    forged = first.chat_context.model_copy(deep=True)
    forged.option_scope[0].option_id = "foreign-option"
    service._llm.plan = {"intent": "refine", "scope": "previous", "maxPriceKRW": 9000}
    followup = request(forged, "그중 9천원 이하로")
    second = await service.answer(followup, "user:a")
    assert (await service.answer(followup, "user:a")).model_dump() == second.model_dump()
    assert service._catalog.calls[-1].option_scope[0].option_id == "synthetic-option"
    assert second.chat_context.session.state_version == 2
    assert second.chat_context.session.expires_at >= first.chat_context.session.expires_at
    stored = await repo.load("user:a", second.chat_context.session)
    assert stored.context.option_scope[0].option_id == "synthetic-option"


@pytest.mark.anyio
async def test_failure_does_not_commit_and_foreign_owner_cannot_search(setup):
    service, redis, _ = setup
    first = await service.answer(request(), "user:a")
    service._llm.plan = {"intent": "refine", "scope": "previous", "maxPriceKRW": 9000}
    service._catalog.fail = True
    with pytest.raises(ApiError):
        await service.answer(request(first.chat_context, "그중 9천원 이하"), "user:a")
    assert redis.writes == 1
    count = len(service._catalog.calls)
    with pytest.raises(ApiError):
        await service.answer(request(first.chat_context), "user:b")
    assert len(service._catalog.calls) == count


@pytest.mark.anyio
@pytest.mark.parametrize(
    "mutation",
    [
        "identity",
        "scope",
        "ingredient",
        "success",
        "current_price",
        "group",
        "request",
        "texture",
        "ingredient_resolution",
        "product_type",
    ],
)
async def test_catalog_http_boundary_rejects_forged_results(monkeypatch, mutation):
    catalog = OptionCatalog()
    req = OptionSearchRequest(category="lip", maxPriceKRW=10000)
    payload = (await catalog.search_options(req)).model_dump(mode="json", by_alias=True)
    item = payload["items"][0]
    if mutation == "product_type":
        req = OptionSearchRequest(category="base", maxPriceKRW=10000, productType="foundation")
        payload = (await catalog.search_options(req)).model_dump(mode="json", by_alias=True)
        payload["items"][0]["productType"] = "cushion"
    if mutation == "ingredient_resolution":
        payload["ingredientResolutions"] = [
            {
                "ingredientName": "unrequested name",
                "operator": "excludes",
                "status": "resolved",
                "canonicalName": "unrequested name",
            }
        ]
    if mutation == "request":
        payload["effectiveRequest"]["maxPriceKRW"] = 99999
    if mutation == "texture":
        req.texture = "matte"
        payload["effectiveRequest"] = req.model_dump(mode="json", by_alias=True)
        item["checks"].append(
            {"condition": "texture", "verdict": "MATCH", "reason": "catalog_texture"}
        )
    if mutation == "identity":
        item["checks"][0]["sourceVersion"] = "foreign-version"
    if mutation == "scope":
        item["shadeId"] = "foreign-shade"
    if mutation == "success":
        payload["status"] = "SUCCESS"
    if mutation == "current_price":
        item["checks"][-1]["verdict"] = "MATCH"
        item["group"] = "ELIGIBLE"
    if mutation == "group":
        item["group"] = "ELIGIBLE"
    original = httpx.AsyncClient
    observed = []

    def handler(request):
        observed.append(request)
        return httpx.Response(200, json=deepcopy(payload))

    monkeypatch.setattr(
        httpx, "AsyncClient", lambda **kw: original(transport=httpx.MockTransport(handler), **kw)
    )
    if mutation == "ingredient":
        req = OptionSearchRequest(
            category="lip",
            maxPriceKRW=10000,
            ingredient_conditions=[{"ingredient_name": "Water", "operator": "includes"}],
        )
    with pytest.raises(UpstreamError):
        await CatalogClient("http://catalog.test").search_options(req)
    assert observed[0].method == "POST" and observed[0].url.path == "/api/catalog/options/search"


@pytest.mark.anyio
@pytest.mark.parametrize("option_ref", ["synthetic-option", "different-option"])
async def test_catalog_accepts_only_texture_proof_bound_to_this_option(monkeypatch, option_ref):
    catalog = OptionCatalog()
    req = OptionSearchRequest(category="lip", maxPriceKRW=10000, texture="matte")
    payload = (await catalog.search_options(req)).model_dump(mode="json", by_alias=True)
    payload["products"][0]["texture"] = "matte"
    payload["items"][0]["checks"].append(
        {
            "condition": "texture",
            "verdict": "MATCH",
            "reason": "official_option_texture_reviewed",
            "textureBasis": "official_reviewed",
            "textureCode": "matte",
            "sourceRef": "https://example.test/official",
            "sourceVersion": "v1",
            "evidenceId": f"texture:{option_ref}:v1",
            "reviewRef": "fixture://review",
            "reviewedAt": "2026-11-17T00:00:00Z",
            "reviewStatus": "verified",
        }
    )
    original = httpx.AsyncClient
    monkeypatch.setattr(
        httpx,
        "AsyncClient",
        lambda **kw: original(
            transport=httpx.MockTransport(lambda _: httpx.Response(200, json=payload)), **kw
        ),
    )
    client = CatalogClient("http://catalog.test")
    if option_ref == "different-option":
        with pytest.raises(UpstreamError):
            await client.search_options(req)
    else:
        result = await client.search_options(req)
        assert result.items[0].checks[-1].verdict == "MATCH"


@pytest.mark.anyio
async def test_catalog_http_valid_result_has_no_raw_ingredient_text(monkeypatch):
    catalog = OptionCatalog()
    req = OptionSearchRequest(category="lip", maxPriceKRW=10000)
    payload = (await catalog.search_options(req)).model_dump(mode="json", by_alias=True)
    original = httpx.AsyncClient
    monkeypatch.setattr(
        httpx,
        "AsyncClient",
        lambda **kw: original(
            transport=httpx.MockTransport(lambda r: httpx.Response(200, json=payload)), **kw
        ),
    )
    result = await CatalogClient("http://catalog.test").search_options(req)
    assert result.items[0].group == "REFERENCE_ONLY"
    assert "ingredientsRaw" not in result.model_dump_json()


@pytest.mark.anyio
@pytest.mark.parametrize("missing_proof", [False, True])
async def test_presence_proof_is_retained_and_missing_proof_rejected(monkeypatch, missing_proof):
    req = OptionSearchRequest(
        category="lip",
        maxPriceKRW=10000,
        ingredient_conditions=[{"ingredient_name": "Panthenol", "operator": "includes"}],
    )
    payload = (await OptionCatalog().search_options(req)).model_dump(mode="json", by_alias=True)
    payload["items"][0]["checks"].append(
        {
            "condition": "ingredient",
            "ingredientName": "Panthenol",
            "operator": "includes",
            "verdict": "MATCH",
            "reason": "ingredient_present",
            "evidenceId": "synthetic-proof",
            "sourceVersion": "synthetic-v1",
            "sourceRef": "fixture://only",
            "observedAt": "2026-11-01T00:00:00Z",
            "reviewStatus": "verified",
            "ingredientCoverage": "partial",
            "normalizationStatus": "unverified",
        }
    )
    if missing_proof:
        payload["items"][0]["checks"][-1].pop("sourceRef")
    original = httpx.AsyncClient
    monkeypatch.setattr(
        httpx,
        "AsyncClient",
        lambda **kw: original(
            transport=httpx.MockTransport(lambda r: httpx.Response(200, json=payload)), **kw
        ),
    )
    client = CatalogClient("http://catalog.test")
    if missing_proof:
        with pytest.raises(UpstreamError):
            await client.search_options(req)
    else:
        result = await client.search_options(req)
        assert result.items[0].checks[-1].ingredient_coverage == "partial"
        assert result.items[0].checks[-1].observed_at is not None


@pytest.mark.anyio
@pytest.mark.parametrize("missing_limitation", [False, True])
async def test_recorded_price_with_unknown_timezone_contract(monkeypatch, missing_limitation):
    req = OptionSearchRequest(category="lip", maxPriceKRW=10000)
    payload = (await OptionCatalog().search_options(req)).model_dump(mode="json", by_alias=True)
    payload["status"] = "SUCCESS"
    item = payload["items"][0]
    item["group"] = "ELIGIBLE"
    item["checks"][-1].update(verdict="MATCH", reason="requested_price_basis")
    item["price"] = {
        "requestedBasis": "collected_snapshot",
        "observedBasis": "collected_snapshot",
        "amountKRW": 7600,
        "observedAtRaw": "2026-10-27T17:23:57",
        "checkedAt": "2026-11-17T00:00:00Z",
        "sourceRef": "fixture://price",
        "sourceVersion": "price-v1",
        "limitations": [] if missing_limitation else ["timezone_unknown"],
    }
    original = httpx.AsyncClient
    monkeypatch.setattr(
        httpx,
        "AsyncClient",
        lambda **kw: original(
            transport=httpx.MockTransport(lambda r: httpx.Response(200, json=payload)), **kw
        ),
    )
    if missing_limitation:
        with pytest.raises(UpstreamError):
            await CatalogClient("http://catalog.test").search_options(req)
    else:
        result = await CatalogClient("http://catalog.test").search_options(req)
        assert result.items[0].price.observed_at is None
        assert result.items[0].price.observed_at_raw.tzinfo is None


@pytest.mark.anyio
@pytest.mark.parametrize(
    "message,model_basis,expected",
    [
        ("지금 만원 이하 립 찾아줘", "current_offer", "catalog_reference"),
        ("올리브영에서 지금 만원 이하 립 찾아줘", "catalog_reference", "current_offer"),
        ("옵션 수집가 기준 만원 이하 립 찾아줘", None, "collected_snapshot"),
        ("앱 등록 가격 기준 만원 이하 립 찾아줘", None, "catalog_reference"),
    ],
)
async def test_price_basis_default_and_explicit_choice_are_stored(
    monkeypatch, message, model_basis, expected
):
    from app.schemas.supervisor import SearchPlan
    from app.services.beauty_consultation_service import execute_beauty

    monkeypatch.setattr(get_settings(), "g1_supervisor_enabled", True)
    catalog = OptionCatalog()
    response = await execute_beauty(
        request(message=message),
        SearchPlan(
            intent="search",
            category="lip",
            optionSearch=True,
            maxPriceKRW=10000,
            priceBasis=model_basis,
        ),
        catalog,
    )
    assert catalog.calls[-1].price_basis == expected
    assert response.chat_context.filters.price_basis == expected


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("follow_up", "expected_budget", "within_previous"),
    [
        ("그럼 같은 예산으로 색상을 골라볼 수 있는 립 추천해줘.", 20000, False),
        ("그중 같은 예산으로 색상을 골라볼 수 있는 립 추천해줘.", 20000, True),
        ("같은 예산 말고 1만 5천 원 미만으로 색상을 골라볼 수 있는 립 추천해줘.", 14999, False),
    ],
)
async def test_same_budget_survives_price_lookup_and_search_classification(
    setup, follow_up, expected_budget, within_previous
):
    service, _, repo = setup
    owner = "user:a"
    service._llm.search_arguments = {
        "category": "lip",
        "moisturizing": True,
        "priceBasis": "catalog_reference",
    }
    first = await service.answer(request(message="2만 원 이하 촉촉한 립 추천해줘."), owner)
    assert len(first.products) == 2
    assert not service._catalog.calls

    service._llm.plan = {
        "intent": "price",
        "scope": "previous",
        "ordinal": 2,
        "priceBasis": "collected_snapshot",
        "clearFilters": ["maxPriceKRW"],
    }
    price = await service.answer(request(first.chat_context, "두 번째 제품 가격이 얼마야?"), owner)
    assert [product.id for product in price.products] == [first.products[1].id]
    assert price.chat_context.session.result_set_id == first.chat_context.session.result_set_id

    service._llm.plan = {
        "intent": "search",
        "scope": "catalog",
        "category": "lip",
        "optionSearch": True,
        "maxPriceKRW": 30000,
    }
    response = await service.answer(request(price.chat_context, follow_up), owner)
    payload = service._catalog.calls[-1]
    assert payload.max_price_krw == expected_budget
    assert payload.price_basis == "catalog_reference"
    assert payload.product_ids == (first.chat_context.candidate_ids if within_previous else None)

    stored = await repo.load(owner, response.chat_context.session)
    for turn in (first, price):
        assert turn.chat_context.filters.max_price_krw == 20000
        assert "priceBasis" not in turn.model_dump(mode="json")["chatContext"]["filters"]
    assert (stored.context.filters.max_price_krw, stored.context.filters.price_basis) == (
        expected_budget,
        "catalog_reference",
    )


@pytest.mark.anyio
@pytest.mark.parametrize("with_session", [True, False])
async def test_same_budget_clarifies_without_a_saved_limit(setup, with_session):
    service, _, _ = setup
    service._llm.search_arguments = {"category": "lip"}
    context = None
    if with_session:
        first = await service.answer(request(message="립 추천해줘."), "user:a")
        context = first.chat_context
    service._llm.plan = {"intent": "refine", "optionSearch": True}
    response = await service.answer(
        request(
            context,
            "그럼 같은 예산으로 색상을 골라볼 수 있는 립 추천해줘.",
        ),
        "user:a",
    )
    assert response.result_type == "clarification"
    assert "얼마 이하" in response.answer
    assert not service._catalog.calls and not response.products


@pytest.mark.anyio
async def test_first_shopping_reply_describes_the_registered_price(setup):
    service, _, _ = setup
    service._llm.search_arguments = {"category": "lip", "moisturizing": True}
    response = await service.answer(request(message="2만 원 이하 촉촉한 립 추천해줘."), "user:a")
    assert response.option_search is None and response.products
    assert "가격은 앱 등록 가격을 기준으로 확인했어요." in response.answer


@pytest.mark.anyio
@pytest.mark.parametrize(
    "message,query,basis",
    [
        ("지금 2만 원 이하 무향료 립으로 골라줘.", None, "catalog_reference"),
        (
            "올리브영에서 지금 2만 원 이하로 살 수 있는 무향료 립 골라줘.",
            "올리브영",
            "current_offer",
        ),
    ],
)
async def test_session_budget_and_fragrance_search_uses_option_evidence(
    setup, message, query, basis
):
    from app.schemas.supervisor import SearchPlan
    from app.services.beauty_consultation_service import execute_beauty

    service, _, _ = setup
    catalog = service._catalog
    req = request(message=message).model_copy(update={"request_id": uuid4()})
    plan = SearchPlan(
        intent="search", category="lip", query=query, maxPriceKRW=20000, fragranceFree=True
    )
    result = await execute_beauty(req, plan, catalog, g1=True)
    assert result.option_search is not None
    assert catalog.calls[-1].price_basis == basis
    assert catalog.calls[-1].fragrance_free is True
    assert not catalog.calls[-1].query
    assert result.answer.startswith("확인한 후보 중 무향료로 확인된 제품은 없어요.")
    assert ("판매처의 현재 가격은 확인할 수 없어요." in result.answer) == (basis == "current_offer")


@pytest.mark.anyio
@pytest.mark.parametrize(
    "overrides",
    [
        {},
        {"sourceVersion": "stale"},
        {"reviewStatus": "unreviewed"},
        {"ingredientName": "판테놀"},
        {"evidenceId": None},
        {"verdict": "MATCH"},
    ],
)
async def test_fragrance_exclusion_http_contract_requires_option_proof(monkeypatch, overrides):
    req = OptionSearchRequest(category="lip", fragranceFree=True, maxPriceKRW=20000)
    payload = (await OptionCatalog().search_options(req)).model_dump(mode="json", by_alias=True)
    item = payload["items"][0]
    item["checks"].append(
        {
            "condition": "fragrance_free",
            "verdict": "NOT_MATCH",
            "reason": "ingredient_present",
            "ingredientName": "향료",
            "operator": "excludes",
            "evidenceId": "reviewed-fragrance",
            "sourceVersion": item["sourceVersion"],
            "sourceRef": "fixture://ingredients",
            "reviewStatus": "verified",
            "ingredientCoverage": "partial",
            "observedAt": "2026-11-17T00:00:00Z",
            **overrides,
        }
    )
    if overrides.get("verdict") != "MATCH":
        item["group"] = "EXCLUDED"
        payload.update(products=[], excludedCount=1)
    original = httpx.AsyncClient
    monkeypatch.setattr(
        httpx,
        "AsyncClient",
        lambda **kw: original(
            transport=httpx.MockTransport(lambda r: httpx.Response(200, json=payload)), **kw
        ),
    )
    if overrides:
        with pytest.raises(UpstreamError):
            await CatalogClient("http://catalog.test").search_options(req)
    else:
        result = await CatalogClient("http://catalog.test").search_options(req)
        assert result.items[0].group == "EXCLUDED"


@pytest.mark.anyio
async def test_fragrance_reply_explains_when_all_options_are_excluded(setup):
    from app.schemas.supervisor import SearchPlan
    from app.services.beauty_consultation_service import execute_beauty

    service, _, _ = setup
    catalog = service._catalog
    original_search = catalog.search_options

    async def search(req):
        payload = (await original_search(req)).model_dump(mode="json", by_alias=True)
        item = payload["items"][0]
        item.update(group="EXCLUDED")
        item["checks"].append(
            {"condition": "fragrance_free", "verdict": "NOT_MATCH", "reason": "ingredient_present"}
        )
        payload.update(products=[], excludedCount=1)
        return OptionSearchResponse.model_validate(payload)

    catalog.search_options = search
    result = await execute_beauty(
        request(message="지금 2만 원 이하 무향료 립으로 골라줘."),
        SearchPlan(intent="search", category="lip", maxPriceKRW=20000, fragranceFree=True),
        catalog,
        g1=True,
    )
    assert result.answer == (
        "확인한 후보 중 무향료로 확인된 제품은 없어요. 향료가 확인된 옵션은 제외했어요."
    )
    assert not result.products


@pytest.mark.anyio
@pytest.mark.parametrize(
    "enabled,locale", [(False, "ko"), (True, "en"), (True, "ja"), (True, "zh")]
)
async def test_off_and_non_korean_keep_existing_route(monkeypatch, enabled, locale):
    from app.schemas.chat import ChatRequest
    from app.schemas.supervisor import SearchPlan
    from app.services.beauty_consultation_service import execute_beauty

    monkeypatch.setattr(get_settings(), "g1_supervisor_enabled", enabled)
    catalog = OptionCatalog()
    response = await execute_beauty(
        ChatRequest(message="lip", locale=locale),
        SearchPlan(intent="search", category="lip", optionSearch=True),
        catalog,
    )
    assert response.option_search is None and not catalog.calls


@pytest.mark.anyio
async def test_detail_keeps_option_scope_and_never_uses_reference_price_as_current(setup):
    service, _, _ = setup
    initial = await service.answer(request(), "user:a")
    service._llm.plan = {"intent": "price", "scope": "previous", "ordinal": 1}
    detail = await service.answer(request(initial.chat_context, "첫 번째 가격은?"), "user:a")
    product = service._catalog.products[0]
    assert detail.answer == f"{product.name}의 앱 등록 가격은 {product.price_krw:,}원이에요."
    assert detail.chat_context.option_scope == initial.chat_context.option_scope
    assert detail.chat_context.session.result_set_id == initial.chat_context.session.result_set_id
    assert detail.chat_context.session.expires_at == initial.chat_context.session.expires_at
    assert all(
        c.verdict == "UNKNOWN"
        for c in detail.tool_result.conditions
        if c.condition == "maxPriceKRW"
    )
    service._llm.plan = {"intent": "detail", "scope": "previous", "selection": "lowest_price"}
    cheapest = await service.answer(request(detail.chat_context, "그중 가장 싼 옵션"), "user:a")
    assert cheapest.result_type == "clarification"
    assert cheapest.chat_context.option_scope == initial.chat_context.option_scope


@pytest.mark.anyio
@pytest.mark.parametrize(
    "verdict,reason,coverage,expected_text",
    [
        ("MATCH", "ingredient_present", "partial", "얼그레이 70%에는 판테놀 성분이 들어 있어요."),
        (
            "NOT_MATCH",
            "ingredient_absent",
            "full",
            "얼그레이 70%에는 판테놀 성분이 들어 있지 않아요.",
        ),
        ("UNKNOWN", "absence_not_verifiable", "partial", "성분표가 일부라서"),
    ],
)
async def test_selected_g4_shade_is_named_in_its_ingredient_answer(
    setup, monkeypatch, verdict, reason, coverage, expected_text
):
    service, _, _ = setup
    product = service._catalog.products[0]
    shade = product.shades[0].model_copy(update={"name": "얼그레이 70%"})
    product.shades = [shade.model_copy(update={"id": "a-other", "name": "로즈 30%"}), shade]
    original_search = service._catalog.search_options

    async def search_options(req):
        result = await original_search(req)
        if req.option_scope is None:
            excluded = result.items[0].model_dump(mode="json", by_alias=True)
            excluded.update(shadeId=shade.id, optionId="excluded-option", group="EXCLUDED")
            excluded["checks"][1].update(verdict="NOT_MATCH", reason="requested_price_basis")
            result = OptionSearchResponse.model_validate(
                result.model_dump(mode="json", by_alias=True)
                | {
                    "items": [result.items[0].model_dump(mode="json", by_alias=True), excluded],
                    "excludedCount": 1,
                    "checkedScope": result.checked_scope.model_dump(mode="json", by_alias=True)
                    | {
                        "candidateOptions": 2,
                        "checkedOptions": 2,
                    },
                }
            )
        return result

    monkeypatch.setattr(service._catalog, "search_options", search_options)

    async def get_ingredients(pid, sid, *, ingredient_name, operator):
        assert (pid, sid, ingredient_name, operator) == (product.id, shade.id, "판테놀", "includes")
        return CatalogIngredients.model_validate(
            evidence(
                pid=pid,
                shade=sid,
                name=ingredient_name,
                operator=operator,
                optionId="excluded-option",
                synthetic=False,
                verdict=verdict,
                reason=reason,
                ingredientCoverage=coverage,
                normalizationStatus="verified" if coverage == "full" else "unverified",
            )
        )

    monkeypatch.setattr(service._catalog, "get_ingredients", get_ingredients)
    initial = await service.answer(request(), "user:a")
    service._llm.plan = {"intent": "detail", "ingredientLookup": True, "ingredientName": "판테놀"}
    followup = request(initial.chat_context, "이 색에도 판테놀 들어 있어?")
    followup.screen_context = ScreenContext(screenId="chat", productId=product.id, shadeId=shade.id)
    detail = await service.answer(followup, "user:a")

    assert detail.chat_context.shade_selections[product.id] == shade.id
    result = detail.ingredient_results[0]
    assert (result.product_id, result.shade_id, result.option_id, result.verdict) == (
        product.id,
        shade.id,
        "excluded-option",
        verdict,
    )
    assert result.shade_name == "얼그레이 70%"
    assert detail.model_dump(by_alias=True)["ingredientResults"][0]["shadeName"] == shade.name
    if verdict == "UNKNOWN":
        assert detail.answer.splitlines()[0].endswith(" · 얼그레이 70%")
    assert detail.answer.count(expected_text) == 1
    assert "로즈 30%" not in detail.answer
    assert "성분 부재를 확정" not in detail.answer
    assert detail.chat_context.option_scope == initial.chat_context.option_scope
    assert all(option.shade_id != shade.id for option in detail.chat_context.option_scope)

    service._llm.plan = {"intent": "refine", "optionSearch": True, "maxPriceKRW": 20000}
    await service.answer(request(detail.chat_context, "그중 2만 원 이하로 찾아줘."), "user:a")
    assert service._catalog.calls[-1].option_scope == initial.chat_context.option_scope


@pytest.mark.anyio
async def test_five_step_condition_changes_keep_other_constraints_and_session(setup):
    service, _, repo = setup
    response = await service.answer(request(), "user:a")
    fragrance = {"ingredientName": "Fragrance", "operator": "excludes"}
    panthenol = {"ingredientName": "Panthenol", "operator": "includes"}
    water = {"ingredientName": "Water", "operator": "includes"}
    steps = [
        (
            {"texture": "matte", "ingredientConditions": [fragrance, panthenol]},
            "매트 립 중 향료 제외 판테놀 포함",
            [fragrance, panthenol],
        ),
        (
            {"clearFilters": ["ingredientConditions"], "ingredientConditions": [fragrance]},
            "판테놀 조건만 빼줘",
            [fragrance],
        ),
        ({"ingredientConditions": [water]}, "Water 포함 추가", [fragrance, water]),
        (
            {"ingredientConditions": [{**fragrance, "operator": "includes"}]},
            "향료는 포함으로 바꿔줘",
            [{**fragrance, "operator": "includes"}, water],
        ),
        (
            {"maxPriceKRW": 5000},
            "가격만 5천원 이하로",
            [{**fragrance, "operator": "includes"}, water],
        ),
        (
            {"priceBasis": "catalog_reference"},
            "가격 기준만 참고가로",
            [{**fragrance, "operator": "includes"}, water],
        ),
    ]
    for change, message, expected in steps:
        service._llm.plan = {"intent": "refine", "scope": "previous", **change}
        response = await service.answer(request(response.chat_context, message), "user:a")
        payload = service._catalog.calls[-1]
        assert [c.model_dump(by_alias=True) for c in payload.ingredient_conditions] == expected
        assert payload.texture == "matte"
        assert response.option_search.effective_request == payload
    assert payload.max_price_krw == 5000 and payload.price_basis == "catalog_reference"
    state = await repo.load("user:a", response.chat_context.session)
    assert (
        OptionSearchResponse.model_validate(state.last_response["optionSearch"]).effective_request
        == payload
    )


@pytest.mark.anyio
@pytest.mark.parametrize(
    "message,expected",
    [
        ("3만원 이하 립 옵션 찾아줘", 30000),
        ("3만원 미만 립 옵션 찾아줘", 29999),
        ("1만 5천 원 이하 립 옵션 찾아줘", 15000),
        ("1만5천원 이하 립 옵션 찾아줘", 15000),
        ("1만 5천 원 미만 립 옵션 찾아줘", 14999),
        ("15,000원 이하 립 옵션 찾아줘", 15000),
    ],
)
async def test_explicit_price_boundary_overrides_bad_model_number(setup, message, expected):
    service, _, _ = setup
    result = await service.answer(request(message=message), "user:a")
    assert result.option_search.effective_request.max_price_krw == expected
    assert result.chat_context.filters.max_price_krw == expected


@pytest.mark.anyio
async def test_live_fragrance_flag_failure_and_scope_regression(setup):
    service, _, _ = setup
    first = await service.answer(request(), "user:a")
    service._llm.plan = {
        "intent": "refine",
        "scope": "previous",
        "fragranceFree": True,
        "ingredientConditions": [{"ingredientName": "판테놀", "operator": "includes"}],
    }
    second = await service.answer(request(first.chat_context, "향료 제외, 판테놀 포함"), "user:a")
    payload = service._catalog.calls[-1]
    assert not payload.fragrance_free
    assert {(c.ingredient_name, c.operator) for c in payload.ingredient_conditions} == {
        ("향료", "excludes"),
        ("판테놀", "includes"),
    }
    assert payload.product_ids is None and payload.option_scope is None
    service._llm.plan = {
        "intent": "refine",
        "scope": "previous",
        "ingredientConditions": [{"ingredientName": "향료", "operator": "includes"}],
    }
    third = await service.answer(
        request(second.chat_context, "향료는 제외가 아니라 포함으로 바꿔줘"), "user:a"
    )
    assert {
        (c.ingredient_name, c.operator) for c in third.chat_context.filters.ingredient_conditions
    } == {("향료", "includes"), ("판테놀", "includes")}
    service._llm.plan = {"intent": "refine", "scope": "catalog", "maxPriceKRW": 20000}
    fourth = await service.answer(request(third.chat_context, "그중 2만원 이하로"), "user:a")
    assert service._catalog.calls[-1].option_scope == third.chat_context.option_scope
    assert "앞서 보여드린 후보 안에서" in fourth.answer


@pytest.mark.anyio
async def test_broad_fragrance_conflict_asks_then_explicit_replacement_clears(setup):
    service, _, _ = setup
    first = await service.answer(request(), "user:a")
    service._llm.plan = {"intent": "refine", "fragranceFree": True}
    broad = await service.answer(request(first.chat_context, "무향료 조건 추가"), "user:a")
    calls = len(service._catalog.calls)
    service._llm.plan = {
        "intent": "refine",
        "ingredientConditions": [{"ingredientName": "향료", "operator": "includes"}],
    }
    ambiguous = await service.answer(request(broad.chat_context, "향료 포함 추가"), "user:a")
    assert len(service._catalog.calls) == calls
    assert "해제할까요" in ambiguous.answer
    assert ambiguous.chat_context.filters.fragrance_free
    explicit = await service.answer(
        request(ambiguous.chat_context, "향료는 제외가 아니라 포함으로 바꿔줘"), "user:a"
    )
    assert not explicit.chat_context.filters.fragrance_free


def test_bounded_price_guard_does_not_guess_complex_prices():
    from app.services.beauty_consultation_service import _explicit_krw_budget

    for message in [
        "1만 15천 원 이하",
        "3.5만원 이하",
        "1만원 또는 2만원 이하",
        "2억원 이하",
        "100000001원 이하",
    ]:
        assert _explicit_krw_budget(message) is None


@pytest.mark.anyio
async def test_partial_result_does_not_permanently_restrict_condition_changes(setup):
    service, _, repo = setup
    original = service._catalog.search_options

    async def partial(req):
        result = await original(req)
        result.checked_scope.candidate_options = 5
        result.checked_scope.exhaustive = False
        result.checked_scope.stopped_reason = "WORK_LIMIT"
        return result

    service._catalog.search_options = partial
    first = await service.answer(request(), "user:a")
    assert not first.option_search.checked_scope.exhaustive
    assert "일부 후보만 확인했어요" in first.answer
    assert "5개 중" not in first.answer
    service._catalog.search_options = original
    service._llm.plan = {"intent": "refine", "scope": "previous", "maxPriceKRW": 20000}
    wider = await service.answer(
        request(first.chat_context, "가격만 2만원 이하로 바꿔줘"), "user:a"
    )
    assert service._catalog.calls[-1].product_ids is None
    assert service._catalog.calls[-1].option_scope is None
    stored = await repo.load("user:a", wider.chat_context.session)
    assert (
        OptionSearchResponse.model_validate(
            stored.last_response["optionSearch"]
        ).effective_request.option_scope
        is None
    )
    within = await service.answer(request(wider.chat_context, "그중 1만원 이하로"), "user:a")
    assert service._catalog.calls[-1].option_scope == wider.chat_context.option_scope
    assert within.option_search.checked_scope.exhaustive
    assert "앞서 보여드린 후보 안에서" in within.answer


@pytest.mark.parametrize(
    "message", ["향료 포함하지 마", "향료 제외하지 말아줘", "향료 포함 조건 빼줘"]
)
def test_named_fragrance_guard_does_not_reverse_negation_or_removal(message):
    from app.schemas.supervisor import SearchPlan
    from app.services.beauty_consultation_service import _normalize_option_plan

    plan = SearchPlan(intent="refine", optionSearch=True)
    result = _normalize_option_plan(request(message=message), plan)
    assert result.ingredient_conditions == []
    assert result.fragrance_free is None


@pytest.mark.anyio
async def test_ingredient_name_confirmation_preserves_previous_search(setup):
    service, redis, _ = setup
    first = await service.answer(request(), "user:a")
    assert first.products

    async def requires_confirmation(req):
        return OptionSearchResponse.model_validate(
            {
                "effectiveRequest": req.model_dump(by_alias=True),
                "checkedAt": "2026-11-17T00:00:00Z",
                "status": "PARTIAL",
                "excludedCount": 0,
                "omittedCount": 0,
                "ingredientResolutions": [
                    {
                        "ingredientName": "미네랄오잉",
                        "operator": "excludes",
                        "status": "unresolved",
                        "suggestions": ["미네랄오일"],
                    }
                ],
                "checkedScope": {
                    "candidateProducts": 0,
                    "candidateOptions": 0,
                    "checkedOptions": 0,
                    "unidentifiedOptions": 0,
                    "exhaustive": False,
                    "stoppedReason": "INGREDIENT_CONFIRMATION",
                    "errors": 0,
                },
            }
        )

    service._catalog.search_options = requires_confirmation
    service._llm.plan = {
        "intent": "refine",
        "ingredientConditions": [
            {"ingredientName": "미네랄오잉", "operator": "excludes"},
        ],
    }
    follow = await service.answer(request(first.chat_context, "미네랄오잉 성분 제외해줘"), "user:a")
    assert follow.result_type == "clarification" and not follow.products
    assert "미네랄오일" in follow.answer and "확인하지 못했어요" in follow.answer
    assert follow.chat_context.session == first.chat_context.session
    assert follow.chat_context.filters == first.chat_context.filters
    assert redis.writes == 1


def test_g4_preserves_literal_hangul_spacing_without_rewriting_chemical_names():
    from app.schemas.supervisor import SearchPlan
    from app.services.beauty_consultation_service import _normalize_option_plan

    plan = SearchPlan.model_validate(
        {
            "intent": "search",
            "optionSearch": True,
            "ingredientConditions": [{"ingredientName": "판테놀", "operator": "includes"}],
        }
    )
    result = _normalize_option_plan(request(message="판 테놀 성분이 들어간 립 찾아줘"), plan)
    assert result.ingredient_conditions[0].ingredient_name == "판 테놀"
    different = _normalize_option_plan(
        request(message="‘덱스판테놀’ 성분이 들어간 립 찾아줘"), plan
    )
    assert different.ingredient_conditions[0].ingredient_name == "덱스판테놀"


def test_model_correction_cannot_replace_explicit_ingredient_or_limit_product_names():
    from app.schemas.supervisor import SearchPlan
    from app.services.beauty_consultation_service import _normalize_option_plan

    plan = SearchPlan.model_validate(
        {
            "intent": "search",
            "optionSearch": True,
            "category": "lip",
            "query": "미네랄오일",
            "ingredientConditions": [{"ingredientName": "미네랄오일", "operator": "excludes"}],
        }
    )
    result = _normalize_option_plan(
        request(message="미네랄오잉 성분을 제외한 립밤 옵션을 찾아줘."), plan
    )
    assert result.ingredient_conditions[0].ingredient_name == "미네랄오잉"
    assert result.query is None
    plan.query = "퓌"
    named = _normalize_option_plan(request(message="퓌 제품에서 해당 성분을 제외해줘"), plan)
    assert named.query == "퓌"
    assert named.ingredient_conditions[0].ingredient_name == "미네랄오일"


@pytest.mark.anyio
async def test_product_type_is_preserved_switched_cleared_and_scoped(setup):
    service, _, repo = setup
    first = await service.answer(request(message="파운데이션 옵션을 찾아줘"), "user:a")
    assert first.chat_context.filters.product_type == "foundation"

    service._llm.plan = {"intent": "search", "maxPriceKRW": 20000}
    price = await service.answer(
        request(first.chat_context, "가격만 2만원 이하로 바꿔줘"), "user:a"
    )
    payload = service._catalog.calls[-1]
    assert (payload.product_type, payload.max_price_krw, payload.product_ids) == (
        "foundation",
        20000,
        None,
    )

    service._llm.plan = {"intent": "refine", "maxPriceKRW": 19000}
    prior = await service.answer(request(price.chat_context, "그중 19000원 이하로"), "user:a")
    payload = service._catalog.calls[-1]
    assert payload.product_type == "foundation"
    assert payload.option_scope == price.chat_context.option_scope

    service._llm.plan = {"intent": "refine"}
    switched = await service.answer(request(prior.chat_context, "쿠션으로 바꿔줘"), "user:a")
    payload = service._catalog.calls[-1]
    assert (payload.category, payload.product_type, payload.max_price_krw) == (
        "base",
        "cushion",
        19000,
    )
    assert payload.option_scope is None
    stored = await repo.load("user:a", switched.chat_context.session)
    assert stored.context.filters.product_type == "cushion"

    broader = await service.answer(
        request(switched.chat_context, "쿠션 조건만 빼고 베이스 전체로 넓혀줘"), "user:a"
    )
    assert broader.chat_context.filters.product_type is None
    assert service._catalog.calls[-1].category == "base"
    assert service._catalog.calls[-1].product_type is None


@pytest.mark.anyio
async def test_ambiguous_types_ask_without_scanning_cards(setup):
    service, _, _ = setup
    result = await service.answer(request(message="쿠션 파운데이션 옵션 찾아줘"), "user:a")
    assert result.result_type == "clarification"
    assert "파운데이션과 쿠션 중" in result.answer
    assert not result.products and not service._catalog.calls

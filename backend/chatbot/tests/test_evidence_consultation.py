"""Synthetic consultation cases and the opt-in real Catalog HTTP/Redis runner."""

import asyncio
import json
import os
import sys
from urllib.parse import urlsplit
from uuid import uuid4

import httpx
import pytest
from redis.asyncio import Redis

from app.clients.catalog_client import CatalogClient
from app.core.errors import ApiError, UpstreamError
from app.main import create_app
from app.repositories.chat_session_repository import ChatSessionRepository
from app.schemas.catalog import (
    CatalogOption,
    ClaimCitation,
    ClaimSearchResult,
    OptionCategories,
    OptionPage,
)
from app.schemas.chat import BeautyContext, ChatRequest
from app.services import evidence_consultation_service as evidence_service
from app.services.chat_service import ChatService, get_chat_service
from tests.test_beauty_consultation import Catalog, PlanLlm, product
from tests.test_chat_sessions import RedisDouble

pytestmark = pytest.mark.anyio
CATEGORY = {"categoryId": "cream", "name": "크림", "path": "스킨케어 > 크림"}
HASH = "a" * 64
CONDITIONS = [
    {"ingredientName": "글리세린", "operator": "includes"},
    {"ingredientName": "향료", "operator": "excludes"},
]
SHOP = {
    "intent": "search",
    "evidenceIntent": "recommend",
    "optionCategory": "크림",
    "category": "skincare",
    "maxPriceKRW": 20000,
    "claimContext": {"concern": "건조"},
}
CAPTURED = SHOP | {"optionPriceBasis": "collected_sale"}
MESSAGE = "건조 피부 크림 2만원 이하 추천"
OWNER = "guest:fixture-i3"


@pytest.fixture
def anyio_backend():
    return "asyncio"


def chat(message=MESSAGE, context=None):
    return ChatRequest(
        message=message,
        locale="ko",
        request_type="beauty_consultation",
        chat_context=context,
        request_id=uuid4(),
    )


def synthetic_claim(use):
    return ClaimCitation.model_validate(
        {
            "publicationId": uuid4(),
            "revision": 1,
            "ingredient": {"mfdsIngredientId": 1, "sourceHash": HASH},
            "ingredientName": "글리세린",
            "summary": "SYNTHETIC approved study summary",
            "use": use,
            "scope": {"concerns": ["건조"]},
            "sourceTitle": "Synthetic citation",
            "sourceUrl": "https://example.test/citation",
            "sourceVersion": "synthetic-source-v1",
            "studyType": "synthetic study",
        }
    )


class FixtureCatalog(Catalog):
    def __init__(self):
        self.products = [product(pid, 1, category="skincare") for pid in ("a", "b", "c")]
        self.options = [
            ("a", "a-01", 9000, True, HASH),
            ("b", "b-03", 20000, True, HASH),
        ]
        self.claims = {use: synthetic_claim(use) for use in ("explain", "rank")}
        self.option_requests, self.claim_requests = [], []
        self.fail_page = None
        self.fail_claims = False

    async def option_categories(self):
        return OptionCategories.model_validate(
            {
                "categories": [
                    {"categoryId": "parent", "name": "크림", "path": "크림"},
                    {**CATEGORY, "parentId": "parent"},
                ]
            }
        )

    async def search_claims(self, lookup):
        self.claim_requests.append(lookup)
        if self.fail_claims:
            raise UpstreamError("synthetic claim error")
        claim = self.claims.get(lookup.use)
        if not claim or lookup.context.concern != "건조":
            return ClaimSearchResult(claims=[])
        return ClaimSearchResult(claims=[claim])

    def option(self, selection, request):
        pid, oid, amount, reviewed, source_hash = selection
        check_data = []
        for condition in request.ingredient_conditions:
            verdict = "UNKNOWN"
            if reviewed:
                verdict = "MATCH" if pid == "a" or condition.operator == "includes" else "NOT_MATCH"
            check_data.append(
                {
                    **condition.model_dump(by_alias=True),
                    "productId": pid,
                    "optionId": oid,
                    "shadeId": None,
                    "condition": "ingredient",
                    "verdict": verdict,
                    "reason": "synthetic condition",
                    "evidenceId": oid if reviewed else None,
                }
            )
        budget = None
        if request.max_price_krw is not None:
            verdict = "UNKNOWN"
            if request.price_basis == "collected_sale" and amount is not None:
                verdict = "MATCH" if amount <= request.max_price_krw else "NOT_MATCH"
            budget = {
                "priceBasis": request.price_basis,
                "maxPriceKRW": request.max_price_krw,
                "verdict": verdict,
                "reason": "synthetic budget",
                "evidenceId": f"price:{oid}",
            }
        verdicts = [item["verdict"] for item in check_data] + (
            [budget["verdict"]] if budget else []
        )
        return CatalogOption.model_validate(
            {
                "productId": pid,
                "productName": f"Fixture {pid}",
                "catalogCategory": "skincare",
                "category": CATEGORY,
                "optionId": oid,
                "optionName": f"Option {oid}",
                "price": {
                    "referencePriceKRW": 1,
                    "currentSalePriceKRW": None,
                    "currentStockStatus": "unknown",
                    "collected": {
                        "evidenceId": f"price:{oid}",
                        "source": "oliveyoung_price_snapshot",
                        "salePriceKRW": amount,
                        "sourceUrl": "https://example.test/price",
                        "collectedAtRaw": "2026-11-01",
                        "stockStatus": "in_stock",
                    }
                    if amount is not None
                    else None,
                },
                "ingredients": {
                    "review": {
                        "productId": pid,
                        "optionId": oid,
                        "shadeId": None,
                        "status": "ok" if reviewed else "unknown",
                        "verdict": "UNKNOWN",
                        "reason": "synthetic review",
                        "reviewStatus": "verified" if reviewed else "unreviewed",
                        "mappingStatus": "directly_reviewed" if reviewed else "candidate",
                        "ingredientCoverage": "full" if reviewed else "unknown",
                        "normalizationStatus": "verified" if reviewed else "unverified",
                        "source": "fixture-label",
                        "sourceVersion": "label-v1",
                        "evidenceId": oid,
                        "reviewRef": "fixture",
                        "reviewedAt": "2026-11-02T00:00:00Z",
                        "synthetic": True,
                        "ingredients": [
                            {
                                "name": "글리세린",
                                "sequence": 1,
                                "identity": {
                                    "mfdsIngredientId": 1,
                                    "nameKo": "글리세린",
                                    "sourceHash": source_hash,
                                    "matchMethod": "standard_name",
                                    "ruleVersion": "test",
                                },
                            }
                        ]
                        if reviewed
                        else [],
                        "conditions": check_data,
                    }
                },
                "budgetCondition": budget,
                "requiredVerdict": next(
                    (v for v in ("NOT_MATCH", "UNKNOWN") if v in verdicts), "MATCH"
                ),
            }
        )

    async def search_options(self, request):
        self.option_requests.append(request)
        if request.offset == self.fail_page:
            raise UpstreamError("synthetic page failure")
        rows = [
            self.option(row, request)
            for row in self.options
            if (not request.product_id or request.product_id == row[0])
            and (not request.option_id or request.option_id == row[1])
        ]
        total = len(rows)
        page = rows[request.offset : request.offset + request.limit]
        stop = request.offset + len(page)
        return OptionPage.model_validate(
            {
                "scope": {
                    "request": request,
                    "category": CATEGORY,
                    "candidateCount": total,
                    "evaluatedCount": len(page),
                    "nextOffset": stop if stop < total else None,
                    "optionsWithLookupErrors": 0,
                },
                "matches": [row for row in page if row.required_verdict == "MATCH"],
                "excluded": [row for row in page if row.required_verdict == "NOT_MATCH"],
                "unconfirmed": [
                    row for row in page if row.required_verdict in {"UNKNOWN", "ERROR"}
                ],
            }
        )


class NoGraph:
    async def find_products(self, *args, **kwargs):
        pytest.fail("Evidence consultation must not query Neo4j")


@pytest.fixture
def setup():
    catalog = FixtureCatalog()
    llm = PlanLlm(**CAPTURED)
    repo = ChatSessionRepository(RedisDouble())
    return ChatService(NoGraph(), llm, catalog, sessions=repo), catalog, llm


async def first(service):
    return await service.answer(chat(MESSAGE + " (수집 당시 가격 기준)"), OWNER)


async def test_explanation_uses_only_published_claims_without_product_cards(setup):
    service, catalog, llm = setup
    llm.plan = {
        "intent": "general",
        "evidenceIntent": "explain",
        "explanationIngredients": ["글리세린"],
        "claimContext": {"concern": "건조"},
    }
    answer = await service.answer(chat("건조 피부 글리세린 효능 설명"), OWNER)
    assert answer.products == [] and answer.option_search is None
    assert answer.claim_status == "available" and "Synthetic citation" in answer.answer
    assert "SYNTHETIC approved study summary" not in json.dumps(llm.messages)
    assert not catalog.option_requests and llm.calls == 1


async def test_avoid_request_uses_only_publication_authorized_for_avoidance(setup):
    service, catalog, llm = setup
    llm.plan = {
        "intent": "general",
        "evidenceIntent": "explain",
        "explanationUse": "avoid",
        "explanationIngredients": ["글리세린"],
        "claimContext": {"concern": "건조"},
    }
    request = chat("건조 피부는 글리세린을 피해야 해?")
    answer = await service.answer(request, OWNER)
    assert answer.claim_status == "not_found"
    assert catalog.claim_requests[-1].use == "avoid"
    catalog.claims["avoid"] = synthetic_claim("avoid")
    answer = await service.answer(request, OWNER)
    assert answer.published_claims[0].use == "avoid" and not answer.products


async def test_current_budget_unknown_and_explicit_captured_budget_boundary(setup):
    service, catalog, llm = setup
    llm.plan = CAPTURED  # A planner cannot authorize a historical quote on its own.
    current = await service.answer(chat(), OWNER)
    assert current.products == [] and current.option_search.status == "unconfirmed"
    assert {item.budget.verdict for item in current.option_search.evaluations} == {"UNKNOWN"}
    captured = await first(service)
    assert [item.id for item in captured.products] == ["a", "b"]
    assert captured.option_search.category_id == "cream"
    assert captured.option_search.price_basis == "collected_sale"
    assert "현재 판매가 미확인" in captured.answer and "20,000 KRW" in captured.answer
    assert catalog.option_requests[-1].price_basis == "collected_sale"


async def test_claim_link_requires_matching_reviewed_mfds_version(setup):
    service, catalog, _ = setup
    catalog.options[1] = ("b", "b-03", 20000, True, "b" * 64)
    result = await first(service)
    assert [item.id for item in result.products] == ["a", "b"]
    assert len(result.published_claims) == 1
    link = result.option_claim_links[0]
    assert (link.product_id, link.option_id, link.ingredient_source_version) == (
        "a",
        "a-01",
        "label-v1",
    )
    assert len(result.option_claim_links) == 1
    assert "완제품 효능과 개인 적합성은 미확인" in result.answer


async def test_compound_conditions_keep_exclusion_and_exact_absence(setup):
    service, catalog, llm = setup
    llm.plan = CAPTURED | {"ingredientConditions": CONDITIONS}
    catalog.options.append(("c", "c-01", 20000, False, HASH))
    answer = await first(service)
    rows = {item.option_id: item for item in answer.option_search.evaluations}
    assert {key: item.verdict for key, item in rows.items()} == {
        "a-01": "MATCH",
        "b-03": "NOT_MATCH",
        "c-01": "UNKNOWN",
    }
    assert rows["a-01"].ingredient_conditions[1].evidence_id == "a-01"
    assert [p.id for p in answer.products] == ["a"]
    llm.plan |= {"fragranceFree": True}
    fragrance = await first(service)
    assert not fragrance.products
    assert fragrance.option_search.evaluations[0].other_conditions[0].verdict == "UNKNOWN"


async def test_second_option_and_followup_filters_are_authoritative_in_redis(setup):
    service, catalog, llm = setup
    initial = await first(service)
    context = initial.chat_context.model_copy(deep=True)
    context.candidate_ids.reverse()
    context.filters.max_price_krw = 10
    llm.plan = {"intent": "detail", "scope": "previous", "ordinal": 2}
    detail = await service.answer(chat("두 번째 제품 자세히", context), OWNER)
    assert [(p.id, p.option_id) for p in detail.products] == [("b", "b-03")]
    assert detail.chat_context.candidate_ids == ["a", "b"] and detail.session_status == "stored"
    assert detail.chat_context.filters.max_price_krw == 20000
    assert catalog.option_requests[-1].option_id == "b-03"


async def test_refine_retains_ingredient_conditions_and_explicit_price_basis(setup):
    service, catalog, llm = setup
    llm.plan |= {"ingredientConditions": CONDITIONS[:1]}
    initial = await first(service)
    llm.plan = {"intent": "refine", "scope": "catalog", "maxPriceKRW": 10000}
    answer = await service.answer(chat("1만원 이하로 바꿔줘", initial.chat_context), OWNER)
    assert [p.id for p in answer.products] == ["a"]
    lookup = catalog.option_requests[-1]
    assert lookup.price_basis == "collected_sale" and lookup.max_price_krw == 10000
    assert lookup.ingredient_conditions[0].ingredient_name == "글리세린"


async def test_without_publishable_claims_recommendation_has_only_option_facts(setup):
    service, catalog, _ = setup
    catalog.claims.clear()
    answer = await first(service)
    assert answer.products and answer.claim_status == "not_found"
    assert not answer.published_claims and not answer.option_claim_links
    assert "SYNTHETIC approved" not in answer.answer


async def test_no_matches_is_distinct_from_unsupported_category(setup):
    service, _, llm = setup
    llm.plan = CAPTURED | {"maxPriceKRW": 1}
    empty = await service.answer(chat("수집가 1원 이하 크림 추천"), OWNER)
    assert not empty.products and empty.option_search.status == "no_matches"
    assert empty.option_search.exhaustive
    llm.plan |= {"optionCategory": "알수없는카테고리"}
    invalid = await service.answer(chat("수집가 알수없는카테고리 추천"), OWNER)
    assert invalid.option_search.status == "unsupported_category"


async def test_missing_price_ingredients_and_current_stock_remain_unknown(setup):
    service, catalog, llm = setup
    catalog.options = [("a", "a-01", None, False, HASH)]
    llm.plan |= {"ingredientConditions": CONDITIONS, "requireInStock": True}
    answer = await service.answer(chat("수집가 2만원 이하 재고 있는 크림 추천"), OWNER)
    (row,) = answer.option_search.evaluations
    assert row.verdict == row.budget.verdict == "UNKNOWN"
    assert row.ingredient_verification == "unknown"
    assert all(c.verdict == "UNKNOWN" for c in row.ingredient_conditions + row.other_conditions)
    assert not answer.products and not catalog.claim_requests


async def test_redis_retries_revalidate_publication_and_fail_closed(setup):
    service, catalog, llm = setup
    initial = await first(service)
    llm.plan = {"intent": "detail", "scope": "previous", "ordinal": 2}
    request = chat("두 번째 제품 자세히", initial.chat_context)
    detail = await service.answer(request, OWNER)
    assert detail.published_claims and detail.option_claim_links
    assert (await service.answer(request, OWNER)).answer == detail.answer
    assert catalog.claim_requests[-1].publication_ids == [detail.published_claims[0].publication_id]
    catalog.fail_claims = True
    with pytest.raises(ApiError) as exc:
        await service.answer(request, OWNER)
    assert exc.value.code == "claim_lookup_failed"
    catalog.fail_claims = False
    catalog.claims.clear()
    with pytest.raises(ApiError) as exc:
        await service.answer(request, OWNER)
    assert exc.value.code == "chat_evidence_changed"


@pytest.mark.parametrize("change", ["version", "evidence", "conditions", "failure"])
async def test_cached_option_answer_revalidates_observation_without_replacing_candidates(
    setup, change
):
    service, catalog, llm = setup
    # No publication is required for this invalidation: an option fact alone can go stale.
    catalog.claims.clear()
    initial = await first(service)
    llm.plan = {"intent": "detail", "scope": "previous", "ordinal": 2}
    request = chat("두 번째 제품 자세히", initial.chat_context)
    detail = await service.answer(request, OWNER)
    assert (await service.answer(request, OWNER)).answer == detail.answer
    original = catalog.search_options

    async def changed(lookup):
        if change == "failure":
            raise UpstreamError("synthetic outage")
        page = await original(lookup)
        row = [*page.matches, *page.excluded, *page.unconfirmed][0]
        if change == "version":
            row.ingredients.review.source_version = "changed-original-hash"
        elif change == "evidence":
            row.ingredients.review.evidence_id = None
        else:
            row.ingredients.review.review_status = "unreviewed"
            row.ingredients.review.ingredient_coverage = "unknown"
        return page

    catalog.search_options = changed
    with pytest.raises(ApiError) as exc:
        await service.answer(request, OWNER)
    assert exc.value.code == (
        "option_evidence_lookup_failed" if change == "failure" else "chat_option_evidence_changed"
    )
    catalog.search_options = original
    retried = await service.answer(request, OWNER)
    assert retried.chat_context.candidate_ids == ["a", "b"]
    assert retried.chat_context.filters == detail.chat_context.filters


@pytest.mark.skipif(not os.getenv("G_TEST_REDIS_URL"), reason="requires dedicated G Redis")
async def test_real_redis_does_not_replay_changed_option_original():
    url = os.environ["G_TEST_REDIS_URL"]
    assert urlsplit(url).hostname == "127.0.0.1" and urlsplit(url).port == 16389
    redis = Redis.from_url(url)
    catalog = FixtureCatalog()
    llm = PlanLlm(**CAPTURED)
    service = ChatService(NoGraph(), llm, catalog, sessions=ChatSessionRepository(redis))
    owner = "guest:g-real-redis-" + str(uuid4())
    try:
        initial = await service.answer(chat(MESSAGE + " (수집 당시 가격 기준)"), owner)
        llm.plan = {"intent": "detail", "scope": "previous", "ordinal": 2}
        request = chat("두 번째 제품 자세히", initial.chat_context)
        detail = await service.answer(request, owner)
        assert (await service.answer(request, owner)).answer == detail.answer
        catalog.options = [("a", "a-01", 9000, True, HASH)]
        with pytest.raises(ApiError, match="Option evidence changed"):
            await service.answer(request, owner)
        assert await redis.ping()
    finally:
        await redis.aclose()


async def test_cached_legacy_product_ingredient_route_also_revalidates_original():
    from unittest.mock import AsyncMock

    from app.schemas.catalog import OptionLookup
    from app.schemas.chat import ChatResponse

    catalog = FixtureCatalog()
    review = catalog.option(
        catalog.options[0], OptionLookup(category_id="cream")
    ).ingredients.review
    response = ChatResponse(
        answer="Synthetic",
        products=[dict(id="a", brand="Fixture", name="A", category="skincare")],
        ingredient_results=[review],
    )
    current = review.model_copy(deep=True)
    catalog.get_ingredients = AsyncMock(return_value=current)
    await evidence_service.revalidate_option_evidence(response, catalog)
    current.source_version = "changed-option-original"
    with pytest.raises(ApiError) as exc:
        await evidence_service.revalidate_option_evidence(response, catalog)
    assert exc.value.code == "chat_option_evidence_changed"
    catalog.get_ingredients = AsyncMock(side_effect=UpstreamError("synthetic failure"))
    with pytest.raises(ApiError) as exc:
        await evidence_service.revalidate_option_evidence(response, catalog)
    assert exc.value.code == "option_evidence_lookup_failed"


@pytest.mark.parametrize("stop", ["page_limit", "lookup_failed", "time_limit"])
async def test_pagination_never_claims_global_absence(setup, monkeypatch, stop):
    service, catalog, _ = setup
    catalog.options = [("a", f"a-{i:03d}", 90000, False, HASH) for i in range(160)]
    if stop == "lookup_failed":
        catalog.fail_page = 32
    if stop == "time_limit":

        async def delay(request):
            await asyncio.sleep(1)

        catalog.search_options = delay
        monkeypatch.setattr(evidence_service, "OPTION_DEADLINE", 0.01)
    response = await first(service)
    assert response.products == [] and not response.option_search.exhaustive
    assert response.option_search.status in {"partial_failure", "search_incomplete"}
    assert response.option_search.stop_reason == stop
    assert "조건을 충족한 옵션이 없습니다" not in response.answer
    if stop == "page_limit":
        assert response.option_search.evaluated_count == 128
        assert [request.offset for request in catalog.option_requests] == [0, 32, 64, 96]


async def run_live(api_url, mode):
    redis_url = os.environ.get("VISHUE_I3_TEST_REDIS_URL")
    if redis_url and urlsplit(redis_url).hostname not in {"127.0.0.1", "::1"}:
        raise ValueError("Use an isolated loopback Redis")
    redis = Redis.from_url(redis_url) if redis_url else None
    llm = PlanLlm(**CAPTURED)
    try:
        service = ChatService(
            NoGraph(),
            llm,
            CatalogClient(api_url),
            sessions=ChatSessionRepository(redis) if redis else None,
        )
        app = create_app()
        app.dependency_overrides[get_chat_service] = lambda: service
        headers = {"X-Vishue-Anonymous-Id": f"fixture-i3-{uuid4()}"}
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://test",
            headers=headers,
        ) as client:

            async def ask(request):
                response = await client.post("/api/chat", json=request.model_dump(mode="json"))
                assert response.status_code == 200, response.text
                return response.json()

            if mode == "actual":
                await probe_real_snapshots(ask, llm)
                return

            llm.plan = {
                "intent": "general",
                "evidenceIntent": "explain",
                "explanationIngredients": ["합성글리세린시험"],
                "claimContext": {"concern": "건조"},
            }
            a = await ask(chat("건조 피부 합성글리세린시험 성분 설명"))
            assert not a["products"] and len(a["publishedClaims"]) == 1
            llm.plan = CAPTURED
            b = await ask(chat(MESSAGE + " 수집 당시 가격"))
            assert b["claimStatus"] == "available", b
            assert b["products"][0]["optionId"] == "fixture-exact-option"
            assert b["optionClaimLinks"][0]["ingredientSourceVersion"] == "fixture-label-version"
            if redis:
                assert b["sessionStatus"] == "stored"
                assert await redis.ping()
                llm.plan = {"intent": "detail", "scope": "previous", "ordinal": 1}
                ctx = BeautyContext.model_validate(b["chatContext"])
                followup = chat("첫 번째 제품 자세히", ctx)
                detail = await ask(followup)
                assert detail["optionClaimLinks"] == b["optionClaimLinks"]
                assert await ask(followup) == detail
                revoked = await client.post("/api/chat", json=followup.model_dump(mode="json"))
                assert revoked.status_code == 409
                assert revoked.json()["code"] == "chat_evidence_changed"
        print(
            json.dumps(
                {
                    "postgres": "real",
                    "catalogHttp": "real",
                    "chatRoute": "ASGI",
                    "redis": "real" if redis else "not used",
                    "planner": "fixture",
                    "claimsAndOptions": "synthetic",
                    "revokedReplayBlocked": bool(redis),
                }
            )
        )
    finally:
        if redis:
            await redis.aclose()


async def probe_real_snapshots(ask, llm):
    llm.plan = {
        "intent": "general",
        "evidenceIntent": "explain",
        "explanationIngredients": ["글리세린"],
        "claimContext": {"concern": "건조"},
    }
    unavailable = await ask(chat("건조 피부 글리세린 성분 설명"))
    assert unavailable["claimStatus"] == "not_found" and unavailable["publishedClaims"] == []
    assert unavailable["products"] == []

    llm.plan = SHOP
    current = await ask(chat())
    checked = current["optionSearch"]
    assert checked["categoryId"] == "1000001000100150001", checked
    assert checked["evaluatedCount"] == 128 and checked["candidateCount"] == 808
    assert checked["stopReason"] == "page_limit" and not checked["exhaustive"]
    assert not current["products"]
    assert all(item["budget"]["verdict"] == "UNKNOWN" for item in checked["evaluations"])

    llm.plan = CAPTURED
    captured = await ask(chat(MESSAGE + " 수집 당시 가격"))
    assert len(captured["products"]) == 6
    assert not captured["optionClaimLinks"] and captured["claimStatus"] == "not_found"
    prices = captured["optionSearch"]["evaluations"]
    assert all(item["budget"]["verdict"] == "MATCH" for item in prices)
    assert all(item["price"]["currentSalePriceKRW"] is None for item in prices)

    llm.plan = CAPTURED | {"ingredientConditions": CONDITIONS}
    compound = await ask(chat(MESSAGE + " 수집가, 글리세린 포함 향료 제외"))
    assert not compound["products"] and not compound["optionSearch"]["exhaustive"]
    assert all(
        condition["verdict"] == "UNKNOWN"
        for item in compound["optionSearch"]["evaluations"]
        for condition in item["ingredientConditions"]
    )
    print(
        json.dumps(
            {
                "realCatalogCandidates": checked["candidateCount"],
                "evaluated": checked["evaluatedCount"],
                "currentBudgetUnknown": checked["evaluatedCount"],
                "capturedBudgetMatches": len(prices),
                "capturedCards": len(captured["products"]),
                "compoundCards": len(compound["products"]),
                "publishedAihubClaims": len(unavailable["publishedClaims"]),
                "planner": "fixture",
            }
        )
    )


if __name__ == "__main__":
    asyncio.run(run_live(sys.argv[1], sys.argv[2]))

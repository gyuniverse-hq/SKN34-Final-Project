"""Synthetic HTTP evidence fixtures; no real ingredient review or paid LLM requests."""

import json
import time
from pathlib import Path

import httpx
import pytest
from pydantic import ValidationError

from app.clients.catalog_client import CatalogClient, IngredientLookupError
from app.core.errors import ApiError, UpstreamError
from app.schemas.chat import BeautyContext, BeautyFilters, ChatRequest, ChatResponse
from app.services.chat_service import ChatService, get_chat_service
from tests.test_beauty_consultation import Catalog, PlanLlm


@pytest.fixture
def anyio_backend():
    return "asyncio"


def evidence(pid="a", shade="a-03", *, name=None, operator="includes", **changes):
    data = dict(
        productId=pid,
        shadeId=shade,
        optionId=f"option-{pid}",
        status="ok",
        verdict="UNKNOWN",
        mappingStatus="reproduced",
        ingredientCoverage="full",
        reviewStatus="verified",
        normalizationStatus="verified",
        ingredients=[{"name": "향료", "sequence": 1}],
        source="https://synthetic.test/notice",
        collectedAt="2026-01-01T10:00:00+09:00",
        sourceVersion="synthetic-v1",
        sourceFingerprint="synthetic-input",
        generatorVersion="synthetic-generator",
        evidenceId=f"synthetic-{pid}",
        reason="ingredient_present",
        synthetic=True,
        conditions=[],
    )
    data.update(changes)
    if name:
        if "verdict" not in changes:
            present = name in [i["name"] for i in data["ingredients"]]
            data["verdict"] = "MATCH" if present == (operator == "includes") else "NOT_MATCH"
        data["conditions"] = [
            dict(
                productId=pid,
                shadeId=shade,
                optionId=data["optionId"],
                condition="ingredient",
                ingredientName=name,
                operator=operator,
                verdict=data["verdict"],
                reason=data["reason"],
                evidenceId=data["evidenceId"],
                synthetic=True,
            )
        ]
    return data


def install_http(monkeypatch, handler):
    original = httpx.AsyncClient
    monkeypatch.setattr(
        httpx, "AsyncClient", lambda **kw: original(transport=httpx.MockTransport(handler), **kw)
    )


class IngredientsCatalog(Catalog):
    def __init__(self, client):
        super().__init__()
        self.client = client
        self.calls = []
        for p in self.products:
            p.shades = [p.shades[0].model_copy(update={"id": f"{p.id}-03", "name": "03 Rose"})]

    async def get_ingredients(self, pid, shade, **kwargs):
        self.calls.append((pid, shade, kwargs))
        return await self.client.get_ingredients(pid, shade, **kwargs)


def context(*, shades=True, **changes):
    return BeautyContext(
        issued_at=int(time.time()),
        filters=BeautyFilters(),
        candidate_ids=["a", "b"],
        selected_product_id="a",
        shade_selections={"a": "a-03", "b": "b-03"} if shades else {},
        **changes,
    )


def request(ctx=None, locale="ko", **changes):
    return ChatRequest.model_validate(
        dict(
            message="이 상품에 향료가 들어 있어?",
            request_type="beauty_consultation",
            chat_context=ctx,
            locale=locale,
        )
        | changes
    )


@pytest.mark.anyio
@pytest.mark.parametrize(
    "name,operator,verdict",
    [
        ("향료", "includes", "MATCH"),
        ("향료", "excludes", "NOT_MATCH"),
        ("나이아신아마이드", "includes", "UNKNOWN"),
        ("나이아신아마이드", "excludes", "UNKNOWN"),
    ],
)
async def test_client_verified_evidence_and_query_encoding(monkeypatch, name, operator, verdict):
    def handler(req):
        assert req.url.params["shadeId"] == "a-03"
        assert req.url.params["ingredientName"] == name
        assert req.url.params["operator"] == operator
        return httpx.Response(200, json=evidence(name=name, operator=operator))

    install_http(monkeypatch, handler)
    result = await CatalogClient("http://catalog.test").get_ingredients(
        "a", "a-03", ingredient_name=name, operator=operator
    )
    assert result.verdict == verdict and result.synthetic and result.verified


@pytest.mark.anyio
@pytest.mark.parametrize(
    "status,body,reason",
    [
        (404, {"code": "not_found"}, "product_not_found"),
        (404, {"code": "shade_not_found"}, "shade_not_found"),
        (503, {}, "source_unavailable"),
        (500, {}, "http_error"),
        (200, {"productId": "a"}, "invalid_response"),
        (200, evidence(pid="b"), "invalid_response"),
        (200, evidence(shade="b-03"), "invalid_response"),
    ],
)
async def test_client_error_states(monkeypatch, status, body, reason):
    install_http(monkeypatch, lambda req: httpx.Response(status, json=body))
    with pytest.raises(IngredientLookupError) as exc:
        await CatalogClient("http://catalog.test").get_ingredients("a", "a-03")
    assert exc.value.reason == reason


@pytest.mark.anyio
@pytest.mark.parametrize(
    "error,reason",
    [
        (httpx.ReadTimeout, "timeout"),
        (httpx.ConnectError, "network_error"),
    ],
)
async def test_transport_errors(monkeypatch, error, reason):
    def handler(req):
        raise error("synthetic", request=req)

    install_http(monkeypatch, handler)
    with pytest.raises(IngredientLookupError) as exc:
        await CatalogClient("http://catalog.test").get_ingredients("a", "a-03")
    assert exc.value.reason == reason


@pytest.mark.anyio
@pytest.mark.parametrize(
    "changes",
    [
        {"reviewStatus": "unreviewed"},
        {"mappingStatus": "candidate"},
        {"ingredientCoverage": "partial"},
        {"normalizationStatus": "unverified"},
        {"ingredients": [{"name": "향료", "sequence": 2}]},
        {"sourceVersion": None},
        {"issues": ["ingredient_list_inconsistent"]},
    ],
)
async def test_unreviewed_or_partial_never_proves_absence(monkeypatch, changes):
    install_http(
        monkeypatch,
        lambda req: httpx.Response(200, json=evidence(name="나이아신아마이드", **changes)),
    )
    with pytest.raises(IngredientLookupError, match="invalid_response"):
        await CatalogClient("http://catalog.test").get_ingredients(
            "a", "a-03", ingredient_name="나이아신아마이드"
        )


@pytest.mark.anyio
async def test_partial_presence_can_be_verified(monkeypatch):
    install_http(
        monkeypatch,
        lambda req: httpx.Response(200, json=evidence(name="향료", ingredientCoverage="partial")),
    )
    result = await CatalogClient("http://catalog.test").get_ingredients(
        "a", "a-03", ingredient_name="향료"
    )
    assert result.verdict == "MATCH" and not result.complete


@pytest.mark.anyio
@pytest.mark.parametrize("locale", ["ko", "en", "ja", "zh"])
async def test_supervisor_reuses_one_interpretation_and_keeps_public_contract(monkeypatch, locale):
    catalog = IngredientsCatalog(CatalogClient("http://catalog.test"))
    llm = PlanLlm(intent="detail", ingredientLookup=True, ingredientName="향료", ordinal=2)
    # Return the exact second product IDs, not a guessed ordinal in the upstream response.
    install_http(
        monkeypatch,
        lambda req: httpx.Response(200, json=evidence(pid="b", shade="b-03", name="향료")),
    )
    result = await ChatService(None, llm, catalog).answer(request(context(), locale))
    assert llm.calls == 1
    assert [p.id for p in result.products] == ["b"]
    assert result.ingredient_results[0].verdict == "MATCH"
    assert {"ko": "충족", "en": "meets", "ja": "満た", "zh": "符合"}[locale] in result.answer
    assert result.supervisor.result.conditions[0].shade_id == "b-03"
    assert result.supervisor.result.evidence[0].evidence_id == "synthetic-b"
    assert result.supervisor.result.application == "not_requested"
    payload = result.model_dump(mode="json", by_alias=True)
    assert "supervisor" not in payload and "toolResult" not in payload and "arResult" not in payload
    assert {"answer", "products", "chatContext", "ingredientResults"} <= payload.keys()
    assert payload["ingredientResults"][0]["productId"] == payload["products"][0]["id"]
    assert result.chat_context.shade_selections == {"a": "a-03", "b": "b-03"}


@pytest.mark.anyio
@pytest.mark.parametrize("locale", ["ko", "en", "ja", "zh"])
@pytest.mark.parametrize("selection", ["none", "missing_shade", "foreign_shade"])
async def test_missing_selection_clarifies_without_api_or_first_shade(
    monkeypatch, locale, selection
):
    catalog = IngredientsCatalog(CatalogClient("http://must-not-call.test"))
    ctx = None if selection == "none" else context(shades=False)
    if selection == "foreign_shade":
        ctx.shade_selections = {"a": "b-03"}
    result = await ChatService(
        None, PlanLlm(intent="detail", ingredientLookup=True), catalog
    ).answer(request(ctx, locale))
    assert result.result_type == "clarification"
    assert catalog.calls == []
    assert result.supervisor.result.status == "clarification"
    assert {"ko": "선택", "en": "Select", "ja": "選んで", "zh": "选择"}[locale] in result.answer


@pytest.mark.anyio
async def test_explicit_shade_then_followup_retains_selection(monkeypatch):
    install_http(monkeypatch, lambda req: httpx.Response(200, json=evidence()))
    catalog = IngredientsCatalog(CatalogClient("http://catalog.test"))
    service = ChatService(
        None, PlanLlm(intent="detail", ingredientLookup=True, shadeName="03"), catalog
    )
    first = await service.answer(request(context(shades=False), message="그 제품 03호 성분은?"))
    assert catalog.calls[0][:2] == ("a", "a-03")
    service._llm = PlanLlm(intent="detail", ingredientLookup=True)
    second = await service.answer(request(first.chat_context))
    assert second.chat_context.shade_selections["a"] == "a-03"
    assert len(catalog.calls) == 2
    service._llm = PlanLlm(intent="price")
    priced = await service.answer(request(second.chat_context))
    assert priced.chat_context.shade_selections["a"] == "a-03"


@pytest.mark.anyio
async def test_screen_selection_is_revalidated(monkeypatch):
    install_http(monkeypatch, lambda req: httpx.Response(200, json=evidence()))
    catalog = IngredientsCatalog(CatalogClient("http://catalog.test"))
    result = await ChatService(
        None, PlanLlm(intent="detail", ingredientLookup=True), catalog
    ).answer(request(screen_context={"productId": "a", "shadeId": "a-03"}))
    assert result.products[0].id == "a" and result.ingredient_results[0].verified


@pytest.mark.anyio
@pytest.mark.parametrize(
    "review,coverage,reason",
    [
        ("unreviewed", "unknown", "evidence_not_reviewed"),
        ("verified", "partial", "absence_not_verifiable"),
    ],
)
async def test_unknown_is_not_empty_or_absence(monkeypatch, review, coverage, reason):
    install_http(
        monkeypatch,
        lambda req: httpx.Response(
            200,
            json=evidence(
                name="향료",
                status="unknown",
                verdict="UNKNOWN",
                reviewStatus=review,
                ingredientCoverage=coverage,
                ingredients=[],
                reason=reason,
            ),
        ),
    )
    result = await ChatService(
        None,
        PlanLlm(intent="detail", ingredientName="향료"),
        IngredientsCatalog(CatalogClient("http://catalog.test")),
    ).answer(request(context()))
    assert result.ingredient_results[0].verdict == "UNKNOWN"
    assert result.result_type == "clarification" and result.products[0].id == "a"


@pytest.mark.anyio
@pytest.mark.parametrize("locale", ["ko", "en", "ja", "zh"])
async def test_fragrance_filter_cannot_infer_fragrance_free_from_single_ingredient(
    monkeypatch, locale
):
    def handler(req):
        pid = req.url.path.split("/")[-2]
        return httpx.Response(
            200,
            json=evidence(
                pid=pid,
                shade=f"{pid}-03",
                name="향료",
                operator="excludes",
                ingredients=[{"name": "정제수" if pid == "b" else "향료", "sequence": 1}],
            ),
        )

    install_http(monkeypatch, handler)
    service = ChatService(
        None,
        PlanLlm(intent="refine", scope="previous", fragranceFree=True),
        IngredientsCatalog(CatalogClient("http://catalog.test")),
    )
    result = await service.answer(request(context(), locale))
    assert [p.id for p in result.products] == ["b"]
    assert result.chat_context.candidate_ids == ["b"]
    assert result.fragrance_search_summary.checked == result.fragrance_search_summary.total == 2
    assert result.fragrance_search_summary.verified_product_ids == []
    assert result.result_type == "clarification"
    assert all(r.verdict == "UNKNOWN" for r in result.ingredient_results)
    checks = [c for c in result.supervisor.result.conditions if c.condition == "fragranceFree"]
    assert checks and all(c.verdict == "UNKNOWN" for c in checks)
    assert all(r.reason == "fragrance_free_unverified" for r in result.ingredient_results)
    assert all(r.mapping_status == "reproduced" for r in result.ingredient_results)
    assert {"ko": "무향료", "en": "Fragrance-free", "ja": "無香料", "zh": "无香料"}[
        locale
    ] in result.answer
    unknown = await service.answer(request(context(shades=False)))
    assert unknown.result_type == "clarification" and len(unknown.products) == 2
    assert all(r.verdict == "UNKNOWN" for r in unknown.ingredient_results)


@pytest.mark.anyio
@pytest.mark.parametrize("operator", ["includes", "excludes"])
async def test_fragrance_and_named_ingredient_are_separate_conditions(monkeypatch, operator):
    def handler(req):
        pid = req.url.path.split("/")[-2]
        assert req.url.params["ingredientName"] == "나이아신아마이드"
        assert req.url.params["operator"] == operator
        if operator == "excludes" and pid == "b":
            return httpx.Response(
                200,
                json=evidence(
                    pid=pid,
                    shade=f"{pid}-03",
                    name="나이아신아마이드",
                    operator=operator,
                    verdict="UNKNOWN",
                    reason="ingredient_identity_unresolved",
                ),
            )
        return httpx.Response(
            200,
            json=evidence(
                pid=pid,
                shade=f"{pid}-03",
                name="나이아신아마이드",
                operator=operator,
                ingredients=[{"name": "나이아신아마이드", "sequence": 1}],
            ),
        )

    install_http(monkeypatch, handler)
    service = ChatService(
        None,
        PlanLlm(
            intent="refine",
            scope="previous",
            fragranceFree=True,
            ingredientLookup=True,
            ingredientName="나이아신아마이드",
            ingredientOperator=operator,
        ),
        IngredientsCatalog(CatalogClient("http://catalog.test")),
    )
    message = (
        "무향료이면서 나이아신아마이드가 있는 제품"
        if operator == "includes"
        else "무향료이면서 나이아신아마이드가 없는 제품"
    )
    result = await service.answer(request(context(), message=message))
    expected = ["a", "b"] if operator == "includes" else ["b"]
    assert [p.id for p in result.products] == expected
    assert result.chat_context.candidate_ids == expected
    assert result.chat_context.filters.fragrance_free
    assert result.result_type == "clarification"
    checks = result.supervisor.result.conditions
    expected_verdict = "MATCH" if operator == "includes" else "UNKNOWN"
    assert any(c.condition == "ingredient" and c.verdict == expected_verdict for c in checks)
    assert any(c.condition == "fragranceFree" and c.verdict == "UNKNOWN" for c in checks)
    assert "무향료 여부는 미확인" in result.answer


@pytest.mark.anyio
async def test_fragrance_filter_keeps_lookup_errors_distinct_from_unknown(monkeypatch):
    install_http(monkeypatch, lambda req: httpx.Response(503, json={}))
    service = ChatService(
        None,
        PlanLlm(intent="refine", scope="previous", fragranceFree=True),
        IngredientsCatalog(CatalogClient("http://catalog.test")),
    )
    result = await service.answer(request(context(), message="무향료 제품만 보여줘"))
    assert result.supervisor.result.status == "error"
    assert [p.id for p in result.products] == ["a", "b"]
    assert all(r.verdict == "ERROR" for r in result.ingredient_results)
    assert all(r.reason == "source_unavailable" for r in result.ingredient_results)


@pytest.mark.anyio
async def test_fragrance_filter_keeps_error_from_successful_http_response(monkeypatch):
    def handler(req):
        pid = req.url.path.split("/")[-2]
        return httpx.Response(
            200,
            json=evidence(
                pid=pid,
                shade=f"{pid}-03",
                name="향료",
                operator="excludes",
                status="error",
                verdict="ERROR",
                mappingStatus="candidate",
                reviewStatus="unreviewed",
                ingredientCoverage="unknown",
                ingredients=[],
                reason="source_unavailable",
            ),
        )

    install_http(monkeypatch, handler)
    service = ChatService(
        None,
        PlanLlm(intent="refine", scope="previous", fragranceFree=True),
        IngredientsCatalog(CatalogClient("http://catalog.test")),
    )
    result = await service.answer(request(context(), message="무향료 제품만 보여줘"))
    assert result.supervisor.result.status == "error"
    assert [p.id for p in result.products] == ["a", "b"]
    assert all(r.status == "error" and r.verdict == "ERROR" for r in result.ingredient_results)
    assert all(r.reason == "source_unavailable" for r in result.ingredient_results)


@pytest.mark.anyio
@pytest.mark.parametrize("operator", ["includes", "excludes"])
async def test_fragrance_filter_does_not_override_followup_ingredient_operator(
    monkeypatch, operator
):
    def handler(req):
        requested = req.url.params["operator"]
        return httpx.Response(
            200,
            json=evidence(
                name="나이아신아마이드",
                operator=requested,
                ingredients=[{"name": "나이아신아마이드", "sequence": 1}],
            ),
        )

    install_http(monkeypatch, handler)
    catalog = IngredientsCatalog(CatalogClient("http://catalog.test"))
    ctx = context()
    ctx.filters.fragrance_free = True
    service = ChatService(
        None,
        PlanLlm(
            intent="detail",
            ingredientLookup=True,
            ingredientName="나이아신아마이드",
            ingredientOperator=operator,
        ),
        catalog,
    )
    result = await service.answer(request(ctx, message="이 상품에 나이아신아마이드가 있어?"))
    assert catalog.calls[0][2]["operator"] == operator
    assert result.ingredient_results[0].verdict == (
        "MATCH" if operator == "includes" else "NOT_MATCH"
    )
    assert result.chat_context.filters.fragrance_free is True


@pytest.mark.anyio
async def test_fragrance_filter_can_be_removed_after_ingredient_and_price_followup(monkeypatch):
    def handler(req):
        return httpx.Response(
            200, json=evidence(name="나이아신아마이드", operator=req.url.params["operator"])
        )

    install_http(monkeypatch, handler)
    catalog = IngredientsCatalog(CatalogClient("http://catalog.test"))
    ctx = context()
    ctx.filters.fragrance_free = True
    service = ChatService(
        None,
        PlanLlm(intent="detail", ingredientLookup=True, ingredientName="나이아신아마이드"),
        catalog,
    )
    ingredient = await service.answer(request(ctx, message="나이아신아마이드 들어 있어?"))
    service._llm = PlanLlm(intent="price", scope="previous")
    price = await service.answer(request(ingredient.chat_context, message="그 제품 가격은?"))
    assert price.products[0].id == "a"
    assert "15,000" in price.answer or "15000" in price.answer
    assert price.chat_context.filters.fragrance_free is True
    service._llm = PlanLlm(intent="refine", scope="previous", clearFilters=["fragranceFree"])
    cleared = await service.answer(request(price.chat_context, message="향료 조건만 빼줘"))
    assert not cleared.chat_context.filters.fragrance_free
    assert [p.id for p in cleared.products] == ["a", "b"]


@pytest.mark.anyio
@pytest.mark.parametrize("price_case", ["known", "missing", "partial"])
async def test_cheapest_followup_keeps_unverified_fragrance_candidates(price_case):
    catalog = IngredientsCatalog(CatalogClient("http://catalog.test"))
    if price_case == "missing":
        catalog.products = [p.model_copy(update={"price_krw": 0}) for p in catalog.products]
    elif price_case == "partial":
        catalog.products = [
            p.model_copy(update={"price_krw": 0}) if p.id == "b" else p for p in catalog.products
        ]
    ctx = context()
    ctx.filters.fragrance_free = True
    service = ChatService(
        None, PlanLlm(intent="detail", scope="previous", selection="lowest_price"), catalog
    )
    result = await service.answer(request(ctx, message="이 중 가장 싼 제품은?"))
    assert result.result_type == "clarification"
    assert [p.id for p in result.products] == ["a", "b"]
    assert result.chat_context.candidate_ids == ["a", "b"]
    assert result.chat_context.filters.fragrance_free is True
    assert "무향료" in result.answer and "확정" in result.answer
    assert "15,000" not in result.answer
    if price_case == "missing":
        assert "기준가격을 확인할 수 없습니다" in result.answer
    elif price_case == "partial":
        assert "일부 후보의 기준가격은 미확인" in result.answer
    checks = [c for c in result.supervisor.result.conditions if c.condition == "fragranceFree"]
    assert checks and all(c.verdict == "UNKNOWN" for c in checks)


@pytest.mark.anyio
async def test_cheapest_followup_does_not_treat_catalog_failure_as_missing_price():
    catalog = IngredientsCatalog(CatalogClient("http://catalog.test"))

    async def broken(**kwargs):
        raise UpstreamError("synthetic catalog failure")

    catalog.search_products = broken
    ctx = context()
    ctx.filters.fragrance_free = True
    service = ChatService(
        None, PlanLlm(intent="detail", scope="previous", selection="lowest_price"), catalog
    )
    with pytest.raises(ApiError) as exc:
        await service.answer(request(ctx, message="이 중 가장 싼 제품은?"))
    assert exc.value.status == 502
    assert exc.value.code == "upstream_error"


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("case", "intent"),
    [
        ("same", "detail"),
        ("reordered", "detail"),
        ("different", "detail"),
        ("synthetic", "detail"),
        ("same", "refine"),
    ],
)
async def test_comparison_requires_verified_full_lists(monkeypatch, case, intent):
    def handler(req):
        pid = req.url.path.split("/")[-2]
        return httpx.Response(
            200,
            json=evidence(
                pid=pid,
                shade=f"{pid}-03",
                synthetic=case == "synthetic",
                ingredients=[
                    {"name": name, "sequence": i}
                    for i, name in enumerate(
                        ["정제수", "향료"]
                        if case == "reordered" and pid == "b"
                        else ["정제수", "글리세린"]
                        if case == "different" and pid == "b"
                        else ["향료", "정제수"],
                        1,
                    )
                ],
            ),
        )

    install_http(monkeypatch, handler)
    service = ChatService(
        None,
        PlanLlm(intent=intent, compareOrdinals=[1, 2]),
        IngredientsCatalog(CatalogClient("http://catalog.test")),
    )
    ctx = context()
    result = await service.answer(request(ctx))
    assert result.chat_context.model_dump(exclude={"issued_at"}) == ctx.model_dump(
        exclude={"issued_at"}
    )
    if case == "synthetic":
        assert "차이를 확정할 수 없습니다" in result.answer
    elif case == "different":
        assert "차이 있음" in result.answer
        assert "a에만 있는 표기명: 향료" in result.answer
        assert "b에만 있는 표기명: 글리세린" in result.answer
    else:
        assert "동일" in result.answer
    assert [p.id for p in result.products] == ["a", "b"]
    assert result.result_type == "clarification"
    assert result.supervisor.result.status == "clarification"
    result = await service.answer(request(context(shades=False)))
    assert "차이를 확정할 수 없습니다" in result.answer
    assert result.result_type == "clarification"
    assert result.supervisor.result.status == "clarification"


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("left", "right", "expected", "forbidden"),
    [
        (("글리세린", 101), ("Glycerin", 101), "비교: 동일", "차이 있음"),
        (("성분 A", 101), ("성분 B", 102), "b에만 있는 성분: 성분 B", "비교: 동일"),
        (("같은 표기", 101), ("같은 표기", 102), "차이 있음", "비교: 동일"),
        (("글리세린", None), ("글리세린", None), "표기명 비교: 동일", "전체 목록 비교: 동일"),
        (("글리세린", 101), ("Glycerin", None), "표기명 비교: 차이 있음", "있는 성분:"),
        (("글리세린", 101), ("Glycerin", 101, "b"), "차이를 확정할 수 없습니다", "비교: 동일"),
    ],
)
async def test_comparison_respects_verified_mfds_identity(
    monkeypatch, left, right, expected, forbidden
):
    def handler(req):
        pid = req.url.path.split("/")[-2]
        name, mfds_id, *fingerprint = left if pid == "a" else right
        entry = {"name": name, "sequence": 1}
        if mfds_id is not None:
            entry["identity"] = {
                "mfdsIngredientId": mfds_id,
                "nameKo": "표준명",
                "sourceHash": (fingerprint[0] if fingerprint else "a") * 64,
                "matchMethod": "official_synonym",
                "ruleVersion": "fixture-v1",
            }
        return httpx.Response(
            200,
            json=evidence(pid=pid, shade=f"{pid}-03", synthetic=False, ingredients=[entry]),
        )

    install_http(monkeypatch, handler)
    service = ChatService(
        None,
        PlanLlm(intent="detail", compareOrdinals=[1, 2]),
        IngredientsCatalog(CatalogClient("http://catalog.test")),
    )
    ctx = context()
    result = await service.answer(request(ctx))
    assert expected in result.answer
    assert forbidden not in result.answer
    verified = left[1] is not None and right[1] is not None and len(right) == 2
    assert result.result_type == ("product_detail" if verified else "clarification")
    assert result.supervisor.result.status == ("success" if verified else "clarification")
    assert [p.id for p in result.products] == ["a", "b"]
    assert result.chat_context.model_dump(exclude={"issued_at"}) == ctx.model_dump(
        exclude={"issued_at"}
    )


@pytest.mark.anyio
async def test_lookup_failure_survives_supervisor_as_error_not_empty(monkeypatch):
    install_http(monkeypatch, lambda req: httpx.Response(503, json={}))
    service = ChatService(
        None,
        PlanLlm(intent="detail", ingredientLookup=True),
        IngredientsCatalog(CatalogClient("http://catalog.test")),
    )
    result = await service.answer(request(context()))
    assert result.supervisor.result.status == "error"
    assert result.ingredient_results[0].reason == "source_unavailable"
    assert result.ingredient_results[0].verdict == "ERROR"
    assert result.result_type != "empty" and "조회 중 오류" in result.answer


def test_response_rejects_foreign_product_and_shade():
    for pid, shade in [("b", "a-03"), ("a", "b-03")]:
        with pytest.raises(ValidationError):
            ChatResponse(
                answer="test",
                products=[dict(id="a", brand="b", name="a", category="lip")],
                chat_context=context(),
                ingredient_results=[evidence(pid=pid, shade=shade)],
            )


def test_chat_http_contract(client, monkeypatch):
    install_http(monkeypatch, lambda req: httpx.Response(200, json=evidence()))
    service = ChatService(
        None,
        PlanLlm(intent="detail", ingredientLookup=True),
        IngredientsCatalog(CatalogClient("http://catalog.test")),
    )
    client.app.dependency_overrides[get_chat_service] = lambda: service
    response = client.post(
        "/api/chat",
        json=request(context()).model_dump(mode="json"),
        headers={"X-Vishue-Anonymous-Id": "guest-session-0123456789-abcdefghijk"},
    )
    assert response.status_code == 200
    assert response.json()["ingredientResults"][0]["evidenceId"] == "synthetic-a"


def test_real_review_report_has_zero_verified_mappings_and_reviews():
    """Read actual local report only; not a DB/API or ingredient correctness test."""
    path = Path(__file__).resolve().parents[3] / "reports/ingredients/p0-2b-1-mapping.json"
    if not path.exists():
        pytest.skip("Local review artifact unavailable")
    records = json.loads(path.read_text(encoding="utf-8"))["records"]
    assert records and not any(r["mappingStatus"] == "reproduced" for r in records)
    assert not any(r.get("reviewStatus") == "verified" for r in records)


@pytest.mark.anyio
async def test_current_candidate_mapping_remains_unknown_through_entire_path(monkeypatch):
    install_http(
        monkeypatch,
        lambda req: httpx.Response(
            200,
            json=evidence(
                name="향료",
                status="unknown",
                verdict="UNKNOWN",
                mappingStatus="candidate",
                reviewStatus="unreviewed",
                ingredientCoverage="unknown",
                ingredients=[],
                reason="mapping_not_verified",
            ),
        ),
    )
    result = await ChatService(
        None,
        PlanLlm(intent="detail", ingredientName="향료"),
        IngredientsCatalog(CatalogClient("http://catalog.test")),
    ).answer(request(context()))
    assert result.ingredient_results[0].verdict == "UNKNOWN"
    assert result.supervisor.result.conditions[0].verdict == "UNKNOWN"
    assert "매핑이 미확인" in result.answer


@pytest.mark.anyio
async def test_ar_selection_is_read_only_and_product_specific_general_never_uses_graph(monkeypatch):
    install_http(monkeypatch, lambda req: httpx.Response(200, json=evidence()))
    catalog = IngredientsCatalog(CatalogClient("http://catalog.test"))
    llm = PlanLlm(intent="general")  # Conservative guard against a bad interpretation.
    req = request(
        ar_context={
            "screenId": "A-01",
            "stateVersion": 2,
            "activeZone": "lip",
            "supportedActions": ["set_intensity"],
            "lip": {"productId": "a", "shadeId": "a-03", "intensity": 0.5},
        }
    )
    before = req.ar_context.model_dump()
    result = await ChatService(None, llm, catalog).answer(req)
    assert llm.calls == 1 and result.ar_result is None
    assert req.ar_context.model_dump() == before
    assert result.supervisor.result.tool == "beauty"
    assert result.ingredient_results[0].verified


@pytest.mark.anyio
async def test_unknown_fragrance_does_not_replace_later_price_question(monkeypatch):
    ctx = context()
    ctx.filters.fragrance_free = True
    catalog = IngredientsCatalog(CatalogClient("http://must-not-call.test"))
    result = await ChatService(None, PlanLlm(intent="price"), catalog).answer(request(ctx))
    assert "15,000" in result.answer and not catalog.calls


@pytest.mark.anyio
@pytest.mark.parametrize("locale", ["ko", "en", "ja", "zh"])
@pytest.mark.parametrize(
    "reason,status",
    [
        ("product_not_found", 404),
        ("shade_not_found", 404),
        ("source_unavailable", 503),
    ],
)
async def test_lookup_status_user_answers_in_all_locales(monkeypatch, locale, reason, status):
    code = "not_found" if reason == "product_not_found" else reason
    install_http(monkeypatch, lambda req: httpx.Response(status, json={"code": code}))
    result = await ChatService(
        None,
        PlanLlm(intent="detail", ingredientLookup=True),
        IngredientsCatalog(CatalogClient("http://catalog.test")),
    ).answer(request(context(), locale))
    assert result.ingredient_results[0].reason == reason
    assert result.supervisor.result.status == "error" and result.products
    assert result.result_type != "empty"


@pytest.mark.anyio
async def test_unknown_shade_label_and_colliding_numeric_labels_never_pick_first(monkeypatch):
    catalog = IngredientsCatalog(CatalogClient("http://must-not-call.test"))
    catalog.products[0].shades.append(
        catalog.products[0].shades[0].model_copy(update={"id": "a-03-2", "name": "03 Other"})
    )
    for label in ["03", "99"]:
        result = await ChatService(
            None, PlanLlm(intent="detail", ingredientLookup=True, shadeName=label), catalog
        ).answer(request(context(), message=f"그 제품 {label}호 성분은?"))
        assert result.ingredient_results[0].reason == "shade_required"
        assert not catalog.calls


@pytest.mark.anyio
async def test_llm_cannot_supply_an_unrequested_valid_shade(monkeypatch):
    catalog = IngredientsCatalog(CatalogClient("http://must-not-call.test"))
    result = await ChatService(
        None, PlanLlm(intent="detail", ingredientLookup=True, shadeName="03"), catalog
    ).answer(request(context(shades=False)))
    assert result.result_type == "clarification" and not catalog.calls


@pytest.mark.anyio
async def test_condition_option_mismatch_is_invalid_response(monkeypatch):
    body = evidence(name="향료")
    body["conditions"][0]["optionId"] = "another-products-option"
    install_http(monkeypatch, lambda req: httpx.Response(200, json=body))
    with pytest.raises(IngredientLookupError, match="invalid_response"):
        await CatalogClient("http://catalog.test").get_ingredients(
            "a", "a-03", ingredient_name="향료"
        )


def test_production_never_verifies_synthetic_contract(monkeypatch):
    from types import SimpleNamespace

    from app.schemas.catalog import CatalogIngredients

    monkeypatch.setattr(
        "app.schemas.catalog.get_settings", lambda: SimpleNamespace(is_production=True)
    )
    result = CatalogIngredients.model_validate(evidence(name="향료"))
    assert not result.verified and not result.complete
    assert result.verdict == "UNKNOWN" and result.review_status == "unreviewed"
    assert not result.ingredients and result.conditions[0].verdict == "UNKNOWN"
    body = evidence(name="향료", synthetic=False)
    for condition in body["conditions"]:
        condition["synthetic"] = False
    result = CatalogIngredients.model_validate(body)
    assert result.verified and result.complete


@pytest.mark.anyio
async def test_production_client_sanitizes_synthetic_upstream_facts(monkeypatch):
    from types import SimpleNamespace

    monkeypatch.setattr(
        "app.schemas.catalog.get_settings", lambda: SimpleNamespace(is_production=True)
    )
    install_http(monkeypatch, lambda req: httpx.Response(200, json=evidence(name="향료")))
    result = await CatalogClient("http://catalog.test").get_ingredients(
        "a", "a-03", ingredient_name="향료"
    )
    assert result.status == "unknown" and result.verdict == "UNKNOWN"
    assert not result.ingredients and not result.verified

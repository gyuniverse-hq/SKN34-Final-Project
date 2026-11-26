"""N02 exact-match contract: synthetic Catalog and server-selected consented memory."""

from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.core.config import get_settings
from app.core.errors import UpstreamError
from app.schemas.catalog import CatalogLook, CatalogProduct
from app.schemas.chat import ChatRequest, ChatResponse
from app.schemas.memory import ConsultationMemory, StructuredMemoryValue
from app.services.chat_service import ChatService
from app.services.consultation_memory import select_consultation_memories
from app.services.memory_registry import REGISTRY_VERSION
from app.services.owned_look_consultation_service import execute_owned_look, may_consult_owned_look


@pytest.fixture
def anyio_backend():
    return "asyncio"


def product(pid, zone):
    return CatalogProduct(
        id=pid,
        brand="Fixture",
        name=pid,
        nameKo=pid,
        category="lip" if zone == "lip" else "cheek",
        makeupZone=zone,
        texture="cream",
        priceKRW=12000,
        description="Synthetic",
        keyIngredients=[],
        tags=[],
        shades=[{"id": pid + "-shade", "name": "Fixture shade", "hex": "#A56270"}],
    )


class Catalog:
    def __init__(self):
        self.products = {"lip-a": product("lip-a", "lip"), "blush-b": product("blush-b", "blush")}
        self.searches = []
        self.look_calls = []
        self.fail_ids = set()
        self.stale_shade = False
        self.look = CatalogLook.model_validate(
            {
                "id": "fixture-look",
                "title": "Synthetic look",
                "tags": [],
                "items": [
                    {"productId": pid, "shadeId": pid + "-shade", "step": zone}
                    for pid, zone in [("lip-a", "lip"), ("blush-b", "blush")]
                ],
                "recipe": {
                    "lookId": "fixture-look",
                    "kind": "catalog",
                    "version": "fixture-v1",
                    "reviewStatus": "verified",
                    "reviewerId": "fixture-reviewer",
                    "source": "fixture:recipe",
                    "evidenceId": "fixture:recipe-evidence",
                    "synthetic": True,
                    "steps": [
                        {
                            "order": 1,
                            "zone": "blush",
                            "title": "블러셔",
                            "description": "합성 볼 단계",
                        },
                        {"order": 2, "zone": "lip", "title": "립", "description": "합성 립 단계"},
                    ],
                },
            }
        )

    async def search_products(self, **query):
        self.searches.append(query)
        ids = query.get("ids", list(self.products))
        if self.fail_ids.intersection(ids):
            raise UpstreamError("fixture unavailable")
        rows = [p.model_copy(deep=True) for p in self.products.values() if p.id in ids]
        if self.stale_shade and ids == ["blush-b"]:
            rows[0].shades = []
        return rows

    async def get_style_look(self, kind, look_id):
        self.look_calls.append((kind, look_id))
        return self.look if (kind, look_id) == ("catalog", "fixture-look") else None

    async def get_product(self, pid):
        return self.products.get(pid)


def owned(pid, shade=None):
    value = {"productName": "Fixture " + pid, "productId": pid}
    if shade is not None:
        value["shadeId"] = shade
    return ConsultationMemory(
        id=uuid4(),
        version=1,
        structured=StructuredMemoryValue(
            key="inventory.product",
            kind="owned_product",
            value=value,
            displayValue="Fixture " + pid,
        ),
    )


def request(memories, suffix=""):
    req = ChatRequest(
        message="내가 가진 립으로 이 룩을 따라 해보고, 필요한 것만 추가 추천해줘. " + suffix,
        locale="ko",
        structuredMemory=True,
        requestType="beauty_consultation",
        styleContext={"kind": "catalog", "lookId": "fixture-look"},
    )
    req._g7_execution = SimpleNamespace(owner_id="synthetic-owner")
    req._consultation_memories = tuple(memories)
    return req


@pytest.fixture(autouse=True)
def enabled(monkeypatch):
    monkeypatch.setattr(get_settings(), "g8_enabled", True)


@pytest.mark.anyio
async def test_owned_match_skips_satisfied_zone_and_only_queries_confirmed_need(record_property):
    catalog = Catalog()
    req = request([owned("lip-a", "lip-a-shade")], "블러셔는 없어. 추가 추천해줘.")
    before = req._consultation_memories
    trace = []
    response = await execute_owned_look(req, catalog, trace=trace)
    assert catalog.searches == [{"ids": ["lip-a"]}, {"ids": ["blush-b"]}]
    assert [p.id for p in response.products] == ["blush-b"]
    assert response.ar_result is None and response.memory_proposal is None
    assert response.style_recipe.evidence_id == "fixture:recipe-evidence"
    assert response.style_recipe.synthetic is True
    assert response.applied_memories[0].product_id == "lip-a"
    assert response.applied_memories[0].shade_id == "lip-a-shade"
    assert req._consultation_memories == before
    needs = next(t for t in trace if t["task"]["taskId"] == "N1")
    products = next(t for t in trace if t["task"]["taskId"] == "P1")
    assert needs["result"]["coverage"][0]["status"] == "confirmed_missing"
    assert needs["result"]["coverage"][1]["status"] == "fulfilled"
    assert products["inputs"]["coverage"][0]["zone"] == "blush"
    assert products["inputs"]["queries"] == [{"zone": "blush", "ids": ["blush-b"]}]
    assert (
        ChatResponse.model_validate(response.model_dump(mode="json")).products == response.products
    )
    record_property(
        "n02_exact_connection",
        {
            "tasks": trace,
            "answer": response.answer,
            "catalog": "mock",
            "modelConfiguredMode": "not_called",
            "actualRemoteModelCalls": 0,
        },
    )


@pytest.mark.anyio
async def test_normal_chat_service_connects_owned_look_without_model():
    from tests.conftest import FakeLlm

    catalog = Catalog()
    llm = FakeLlm(configured=False)
    req = request([owned("lip-a", "lip-a-shade")], "블러셔는 없어.")
    response = await ChatService(None, llm, catalog).answer(req)
    assert [p.id for p in response.products] == ["blush-b"]
    assert catalog.searches == [{"ids": ["lip-a"]}, {"ids": ["blush-b"]}]
    assert response.ar_result is None and response.memory_proposal is None
    assert llm.messages == []


@pytest.mark.anyio
async def test_changed_owned_and_missing_zone_changes_downstream_request():
    catalog = Catalog()
    req = request([owned("blush-b", "blush-b-shade")], "립은 없어. 추가 추천해줘.")
    response = await execute_owned_look(req, catalog)
    assert catalog.searches == [{"ids": ["blush-b"]}, {"ids": ["lip-a"]}]
    assert [p.id for p in response.products] == ["lip-a"]


@pytest.mark.anyio
async def test_unknown_ownership_is_not_a_missing_product():
    catalog = Catalog()
    response = await execute_owned_look(request([owned("lip-a", "lip-a-shade")]), catalog)
    assert catalog.searches == [{"ids": ["lip-a"]}]
    assert not response.products and response.result_type == "clarification"
    assert "제품도 가지고 있나요" in response.answer
    empty = await execute_owned_look(request([]), Catalog())
    assert not empty.products and "실제 미보유를 뜻하지는" in empty.answer


@pytest.mark.anyio
@pytest.mark.parametrize("suffix", ["블러셔는 없어?", "블러셔는 없다고 말한 적 없어."])
async def test_questions_or_quoted_absence_are_not_inventory_confirmation(suffix):
    catalog = Catalog()
    response = await execute_owned_look(request([owned("lip-a", "lip-a-shade")], suffix), catalog)
    assert not response.products and len(catalog.searches) == 1


@pytest.mark.anyio
async def test_unimplemented_filter_is_not_silently_ignored():
    catalog = Catalog()
    response = await execute_owned_look(
        request([owned("lip-a", "lip-a-shade")], "블러셔는 없어. 저자극 제품 추천해줘."), catalog
    )
    assert not response.products and len(catalog.searches) == 1
    assert "조건을 확인하기 전에는" in response.answer


@pytest.mark.anyio
@pytest.mark.parametrize("mode", ["no_consent", "no_server", "memory_optout", "no_memory_context"])
async def test_unscoped_or_opted_out_memory_is_not_read(mode):
    catalog = Catalog()
    req = request([owned("lip-a", "lip-a-shade")])
    if mode == "no_consent":
        req.structured_memory = False
    elif mode == "no_server":
        req._g7_execution = None
    elif mode == "memory_optout":
        req.message += " 기억은 쓰지 마."
    else:
        req._consultation_memories = None
    response = await execute_owned_look(req, catalog)
    assert response.result_type == "clarification"
    assert not catalog.searches and not catalog.look_calls


@pytest.mark.anyio
async def test_unverified_recipe_or_retired_shade_never_becomes_match():
    catalog = Catalog()
    catalog.look.recipe = None
    response = await execute_owned_look(
        request([owned("lip-a", "lip-a-shade")], "블러셔는 없어."), catalog
    )
    assert not response.products and not response.applied_memories
    assert len(catalog.searches) == 1
    catalog = Catalog()
    response = await execute_owned_look(request([owned("lip-a", "retired-shade")]), catalog)
    assert not response.applied_memories and not response.products
    assert "립 제품도 가지고 있나요" in response.answer or "립" in response.answer


@pytest.mark.anyio
async def test_product_result_is_rechecked_against_recipe_shade():
    catalog = Catalog()
    catalog.stale_shade = True
    response = await execute_owned_look(
        request([owned("lip-a", "lip-a-shade")], "블러셔는 없어."), catalog
    )
    assert not response.products
    assert "정확한 상품·호수를 다시 확인하지 못했어요" in response.answer


@pytest.mark.anyio
async def test_owned_ids_are_batched_without_dropping_seventh():
    catalog = Catalog()
    memories = []
    for i in range(7):
        pid = f"extra-{i}"
        catalog.products[pid] = product(pid, "lip")
        memories.append(owned(pid, pid + "-shade"))
    await execute_owned_look(request(memories), catalog)
    assert len(catalog.searches) == 2
    assert catalog.searches[-1] == {"ids": ["extra-6"]}


def test_original_n02_selects_only_consented_inventory_topic():
    req = request([])
    memory = owned("lip-a", "lip-a-shade")
    row = SimpleNamespace(
        id=memory.id,
        version=1,
        schema_version=2,
        registry_version=REGISTRY_VERSION,
        semantic_key="inventory.product",
        kind="owned_product",
        value_json=memory.structured.value,
        applicability_json={},
        consent_scope="future_consultations",
        revoked_at=None,
        updated_at=datetime.now(UTC),
    )
    assert may_consult_owned_look(req)
    assert [m.id for m in select_consultation_memories(req, [row])] == [row.id]
    from app.schemas.owned_look_context import OwnedLookContext

    req._owned_look_context = OwnedLookContext(
        kind="catalog", look_id="fixture-look", recipe_version="fixture-v1"
    )
    req.message = "블러셔는 이제 있어."
    assert [m.id for m in select_consultation_memories(req, [row])] == [row.id]
    req.message = "오늘 날씨 설명해줘"
    assert select_consultation_memories(req, [row]) == ()
    req.message = "다시 추천해줘"
    row.revoked_at = datetime.now(UTC)
    assert select_consultation_memories(req, [row]) == ()


def test_g8_off_does_not_enter(monkeypatch):
    monkeypatch.setattr(get_settings(), "g8_enabled", False)
    assert not may_consult_owned_look(request([]))


@pytest.mark.anyio
@pytest.mark.parametrize(
    "suffix",
    ["얼굴에 발라줘", "AR 켜줘", "이 제품 기억해줘", "장바구니에 넣어줘", "강도를 조절해줘"],
)
async def test_mixed_execution_stays_with_parent_without_reading_inventory(suffix):
    req = request([owned("lip-a", "lip-a-shade")], suffix)
    catalog = Catalog()
    assert not may_consult_owned_look(req)
    assert await execute_owned_look(req, catalog) is None
    assert not catalog.searches and not catalog.look_calls


@pytest.mark.anyio
async def test_followup_declarations_change_real_queries_and_release():
    catalog = Catalog()
    req = request([owned("lip-a", "lip-a-shade")], "블러셔는 없어.")
    first = await execute_owned_look(req, catalog)
    state = first._owned_look_context
    assert state.declarations["blush"].source == "user"
    for text, expected, status in [
        ("다시 추천해줘", ["blush-b"], "missing"),
        ("블러셔는 이제 있어.", [], "present"),
        ("블러셔 미보유 조건 해제해줘", [], None),
        ("블러셔는 없어.", ["blush-b"], "missing"),
        ("미보유 조건 전부 해제해줘", [], None),
    ]:
        follow = req.model_copy(update={"message": text})
        follow._owned_look_context = state
        catalog.searches.clear()
        result = await execute_owned_look(follow, catalog)
        assert [p.id for p in result.products] == expected
        assert catalog.searches == (
            [{"ids": ["lip-a"]}, {"ids": ["blush-b"]}] if expected else [{"ids": ["lip-a"]}]
        )
        state = result._owned_look_context
        assert (
            state.declarations["blush"].status if "blush" in state.declarations else None
        ) == status
        assert "ownedLook" not in result.model_dump(by_alias=True)


@pytest.mark.anyio
async def test_changed_recipe_invalidates_missing_declaration():
    catalog = Catalog()
    req = request([owned("lip-a", "lip-a-shade")], "블러셔는 없어.")
    first = await execute_owned_look(req, catalog)
    req._owned_look_context = first._owned_look_context
    req.message = "다시 추천해줘"
    catalog.look.recipe.version = "fixture-v2"
    catalog.searches.clear()
    response = await execute_owned_look(req, catalog)
    assert not response.products
    assert not response._owned_look_context.declarations
    assert catalog.searches == [{"ids": ["lip-a"]}]


@pytest.mark.parametrize(
    "text",
    [
        "블러셔는 없어?",
        "블러셔는 없어도 괜찮아",
        "친구는 블러셔가 없어.",
        "블러셔는 없다고 말했어",
        "블러셔 미보유 조건 해제해줘. 얼굴에 발라줘",
        "블러셔는 있어?",
        "블러셔 기억 삭제해줘",
    ],
)
@pytest.mark.anyio
async def test_ambiguous_or_execution_followup_does_not_change_declarations(text):
    catalog = Catalog()
    req = request([owned("lip-a", "lip-a-shade")], "블러셔는 없어.")
    first = await execute_owned_look(req, catalog)
    req._owned_look_context = first._owned_look_context
    req.message = text
    before = req._owned_look_context.model_dump()
    catalog.searches.clear()
    response = await execute_owned_look(req, catalog)
    assert response is None
    assert not catalog.searches
    assert req._owned_look_context.model_dump() == before


@pytest.mark.anyio
async def test_catalog_failure_preserves_declaration_and_allows_release():
    catalog = Catalog()
    req = request([owned("lip-a", "lip-a-shade")], "블러셔는 없어.")
    first = await execute_owned_look(req, catalog)
    req._owned_look_context = first._owned_look_context
    req.message = "다시 추천해줘"
    failure = await execute_owned_look(req, None)
    assert failure._owned_look_context.declarations["blush"].status == "missing"
    assert not failure.products
    req.message = "미보유 조건 전부 해제해줘"
    released = await execute_owned_look(req, None)
    assert not released._owned_look_context.declarations


@pytest.mark.anyio
async def test_look_switch_and_clear_selection_invalidate_conditions():
    from app.schemas.conversation import UpdateConversationStateRequest
    from app.services.conversation_context import apply_state_update, updated_context

    catalog = Catalog()
    req = request([owned("lip-a", "lip-a-shade")], "블러셔는 없어.")
    first = await execute_owned_look(req, catalog)
    raw = updated_context({"schemaVersion": 1}, first)
    assert raw["ownedLook"]["declarations"]["blush"]["source"] == "user"
    assert "ownedLook" not in updated_context(raw, ChatResponse(answer="다른 상담", products=[]))

    class OtherCatalog:
        async def get_style_look(self, kind, look_id):
            return SimpleNamespace(id=look_id)

    chat = SimpleNamespace(_catalog=OtherCatalog())
    for operation, payload in [
        ("select_look", {"kind": "catalog", "lookId": "different-look"}),
        ("clear_selection", {}),
    ]:
        body = UpdateConversationStateRequest(
            requestId=uuid4(), expectedConversationVersion=1, operation=operation, payload=payload
        )
        result = await apply_state_update(raw, {"type": "general"}, body, chat)
        assert "ownedLook" not in result


class FilteredCatalog(Catalog):
    def __init__(self):
        super().__init__()
        self.option_calls = []
        self.ingredient_verdict = "MATCH"
        self.wrong_shade = False
        self.fail_options = False

    async def search_options(self, req):
        from app.schemas.catalog import OptionSearchResponse

        self.option_calls.append(req)
        if self.fail_options:
            raise UpstreamError("synthetic option outage")
        items, products = [], []
        for pid in req.product_ids:
            p = self.products[pid]
            checks = [{"condition": "identity", "verdict": "MATCH", "reason": "fixture_identity"}]
            if req.max_price_krw is not None:
                checks.append(
                    {
                        "condition": "price",
                        "verdict": "MATCH" if p.price_krw <= req.max_price_krw else "NOT_MATCH",
                        "reason": "fixture_price",
                    }
                )
            checks.extend(
                {
                    "condition": "ingredient",
                    "ingredientName": c.ingredient_name,
                    "operator": c.operator,
                    "verdict": self.ingredient_verdict,
                    "reason": "fixture_ingredient",
                    "ingredientCoverage": "full",
                    "sourceVersion": "synthetic-v1",
                }
                for c in req.ingredient_conditions
            )
            if req.fragrance_free:
                checks.append(
                    {
                        "condition": "fragrance_free",
                        "verdict": self.ingredient_verdict,
                        "reason": "fixture_fragrance",
                    }
                )
            verdicts = {c["verdict"] for c in checks}
            group = (
                "EXCLUDED"
                if "NOT_MATCH" in verdicts
                else "ELIGIBLE"
                if verdicts == {"MATCH"}
                else "REFERENCE_ONLY"
            )
            items.append(
                {
                    "productId": pid,
                    "shadeId": "wrong-shade" if self.wrong_shade else p.shades[0].id,
                    "optionId": pid + "-sale",
                    "sourceVersion": "synthetic-v1",
                    "synthetic": True,
                    "group": group,
                    "checks": checks,
                }
            )
            if group != "EXCLUDED":
                products.append(p)
        return OptionSearchResponse.model_validate(
            {
                "effectiveRequest": req,
                "checkedAt": "2026-11-26T00:00:00Z",
                "status": "PARTIAL"
                if any(i["group"] == "REFERENCE_ONLY" for i in items)
                else "SUCCESS",
                "items": items,
                "products": products,
                "limitations": [],
                "excludedCount": sum(i["group"] == "EXCLUDED" for i in items),
                "omittedCount": 0,
                "checkedScope": {
                    "candidateProducts": len(items),
                    "candidateOptions": len(items),
                    "checkedOptions": len(items),
                    "unidentifiedOptions": 0,
                    "exhaustive": True,
                    "stoppedReason": "COMPLETE",
                    "errors": 0,
                },
            }
        )


@pytest.mark.anyio
async def test_budget_ingredient_keep_change_release_actual_tool_inputs(record_property):
    catalog = FilteredCatalog()
    req = request([owned("lip-a", "lip-a-shade")], "블러셔는 없어. 2만원 이하, 향료 제외.")
    trace, turns = [], []
    for message, expected, price, conditions in [
        (req.message, ["blush-b"], 20000, 1),
        ("예산은 1만원 이하", [], 10000, 1),
        ("예산 조건 해제해줘", ["blush-b"], None, 1),
        ("향료 제외 조건 해제해줘", ["blush-b"], None, 0),
    ]:
        req.message = message
        before = len(catalog.option_calls)
        response = await execute_owned_look(req, catalog, trace=trace)
        assert [p.id for p in response.products] == expected
        req._owned_look_context = response._owned_look_context
        filters = req._owned_look_context.filters
        assert filters.max_price_krw == price
        assert len(filters.ingredient_conditions) == conditions
        if price is not None or conditions:
            call = catalog.option_calls[-1]
            assert call.max_price_krw == price
            assert len(call.ingredient_conditions) == conditions
            assert call.product_ids == ["blush-b"]
        else:
            assert len(catalog.option_calls) == before
        turns.append(
            {
                "message": message,
                "answer": response.answer,
                "products": [p.id for p in response.products],
                "filters": filters.model_dump(mode="json", by_alias=True),
                "modelMode": "not_used",
                "modelCalls": 0,
            }
        )
    record_property(
        "n02_filters_mock",
        __import__("json").dumps(
            {
                "catalogMode": "mock",
                "turns": turns,
                "tasks": trace,
                "requests": [
                    q.model_dump(mode="json", by_alias=True) for q in catalog.option_calls
                ],
            },
            ensure_ascii=False,
        ),
    )


@pytest.mark.anyio
@pytest.mark.parametrize("mode", ["unknown", "excluded", "failed", "wrong_shade"])
async def test_unverified_conditions_or_other_shade_never_make_recommendation(mode):
    catalog = FilteredCatalog()
    catalog.ingredient_verdict = {"unknown": "UNKNOWN", "excluded": "NOT_MATCH"}.get(mode, "MATCH")
    catalog.fail_options = mode == "failed"
    catalog.wrong_shade = mode == "wrong_shade"
    response = await execute_owned_look(
        request([owned("lip-a", "lip-a-shade")], "블러셔는 없어. 2만원 이하, 향료 제외."), catalog
    )
    assert not response.products
    assert {
        "unknown": "미확인 1개",
        "excluded": "불일치 1개",
        "failed": "조회에 실패",
        "wrong_shade": "옵션 근거를 확보하지 못",
    }[mode] in response.answer


@pytest.mark.anyio
async def test_option_batches_do_not_drop_seventh_recipe_candidate():
    catalog = FilteredCatalog()
    for i in range(7):
        pid = f"blush-extra-{i}"
        catalog.products[pid] = product(pid, "blush")
        catalog.look.items.append(
            type(catalog.look.items[0]).model_validate(
                {"productId": pid, "shadeId": pid + "-shade", "step": "blush"}
            )
        )
    response = await execute_owned_look(
        request([owned("lip-a", "lip-a-shade")], "블러셔는 없어. 2만원 이하."), catalog
    )
    assert len(response.products) == 8
    assert [len(call.product_ids) for call in catalog.option_calls] == [6, 2]


@pytest.mark.anyio
async def test_same_zone_owned_alternative_is_not_a_verified_substitute():
    catalog = Catalog()
    catalog.products["different-lip"] = product("different-lip", "lip")
    trace = []
    response = await execute_owned_look(
        request([owned("different-lip", "different-lip-shade")]), catalog, trace=trace
    )
    coverage = next(t for t in trace if t["task"]["taskId"] == "N1")["result"]["coverage"]
    lip = next(c for c in coverage if c["zone"] == "lip")
    assert lip["substitutionStatus"] == "unverified"
    assert lip["alternativeProductIds"] == ["different-lip"]
    assert lip["substitutionEvidence"] is None
    assert not response.products and not response.applied_memories


def test_filter_alias_limit_and_unknown_expression_fail_closed():
    from app.services.owned_look_filters import update_filters

    filters = update_filters(
        None,
        "향료 제외, Fragrance 제외, 에탄올 제외, 글리세린 제외, "
        "판테놀 제외, 나이아신아마이드 제외, 살리실산 제외",
    )
    assert len(filters.ingredient_conditions) == 6 and not filters.unsupported
    overflow = update_filters(filters, "벤조산 제외")
    assert overflow.unsupported and len(overflow.ingredient_conditions) == 6
    assert not update_filters(overflow, "상품 조건 전체 해제해줘").unsupported
    assert update_filters(None, "향료 제외하지 마").unsupported
    assert update_filters(None, "2만원에서 3만원 사이").unsupported
    long_name = update_filters(None, "성분 " + "a" * 121 + " 제외")
    assert long_name.unsupported and not long_name.ingredient_conditions


@pytest.mark.anyio
async def test_live_catalog_budget_ingredient_option_contract(record_property):
    import json
    import os

    from app.clients.catalog_client import CatalogClient
    from app.schemas.catalog import OptionSearchRequest
    from app.services.owned_look_filters import update_filters

    base = os.environ.get("G8_N02_LIVE_CATALOG")
    if not base:
        pytest.skip("live Catalog opt-in required")
    catalog = CatalogClient(base)
    products = await catalog.search_products(category="lip")
    assert products
    product = next(p for p in products if p.shades)
    observations = []
    filters = None
    for text in ["2만원 이하", "예산은 1만원 이하, 향료 제외", "성분 조건 전체 해제해줘"]:
        filters = update_filters(filters, text)
        assert not filters.unsupported
        req = OptionSearchRequest(
            product_ids=[product.id],
            maxPriceKRW=filters.max_price_krw,
            ingredient_conditions=filters.ingredient_conditions,
            fragrance_free=filters.fragrance_free,
            price_basis=filters.price_basis,
        )
        result = await catalog.search_options(req)
        assert result.effective_request == req
        assert result.status != "ERROR", result.checked_scope
        assert result.items, "No identified sale option was returned"
        assert all(i.product_id == product.id for i in result.items)
        observations.append(
            {
                "message": text,
                "request": req.model_dump(mode="json", by_alias=True),
                "result": result.model_dump(mode="json", by_alias=True),
                "modelMode": "not_used",
                "modelCalls": 0,
            }
        )
    assert observations[0]["request"]["maxPriceKRW"] == 20000
    assert observations[1]["request"]["maxPriceKRW"] == 10000
    assert len(observations[1]["request"]["ingredientConditions"]) == 1
    assert observations[2]["request"]["ingredientConditions"] == []
    record_property(
        "n02_filters_live_options",
        json.dumps(
            {
                "catalogMode": "live HTTP",
                "scope": "direct option contract, not positive look recommendation",
                "productId": product.id,
                "knownShadeIds": [s.id for s in product.shades],
                "observations": observations,
            },
            ensure_ascii=False,
        ),
    )


@pytest.mark.anyio
async def test_recipe_revision_does_not_silently_drop_explicit_shopping_filters():
    catalog = FilteredCatalog()
    req = request([owned("lip-a", "lip-a-shade")], "블러셔는 없어. 1만원 이하, 향료 제외.")
    first = await execute_owned_look(req, catalog)
    req._owned_look_context = first._owned_look_context
    catalog.look.recipe.version = "fixture-v2"
    req.message = "블러셔는 없어."
    second = await execute_owned_look(req, catalog)
    assert not second.products
    assert catalog.option_calls[-1].max_price_krw == 10000
    assert catalog.option_calls[-1].ingredient_conditions[0].ingredient_name == "향료"

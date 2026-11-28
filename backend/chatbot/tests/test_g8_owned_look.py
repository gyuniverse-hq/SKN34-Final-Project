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

    async def get_product_option(self, pid, oid):
        from app.schemas.catalog import CatalogProductOption

        return CatalogProductOption(product_id=pid, option_id=oid, name="Synthetic option")

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
@pytest.mark.parametrize(
    "ambiguous,usage,catalog_zone,stale_shade",
    [
        (True, False, "blush", False),
        (False, False, "blush", False),
        (True, True, "blush", False),
        (True, True, None, False),
        (False, False, None, False),
        (True, True, "lip", False),
        (True, True, None, True),
    ],
)
async def test_video_zone_ambiguity_does_not_satisfy_or_recommend_step(
    ambiguous, usage, catalog_zone, stale_shade, record_property
):
    import json

    from app.schemas.catalog import CatalogStyleLook

    catalog = Catalog()
    recipe = catalog.look.recipe.model_copy(update={"kind": "video"})
    catalog.look = CatalogStyleLook.model_validate(
        {
            "id": "fixture-look",
            "title": "Synthetic video",
            "group": "fixture",
            "tag": "fixture",
            "videoUrl": "https://www.youtube.com/watch?v=fixture-look",
            "recipe": recipe,
            "products": [
                {
                    "number": i,
                    "brand": "Fixture",
                    "name": pid,
                    "option": "Fixture shade",
                    "category": "cheek" if zone == "blush" else "lip",
                    "zone": "베이스·블러셔" if zone == "blush" and ambiguous else zone,
                    "reviewStatus": "verified",
                    "mappingVerified": True,
                    "catalogProductId": pid,
                    "catalogShadeId": pid + "-shade",
                }
                for i, (pid, zone) in enumerate([("blush-b", "blush"), ("lip-a", "lip")], 1)
            ],
        }
    )

    if usage:
        from app.schemas.style_recipe import ReviewedProductUsage

        catalog.look.recipe.product_usages = [
            ReviewedProductUsage(
                stepOrder=1,
                productId="blush-b",
                shadeId="blush-b-shade",
                evidenceId="fixture:usage",
                source="fixture:segment",
            )
        ]
    catalog.products["blush-b"].makeup_zone = catalog_zone
    catalog.stale_shade = stale_shade
    unresolved = ambiguous and not usage
    eligible = not stale_shade and (
        catalog_zone == "blush" or (catalog_zone is None and (usage or not ambiguous))
    )

    async def selected(kind, look_id):
        return catalog.look if (kind, look_id) == ("video", "fixture-look") else None

    catalog.get_style_look = selected
    req = request(
        [owned("lip-a", "lip-a-shade"), owned("blush-b", "blush-b-shade")], "블러셔는 없어."
    )
    req.style_context.kind = "video"
    trace = []
    response = await execute_owned_look(req, catalog, trace=trace)
    needs = next(row["result"]["coverage"] for row in trace if row["task"]["taskId"] == "N1")
    blush = next(c for c in needs if c["zone"] == "blush")
    assert next(c for c in needs if c["zone"] == "lip")["status"] == "fulfilled"
    assert blush["status"] == "confirmed_missing"
    assert [p.id for p in response.products] == (["blush-b"] if eligible else [])
    link = next(p for p in response.style_recipe.products if p.product_id == "blush-b")
    assert link.zone == ("unknown" if unresolved else "blush")
    if catalog_zone is None or catalog_zone == "lip":
        assert not link.ar_eligible
    if usage:
        assert link.product_usages[0].evidence_id == "fixture:usage"
    if unresolved:
        assert not link.ar_eligible
        assert blush["productIds"] == ["blush-b"]
        assert catalog.searches == [{"ids": ["lip-a", "blush-b"]}, {"ids": ["blush-b"]}]
    record_property(
        "zone_ambiguity_evidence",
        json.dumps(
            {
                "catalogMode": "mock",
                "modelMode": "not_used",
                "externalModelCalls": 0,
                "ambiguous": ambiguous,
                "reviewedUsage": usage,
                "catalogZone": catalog_zone,
                "staleShade": stale_shade,
                "tasks": trace,
                "response": response.model_dump(mode="json", by_alias=True),
            },
            ensure_ascii=False,
        ),
    )


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
    assert "제품을 가지고 있나요" in response.answer
    empty = await execute_owned_look(request([]), Catalog())
    assert not empty.products and "제품을 가지고 있나요" in empty.answer
    assert all(i.status == "ownership_unknown" for i in empty._owned_look_outcome.items)


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
async def test_general_guide_allows_exact_product_but_retired_shade_stays_unmatched():
    catalog = Catalog()
    catalog.look.recipe = None
    response = await execute_owned_look(
        request([owned("lip-a", "lip-a-shade")], "블러셔는 없어."), catalog
    )
    assert [p.id for p in response.products] == ["blush-b"]
    assert len(response.applied_memories) == 1
    assert response.style_recipe.basis != "reviewed_recipe"
    assert len(catalog.searches) == 2
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
    assert "추가 후보를 확정하지 못했어요" in response.answer


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
@pytest.mark.parametrize("request_type", ["chat", "style_consultation"])
async def test_mixed_execution_stays_with_parent_without_reading_inventory(suffix, request_type):
    req = request([owned("lip-a", "lip-a-shade")], suffix)
    req.request_type = request_type
    catalog = Catalog()
    assert not may_consult_owned_look(req)
    assert await execute_owned_look(req, catalog) is None
    assert not catalog.searches and not catalog.look_calls


def test_selected_look_explanation_alone_does_not_enter_owned_recommendation():
    req = request([])
    req.request_type = "style_consultation"
    req.message = "이 룩 화장법을 단계별로 알려줘"
    assert not may_consult_owned_look(req)


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
                        "verdict": "UNKNOWN"
                        if req.price_basis == "current_offer"
                        else "MATCH"
                        if req.max_price_krw >= 15000
                        else "NOT_MATCH",
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
                    "price": {
                        "amountKRW": 15000,
                        "requestedBasis": req.price_basis,
                        "observedBasis": "collected_snapshot",
                        "observedAt": "2026-11-25T00:00:00Z",
                        "checkedAt": "2026-11-26T00:00:00Z",
                        "sourceRef": "https://example.test/option",
                        "sourceVersion": "synthetic-v1",
                    },
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
        "unknown": "정보가 부족해요",
        "excluded": "조건에 맞지 않아",
        "failed": "정보를 불러오지 못했어요",
        "wrong_shade": "정확한 옵션이나",
    }[mode] in response.answer
    expected_status = {
        "unknown": "evidence_missing",
        "excluded": "excluded",
        "failed": "lookup_failed",
        "wrong_shade": "evidence_missing",
    }[mode]
    assert (
        next(i for i in response._owned_look_outcome.items if i.zone == "blush").status
        == expected_status
    )


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
    assert len(response.owned_look_options.selections) == 8
    assert [len(b.items) for b in response.owned_look_options.batches] == [6, 2]


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
    assert "대체품으로 적합한지는 아직 확인하지 못했어요" in response.answer
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
    for text in [
        "2만원 이하",
        "예산은 1만원 이하, 향료 제외",
        "성분 조건 전체 해제해줘",
        "상품 조건 전체 해제해줘. 예산은 1만원 이하.",
        "상품 조건 전체 해제해줘. 현재가 기준으로 추천해줘.",
    ]:
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
    assert observations[3]["request"]["maxPriceKRW"] == 10000
    assert observations[4]["request"]["priceBasis"] == "current_offer"
    # Actual Catalog omits price evaluation without a budget. This is NOT live-price success.
    assert all(item["price"] is None for item in observations[4]["result"]["items"])
    assert not any(
        c["condition"] == "price" and c["verdict"] == "MATCH"
        for item in observations[4]["result"]["items"]
        for c in item["checks"]
    )
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


@pytest.mark.parametrize(
    "message, price, ingredients",
    [
        ("상품 조건 전체 해제해줘. 예산은 1만원 이하.", 10000, []),
        ("상품 조건 전체 해제해줘. 판테놀 제외.", None, ["판테놀"]),
        ("향료 제외. 성분 조건 전체 해제해줘.", 20000, []),
        ("성분 조건 전체 해제해줘. 향료 제외.", 20000, ["향료"]),
        ("상품 조건 전체 해제하고 예산은 1만원 이하", 10000, []),
        ("1만원 이하. 예산 조건 해제해줘.", None, ["향료"]),
    ],
)
def test_filter_operations_follow_user_order(message, price, ingredients):
    from app.services.owned_look_filters import update_filters

    previous = update_filters(None, "2만원 이하, 향료 제외")
    result = update_filters(previous, message)
    assert not result.unsupported
    assert result.max_price_krw == price
    assert [c.ingredient_name for c in result.ingredient_conditions] == ingredients


@pytest.mark.anyio
async def test_public_options_preserve_exact_selection_batch_price_and_serialization(
    record_property,
):
    from app.schemas.chat import ChatResponse

    catalog = FilteredCatalog()
    req = request([owned("lip-a", "lip-a-shade")], "블러셔는 없어. 2만원 이하, 향료 제외.")
    response = await execute_owned_look(req, catalog)
    payload = response.model_dump(mode="json", by_alias=True)
    display = payload["ownedLookOptions"]
    assert display["selections"][0]["shadeId"] == "blush-b-shade"
    assert display["selections"][0]["optionId"] == "blush-b-sale"
    assert display["batches"][0]["items"][0]["price"]["amountKRW"] == 15000
    assert display["batches"][0]["products"][0]["priceKRW"] != 15000
    assert ChatResponse.model_validate(payload).owned_look_options == response.owned_look_options
    req._owned_look_context = response._owned_look_context
    req.message = "상품 조건 전체 해제해줘. 예산은 1만원 이하."
    lower = await execute_owned_look(req, catalog)
    assert catalog.option_calls[-1].max_price_krw == 10000
    assert not catalog.option_calls[-1].ingredient_conditions
    assert not lower.products and not lower.owned_look_options.selections
    req._owned_look_context = lower._owned_look_context
    req.message = "상품 조건 전체 해제해줘. 현재가 기준으로 추천해줘."
    current = await execute_owned_look(req, catalog)
    assert catalog.option_calls[-1].price_basis == "current_offer"
    assert current.owned_look_options.batches
    assert not current.products and not current.owned_look_options.selections
    assert "실시간 현재가는 확인하지 못했어요" in current.answer
    record_property(
        "n02_option_delivery_mock",
        __import__("json").dumps(
            {
                "catalogMode": "mock",
                "actualModelCalls": 0,
                "turns": [
                    payload,
                    lower.model_dump(mode="json", by_alias=True),
                    current.model_dump(mode="json", by_alias=True),
                ],
                "requests": [
                    q.model_dump(mode="json", by_alias=True) for q in catalog.option_calls
                ],
            },
            ensure_ascii=False,
        ),
    )


@pytest.mark.anyio
@pytest.mark.parametrize("condition", [False, True])
async def test_unreviewed_video_sale_option_without_ar_is_queried_exactly(
    condition, record_property
):
    import json

    from app.schemas.catalog import CatalogStyleLook, OptionSearchResponse

    catalog = Catalog()
    catalog.products["blush-b"].shades = []
    look = CatalogStyleLook.model_validate(
        {
            "id": "fixture-look",
            "title": "General guide fixture",
            "group": "fixture",
            "tag": "fixture",
            "videoUrl": "https://www.youtube.com/watch?v=fixture-look",
            "products": [
                {
                    "number": 1,
                    "brand": "Fixture",
                    "name": "blush-b",
                    "option": "01",
                    "category": "cheek",
                    "zone": "blush",
                    "reviewStatus": "ok",
                    "mappingVerified": True,
                    "catalogProductId": "blush-b",
                    "catalogOptionId": "sale-01",
                    "catalogOptionSource": "raw_oy_product_option:sale-01",
                }
            ],
        }
    )
    calls = []

    async def selected(kind, look_id):
        return look

    async def options(req):
        calls.append(req)
        return OptionSearchResponse.model_validate(
            {
                "effectiveRequest": req,
                "checkedAt": "2026-11-27T00:00:00Z",
                "status": "PARTIAL" if condition else "SUCCESS",
                "products": [catalog.products["blush-b"]],
                "items": [
                    {
                        "productId": "blush-b",
                        "shadeId": None,
                        "optionId": "sale-01",
                        "optionName": "01 Rose",
                        "sourceVersion": "fixture",
                        "group": "REFERENCE_ONLY" if condition else "ELIGIBLE",
                        "checks": [
                            {"condition": "identity", "verdict": "MATCH", "reason": "fixture"}
                        ]
                        + (
                            [
                                {
                                    "condition": "fragrance",
                                    "verdict": "UNKNOWN",
                                    "reason": "no_evidence",
                                }
                            ]
                            if condition
                            else []
                        ),
                    }
                ],
                "checkedScope": {
                    "candidateProducts": 1,
                    "candidateOptions": 1,
                    "checkedOptions": 1,
                    "unidentifiedOptions": 0,
                    "exhaustive": True,
                    "stoppedReason": "COMPLETE",
                    "errors": 0,
                },
                "excludedCount": 0,
                "omittedCount": 0,
            }
        )

    catalog.get_style_look = selected
    catalog.search_options = options
    req = request([], "블러셔는 없어." + (" 향료 제외." if condition else ""))
    req.style_context.kind = "video"
    trace = []
    response = await execute_owned_look(req, catalog, trace=trace)
    assert len(calls) == 1
    assert calls[0].option_scope[0].option_id == "sale-01"
    assert calls[0].option_scope[0].shade_id is None
    assert [p.id for p in response.products] == ([] if condition else ["blush-b"])
    assert not response.style_recipe.products[0].ar_eligible
    assert response.style_recipe.basis == "video_metadata"
    assert response._consultation_answer.guidance
    assert all("None" not in line for line in response._consultation_answer.guidance)
    assert "None" not in response.answer
    if not condition:
        assert response.owned_look_options.selections[0].shade_id is None
        assert response.owned_look_options.selections[0].shade_name == "01 Rose"
        memory = owned("blush-b")
        memory.structured.value["optionId"] = "sale-01"
        held = request([memory])
        held.style_context.kind = "video"
        held_response = await execute_owned_look(held, catalog)
        assert [m.product_id for m in held_response.applied_memories] == ["blush-b"]
        assert not held_response.products
        memory.structured.value["optionId"] = "other-sale"
        other_response = await execute_owned_look(held, catalog)
        assert not other_response.applied_memories
    record_property(
        "sale_option_without_ar",
        json.dumps(
            {
                "catalogMode": "mock",
                "modelConfiguredMode": "not_used",
                "actualRemoteModelCalls": 0,
                "tasks": trace,
                "response": response.model_dump(mode="json", by_alias=True),
            },
            ensure_ascii=False,
        ),
    )


@pytest.mark.anyio
async def test_live_sale_option_without_ar_uses_current_catalog(record_property, monkeypatch):
    import json
    import os

    from app.clients.catalog_client import CatalogClient

    base = os.environ.get("G8_SALE_CATALOG_URL")
    if not base:
        pytest.skip("G8_SALE_CATALOG_URL current-source read-only Catalog required")
    from app.services import owned_look_consultation_service as owned_service
    from tests.conftest import FakeLlm

    catalog = CatalogClient(base)
    captured = []
    original = owned_service.execute_owned_look

    async def observed(req, catalog, *, trace=None):
        local = []
        result = await original(req, catalog, trace=local)
        captured.extend(local)
        if trace is not None:
            trace.extend(local)
        return result

    monkeypatch.setattr(owned_service, "execute_owned_look", observed)
    service = ChatService(None, FakeLlm(configured=False), catalog)
    req = request([], "아이섀도는 없어. 추가 추천해줘.")
    req.style_context.kind = "video"
    req.style_context.look_id = "AG03mUj4vnY"
    turns = []
    for message, expected in [
        (req.message, True),
        ("향료 제외 조건 추가해줘", False),
        ("향료 제외 조건 해제해줘", True),
    ]:
        req.message = message
        trace = []
        captured.clear()
        response = await service.answer(req)
        trace.extend(captured)
        req._owned_look_context = response._owned_look_context
        link = next(p for p in response.style_recipe.products if p.product_id == "oy-a000000162667")
        assert link.option_id == "A000000162667-012" and link.shade_id is None
        assert not link.ar_eligible
        assert ("oy-a000000162667" in [p.id for p in response.products]) is expected
        assert response.style_recipe.basis != "reviewed_recipe"
        assert response.ar_result is None
        turns.append(
            {
                "message": message,
                "catalogMode": "live_http_current_source",
                "databaseMode": "live_read_only",
                "modelConfiguredMode": "not_used",
                "actualRemoteModelCalls": 0,
                "tasks": trace,
                "response": response.model_dump(mode="json", by_alias=True),
            }
        )
    record_property("live_sale_option_without_ar", json.dumps(turns, ensure_ascii=False))


@pytest.mark.anyio
@pytest.mark.parametrize(
    "look_id,pid,oid,zone,label",
    [
        ("kWI7_DkDjZ0", "oy-a000000183683", "A000000183683-004", "lip", "립"),
        ("EiYeC-hlMNQ", "oy-a000000180532", "A000000180532-023", "eyeshadow", "아이섀도"),
    ],
)
async def test_live_other_looks_owned_and_alternative_boundary(
    look_id, pid, oid, zone, label, record_property
):
    import json
    import os

    from app.clients.catalog_client import CatalogClient

    base = os.environ.get("G8_SALE_CATALOG_URL")
    if not base:
        pytest.skip("current-source live Catalog required")
    catalog = CatalogClient(base)
    req = request([], f"{label}는 없어. 필요한 제품만 추가 추천해줘.")
    req.style_context.kind = "video"
    req.style_context.look_id = look_id
    cases = []
    trace = []
    reply = await execute_owned_look(req, catalog, trace=trace)
    assert pid in [p.id for p in reply.products]
    assert any(o.option_id == oid for o in reply.owned_look_options.selections)
    cases.append(
        {
            "case": "missing",
            "response": reply.model_dump(mode="json", by_alias=True),
            "tasks": trace,
        }
    )
    memory = owned(pid)
    memory.structured.value["optionId"] = oid
    req._consultation_memories = (memory,)
    req.message = "내가 가진 제품으로 이 룩을 따라 하고 필요한 것만 추천해줘."
    trace = []
    reply = await execute_owned_look(req, catalog, trace=trace)
    assert pid not in [p.id for p in reply.products]
    assert pid in [p.product_id for p in reply.applied_memories]
    cases.append(
        {
            "case": "same_sale_option",
            "response": reply.model_dump(mode="json", by_alias=True),
            "tasks": trace,
        }
    )
    if zone == "lip":
        alternative = await catalog.get_product("oy-a000000158896")
        assert alternative.makeup_zone == "lip"
        req._consultation_memories = (owned(alternative.id),)
        trace = []
        reply = await execute_owned_look(req, catalog, trace=trace)
        coverage = next(t["result"]["coverage"] for t in trace if t["task"]["taskId"] == "N1")
        area = next(c for c in coverage if c["zone"] == "lip")
        assert alternative.id in area["alternativeProductIds"]
        assert area["substitutionStatus"] == "unverified"
        assert not reply.applied_memories
        assert "같은 부위의 활용 후보" in reply.answer
        cases.append(
            {
                "case": "different_owned_product",
                "response": reply.model_dump(mode="json", by_alias=True),
                "tasks": trace,
            }
        )
    record_property(
        "live_other_look_cases",
        json.dumps(
            {
                "lookId": look_id,
                "catalogMode": "live_http_current_source",
                "inventoryMode": "synthetic_consented_fixture",
                "modelConfiguredMode": "not_used",
                "actualRemoteModelCalls": 0,
                "cases": cases,
            },
            ensure_ascii=False,
        ),
    )


class MultiLipCatalog(FilteredCatalog):
    """Two different listed lip products; joint use is deliberately unverified."""

    def __init__(self):
        super().__init__()
        self.products["lip-b"] = product("lip-b", "lip")
        self.look.items.append(
            self.look.items[0].model_copy(update={"product_id": "lip-b", "shade_id": "lip-b-shade"})
        )


@pytest.mark.anyio
async def test_multiple_products_same_zone_do_not_collapse(record_property):
    catalog = MultiLipCatalog()
    req = request([owned("lip-a", "lip-a-shade"), owned("blush-b", "blush-b-shade")])
    trace = []
    response = await execute_owned_look(req, catalog, trace=trace)
    coverage = next(e["result"]["coverage"] for e in trace if e["task"]["taskId"] == "N1")
    lips = [c for c in coverage if c["zone"] == "lip"]
    assert [(c["productId"], c["status"]) for c in lips] == [
        ("lip-a", "fulfilled"),
        ("lip-b", "ownership_unknown"),
    ]
    assert len({c["needId"] for c in lips}) == 2
    assert all(c["roleBasis"] == "product_listing" for c in lips)
    assert all(c["relationship"] == "unconfirmed" for c in lips)
    assert "모두 함께 써야 하는지" in response.answer
    assert not response.products
    assert response._owned_look_outcome.status == "waiting_user"
    record_property(
        "same_zone_mock",
        {
            "catalogMode": "mock",
            "modelConfiguredMode": "disabled",
            "actualModelCalls": 0,
            "tasks": trace,
            "answer": response.answer,
        },
    )


@pytest.mark.anyio
async def test_named_item_missing_budget_change_release_and_recipe_change():
    catalog = MultiLipCatalog()
    req = request(
        [owned("lip-a", "lip-a-shade"), owned("blush-b", "blush-b-shade")],
        "lip-b는 없어. 2만원 이하로 추천해줘.",
    )
    first = await execute_owned_look(req, catalog)
    assert [p.id for p in first.products] == ["lip-b"]
    assert first._owned_look_outcome.status == "completed"
    (key,) = first._owned_look_context.item_declarations
    req._owned_look_context = first._owned_look_context
    req.message = "예산 1만원 이하로 바꿔줘."
    second = await execute_owned_look(req, catalog)
    assert key in second._owned_look_context.item_declarations
    assert not second.products
    assert (
        next(i.status for i in second._owned_look_outcome.items if i.need_id == key) == "excluded"
    )
    assert second._owned_look_outcome.status == "partial"
    req._owned_look_context = second._owned_look_context
    req.message = "lip-b 미보유 조건 해제해줘."
    third = await execute_owned_look(req, catalog)
    assert not third._owned_look_context.item_declarations
    assert third._owned_look_outcome.status == "waiting_user"
    req._owned_look_context = first._owned_look_context
    req.message = "다시 추천해줘"
    catalog.look.recipe.version = "fixture-v2"
    fourth = await execute_owned_look(req, catalog)
    assert not fourth._owned_look_context.item_declarations
    assert fourth._owned_look_outcome.status == "waiting_user"


@pytest.mark.anyio
async def test_same_product_two_sale_options_exact_scope_and_memory(monkeypatch):
    from app.schemas.catalog import CatalogProductOption, OptionSearchResponse
    from app.schemas.style_recipe import StyleRecipe
    from app.services import owned_look_consultation_service as module

    catalog = Catalog()
    recipe = StyleRecipe(
        kind="catalog",
        look_id="fixture-look",
        source_look_id="fixture-look",
        source="fixture:catalog",
        features=[],
        current_step=0,
        reason="catalog_settings",
        recipe_id="fixture-two-options",
        recipe_version="fixture-two-options-v1",
        title="Two options",
        basis="catalog_settings",
        review_status="unreviewed",
        synthetic=True,
        steps=[{"order": 1, "zone": "lip", "title": "립"}],
        products=[
            {
                "label": "같은 립",
                "zone": "lip",
                "productId": "lip-a",
                "optionId": oid,
                "optionName": oid,
                "mappingStatus": "verified",
                "catalogValid": True,
            }
            for oid in ("sale-a", "sale-b")
        ],
        ar_eligible=False,
    )

    async def style(*args):
        return ChatResponse(answer="상품 목록 안내", products=[], style_recipe=recipe), None

    calls = []

    async def options(req):
        calls.append(req)
        return OptionSearchResponse.model_validate(
            {
                "effectiveRequest": req,
                "checkedAt": "2026-11-27T00:00:00Z",
                "status": "SUCCESS",
                "items": [
                    {
                        "productId": "lip-a",
                        "optionId": "sale-b",
                        "shadeId": None,
                        "sourceVersion": "fixture-v1",
                        "synthetic": True,
                        "group": "ELIGIBLE",
                        "checks": [
                            {"condition": "identity", "verdict": "MATCH", "reason": "fixture"}
                        ],
                    }
                ],
                "products": [catalog.products["lip-a"]],
                "limitations": [],
                "excludedCount": 0,
                "omittedCount": 0,
                "checkedScope": {
                    "candidateProducts": 1,
                    "candidateOptions": 1,
                    "checkedOptions": 1,
                    "unidentifiedOptions": 0,
                    "stoppedReason": "COMPLETE",
                    "errors": 0,
                    "exhaustive": True,
                },
            }
        )

    async def option(pid, oid):
        return CatalogProductOption(product_id=pid, option_id=oid, name=oid)

    monkeypatch.setattr(module, "execute_style", style)
    catalog.search_options = options
    catalog.get_product_option = option
    memory = owned("lip-a")
    memory.structured.value["optionId"] = "sale-a"
    req = request([memory], "sale-b는 없어.")
    first = await execute_owned_look(req, catalog)
    assert [s.option_id for s in calls[0].option_scope] == ["sale-b"]
    assert first.owned_look_options.selections[0].option_id == "sale-b"
    assert first.applied_memories[0].memory_id == memory.id
    assert first._owned_look_outcome.status == "completed"
    assert [i.label for i in first._owned_look_outcome.items] == [
        "같은 립 (sale-a)",
        "같은 립 (sale-b)",
    ]
    assert first.ar_result is None


@pytest.mark.anyio
async def test_live_multi_item_catalog_independent_targets(record_property):
    import json
    import os

    from app.clients.catalog_client import CatalogClient

    base = os.environ.get("G8_N02_LIVE_CATALOG")
    if not base:
        pytest.skip("read-only live Catalog required")
    catalog = CatalogClient(base)
    req = request([])
    req.style_context.kind = "video"
    req.style_context.look_id = "XyqUi5HKkX8"
    first_trace = []
    first = await execute_owned_look(req, catalog, trace=first_trace)
    coverage = next(t["result"]["coverage"] for t in first_trace if t["task"]["taskId"] == "N1")
    pairs = [
        (a, b)
        for a in coverage
        for b in coverage
        if a["zone"] == b["zone"]
        and a["needId"] != b["needId"]
        and a["productId"]
        and b["productId"]
        and a["optionId"]
        and b["optionId"]
    ]
    assert pairs, (
        "Live look has no verified same-zone sale-option pair; do not substitute mock data"
    )
    a, b = pairs[0]
    memory = owned(a["productId"])
    memory.structured.value["optionId"] = a["optionId"]
    req._consultation_memories = (memory,)
    req._owned_look_context = first._owned_look_context
    req._owned_look_answer = (b["needId"], first.style_recipe.recipe_version, "없어")
    second_trace = []
    second = await execute_owned_look(req, catalog, trace=second_trace)
    after = next(t["result"]["coverage"] for t in second_trace if t["task"]["taskId"] == "N1")
    assert next(c["status"] for c in after if c["needId"] == a["needId"]) == "fulfilled"
    assert next(c["status"] for c in after if c["needId"] == b["needId"]) == "confirmed_missing"
    v1 = next(t for t in second_trace if t["task"]["taskId"] == "V1")
    assert [o["optionId"] for q in v1["inputs"]["requests"] for o in q["optionScope"]] == [
        b["optionId"]
    ]
    assert any(o.option_id == b["optionId"] for o in second.owned_look_options.selections)
    assert second.ar_result is None
    assert all(c["relationship"] == "unconfirmed" for c in after)
    record_property(
        "same_zone_live_catalog",
        json.dumps(
            {
                "catalogMode": "live_http",
                "catalogBase": base,
                "storageMode": "none",
                "modelConfiguredMode": "disabled",
                "actualExternalModelCalls": 0,
                "syntheticInventory": True,
                "lookId": req.style_context.look_id,
                "recipeVersion": first.style_recipe.recipe_version,
                "chosenTargets": [a, b],
                "turns": [
                    {
                        "modelMode": "disabled",
                        "actualModelCalls": 0,
                        "tasks": trace,
                        "response": response.model_dump(mode="json", by_alias=True),
                    }
                    for trace, response in [(first_trace, first), (second_trace, second)]
                ],
            },
            ensure_ascii=False,
        ),
    )


@pytest.mark.anyio
async def test_item_present_and_missing_in_one_sentence():
    catalog = MultiLipCatalog()
    result = await execute_owned_look(
        request([owned("blush-b", "blush-b-shade")], "lip-a는 있고 lip-b는 없어."), catalog
    )
    assert [p.id for p in result.products] == ["lip-b"]
    assert result._owned_look_outcome.status == "waiting_user"
    assert any(
        i.status == "ownership_unknown" and "lip-a" in i.label
        for i in result._owned_look_outcome.items
    )
    assert len(result._owned_look_context.item_declarations) == 2


@pytest.mark.anyio
async def test_all_option_queries_fail_is_failed_not_completed():
    catalog = FilteredCatalog()
    catalog.fail_options = True
    result = await execute_owned_look(
        request([], "립은 없어. 블러셔는 없어. 2만원 이하로 추천해줘."), catalog
    )
    assert result._owned_look_outcome.status == "failed"
    assert {i.status for i in result._owned_look_outcome.items} == {"lookup_failed"}


@pytest.mark.anyio
async def test_item_missing_conflict_requires_confirmation_not_memory_write():
    catalog = MultiLipCatalog()
    memories = [owned("lip-a", "lip-a-shade"), owned("blush-b", "blush-b-shade")]
    req = request(memories, "lip-a는 없어. lip-b-shade는 있어.")
    first = await execute_owned_look(req, catalog)
    item = next(i for i in first._owned_look_outcome.items if "lip-a" in i.label)
    assert item.status == "ownership_unknown"
    req._owned_look_context = first._owned_look_context
    req.message = "추가 추천해줘"
    req._owned_look_answer = (item.need_id, first.style_recipe.recipe_version, "없어")
    second = await execute_owned_look(req, catalog)
    assert [p.id for p in second.products] == ["lip-a"]
    assert second._owned_look_outcome.status == "completed"
    assert not second.memory_proposal
    assert req._consultation_memories == tuple(memories)


@pytest.mark.anyio
async def test_reviewed_usage_keeps_distinct_same_zone_step_roles():
    from app.schemas.style_recipe import RecipeStep, ReviewedProductUsage

    catalog = MultiLipCatalog()
    catalog.look.recipe.steps.append(
        RecipeStep(order=3, zone="lip", title="립 포인트", description="합성 포인트 단계")
    )
    catalog.look.recipe.product_usages = [
        ReviewedProductUsage(
            step_order=step,
            product_id=pid,
            shade_id=pid + "-shade",
            source="fixture:usage",
            evidence_id="fixture:usage-" + pid,
        )
        for step, pid in [(1, "blush-b"), (2, "lip-a"), (3, "lip-b")]
    ]
    from app.schemas.catalog import CatalogStyleLook

    recipe = catalog.look.recipe.model_copy(update={"kind": "video"})
    catalog.look = CatalogStyleLook.model_validate(
        {
            "id": "fixture-look",
            "title": "Synthetic roles",
            "group": "fixture",
            "tag": "fixture",
            "videoUrl": "https://www.youtube.com/watch?v=fixture-look",
            "recipe": recipe,
            "products": [
                {
                    "number": i,
                    "brand": "Fixture",
                    "name": pid,
                    "option": "Fixture shade",
                    "category": zone,
                    "zone": zone,
                    "reviewStatus": "verified",
                    "mappingVerified": True,
                    "catalogProductId": pid,
                    "catalogShadeId": pid + "-shade",
                }
                for i, (pid, zone) in enumerate(
                    [("blush-b", "blush"), ("lip-a", "lip"), ("lip-b", "lip")], 1
                )
            ],
        }
    )

    async def selected(kind, look_id):
        return catalog.look if (kind, look_id) == ("video", "fixture-look") else None

    catalog.get_style_look = selected
    req = request([owned("lip-a", "lip-a-shade")])
    req.style_context.kind = "video"
    trace = []
    await execute_owned_look(req, catalog, trace=trace)
    coverage = next(t["result"]["coverage"] for t in trace if t["task"]["taskId"] == "N1")
    lips = [c for c in coverage if c["zone"] == "lip"]
    assert [(c["productId"], c["stepOrders"]) for c in lips] == [("lip-a", [2]), ("lip-b", [3])]
    assert all(c["roleBasis"] == "reviewed_usage" for c in lips)


@pytest.mark.anyio
async def test_unidentified_sibling_is_preserved_in_final_coverage():
    catalog = MultiLipCatalog()
    catalog.look.items[-1].shade_id = "stale-shade"
    response = await execute_owned_look(
        request([owned("lip-a", "lip-a-shade"), owned("blush-b", "blush-b-shade")]), catalog
    )
    assert response._owned_look_outcome.status == "partial"
    assert any(
        i.status == "evidence_missing" and "lip-b" in i.label
        for i in response._owned_look_outcome.items
    )


class KoreanScopeCatalog(MultiLipCatalog):
    """Mock Catalog with natural Korean names and colorless exact sale options."""

    def __init__(self):
        from app.schemas.catalog import CatalogStyleLook

        super().__init__()
        self.products["lip-a"].brand = "하트퍼센트"
        self.products["lip-a"].name = "립펜슬"
        self.products["lip-b"].brand = "롬앤"
        self.products["lip-b"].name = "쥬시 래스팅 틴트"
        recipe = self.look.recipe.model_copy(deep=True)
        recipe.kind = "video"
        recipe.steps = [recipe.steps[1].model_copy(update={"order": 1})]
        self.look = CatalogStyleLook.model_validate(
            {
                "id": "fixture-look",
                "title": "합성 립 룩",
                "group": "fixture",
                "tag": "fixture",
                "videoUrl": "https://www.youtube.com/watch?v=fixture-look",
                "recipe": recipe,
                "products": [
                    {
                        "number": i,
                        "brand": p.brand,
                        "name": p.name,
                        "option": "07호",
                        "category": "립 메이크업",
                        "zone": "립",
                        "mappingVerified": True,
                        "reviewStatus": "verified",
                        "catalogProductId": p.id,
                        "catalogOptionId": p.id + "-07",
                        "catalogOptionSource": "fixture:option",
                    }
                    for i, p in enumerate([self.products["lip-a"], self.products["lip-b"]], 1)
                ],
            }
        )

    async def get_style_look(self, kind, look_id):
        return self.look if (kind, look_id) == ("video", "fixture-look") else None

    async def search_options(self, req):
        result = await super().search_options(req)
        for item in result.items:
            selected = next(s for s in req.option_scope if s.product_id == item.product_id)
            item.option_id = selected.option_id
            item.shade_id = selected.shade_id
            item.option_name = "07호"
        return result


def scope_request(message, *, other_option=False):
    memories = [owned("lip-a")]
    memories[0].structured.value["optionId"] = "lip-a-07"
    if other_option:
        memory = owned("lip-b")
        memory.structured.value["optionId"] = "lip-b-02"
        memories.append(memory)
    req = request(memories, message)
    req.style_context.kind = "video"
    return req


@pytest.mark.anyio
@pytest.mark.parametrize("possession", ["있어", "갖고 있어", "가지고 있어", "없어"])
async def test_bound_answer_keeps_additional_named_product_ownership_and_budget(possession):
    from app.schemas.consultation_parent import ParentQuestion

    catalog = KoreanScopeCatalog()
    req = scope_request("이 룩에 필요한 상품 추천해줘")
    req._consultation_memories = ()
    first = await execute_owned_look(req, catalog)
    first_item = next(i for i in first._owned_look_outcome.items if "하트퍼센트" in i.label)
    req._owned_look_context = first._owned_look_context
    req._question_answers = [(ParentQuestion(
        task_id="task-look", goal="owned_look", version=1, text="첫 상품 있나요?",
        input_key="ownership", need_id=first_item.need_id,
        recipe_version=first.style_recipe.recipe_version, ownership_scope="option",
    ), "없어")]
    req.message = f"없어. 롬앤 쥬시 래스팅 틴트는 {possession}. 각각 2만원 이하로 찾아줘."
    result = await execute_owned_look(req, catalog)
    state = result._owned_look_context
    assert state.item_declarations[first_item.need_id].status == "missing"
    extra = next(i for i in result._owned_look_outcome.items if "롬앤" in i.label)
    declaration = state.item_declarations[extra.need_id]
    assert declaration.status == ("missing" if possession == "없어" else "present")
    assert declaration.scope == "product"
    assert extra.status != "fulfilled"  # A product statement never proves its exact sale option.
    assert state.filters.max_price_krw == 20000
    req._owned_look_context = state
    req._question_answers = []
    req.message = "예산만 3만원 이하로 바꿔줘"
    follow = await execute_owned_look(req, catalog)
    assert follow._owned_look_context.item_declarations[extra.need_id] == declaration
    assert follow._owned_look_context.filters.max_price_krw == 30000


@pytest.mark.anyio
async def test_additional_name_variant_uses_existing_reference_interpreter_without_budget():
    import json

    from app.schemas.consultation_parent import ParentQuestion

    req = scope_request("이 룩에 필요한 상품 추천해줘")
    req._consultation_memories = ()
    catalog = KoreanScopeCatalog()
    first = await execute_owned_look(req, catalog)
    target = next(i for i in first._owned_look_outcome.items if "하트퍼센트" in i.label)
    req._owned_look_context = first._owned_look_context
    req._question_answers = [(ParentQuestion(
        task_id="task-look", goal="owned_look", version=1, text="첫 상품 있나요?",
        input_key="ownership", need_id=target.need_id,
        recipe_version=first.style_recipe.recipe_version, ownership_scope="option",
    ), "없어")]
    req.message = "없어. 롬앤 틴트는 갖고 있어. 각각 2만원 이하로 찾아줘."
    calls = []

    class Model:
        configured = True

        async def complete_with_tools(self, messages, tools, *, required_tool=None):
            payload = json.loads(messages[-1]["content"])
            calls.append(payload)
            snapshot = payload["snapshot"]
            extra = next(t for t in snapshot["targets"] if t["productId"] == "lip-b")
            args = {"snapshotVersion": snapshot["version"], "action": "update", "operations": [
                {"action": "declare", "targetId": extra["targetId"],
                 "scope": "product", "status": "present"},
            ]}
            return {"choices": [{"message": {"tool_calls": [{"function": {
                "name": required_tool, "arguments": json.dumps(args),
            }}]}}]}, 0

    req._owned_look_llm = Model()
    result = await execute_owned_look(req, catalog)
    assert len(calls) == 1
    assert calls[0]["utterance"].strip() == "롬앤 틴트는 갖고 있어."
    state = result._owned_look_context
    assert state.item_declarations[target.need_id].status == "missing"
    assert state.product_declarations["lip-b"].status == "present"
    assert state.filters.max_price_krw == 20000


@pytest.mark.anyio
async def test_korean_product_missing_never_expands_to_zone_and_release_is_scoped():
    from app.schemas.owned_look_context import OwnershipDeclaration

    catalog = KoreanScopeCatalog()
    req = scope_request("롬앤 쥬시 래스팅 틴트는 없어.")
    trace = []
    from tests.conftest import FakeLlm

    result = await ChatService(None, FakeLlm(configured=False), catalog).answer(req)
    assert [p.id for p in result.products] == ["lip-b"]
    assert not result._owned_look_context.declarations
    assert catalog.option_calls[-1].product_ids == ["lip-b"]
    # Preserve an independent declaration for the other lip while clearing B only.
    direct = await execute_owned_look(req, catalog, trace=trace)
    coverage = next(t["result"]["coverage"] for t in trace if t["task"]["taskId"] == "N1")
    a = next(c["needId"] for c in coverage if c["productId"] == "lip-a")
    direct._owned_look_context.item_declarations[a] = OwnershipDeclaration(
        status="present", quote="07호 확인", scope="option"
    )
    req._owned_look_context = direct._owned_look_context
    req.message = "롬앤 쥬시 래스팅 틴트 미보유 조건 해제해줘."
    released = await execute_owned_look(req, catalog)
    assert set(released._owned_look_context.item_declarations) == {a}
    assert not released.products
    assert released._owned_look_outcome.status == "waiting_user"


@pytest.mark.anyio
async def test_fingerprint_includes_item_declaration_and_is_order_independent():
    from app.schemas.owned_look_context import OwnershipDeclaration

    catalog = KoreanScopeCatalog()
    req = scope_request("하트퍼센트 립펜슬 07호는 있어. 롬앤 쥬시 래스팅 틴트는 없어.")
    traces = []
    first = await execute_owned_look(req, catalog)
    req._owned_look_context = first._owned_look_context
    req.message = "다시 추천해줘"
    for status in ["missing", "present"]:
        for key in req._owned_look_context.item_declarations:
            req._owned_look_context.item_declarations[key] = OwnershipDeclaration(
                status=status, quote="합성 동일 발화", scope="product"
            )
        trace = []
        await execute_owned_look(req, catalog, trace=trace)
        traces.append(next(t for t in trace if t["task"]["taskId"] == "N1"))
    assert traces[0]["result"]["inputFingerprint"] != traces[1]["result"]["inputFingerprint"]
    assert traces[0]["inputs"]["itemDeclarations"] != traces[1]["inputs"]["itemDeclarations"]
    assert len(req._owned_look_context.item_declarations) == 2
    # Reordering serialized declaration dictionaries does not change the fingerprint.
    req._owned_look_context.item_declarations = dict(
        reversed(list(req._owned_look_context.item_declarations.items()))
    )
    trace = []
    await execute_owned_look(req, catalog, trace=trace)
    assert (
        next(t["result"]["inputFingerprint"] for t in trace if t["task"]["taskId"] == "N1")
        == traces[1]["result"]["inputFingerprint"]
    )


@pytest.mark.anyio
async def test_korean_explicit_whole_zone_and_ambiguous_option():
    catalog = KoreanScopeCatalog()
    req = scope_request("립 제품은 전부 없어.")
    result = await execute_owned_look(req, catalog)
    assert {p.id for p in result.products} == {"lip-a", "lip-b"}
    assert result._owned_look_context.declarations["lip"].scope == "zone"
    ambiguous = scope_request("07호는 있어.")
    response = await execute_owned_look(ambiguous, catalog)
    assert not response._owned_look_context.item_declarations
    assert response._owned_look_outcome.status == "waiting_user"


@pytest.mark.anyio
async def test_live_korean_utterance_to_exact_option_request(record_property):
    import json
    import os

    from app.clients.catalog_client import CatalogClient
    from app.services.conversation_context import prepare_request, updated_context
    from tests.conftest import FakeLlm

    base = os.environ.get("G8_N02_LIVE_CATALOG")
    if not base:
        pytest.skip("read-only live Catalog required")
    catalog = CatalogClient(base)
    service = ChatService(None, FakeLlm(configured=False), catalog)
    memory = owned("oy-a000000183683")
    memory.structured.value["optionId"] = "A000000183683-001"
    req = request([memory])
    req.style_context.kind = "video"
    req.style_context.look_id = "XyqUi5HKkX8"
    first = await service.answer(req)
    target = next(p for p in first.style_recipe.products if p.product_id == "oy-a000000158896")
    assert target.option_id == "A000000158896-010"
    # Natural name from the actual Catalog, with no injected internal answer.
    message = f"{target.label}는 없어. 2만원 이하로 추천해줘."
    follow = prepare_request(
        req.model_copy(update={"message": message}), updated_context({}, first), []
    )
    assert follow._owned_look_answer is None
    second = await service.answer(follow)
    n1 = next(
        t
        for e in second._parent_trace
        for t in e.get("specialistTrace", [])
        if t["task"]["taskId"] == "N1"
    )
    coverage = n1["result"]["coverage"]
    assert (
        next(c["status"] for c in coverage if c["productId"] == "oy-a000000183683") == "fulfilled"
    )
    assert (
        next(c["status"] for c in coverage if c["productId"] == target.product_id)
        == "confirmed_missing"
    )
    assert "lip" not in second._owned_look_context.declarations
    v1 = next(
        t
        for e in second._parent_trace
        for t in e.get("specialistTrace", [])
        if t["task"]["taskId"] == "V1"
    )
    assert [s["optionId"] for q in v1["inputs"]["requests"] for s in q["optionScope"]] == [
        target.option_id
    ]
    assert any(s.option_id == target.option_id for s in second.owned_look_options.selections)
    third_req = prepare_request(
        req.model_copy(update={"message": "설명은 빼고 상품만 찾아줘"}),
        updated_context({}, second),
        [],
    )
    third = await service.answer(third_req)
    assert third._owned_look_context.filters.max_price_krw == 20000
    assert any(s.option_id == target.option_id for s in third.owned_look_options.selections)
    assert not third.ar_result
    record_property(
        "scope_live_catalog",
        json.dumps(
            {
                "catalogMode": "live_http",
                "inventoryMode": "synthetic",
                "postgresMode": "not_used",
                "modelConfiguredMode": "disabled",
                "actualExternalModelCalls": 0,
                "lookId": req.style_context.look_id,
                "recipeVersion": first.style_recipe.recipe_version,
                "turns": [
                    {
                        "message": m,
                        "actualModelCalls": 0,
                        "modelMode": "disabled",
                        "trace": r._parent_trace,
                        "response": r.model_dump(mode="json", by_alias=True),
                    }
                    for m, r in [
                        (req.message, first),
                        (message, second),
                        (third_req.message, third),
                    ]
                ],
            },
            ensure_ascii=False,
        ),
    )


@pytest.mark.anyio
async def test_unrecognized_product_name_does_not_become_zone_declaration():
    catalog = KoreanScopeCatalog()
    result = await execute_owned_look(scope_request("다른 브랜드의 틴트는 없어."), catalog)
    assert not result._owned_look_context.declarations
    assert not result._owned_look_context.item_declarations
    assert not result.products
    assert result._owned_look_outcome.status == "waiting_user"

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
        request([owned("lip-a", "lip-a-shade")], "블러셔는 없어. 1만원 이하로 추천해줘."), catalog
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

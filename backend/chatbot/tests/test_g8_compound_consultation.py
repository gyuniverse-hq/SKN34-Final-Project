"""G8 contract runs. The Tool HTTP clients are real; data, planner and G5 are doubles."""

import json
from unittest.mock import AsyncMock
from uuid import uuid4

import httpx
import pytest

from app.clients.catalog_client import CatalogClient
from app.clients.skincare_recommendation_client import SkincareRecommendationClient
from app.core.config import get_settings
from app.core.errors import UpstreamError
from app.schemas.chat import ChatRequest
from app.schemas.compound_consultation import (
    CompoundDisplay,
    CompoundGoal,
    InputBinding,
    TaskRequest,
    TaskResult,
)
from app.schemas.knowledge import KnowledgeReply
from app.services import compound_consultation_graph as graph
from app.services import compound_consultation_service as specialists
from app.services.chat_service import ChatService
from app.services.knowledge_service import Consultation
from app.services.skincare_recommendation_tool import SkincareRecommendationTool
from tests.test_skincare_recommendation_tool import match, payload

QUESTION = (
    "건조함과 모공이 고민이야. 관리 방법을 설명해 주고, "
    "2만 원 이하에서 향료 제외 조건을 확인할 수 있는 제품을 추천해 줘."
)
CARE_QUESTION = "건조함과 모공을 관리하는 방법은?"
CARE_ADVICE = (
    "세안 뒤 피부가 당긴다면 보습제를 얇게 펴 발라 보세요. "
    "모공 주변도 세게 문지르지 말고 부드럽게 씻어 주세요."
)
GOAL = CompoundGoal(goals=["dryness", "pores"], maxPriceKRW=20000, excluded_ingredients=["향료"])
STAMP = "2026-11-25T01:00:00Z"


@pytest.fixture
def anyio_backend():
    return "asyncio"


class SkinApi:
    def __init__(self):
        self.calls = []
        self.options = [f"sale-{rank}" for rank in range(1, 11)]
        self.fail_ids = set()

    def __call__(self, request):
        body = json.loads(request.content)
        path = request.url.path
        self.calls.append((path, body))
        rows = []
        for rank, option_id in enumerate(self.options, 1):
            row = match()
            row["product"].update(id=f"p{rank}", nameKo=f"시험 상품 {rank}")
            if rank == 9:
                row["product"].update(brand="예시랩", nameKo="데일리 보습 로션")
            row.update(optionId=option_id, optionName=f"{rank * 10}ml")
            rows.append(row)
        if path == "/api/recommendations/skincare/v4":
            return httpx.Response(200, json=payload(("dryness", "pores"), matches=rows))
        assert path == "/api/catalog/options/search"
        if set(body["productIds"]) & self.fail_ids:
            return httpx.Response(503)
        items, products = [], []
        for scope in body["optionScope"]:
            rank = int(scope["productId"][1:])
            # The source contains one confirmed option at rank 9 and one partial label at rank 3.
            amount = 18500
            present = rank != 9
            label_unknown = rank == 3
            source = {"sourceRef": "https://example.test/label", "sourceVersion": "fixture-label"}
            checks = [{"condition": "identity", "verdict": "MATCH", "reason": "exact", **source}]
            price_ok = amount <= body["maxPriceKRW"]
            checks.append(
                {
                    "condition": "price",
                    "verdict": "MATCH" if price_ok else "NOT_MATCH",
                    "reason": "snapshot_price",
                }
            )
            checks.append(
                {
                    "condition": "ingredient",
                    "ingredientName": "향료",
                    "operator": "excludes",
                    "verdict": "UNKNOWN" if label_unknown else "NOT_MATCH" if present else "MATCH",
                    "reason": "absence_not_verifiable"
                    if label_unknown
                    else ("ingredient_present" if present else "ingredient_absent"),
                    "evidenceId": f"label-{rank}",
                    "observedAt": STAMP,
                    "reviewStatus": "verified",
                    "normalizationStatus": "verified",
                    "ingredientCoverage": "partial" if label_unknown else "full",
                    **source,
                }
            )
            group = (
                "EXCLUDED"
                if not price_ok or present and not label_unknown
                else ("REFERENCE_ONLY" if label_unknown else "ELIGIBLE")
            )
            items.append(
                {
                    **scope,
                    "sourceVersion": "fixture-label",
                    "group": group,
                    "checks": checks,
                    "price": {
                        "amountKRW": amount,
                        "requestedBasis": body["priceBasis"],
                        "observedBasis": "collected_snapshot",
                        "observedAt": STAMP,
                        "checkedAt": STAMP,
                        **source,
                    },
                }
            )
            if group != "EXCLUDED":
                products.append(rows[rank - 1]["product"])
        return httpx.Response(
            200,
            json={
                "effectiveRequest": body,
                "checkedAt": STAMP,
                "status": "PARTIAL"
                if any(i["group"] == "REFERENCE_ONLY" for i in items)
                else "SUCCESS",
                "items": items,
                "products": products,
                "checkedScope": {
                    "candidateProducts": len(items),
                    "candidateOptions": len(items),
                    "checkedOptions": len(items),
                    "unidentifiedOptions": 0,
                    "exhaustive": True,
                    "stoppedReason": "COMPLETE",
                    "errors": 0,
                },
                "excludedCount": sum(i["group"] == "EXCLUDED" for i in items),
                "omittedCount": 0,
            },
        )


@pytest.fixture
def connections(monkeypatch):
    api = SkinApi()
    original = httpx.AsyncClient
    monkeypatch.setattr(
        httpx, "AsyncClient", lambda **kw: original(transport=httpx.MockTransport(api), **kw)
    )
    return (
        api,
        SkincareRecommendationTool(SkincareRecommendationClient("https://api.test")),
        CatalogClient("https://api.test"),
    )


def install_knowledge(monkeypatch):
    monkeypatch.setattr(get_settings(), "g5_enabled", True)
    reply = KnowledgeReply.model_validate(
        {
            "status": "answered",
            "claims": [{"claim": CARE_ADVICE, "citations": ["E1"]}],
            "evidence": [
                {
                    "id": "E1",
                    "documentId": 8,
                    "chunkId": "chunk8",
                    "title": "세안 후 피부 관리 (합성 자료)",
                    "sourceFileId": 3,
                    "sourceVersion": "fixture-rag",
                    "blockOrder": 1,
                    "startUtf16": 0,
                    "endUtf16": len(CARE_ADVICE.encode("utf-16-le")) // 2,
                    "sourceLocator": {"paragraph": 1},
                    "quote": CARE_ADVICE,
                    "relevance": "essential",
                }
            ],
        }
    )
    consult = AsyncMock(return_value=Consultation(reply=reply, trace={}))
    monkeypatch.setattr(specialists, "consult_knowledge", consult)
    return consult


@pytest.mark.anyio
async def test_ranked_options_bind_to_real_http_arguments_and_survive_partial_failure(connections):
    api, skincare, catalog = connections
    candidates, limits = await specialists.recommend(GOAL, skincare)
    assert not limits
    assert api.calls[0][1] == {
        "detectedConcerns": [{"goal": g, "sources": ["conversation"]} for g in GOAL.goals]
    }
    assert candidates[8].data_version == "fixture-v1"
    assert candidates[8].reasons[0].evidence_sources == ["cosing_function"]
    options, batches, _ = await specialists.verify(GOAL, candidates, catalog)
    assert [len(b.product_ids) for b in batches] == [6, 4]
    assert [o.candidate.rank for o in options if o.outcome == "eligible"] == [9]
    assert options[2].outcome == "unknown"
    assert batches[0].scope.exhaustive
    body = api.calls[-1][1]
    assert body["optionScope"][2] == {"productId": "p9", "shadeId": None, "optionId": "sale-9"}
    assert body["ingredientConditions"] == [{"ingredientName": "향료", "operator": "excludes"}]
    assert body["fragranceFree"] is False
    assert body["priceBasis"] == "collected_snapshot"
    assert body["maxPriceKRW"] == 20000

    api.options[8] = "replacement-sale-9"
    candidates, _ = await specialists.recommend(GOAL, skincare)
    api.fail_ids.add("p1")
    options, batches, _ = await specialists.verify(GOAL, candidates, catalog)
    assert [o.outcome for o in options[:6]] == ["failed"] * 6
    assert batches[0].scope is None
    assert api.calls[-1][1]["optionScope"][2]["optionId"] == "replacement-sale-9"
    assert options[8].verification.option_id == "replacement-sale-9"
    assert options[8].outcome == "eligible"
    revised = GOAL.model_copy(update={"max_price_krw": 15000})
    options, _, _ = await specialists.verify(revised, candidates, catalog)
    assert api.calls[-1][1]["maxPriceKRW"] == 15000
    assert options[8].outcome == "excluded"


@pytest.mark.anyio
async def test_unidentified_shade_skips_lookup_and_g5_evidence_ids_are_scoped(
    monkeypatch, connections
):
    api, skincare, catalog = connections
    candidates, _ = await specialists.recommend(GOAL, skincare)
    shaded = candidates[0].model_copy(update={"has_shades": True})
    options, batches, _ = await specialists.verify(GOAL, [shaded], catalog)
    assert options[0].outcome == "unknown" and not batches
    assert len(api.calls) == 1
    consult = install_knowledge(monkeypatch)
    first = await specialists.research(CARE_QUESTION, "care")
    second = await specialists.research(CARE_QUESTION, "pores")
    assert first.claims[0].citations == [first.evidence[0].id] == ["care.E1"]
    assert second.claims[0].citations == ["pores.E1"]
    assert first.evidence[0].source_version == "fixture-rag"
    monkeypatch.setattr(get_settings(), "g5_enabled", False)
    assert (await specialists.research(CARE_QUESTION)).status == "error"
    assert consult.await_count == 2


class Planner:
    configured = True

    async def complete_with_tools(self, messages, tools, *, required_tool=None):
        assert required_tool == "plan_skin_consultation"
        decision = {
            "action": "start",
            "goal": GOAL.model_dump(mode="json", by_alias=True),
            "question": CARE_QUESTION,
        }
        call = {
            "type": "function",
            "id": "plan-1",
            "function": {
                "name": required_tool,
                "arguments": json.dumps(decision),
            },
        }
        return {"choices": [{"finish_reason": "tool_calls", "message": {"tool_calls": [call]}}]}, 0


@pytest.mark.anyio
async def test_first_compound_through_chat_service(monkeypatch, connections):
    api, skincare, catalog = connections
    monkeypatch.setattr(get_settings(), "g8_enabled", True)
    consult = install_knowledge(monkeypatch)
    chat = ChatService(None, Planner(), catalog, skincare=skincare)
    answer = await chat.answer(ChatRequest(message=QUESTION, locale="ko"))
    consult.assert_awaited_once_with(CARE_QUESTION)
    cards = [o for o in answer.compound.options if o.outcome == "eligible"]
    assert [(o.candidate.product_id, o.candidate.option_id) for o in cards] == [("p9", "sale-9")]
    assert answer.chat_context.compound.candidates[8].option_id == "sale-9"
    assert "예시랩 데일리 보습 로션 90ml" in answer.answer and "18,500원" in answer.answer
    assert "2026년 11월 25일에 확인한 가격" in answer.answer
    assert "전성분 목록에는 ‘향료’ 표기가 없어요." in answer.answer
    assert f"{CARE_ADVICE} [1]" in answer.answer
    assert answer.knowledge.claims[0].citations == [answer.knowledge.evidence[0].id]
    assert answer.knowledge.evidence[0].quote == CARE_ADVICE
    assert answer.knowledge.evidence[0].source_version == "fixture-rag"
    assert len(api.calls) == 3
    assert answer.knowledge.evidence[0].id not in answer.answer


@pytest.mark.anyio
async def test_failed_knowledge_preserves_verified_products(connections):
    _, skincare, catalog = connections
    candidates, _ = await specialists.recommend(GOAL, skincare)
    options, batches, limits = await specialists.verify(GOAL, candidates, catalog)
    display = CompoundDisplay(
        plan_version=1, goal=GOAL, options=options, batches=batches, limitations=limits
    )
    answer = specialists.compose(
        display, KnowledgeReply(status="error", limitations="지식 조회 실패")
    )
    assert "지식 조회 실패" in answer and "데일리 보습 로션 90ml" in answer
    assert "시험 상품 3" not in answer and "1개는 자료가 부족해" in answer


def test_binding_rejects_invalid_plan_and_late_result():
    binding = InputBinding(source_task="P1")
    base = {"goal": GOAL, "plan_id": uuid4(), "plan_version": 2}
    product = TaskRequest(**base, task_id="P1", agent="recommend")
    verify = TaskRequest(
        **base, task_id="V1", agent="verify", depends_on=["P1"], input_bindings=[binding]
    )
    assert graph.validate_plan([verify, product]) == ["P1", "V1"]
    with pytest.raises(ValueError, match="Unresolved dependency"):
        graph.validate_plan([verify])
    with pytest.raises(ValueError):
        graph.validate_plan([product.model_copy(update={"depends_on": ["V1"]}), verify])
    late = TaskResult(
        task_id="P1",
        plan_id=product.plan_id,
        plan_version=1,
        input_fingerprint="old",
        status="complete",
    )
    with pytest.raises(ValueError, match="Stale specialist result"):
        graph.bound_candidates(verify, binding, late)


@pytest.mark.anyio
async def test_failed_candidate_read_is_replanned_without_repeating_research(
    monkeypatch, connections
):
    api, skincare, catalog = connections
    consult = install_knowledge(monkeypatch)
    result = await specialists.recommend(GOAL, skincare)
    lookup = AsyncMock(side_effect=[UpstreamError("temporary"), result])
    monkeypatch.setattr(specialists, "recommend", lookup)
    trace = []
    answer = await graph.run_compound(GOAL, CARE_QUESTION, skincare, catalog, trace=trace)
    assert consult.await_count == 1 and lookup.await_count == 2
    assert [t["result"]["status"] for t in trace if t["task"]["taskId"] == "V1"] == [
        "skipped",
        "partial",
    ]
    assert len([c for c in api.calls if c[0].endswith("/search")]) == 2
    assert answer.compound.options[8].outcome == "eligible"

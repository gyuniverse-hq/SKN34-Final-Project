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
            row = match(body["detectedConcerns"][0]["goal"] if path.endswith("/v4") else "pores")
            row["product"].update(id=f"p{rank}", nameKo=f"시험 상품 {rank}")
            if rank == 9:
                row["product"].update(brand="예시랩", nameKo="데일리 보습 로션")
            row.update(optionId=option_id, optionName=f"{rank * 10}ml")
            rows.append(row)
        if path == "/api/recommendations/skincare/v4":
            return httpx.Response(
                200, json=payload(tuple(c["goal"] for c in body["detectedConcerns"]), matches=rows)
            )
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
            checks.extend(
                {
                    "condition": "ingredient",
                    "ingredientName": condition["ingredientName"],
                    "operator": condition["operator"],
                    "verdict": "MATCH",
                    "reason": "ingredient_present"
                    if condition["operator"] == "includes"
                    else "ingredient_absent",
                    "evidenceId": f"label-{rank}",
                    "observedAt": STAMP,
                    "reviewStatus": "verified",
                    "normalizationStatus": "verified",
                    "ingredientCoverage": "full",
                    **source,
                }
                for condition in body["ingredientConditions"]
                if condition["ingredientName"] != "향료"
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
        if required_tool == "extract_knowledge_search_conditions":
            return {
                "choices": [
                    {
                        "message": {
                            "tool_calls": [
                                {
                                    "function": {
                                        "name": required_tool,
                                        "arguments": '{"conditions":[]}',
                                    }
                                }
                            ]
                        }
                    }
                ]
            }, 0
        assert required_tool == "plan_skin_consultation"
        decision = {
            "scope": "consultation",
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


@pytest.mark.anyio
async def test_explanation_goal_change_invalidates_candidates(monkeypatch, connections):
    api, skincare, catalog = connections
    install_knowledge(monkeypatch)
    first = await graph.run_compound(GOAL, CARE_QUESTION, skincare, catalog)
    original = first.chat_context.compound
    new_goal = GOAL.model_copy(update={"goals": ["sensitivity"], "wants_products": False})
    second = await graph.run_compound(
        new_goal,
        "민감함을 관리하는 방법은?",
        skincare,
        catalog,
        previous=original,
        reuse_candidates=True,
    )
    restored = type(original).model_validate_json(second.chat_context.compound.model_dump_json())
    assert not restored.candidates and restored.candidate_goals is None
    before = len([p for p, _ in api.calls if p.endswith("/v4")])
    third = await graph.run_compound(
        new_goal.model_copy(update={"wants_products": True, "wants_knowledge": False}),
        "",
        skincare,
        catalog,
        previous=restored,
        reuse_candidates=True,
    )
    calls = [b for p, b in api.calls if p.endswith("/v4")]
    assert len(calls) == before + 1 and calls[-1]["detectedConcerns"] == [
        {"goal": "sensitivity", "sources": ["conversation"]}
    ]
    assert third.chat_context.compound.candidate_goals == ["sensitivity"]
    legacy = original.model_copy(update={"candidate_goals": None})
    assert not graph.can_reuse_candidates(GOAL, legacy)


@pytest.mark.anyio
async def test_serum_cream_question_keeps_order_and_context(monkeypatch, connections):
    monkeypatch.setattr(get_settings(), "g8_enabled", True)
    api, skincare, catalog = connections
    consult = install_knowledge(monkeypatch)
    question = "건조할 때 아침에 세럼과 크림은 어떤 순서와 방법으로 사용하나요?"

    class OrderPlanner(Planner):
        async def complete_with_tools(self, messages, tools, *, required_tool=None):
            reply, ms = await super().complete_with_tools(
                messages, tools, required_tool=required_tool
            )
            if required_tool == "plan_skin_consultation":
                call = reply["choices"][0]["message"]["tool_calls"][0]["function"]
                plan = json.loads(call["arguments"])
                plan["question"] = question
                call["arguments"] = json.dumps(plan)
            return reply, ms

    chat = ChatService(None, OrderPlanner(), catalog, skincare=skincare)
    await chat.answer(ChatRequest(message=question + " 제품도 추천해 줘.", locale="ko"))
    consult.assert_awaited_once_with(question)
    assert len(api.calls) == 3


@pytest.mark.anyio
@pytest.mark.parametrize("ingredient", ["글리세린", "판테놀", "향료"])
async def test_knowledge_condition_changes_actual_catalog_input(
    monkeypatch, connections, ingredient
):
    from app.schemas.compound_consultation import KnowledgeSearchCondition

    api, skincare, catalog = connections
    consult = install_knowledge(monkeypatch)
    reply = consult.return_value.reply
    statement = f"{ingredient} 성분이 포함된 제품을 선택하세요."
    reply.claims[0].claim = statement
    reply.evidence[0].quote = statement
    reply.evidence[0].end_utf16 = len(statement.encode("utf-16-le")) // 2

    class SearchPlanner(Planner):
        async def complete_with_tools(self, messages, tools, *, required_tool=None):
            if required_tool != "extract_knowledge_search_conditions":
                return await super().complete_with_tools(
                    messages, tools, required_tool=required_tool
                )
            condition = KnowledgeSearchCondition(
                ingredient_name=ingredient,
                operator="includes",
                claim_index=0,
                evidence_id="K1.E1",
                quote=statement,
            )
            return {
                "choices": [
                    {
                        "message": {
                            "tool_calls": [
                                {
                                    "function": {
                                        "name": required_tool,
                                        "arguments": json.dumps(
                                            {
                                                "conditions": [
                                                    condition.model_dump(mode="json", by_alias=True)
                                                ]
                                            }
                                        ),
                                    }
                                }
                            ]
                        }
                    }
                ]
            }, 0

    trace = []
    await graph.run_compound(
        GOAL, CARE_QUESTION, skincare, catalog, trace=trace, llm=SearchPlanner()
    )
    body = api.calls[-1][1]
    expected = [{"ingredientName": "향료", "operator": "excludes"}]
    if ingredient != "향료":
        expected.append({"ingredientName": ingredient, "operator": "includes"})
    assert body["ingredientConditions"] == expected
    assert body["maxPriceKRW"] == 20000
    checked = next(t for t in trace if t["task"]["taskId"] == "V1")
    assert checked["inputs"]["conditionDecisions"][0]["decision"] == (
        "user_condition_precedes" if ingredient == "향료" else "accepted"
    )


@pytest.mark.anyio
async def test_failed_knowledge_still_executes_candidate_and_option_http(monkeypatch, connections):
    api, skincare, catalog = connections
    monkeypatch.setattr(specialists, "research", AsyncMock(side_effect=UpstreamError("offline")))
    answer = await graph.run_compound(GOAL, CARE_QUESTION, skincare, catalog)
    assert len(api.calls) == 3
    assert answer.compound.options[8].outcome == "eligible"


@pytest.mark.anyio
async def test_three_turn_goal_change_through_chat_service(monkeypatch, connections):
    from app.services.conversation_context import read_context, updated_context

    api, skincare, catalog = connections
    monkeypatch.setattr(get_settings(), "g8_enabled", True)
    install_knowledge(monkeypatch)

    class TurnPlanner(Planner):
        turn = 0

        async def complete_with_tools(self, messages, tools, *, required_tool=None):
            reply, usage = await super().complete_with_tools(
                messages, tools, required_tool=required_tool
            )
            if required_tool == "plan_skin_consultation":
                self.turn += 1
                function = reply["choices"][0]["message"]["tool_calls"][0]["function"]
                decision = json.loads(function["arguments"])
                if self.turn > 1:
                    decision["action"] = "refine"
                    decision["goal"].update(
                        goals=["sensitivity"],
                        wantsProducts=self.turn == 3,
                        wantsKnowledge=self.turn == 2,
                    )
                    decision["question"] = "민감함 관리 방법은?" if self.turn == 2 else ""
                function["arguments"] = json.dumps(decision)
            return reply, usage

    chat = ChatService(None, TurnPlanner(), catalog, skincare=skincare)
    saved = {}
    for turn, utterance in enumerate(
        [QUESTION, "모공 말고 민감함 관리 방법만 설명해 줘.", "그 목표로 제품을 다시 추천해 줘."], 1
    ):
        request = ChatRequest(message=utterance, locale="ko")
        request._compound_context = read_context(saved).compound
        response = await chat.answer(request)
        assert response.compound is not None
        saved = updated_context(saved, response)
        restored = read_context(saved).compound
        if turn == 2:
            assert restored.candidates == [] and restored.candidate_goals is None
    calls = [body for path, body in api.calls if path.endswith("/v4")]
    assert len(calls) == 2
    assert calls[-1]["detectedConcerns"] == [{"goal": "sensitivity", "sources": ["conversation"]}]


@pytest.mark.parametrize("invalid", [None, "claim", "quote", "citation"])
def test_search_condition_accepts_paraphrase_only_with_linked_source(monkeypatch, invalid):
    from app.schemas.compound_consultation import KnowledgeSearchCondition

    knowledge = install_knowledge(monkeypatch).return_value.reply
    knowledge.claims[0].claim = "보습을 위해 글리세린을 함유한 제품을 고려할 수 있습니다."
    quote = "글리세린 성분은 피부의 수분 유지에 도움을 줍니다."
    knowledge.evidence[0].quote = quote
    proposal = KnowledgeSearchCondition(
        ingredient_name="글리세린",
        operator="includes",
        claim_index=0,
        evidence_id="E1",
        quote=quote,
    )
    if invalid == "claim":
        knowledge.claims[0].claim = "순한 세안 방법을 사용하세요."
    elif invalid == "quote":
        proposal.quote = "글리세린에 대한 원문에 없는 설명"
    elif invalid == "citation":
        knowledge.claims[0].citations = []
    accepted, decisions = specialists.validate_search_conditions(GOAL, knowledge, [proposal])
    assert bool(accepted) is (invalid is None)
    if invalid:
        assert decisions[0]["decision"] == "unverified_evidence"


def test_search_condition_rejects_unlinked_and_conflicting_evidence(monkeypatch):
    from app.schemas.compound_consultation import KnowledgeSearchCondition

    consult = install_knowledge(monkeypatch)
    knowledge = consult.return_value.reply
    text = "글리세린 성분을 확인하세요."
    knowledge.claims[0].claim = text
    knowledge.evidence[0].quote = text
    proposal = KnowledgeSearchCondition(
        ingredient_name="글리세린", operator="includes", claim_index=0, evidence_id="E1", quote=text
    )
    bad = proposal.model_copy(update={"evidence_id": "missing"})
    accepted, decisions = specialists.validate_search_conditions(GOAL, knowledge, [bad])
    assert not accepted and decisions[0]["decision"] == "unverified_evidence"
    accepted, decisions = specialists.validate_search_conditions(
        GOAL, knowledge, [proposal, proposal.model_copy(update={"operator": "excludes"})]
    )
    assert not accepted and decisions[-1]["decision"] == "conflicting_suggestions"


@pytest.mark.anyio
async def test_unknown_inclusion_is_not_described_as_exclusion(monkeypatch, connections):
    _, skincare, catalog = connections
    install_knowledge(monkeypatch)
    response = await graph.run_compound(GOAL, CARE_QUESTION, skincare, catalog)
    display = response.compound.model_copy(deep=True)
    display.options = [o for o in display.options if o.outcome == "unknown"]
    check = next(c for c in display.options[0].verification.checks if c.condition == "ingredient")
    check.operator = "includes"
    check.ingredient_name = "판테놀"
    answer = specialists.compose(display, None)
    assert "‘판테놀’ 포함 여부" in answer
    assert "‘판테놀’ 제외 여부" not in answer


@pytest.mark.anyio
async def test_extractor_failure_keeps_knowledge_and_product_lookup(monkeypatch, connections):
    api, skincare, catalog = connections
    install_knowledge(monkeypatch)

    class BrokenExtractor:
        configured = True

        async def complete_with_tools(self, *args, **kwargs):
            raise UpstreamError("extractor unavailable")

    response = await graph.run_compound(
        GOAL, CARE_QUESTION, skincare, catalog, llm=BrokenExtractor()
    )
    assert response.knowledge.status == "answered"
    assert len(api.calls) == 3 and response.compound.options[8].outcome == "eligible"


def resolved_ingredient_reply(monkeypatch, name="글리세린"):
    from app.services.knowledge_service import resolve
    from tests.test_knowledge_service import check, verification

    fixture = install_knowledge(monkeypatch).return_value.reply
    sentence = f"{name} 성분이 포함된 제품을 선택하세요."
    fixture.evidence[0].quote = sentence
    fixture.evidence[0].end_utf16 = len(sentence.encode("utf-16-le")) // 2
    draft = {
        "claims": [
            {"claim": "근거 없는 첫 주장", "citations": ["E1"]},
            {"claim": sentence, "citations": ["E1"]},
        ],
        "limitations": "",
    }
    audit = verification(
        check(1, requirements=["R1"], citations=["E1"], label="UNSUPPORTED"),
        check(2, requirements=["R1"], citations=["E1"]),
    )
    return resolve(draft, audit, fixture.evidence)


class IngredientExtractor:
    configured = True
    calls = 0

    async def complete_with_tools(self, messages, tools, *, required_tool=None):
        self.calls += 1
        assert required_tool == "extract_knowledge_search_conditions"
        reply = json.loads(messages[-1]["content"])["knowledge"]
        claim = reply["claims"][0]
        name = "판테놀" if "판테놀" in claim["claim"] else "글리세린"
        condition = {
            "ingredientName": name,
            "operator": "includes",
            "claimIndex": 0,
            "evidenceId": claim["citations"][0],
            "quote": claim["claim"],
        }
        return {
            "choices": [
                {
                    "message": {
                        "tool_calls": [
                            {
                                "function": {
                                    "name": required_tool,
                                    "arguments": json.dumps({"conditions": [condition]}),
                                }
                            }
                        ]
                    }
                }
            ]
        }, 0


@pytest.mark.anyio
async def test_g5_resolved_claim_indices_reach_n01_and_alias_limit(monkeypatch, connections):
    api, skincare, catalog = connections
    reply = resolved_ingredient_reply(monkeypatch)
    assert len(reply.claims) == 1 and reply.findings[0].index == 1
    monkeypatch.setattr(
        specialists,
        "consult_knowledge",
        AsyncMock(return_value=Consultation(reply=reply, trace={})),
    )
    goal = GOAL.model_copy(
        update={"excluded_ingredients": ["향료", "Fragrance", "에탄올", "멘톨", "리모넨", "리날룰"]}
    )
    result = await graph.run_compound(
        goal, CARE_QUESTION, skincare, catalog, llm=IngredientExtractor()
    )
    assert result.compound.options[8].outcome == "eligible"
    body = api.calls[-1][1]
    assert len(body["ingredientConditions"]) == 6
    assert body["ingredientConditions"][-1] == {
        "ingredientName": "글리세린",
        "operator": "includes",
    }
    assert (
        sum(c["ingredientName"] in {"향료", "Fragrance"} for c in body["ingredientConditions"]) == 1
    )


@pytest.mark.anyio
async def test_knowledge_conditions_survive_budget_release_and_goal_change(
    monkeypatch, connections
):
    from app.services.conversation_context import read_context, updated_context

    api, skincare, catalog = connections
    reply = resolved_ingredient_reply(monkeypatch)
    consult = AsyncMock(return_value=Consultation(reply=reply, trace={}))
    monkeypatch.setattr(specialists, "consult_knowledge", consult)
    extractor = IngredientExtractor()
    first = await graph.run_compound(GOAL, CARE_QUESTION, skincare, catalog, llm=extractor)
    previous = read_context(updated_context({}, first)).compound
    assert previous.goal.excluded_ingredients == ["향료"]
    assert previous.knowledge_search.source == "knowledge"
    changed_budget = GOAL.model_copy(update={"max_price_krw": 15000, "wants_knowledge": False})
    second = await graph.run_compound(
        changed_budget,
        "",
        skincare,
        catalog,
        previous=previous,
        reuse_candidates=True,
        llm=extractor,
    )
    previous = read_context(updated_context({}, second)).compound
    assert api.calls[-1][1]["ingredientConditions"][-1]["ingredientName"] == "글리세린"
    assert extractor.calls == 1 and consult.await_count == 1
    assert len([p for p, b in api.calls if p.endswith("/v4")]) == 1
    third = await graph.run_compound(
        changed_budget,
        "",
        skincare,
        catalog,
        previous=previous,
        reuse_candidates=True,
        llm=extractor,
        remove_knowledge_ingredients=["글리세린"],
    )
    previous = read_context(updated_context({}, third)).compound
    assert api.calls[-1][1]["ingredientConditions"] == [
        {"ingredientName": "향료", "operator": "excludes"}
    ]

    assert previous.knowledge_search.removed_ingredients == ["글리세린"]
    # Goal changes request fresh knowledge even for a product-only turn.
    reply = resolved_ingredient_reply(monkeypatch, "판테놀")
    consult.return_value = Consultation(reply=reply, trace={})
    monkeypatch.setattr(specialists, "consult_knowledge", consult)
    fourth = await graph.run_compound(
        changed_budget.model_copy(update={"goals": ["sensitivity"]}),
        "",
        skincare,
        catalog,
        previous=previous,
        reuse_candidates=True,
        llm=extractor,
    )
    assert api.calls[-1][1]["ingredientConditions"][-1]["ingredientName"] == "판테놀"
    assert extractor.calls == 2 and consult.await_count == 2
    assert len([p for p, b in api.calls if p.endswith("/v4")]) == 2
    previous = read_context(updated_context({}, fourth)).compound
    await graph.run_compound(
        fourth.compound.goal,
        "",
        skincare,
        catalog,
        previous=previous,
        reuse_candidates=True,
        llm=extractor,
        knowledge_action="clear",
    )
    assert api.calls[-1][1]["ingredientConditions"] == [
        {"ingredientName": "향료", "operator": "excludes"}
    ]


@pytest.mark.anyio
@pytest.mark.parametrize("verb", ["해제해", "삭제해", "재적용해", "다시 적용해"])
async def test_condition_verbs_through_chat_service(
    monkeypatch, connections, verb, record_property
):
    from app.services.conversation_context import read_context, updated_context

    api, skincare, catalog = connections
    monkeypatch.setattr(get_settings(), "g8_enabled", True)
    reply = resolved_ingredient_reply(monkeypatch)
    consult = AsyncMock(return_value=Consultation(reply=reply, trace={}))
    monkeypatch.setattr(specialists, "consult_knowledge", consult)
    extractor = IngredientExtractor()
    first = await graph.run_compound(GOAL, CARE_QUESTION, skincare, catalog, llm=extractor)
    previous = read_context(updated_context({}, first)).compound

    class ChangePlanner(Planner):
        async def complete_with_tools(self, messages, tools, *, required_tool=None):
            if required_tool == "extract_knowledge_search_conditions":
                return await extractor.complete_with_tools(
                    messages, tools, required_tool=required_tool
                )
            response, ms = await super().complete_with_tools(
                messages, tools, required_tool=required_tool
            )
            f = response["choices"][0]["message"]["tool_calls"][0]["function"]
            plan = json.loads(f["arguments"])
            plan.update(
                action="refine",
                knowledgeAction="clear" if verb in {"해제해", "삭제해"} else "reevaluate",
            )
            plan["goal"]["wantsKnowledge"] = False
            f["arguments"] = json.dumps(plan)
            return response, ms

    req = ChatRequest(message=f"지식 성분 조건을 {verb} 줘. 제품도 추천해 줘.", locale="ko")
    req._compound_context = previous
    answer = await ChatService(None, ChangePlanner(), catalog, skincare=skincare).answer(req)
    assert answer.compound is not None
    expected = [{"ingredientName": "향료", "operator": "excludes"}]
    if verb not in {"해제해", "삭제해"}:
        expected.append({"ingredientName": "글리세린", "operator": "includes"})
    assert api.calls[-1][1]["ingredientConditions"] == expected
    assert consult.await_count == (1 if verb in {"해제해", "삭제해"} else 2)
    record_property(
        "condition_entry",
        {
            "utterance": req.message,
            "optionRequest": api.calls[-1][1],
            "outcomes": [o.outcome for o in answer.compound.options],
            "modelConfiguredMode": "mock",
            "actualRemoteModelCalls": 0,
        },
    )


@pytest.mark.parametrize(
    "message",
    [
        "검색 조건을 삭제해. 기억도 삭제해",
        "추천 조건을 적용해. 립도 발라줘",
        "기억에서 성분 조건을 삭제해",
        "AR 조건을 적용해",
        "제품 추천하고 얼굴에 적용해",
    ],
)
def test_condition_change_does_not_bypass_execution_guard(monkeypatch, message):
    monkeypatch.setattr(get_settings(), "g8_enabled", True)
    assert not graph.is_search_condition_change(message)
    if any(word in message for word in ("기억", "AR")):
        assert not graph.may_plan(ChatRequest(message=message, locale="ko"), previous=True)


def test_condition_routing_preserves_g8_disabled_contract(monkeypatch):
    from app.services.chat_service import resolve_context, route_intent

    req = ChatRequest(message="검색 조건을 다시 적용해 줘. 제품도 추천해 줘.", locale="ko")
    monkeypatch.setattr(get_settings(), "g8_enabled", False)
    assert route_intent(resolve_context(req)).intent == "compound"
    monkeypatch.setattr(get_settings(), "g8_enabled", True)
    assert route_intent(resolve_context(req)).intent != "compound"


@pytest.mark.anyio
@pytest.mark.parametrize(
    "execution", ["얼굴에 발라", "강도를 조절해줘", "립 색도 설정해줘", "얼굴에 발라줄래?"]
)
async def test_mixed_execution_uses_existing_chat_path(
    monkeypatch, connections, execution, record_property
):
    from app.services.chat_service import resolve_context, route_intent

    api, skincare, catalog = connections
    message = "검색 조건을 다시 적용해서 제품 추천하고 " + execution
    planner = Planner()
    planner.complete_with_tools = AsyncMock(
        return_value=(
            {
                "choices": [
                    {
                        "message": {
                            "tool_calls": [
                                {
                                    "function": {
                                        "name": "plan_skin_consultation",
                                        "arguments": json.dumps(
                                            {"scope": "mixed", "action": "other"}
                                        ),
                                    }
                                }
                            ]
                        }
                    }
                ]
            },
            0,
        )
    )
    outputs = []
    for enabled in (False, True):
        monkeypatch.setattr(get_settings(), "g8_enabled", enabled)
        req = ChatRequest(message=message, locale="ko")
        assert route_intent(resolve_context(req)).intent == "compound"
        response = await ChatService(None, planner, catalog, skincare=skincare).answer(req)
        assert response.compound is None and response.ar_result is None
        outputs.append(response.model_dump(mode="json"))
    assert outputs[0] == outputs[1]
    assert api.calls == []
    assert planner.complete_with_tools.await_count == 1
    record_property(
        "mixed_execution",
        {
            "input": message,
            "response": outputs[1],
            "g8OffEqualsOn": True,
            "modelConfiguredMode": "mock",
            "actualRemoteModelCalls": 0,
        },
    )


@pytest.mark.anyio
async def test_original_n01_requests_situation_before_inventing_goal(
    monkeypatch, connections, record_property
):
    api, skincare, catalog = connections
    monkeypatch.setattr(get_settings(), "g8_enabled", True)
    monkeypatch.setattr(get_settings(), "g1_supervisor_enabled", True)
    original = "오후에 화장이 뜨는데 원인 알려주고 나한테 맞는 제품도 찾아줘"

    class ClarifyingPlanner(Planner):
        async def complete_with_tools(self, messages, tools, *, required_tool=None):
            response, ms = await super().complete_with_tools(
                messages, tools, required_tool=required_tool
            )
            f = response["choices"][0]["message"]["tool_calls"][0]["function"]
            f["arguments"] = json.dumps(
                {
                    "scope": "consultation",
                    "action": "clarify",
                    "question": (
                        "당김·각질이 있나요, 유분 때문에 뭉치나요? "
                        "사용 중인 기초와 베이스도 알려주세요."
                    ),
                }
            )
            return response, ms

    result = await ChatService(None, ClarifyingPlanner(), catalog, skincare=skincare).answer(
        ChatRequest(message=original, locale="ko")
    )
    assert result.result_type == "clarification" and result.products == []
    assert result.compound is None and api.calls == []
    assert "당김" in result.answer and "유분" in result.answer
    followup = ChatRequest(
        message="각질과 당김이 있어. 로션과 쿠션을 써. 예산은 2만 원이고 향료는 제외해 줘.",
        locale="ko",
        recentMessages=[
            {"id": "u1", "role": "user", "text": original},
            {"id": "a1", "role": "assistant", "text": result.answer},
        ],
    )
    assert graph.may_plan(followup)
    consult = install_knowledge(monkeypatch)

    class ContextPlanner(Planner):
        async def complete_with_tools(self, messages, tools, *, required_tool=None):
            response, ms = await super().complete_with_tools(
                messages, tools, required_tool=required_tool
            )
            if required_tool == "plan_skin_consultation":
                data = json.loads(messages[-1]["content"])
                assert data["recentMessages"][0]["text"] == original
                assert data["utterance"] == followup.message
                f = response["choices"][0]["message"]["tool_calls"][0]["function"]
                plan = json.loads(f["arguments"])
                plan["goal"].update(goals=["dryness"])
                plan["question"] = original + " / " + followup.message
                f["arguments"] = json.dumps(plan)
            return response, ms

    answer = await ChatService(None, ContextPlanner(), catalog, skincare=skincare).answer(followup)
    consult.assert_awaited_once_with(original + " / " + followup.message)
    assert answer.compound.goal.goals == ["dryness"]
    assert answer.compound.options[8].outcome == "eligible"
    record_property(
        "original_n01",
        {
            "input": original,
            "clarification": result.answer,
            "followup": followup.message,
            "knowledgeInput": consult.call_args.args[0],
            "answer": answer.answer,
            "toolRequests": api.calls,
            "modelConfiguredMode": "mock",
            "actualRemoteModelCalls": 0,
        },
    )


@pytest.mark.anyio
@pytest.mark.parametrize("unsupported", [[], ["실리콘 베이스 밀림 방지 제형"]])
async def test_usage_question_uses_knowledge_without_inferred_goal(
    monkeypatch, connections, unsupported
):
    from app.services import chat_service

    api, skincare, catalog = connections
    monkeypatch.setattr(get_settings(), "g8_enabled", True)
    consult = install_knowledge(monkeypatch)
    monkeypatch.setattr(chat_service, "consult_knowledge", consult)
    question = "세럼과 크림은 어떤 순서로 발라야 해?"
    planner = Planner()
    planner.complete_with_tools = AsyncMock(
        return_value=(
            {
                "choices": [
                    {
                        "message": {
                            "tool_calls": [
                                {
                                    "function": {
                                        "name": "plan_skin_consultation",
                                        "arguments": json.dumps(
                                            {
                                                "scope": "consultation",
                                                "action": "knowledge",
                                                "goal": {"goals": []},
                                                "wantsProducts": True,
                                                "wantsKnowledge": True,
                                                "question": question,
                                                "unsupportedProductConditions": unsupported,
                                            }
                                        ),
                                    }
                                }
                            ]
                        }
                    }
                ]
            },
            0,
        )
    )
    response = await ChatService(None, planner, catalog, skincare=skincare).answer(
        ChatRequest(message=question, locale="ko")
    )
    consult.assert_awaited_once_with(question)
    assert response.knowledge is not None and not response.products and response.compound is None
    assert api.calls == []
    if unsupported:
        assert unsupported[0] in response.answer


@pytest.mark.anyio
async def test_usage_advice_preserves_reapplication_and_goal_change(
    monkeypatch, connections, record_property
):
    from app.services.conversation_context import read_context, updated_context

    api, skincare, catalog = connections
    monkeypatch.setattr(get_settings(), "g8_enabled", True)
    reply = resolved_ingredient_reply(monkeypatch)
    consult = AsyncMock(return_value=Consultation(reply=reply, trace={}))
    monkeypatch.setattr(specialists, "consult_knowledge", consult)
    extractor = IngredientExtractor()
    first = await graph.run_compound(GOAL, CARE_QUESTION, skincare, catalog, llm=extractor)
    cleared = await graph.run_compound(
        GOAL,
        CARE_QUESTION,
        skincare,
        catalog,
        previous=first.chat_context.compound,
        llm=extractor,
        knowledge_action="clear",
    )
    state = read_context(updated_context({}, cleared)).compound
    assert state.knowledge_search.cleared
    observations = []

    class UsagePlanner(Planner):
        async def complete_with_tools(self, messages, tools, *, required_tool=None):
            if required_tool == "extract_knowledge_search_conditions":
                return await extractor.complete_with_tools(
                    messages, tools, required_tool=required_tool
                )
            response, ms = await super().complete_with_tools(
                messages, tools, required_tool=required_tool
            )
            f = response["choices"][0]["message"]["tool_calls"][0]["function"]
            data = json.loads(messages[-1]["content"])
            plan = json.loads(f["arguments"])
            plan.update(action="refine", question=data["utterance"])
            if "민감함" in data["utterance"]:
                plan["goal"].update(goals=["sensitivity"], wantsProducts=False)
            else:
                plan["knowledgeAction"] = "reevaluate"
            f["arguments"] = json.dumps(plan)
            return response, ms

    chat = ChatService(None, UsagePlanner(), catalog, skincare=skincare)
    for message in [
        "검색 조건은 다시 적용해 줘. 세럼은 아침에 발라도 돼?",
        "모공 말고 민감함 관리로 바꿀래. 세럼과 크림은 어떤 순서로 발라야 하는지 방법만 설명해 줘.",
    ]:
        req = ChatRequest(message=message, locale="ko")
        req._compound_context = state
        before = len(api.calls)
        result = await chat.answer(req)
        state = read_context(updated_context({}, result)).compound
        if "민감함" in message:
            assert state.goal.goals == ["sensitivity"]
            assert state.candidates == [] and state.candidate_goals is None
            assert len(api.calls) == before
        else:
            assert not state.knowledge_search.cleared
            assert {"ingredientName": "글리세린", "operator": "includes"} in api.calls[-1][1][
                "ingredientConditions"
            ]
        assert consult.call_args.args[0] == message
        observations.append(
            {
                "input": message,
                "goal": state.goal.model_dump(by_alias=True),
                "candidateCount": len(state.candidates),
                "toolRequests": api.calls[before:],
                "modelConfiguredMode": "mock",
                "actualRemoteModelCalls": 0,
            }
        )
    record_property("usage_advice", observations)


@pytest.mark.anyio
async def test_memory_and_conditions_stay_on_existing_owner_path(monkeypatch, connections):
    from tests.conftest import FakeGraph, FakeLlm

    api, skincare, catalog = connections
    llm = FakeLlm()
    llm.complete_with_tools = AsyncMock(side_effect=AssertionError("Protected memory path"))
    outputs = []
    for enabled in (False, True):
        monkeypatch.setattr(get_settings(), "g8_enabled", enabled)
        result = await ChatService(FakeGraph(), llm, catalog, skincare=skincare).answer(
            ChatRequest(message="성분 조건을 삭제하고 내 기억도 삭제해 줘", locale="ko")
        )
        outputs.append(result.model_dump(mode="json"))
        assert result.compound is None and result.ar_result is None
    assert outputs[0] == outputs[1] and api.calls == []
    llm.complete_with_tools.assert_not_awaited()


@pytest.mark.anyio
@pytest.mark.parametrize("action", ["knowledge", "clarify"])
async def test_question_plan_cannot_discard_condition_mutation(monkeypatch, action):
    from app.core.errors import ApiError

    monkeypatch.setattr(get_settings(), "g8_enabled", True)
    planner = Planner()
    planner.complete_with_tools = AsyncMock(
        return_value=(
            {
                "choices": [
                    {
                        "message": {
                            "tool_calls": [
                                {
                                    "function": {
                                        "name": "plan_skin_consultation",
                                        "arguments": json.dumps(
                                            {
                                                "scope": "consultation",
                                                "action": action,
                                                "question": CARE_QUESTION,
                                                "knowledgeAction": "reevaluate",
                                            }
                                        ),
                                    }
                                }
                            ]
                        }
                    }
                ]
            },
            0,
        )
    )
    with pytest.raises(ApiError):
        await graph.interpret(ChatRequest(message=QUESTION, locale="ko"), planner, None)


@pytest.mark.anyio
@pytest.mark.parametrize("scope", ["state_change", "mixed", "unknown"])
async def test_semantic_execution_scope_is_not_lost_in_lexical_fallback(
    monkeypatch, connections, scope
):
    api, skincare, catalog = connections
    monkeypatch.setattr(get_settings(), "g8_enabled", True)
    planner = Planner()
    planner.complete_with_tools = AsyncMock(
        return_value=(
            {
                "choices": [
                    {
                        "message": {
                            "tool_calls": [
                                {
                                    "function": {
                                        "name": "plan_skin_consultation",
                                        "arguments": json.dumps(
                                            {"scope": scope, "action": "other"}
                                        ),
                                    }
                                }
                            ]
                        }
                    }
                ]
            },
            0,
        )
    )
    result = await ChatService(None, planner, catalog, skincare=skincare).answer(
        ChatRequest(
            message="검색 조건을 다시 적용하고 제품 추천해 줘. 눈썹을 더 진하게 해줄래?",
            locale="ko",
        )
    )
    assert result.products == [] and result.compound is None and result.ar_result is None
    assert result.answer
    assert api.calls == [] and planner.complete_with_tools.await_count == 1


@pytest.mark.anyio
async def test_skin_parent_usage_only_preserves_goal_without_product_tools(
    monkeypatch, connections
):
    from app.services.conversation_context import prepare_request, updated_context

    api, skincare, catalog = connections
    monkeypatch.setattr(get_settings(), "g8_enabled", True)
    consult = install_knowledge(monkeypatch)

    class FollowupPlanner(Planner):
        async def complete_with_tools(self, messages, tools, *, required_tool=None):
            response, ms = await super().complete_with_tools(
                messages, tools, required_tool=required_tool
            )
            fn = response["choices"][0]["message"]["tool_calls"][0]["function"]
            incoming = json.loads(messages[-1]["content"])
            plan = json.loads(fn["arguments"])
            if incoming.get("previousGoal"):
                plan.update(action="refine", question=incoming["utterance"])
                plan["goal"] = {
                    **incoming["previousGoal"],
                    "wantsProducts": False,
                    "wantsKnowledge": True,
                }
            fn["arguments"] = json.dumps(plan)
            return response, ms

    service = ChatService(None, FollowupPlanner(), catalog, skincare=skincare)
    first = await service.answer(ChatRequest(message=QUESTION, locale="ko"))
    raw = updated_context({}, first)
    before = len(api.calls)
    followup = prepare_request(
        ChatRequest(message="상품은 됐고 사용 순서만 알려줘", locale="ko"), raw, []
    )
    result = await service.answer(followup)
    assert len(api.calls) == before
    assert result.compound.goal.goals == GOAL.goals
    assert result.compound.goal.wants_products is False
    assert result.style_recipe is None
    assert consult.call_args.args[0] == followup.message
    assert result._consultation_parent.plan_id == first._consultation_parent.plan_id

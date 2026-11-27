"""Real parent LangGraph, synthetic specialists/Catalog. No external model calls."""

import json
from uuid import uuid4

import pytest

from app.core.config import get_settings
from app.core.errors import UpstreamError
from app.schemas.chat import ChatRequest, ChatResponse
from app.schemas.consultation_parent import ConsultationParent, ParentTask
from app.schemas.knowledge import KnowledgeReply
from app.services import consultation_parent_graph as parent
from app.services.chat_service import ChatService
from app.services.conversation_context import prepare_request, updated_context
from app.services.knowledge_service import Consultation
from tests.conftest import FakeLlm
from tests.test_g8_owned_look import Catalog, owned, request


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.fixture(autouse=True)
def enabled(monkeypatch):
    monkeypatch.setattr(get_settings(), "g8_enabled", True)


@pytest.mark.anyio
async def test_result_binding_changes_actual_knowledge_input(monkeypatch, record_property):
    calls = []

    async def knowledge(question, *, prior_user_context):
        calls.append(json.loads(prior_user_context))
        return Consultation(
            KnowledgeReply(status="insufficient_evidence", limitations="합성 근거 부족"), {}
        )

    monkeypatch.setattr(parent.knowledge_service, "consult_knowledge", knowledge)
    catalog = Catalog()
    req = request([owned("lip-a", "lip-a-shade")], "블러셔는 없어. 이 룩 순서의 이유도 설명해줘.")
    service = ChatService(None, FakeLlm(configured=False), catalog)
    first = await service.answer(req)
    assert [p.id for p in first.products] == ["blush-b"]
    assert [t.goal for t in first._consultation_parent.tasks] == ["owned_look", "knowledge"]
    assert first._consultation_parent.tasks[-1].input_refs
    catalog.look.recipe.steps[0].description = "변경된 합성 볼 단계"
    second = await service.answer(req)
    assert (
        calls[0]["styleRecipe"]["steps"][0]["description"]
        != calls[1]["styleRecipe"]["steps"][0]["description"]
    )
    assert second.knowledge.status == "insufficient_evidence"
    assert second._consultation_parent.tasks[-1].status == "partial"
    assert second.ar_result is None and second.memory_proposal is None
    record_property(
        "parent_evidence",
        json.dumps(
            {
                "catalogMode": "mock",
                "modelConfiguredMode": "mock",
                "externalModelCalls": 0,
                "turns": [
                    {
                        "modelMode": "mock",
                        "externalModelCalls": 0,
                        "tasks": r._parent_trace,
                        "response": r.model_dump(mode="json", by_alias=True),
                    }
                    for r in (first, second)
                ],
            },
            ensure_ascii=False,
        ),
    )


@pytest.mark.anyio
async def test_knowledge_failure_keeps_product_result(monkeypatch):
    async def failure(*args, **kwargs):
        raise UpstreamError("synthetic unavailable")

    monkeypatch.setattr(parent.knowledge_service, "consult_knowledge", failure)
    response = await ChatService(None, FakeLlm(configured=False), Catalog()).answer(
        request([owned("lip-a", "lip-a-shade")], "블러셔는 없어. 주의점도 설명해줘.")
    )
    assert [p.id for p in response.products] == ["blush-b"]
    assert response._consultation_parent.tasks[-1].status == "failed"
    assert "유지" in response.answer


@pytest.mark.anyio
async def test_persisted_question_bare_answer_and_targeted_product_opt_out():
    catalog = Catalog()
    service = ChatService(None, FakeLlm(configured=False), catalog)
    req = request([owned("lip-a", "lip-a-shade")])
    first = await service.answer(req)
    assert first._consultation_parent.question.zone == "blush"
    raw = updated_context({}, first)
    # Serialize/validate just as the server does; no client-supplied parent fields.
    next_req = prepare_request(req.model_copy(update={"message": "없어"}), raw, [])
    assert "블러셔" in next_req.message
    second = await service.answer(next_req)
    assert [p.id for p in second.products] == ["blush-b"]
    assert second._consultation_parent.plan_id == first._consultation_parent.plan_id
    assert second._consultation_parent.version == 2
    assert second._consultation_parent.question is None
    third_req = prepare_request(
        req.model_copy(update={"message": "상품은 됐고 사용 순서만 알려줘"}),
        updated_context(raw, second),
        [],
    )
    before = len(catalog.searches)
    third = await service.answer(third_req)
    assert not third.products
    assert len(catalog.searches) == before
    assert (
        next(t for t in third._consultation_parent.tasks if t.goal == "owned_look").status
        == "superseded"
    )
    assert third.style_recipe and third._owned_look_context == second._owned_look_context
    assert "consultationParent" not in third.model_dump(mode="json", by_alias=True)


@pytest.mark.anyio
async def test_ambiguous_answer_and_changed_look_do_not_reuse_question():
    req = request([owned("lip-a", "lip-a-shade")])
    first = await ChatService(None, FakeLlm(configured=False), Catalog()).answer(req)
    ambiguous = parent.restore_followup(
        req.model_copy(update={"message": "응"}), first._consultation_parent
    )
    assert ambiguous.message == "응"
    changed = ChatRequest(message="없어", styleContext={"kind": "catalog", "lookId": "another"})
    assert parent.restore_followup(changed, first._consultation_parent)._consultation_parent is None


def test_stale_task_result_rejected():
    state = ConsultationParent(version=2)
    with pytest.raises(ValueError, match="Stale"):
        parent.accept_task(state, ParentTask(goal="knowledge", version=1), state.plan_id)
    with pytest.raises(ValueError, match="Stale"):
        parent.accept_task(state, ParentTask(goal="knowledge", version=2), uuid4())


@pytest.mark.anyio
async def test_n01_uses_same_parent_without_changing_payload():
    response = ChatResponse(
        answer="어떤 상황에 화장이 뜨나요?", products=[], resultType="clarification"
    )

    async def skin():
        return response

    result = await parent.run_parent(ChatRequest(message="화장이 떠요"), "skin", skin)
    assert result is response
    assert result._consultation_parent.question.input_key == "situation"
    assert result._consultation_parent.tasks[0].status == "waiting_user"


@pytest.mark.anyio
async def test_normal_n01_entry_reaches_parent(monkeypatch):
    from app.services import compound_consultation_graph as skin

    async def interpret(*args):
        return skin.Interpretation(
            scope="consultation", action="clarify", question="어떤 상황에 뜨나요?"
        )

    monkeypatch.setattr(skin, "interpret", interpret)
    req = ChatRequest(
        message="오후에 화장이 뜨는데 원인 알려주고 나한테 맞는 제품도 찾아줘", locale="ko"
    )
    result = await ChatService(None, FakeLlm(configured=False), Catalog()).answer(req)
    assert result._consultation_parent.question.input_key == "situation"
    assert result._consultation_parent.tasks[0].goal == "skin"


@pytest.mark.anyio
async def test_price_only_change_retains_explanation_reference(monkeypatch):
    from tests.test_g8_owned_look import FilteredCatalog

    calls = []

    async def knowledge(question, **kwargs):
        calls.append(question)
        return Consultation(KnowledgeReply(status="insufficient_evidence"), {})

    monkeypatch.setattr(parent.knowledge_service, "consult_knowledge", knowledge)
    catalog = FilteredCatalog()
    service = ChatService(None, FakeLlm(configured=False), catalog)
    req = request([owned("lip-a", "lip-a-shade")], "블러셔는 없어. 순서를 설명해줘.")
    first = await service.answer(req)
    old = next(t for t in first._consultation_parent.tasks if t.goal == "knowledge")
    raw = updated_context({}, first)
    followup = prepare_request(req.model_copy(update={"message": "예산은 2만원 이하"}), raw, [])
    second = await service.answer(followup)
    kept = next(t for t in second._consultation_parent.tasks if t.goal == "knowledge")
    assert kept == old and len(calls) == 1
    assert catalog.option_calls[-1].max_price_krw == 20000
    catalog.look.recipe.steps[0].description = "다른 단계"
    changed = prepare_request(
        req.model_copy(update={"message": "예산은 1만원 이하"}), updated_context(raw, second), []
    )
    third = await service.answer(changed)
    assert (
        next(t for t in third._consultation_parent.tasks if t.goal == "knowledge").status
        == "superseded"
    )


@pytest.mark.anyio
async def test_skin_explanation_followup_never_enters_style(monkeypatch):
    from app.services import compound_consultation_graph as skin

    calls = []

    async def interpret(req, *_args):
        calls.append(req.message)
        return skin.Interpretation(
            scope="consultation", action="clarify", question="사용 순서를 설명할게요."
        )

    async def forbidden(*_args, **_kwargs):
        raise AssertionError("Skin follow-up must not execute Style")

    monkeypatch.setattr(skin, "interpret", interpret)
    monkeypatch.setattr(parent, "execute_style", forbidden)
    req = ChatRequest(message="상품은 됐고 사용 순서만 알려줘", locale="ko")
    req._consultation_parent = ConsultationParent(tasks=[ParentTask(goal="skin", version=1)])
    from app.schemas.compound_consultation import CompoundContext, CompoundGoal

    req._compound_context = CompoundContext(plan_version=1, goal=CompoundGoal(goals=["dryness"]))
    result = await ChatService(None, FakeLlm(configured=False), Catalog()).answer(req)
    assert calls == [req.message]
    assert result._consultation_parent.tasks[0].goal == "skin"


@pytest.mark.anyio
@pytest.mark.parametrize(
    "message",
    ["블러셔는 없어. 설명은 필요 없고 상품만 추천해줘", "블러셔는 없어. 설명은 빼고 상품만 찾아줘"],
)
async def test_normal_owned_look_withdrawal_skips_knowledge(monkeypatch, message):
    async def forbidden(*_args, **_kwargs):
        raise AssertionError("Withdrawn explanation must not call G5")

    monkeypatch.setattr(parent.knowledge_service, "consult_knowledge", forbidden)
    result = await ChatService(None, FakeLlm(configured=False), Catalog()).answer(
        request([owned("lip-a", "lip-a-shade")], message)
    )
    assert result.products
    assert all(t.goal != "knowledge" for t in result._consultation_parent.tasks)


def test_specific_explanation_withdrawal_preserves_other_question():
    assert parent.wants_explanation("원인은 설명해주고 사용법은 빼줘")
    assert parent.wants_explanation("설명은 빼고 주의점은 알려줘")
    assert not parent.wants_explanation("설명은 필요 없고 상품만")

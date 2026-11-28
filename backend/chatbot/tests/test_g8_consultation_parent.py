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


@pytest.mark.parametrize(
    "states,question,expected",
    [
        (["completed", "completed"], False, "completed"),
        (["completed", "failed"], False, "partial"),
        (["partial", "failed"], False, "partial"),
        (["waiting_user", "failed"], True, "waiting_user"),
        (["completed", "waiting_user"], True, "partial"),
        (["failed", "failed"], False, "failed"),
        (["cancelled", "superseded"], False, "cancelled"),
        (["completed", "cancelled"], False, "completed"),
        (["pending"], False, "pending"),
    ],
)
def test_common_completion_uses_all_active_goal_states(states, question, expected):
    from app.schemas.consultation_parent import ParentQuestion
    from app.services.consultation_result_service import finalize_result

    response = ChatResponse(answer="合成", products=[])
    response._consultation_parent = ConsultationParent(
        tasks=[
            ParentTask(task_id=f"task-{i}", goal="product", version=1, status=s)
            for i, s in enumerate(states)
        ],
        question=ParentQuestion(goal="product", version=1, text="조건?", input_key="selection")
        if question
        else None,
    )
    assert finalize_result(response).consultation.status == expected
    assert response.consultation.has_pending_input == question


@pytest.mark.anyio
async def test_direct_specialist_question_has_owner_and_persistent_queue():
    async def clarify():
        return ChatResponse(answer="당김인가요?", products=[], result_type="clarification")

    result = await parent.run_parent(ChatRequest(message="관리와 상품"), "skin", clarify)
    saved = ConsultationParent.model_validate_json(result._consultation_parent.model_dump_json())
    assert saved.question.task_id == "skin"
    assert saved.pending_questions[0].task_id == "skin"
    assert saved.tasks[0].status == "waiting_user"


@pytest.mark.anyio
async def test_skin_condition_update_passes_current_utterance_and_structured_goal():
    from app.schemas.compound_consultation import CompoundContext, CompoundGoal
    from app.schemas.consultation_parent import ConsultationChange, ConsultationIntent

    quote = "예산만 1만8천 원으로 바꿔줘"
    req = ChatRequest(message=quote)
    compound = CompoundContext(planVersion=1, goal=CompoundGoal(goals=["dryness"]))
    task = ParentTask(
        task_id="task-skin", goal="skin", version=1,
        objective="원인과 관리 방법을 설명하고 제품도 추천", compound_context=compound,
    )
    req._consultation_parent = ConsultationParent(tasks=[task])
    req._parent_intent = ConsultationIntent(
        plan_id=req._consultation_parent.plan_id, version=1, action="continue",
        changes=[ConsultationChange(task_id=task.task_id, operation="update", quote=quote)],
    )
    req._parent_replan = {"updated":[task.task_id], "invalidated":[task.task_id], "withdrawn":[]}
    seen = []

    async def dispatch(kind, child):
        seen.append(child)
        return ChatResponse(answer="synthetic", products=[])

    await parent.run_id_tasks(req, dispatch)
    assert seen[0].message == quote
    assert seen[0]._compound_context.goal.goals == ["dryness"]


@pytest.mark.anyio
async def test_skin_situation_answer_retains_original_workflow_until_goal_is_structured():
    from app.schemas.consultation_parent import ConsultationChange, ConsultationIntent

    objective = "화장이 뜨는 이유를 설명하고 맞는 제품도 찾아줘"
    quote = "볼이 당기고 각질이 떠. 보습 제품을 2만 원 이하로 찾아줘"
    req = ChatRequest(message=quote)
    task = ParentTask(task_id="task-skin", goal="skin", version=1, objective=objective)
    req._consultation_parent = ConsultationParent(tasks=[task])
    req._parent_intent = ConsultationIntent(
        plan_id=req._consultation_parent.plan_id, version=1, action="continue",
        changes=[ConsultationChange(task_id=task.task_id, operation="update", quote=quote)],
    )
    req._parent_replan = {"updated": [task.task_id], "invalidated": [task.task_id], "withdrawn": []}
    seen = []

    async def dispatch(kind, child):
        seen.append(child)
        return ChatResponse(answer="synthetic", products=[])

    await parent.run_id_tasks(req, dispatch)
    assert objective in seen[0].message and quote in seen[0].message
    assert seen[0]._compound_context is None


def scoped_display_result(answer="scope"):
    from app.schemas.catalog import CheckedScope, OptionSearchResponse

    return ChatResponse(
        answer=answer,
        products=[],
        option_search=OptionSearchResponse(
            status="SUCCESS",
            excluded_count=0,
            omitted_count=0,
            checked_scope=CheckedScope(
                candidate_products=0,
                candidate_options=0,
                checked_options=0,
                unidentified_options=0,
                exhaustive=True,
                stopped_reason="COMPLETE",
                errors=0,
            ),
        ),
    )


def test_multiple_scopes_do_not_overwrite_ownership_question_or_become_unfinished_work():
    from app.schemas.consultation_parent import ParentQuestion
    from app.services.consultation_result_service import finalize_result
    from app.services.conversation_context import display_payload, restore_response

    results = {"task-a": scoped_display_result("토너"), "task-b": scoped_display_result("크림")}
    p = ConsultationParent(
        tasks=[
            ParentTask(
                task_id=tid,
                goal="product",
                objective=r.answer,
                version=1,
                status="completed",
                display_result=r.model_dump(mode="json", by_alias=True),
            )
            for tid, r in results.items()
        ]
    )
    r = parent.combine_id_results(p, results)
    r._consultation_parent = p
    finalize_result(r)
    assert r.consultation.status == "completed" and r.consultation.display_selection_required
    assert p.question is None and not r.products and r.option_search is None
    assert [c.task_id for c in r.consultation.display_choices] == list(results)
    assert "1. 토너" in r.answer and "2. 크림" in r.answer
    assert restore_response(r.answer, display_payload(r)).consultation == r.consultation
    p.question = ParentQuestion(
        task_id="task-c",
        goal="owned_look",
        version=1,
        text="립은 있나요?",
        input_key="ownership",
        zone="lip",
        need_id="lip-1",
        recipe_version="v1",
        ownership_scope="option",
    )
    p.tasks.append(
        ParentTask(task_id="task-c", goal="owned_look", version=1, status="waiting_user")
    )
    shown = parent.combine_id_results(p, {"task-b": results["task-b"]}, display_task_id="task-b")
    shown._consultation_parent = p
    finalize_result(shown)
    assert shown.consultation.status == "partial" and shown.consultation.has_pending_input
    assert not shown.consultation.display_selection_required and shown.option_search
    assert p.question.need_id == "lip-1" and p.question.ownership_scope == "option"


@pytest.mark.anyio
async def test_selected_look_app_request_enters_parent_and_preserves_budget():
    from tests.test_g8_owned_look import KoreanScopeCatalog, scope_request

    catalog = KoreanScopeCatalog()
    service = ChatService(None, FakeLlm(configured=False), catalog)
    req = scope_request("립 제품은 전부 없어. 2만원 이하로 찾아줘.")
    req.request_type = "style_consultation"
    first = await service.answer(req)
    assert first._consultation_parent is not None
    assert {p.id for p in first.products} == {"lip-a", "lip-b"}
    assert first.owned_look_options is not None
    follow = prepare_request(
        req.model_copy(update={"message": "예산은 3만원 이하로 바꿔줘"}),
        updated_context({}, first),
        [],
    )
    second = await service.answer(follow)
    assert second._consultation_parent is not None
    assert catalog.option_calls[-1].max_price_krw == 30000
    assert second._owned_look_context.declarations == first._owned_look_context.declarations
    assert second.ar_result is None and second.memory_proposal is None


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


@pytest.mark.anyio
async def test_same_zone_question_only_changes_target_and_final_option_result(record_property):
    from tests.test_g8_owned_look import MultiLipCatalog

    catalog = MultiLipCatalog()
    service = ChatService(None, FakeLlm(configured=False), catalog)
    req = request(
        [owned("lip-a", "lip-a-shade"), owned("blush-b", "blush-b-shade")], "2만원 이하로 추천해줘."
    )
    first = await service.answer(req)
    question = first._consultation_parent.question
    assert question.zone == "lip" and "lip-b" in question.text and question.need_id
    raw = updated_context({}, first)
    next_req = prepare_request(req.model_copy(update={"message": "없어"}), raw, [])
    second = await service.answer(next_req)
    assert [p.id for p in second.products] == ["lip-b"]
    assert catalog.option_calls[-1].product_ids == ["lip-b"]
    assert second.owned_look_options.selections
    assert second._consultation_parent.tasks[0].status == "completed"
    assert second._consultation_parent.question is None
    assert second._owned_look_context.declarations == {}
    assert set(second._owned_look_context.item_declarations) == {question.need_id}
    persisted = updated_context(raw, second)
    assert persisted["consultationParent"]["tasks"][0]["status"] == "completed"
    third_req = prepare_request(
        req.model_copy(update={"message": "예산 1만원 이하로 바꿔줘."}), persisted, []
    )
    third = await service.answer(third_req)
    assert third._consultation_parent.tasks[0].status == "partial"
    assert third._consultation_parent.question is None
    assert not third.products
    record_property(
        "multi_item_parent_mock",
        json.dumps(
            {
                "catalogMode": "mock",
                "modelConfiguredMode": "disabled",
                "actualExternalModelCalls": 0,
                "turns": [
                    {
                        "modelMode": "disabled",
                        "actualModelCalls": 0,
                        "parent": r._consultation_parent.model_dump(mode="json", by_alias=True),
                        "tasks": r._parent_trace,
                        "response": r.model_dump(mode="json", by_alias=True),
                    }
                    for r in [first, second, third]
                ],
            },
            ensure_ascii=False,
        ),
    )


@pytest.mark.anyio
async def test_parent_preserves_owned_success_on_option_failure():
    from tests.test_g8_owned_look import MultiLipCatalog

    catalog = MultiLipCatalog()
    catalog.fail_options = True
    response = await ChatService(None, FakeLlm(configured=False), catalog).answer(
        request(
            [owned("lip-a", "lip-a-shade"), owned("blush-b", "blush-b-shade")],
            "lip-b는 없어. 2만원 이하로 추천해줘.",
        )
    )
    assert response._consultation_parent.tasks[0].status == "partial"
    assert [i.status for i in response._owned_look_outcome.items].count("lookup_failed") == 1
    assert len(response.applied_memories) == 2
    assert not response.products and response._consultation_parent.question is None


@pytest.mark.anyio
async def test_product_present_requires_shown_option_and_legacy_question_is_not_promoted():
    from tests.test_g8_owned_look import KoreanScopeCatalog, scope_request

    catalog = KoreanScopeCatalog()
    service = ChatService(None, FakeLlm(configured=False), catalog)
    req = scope_request("롬앤 쥬시 래스팅 틴트는 있어.", other_option=True)
    first = await service.answer(req)
    question = first._consultation_parent.question
    assert question.ownership_scope == "option" and "07호" in question.text
    assert first._owned_look_outcome.status == "waiting_user"
    assert not first.products
    raw = updated_context({}, first)
    reply = prepare_request(req.model_copy(update={"message": "있어"}), raw, [])
    second = await service.answer(reply)
    assert second._owned_look_outcome.status == "completed"
    assert not second.products
    negative = await service.answer(
        prepare_request(req.model_copy(update={"message": "없어"}), raw, [])
    )
    assert [p.id for p in negative.products] == ["lip-b"]

    def needs(response):
        return next(
            t
            for e in response._parent_trace
            for t in e.get("specialistTrace", [])
            if t["task"]["taskId"] == "N1"
        )

    assert (
        needs(second)["result"]["inputFingerprint"] != needs(negative)["result"]["inputFingerprint"]
    )
    assert needs(second)["inputs"]["targetedAnswer"][2] == "있어"
    assert needs(negative)["inputs"]["targetedAnswer"][2] == "없어"
    # An older question did not record the option displayed to the user.
    raw["consultationParent"]["question"].pop("ownershipScope")
    legacy = await service.answer(
        prepare_request(req.model_copy(update={"message": "있어"}), raw, [])
    )
    assert legacy._owned_look_outcome.status == "waiting_user"
    assert "07호" in legacy._consultation_parent.question.text
    explicit = await service.answer(
        prepare_request(
            req.model_copy(update={"message": "롬앤 쥬시 래스팅 틴트 07호는 있어."}), raw, []
        )
    )
    assert explicit._owned_look_outcome.status == "completed"


@pytest.mark.anyio
@pytest.mark.parametrize("message", ["설명은 빼고 상품만 찾아줘", "설명 말고 제품만 추천해줘"])
async def test_goal_only_withdrawal_preserves_filters_and_product_route(
    monkeypatch, message, record_property
):
    from tests.test_g8_owned_look import KoreanScopeCatalog, scope_request

    calls = []

    async def knowledge(*args, **kwargs):
        calls.append(args)
        return Consultation(
            KnowledgeReply(status="insufficient_evidence", limitations="합성 근거 부족"), {}
        )

    monkeypatch.setattr(parent.knowledge_service, "consult_knowledge", knowledge)
    catalog = KoreanScopeCatalog()
    service = ChatService(None, FakeLlm(configured=False), catalog)
    req = scope_request(
        "롬앤 쥬시 래스팅 틴트는 없어. 2만원 이하 향료 제외하고 추천해줘. 순서의 이유도 설명해줘."
    )
    first = await service.answer(req)
    assert len(calls) == 1 and first.products
    assert first._consultation_answer.explanation in first.answer
    raw = updated_context({}, first)
    next_req = prepare_request(req.model_copy(update={"message": message}), raw, [])
    second = await service.answer(next_req)
    assert len(calls) == 1
    assert second._owned_look_context.filters == first._owned_look_context.filters
    assert second._consultation_answer.explanation is None
    assert (
        second._owned_look_context.item_declarations == first._owned_look_context.item_declarations
    )
    assert [p.id for p in second.products] == ["lip-b"]
    assert (
        next(t.status for t in second._consultation_parent.tasks if t.goal == "knowledge")
        == "superseded"
    )
    assert catalog.option_calls[-1].max_price_krw == 20000
    assert catalog.option_calls[-1].fragrance_free or catalog.option_calls[-1].ingredient_conditions
    assert second._consultation_parent.look.look_id == first._consultation_parent.look.look_id
    assert second.style_recipe.recipe_version == first.style_recipe.recipe_version
    record_property(
        "scope_goal_mock",
        json.dumps(
            {
                "catalogMode": "mock",
                "modelConfiguredMode": "mock",
                "actualExternalModelCalls": 0,
                "turns": [
                    {
                        "message": msg,
                        "mockG5Calls": count,
                        "actualExternalModelCalls": 0,
                        "parent": r._consultation_parent.model_dump(mode="json", by_alias=True),
                        "trace": r._parent_trace,
                        "response": r.model_dump(mode="json", by_alias=True),
                    }
                    for msg, count, r in [(req.message, 1, first), (message, 0, second)]
                ],
            },
            ensure_ascii=False,
        ),
    )


@pytest.mark.anyio
@pytest.mark.parametrize("step_text", ["합성 첫 순서", "합성 변경된 순서"])
async def test_first_entry_result_proposal_binds_actual_recipe(monkeypatch, step_text):
    from app.services import chat_service
    from tests.test_g8_consultation_intent import EntryModel

    calls = []

    async def knowledge(question, *, prior_user_context):
        calls.append((question, json.loads(prior_user_context)))
        return Consultation(KnowledgeReply(status="insufficient_evidence", limitations="합성"), {})

    monkeypatch.setattr(chat_service, "consult_knowledge", knowledge)
    catalog = Catalog()
    catalog.look.recipe.steps[0].description = step_text
    quote = "이 룩 순서의 이유도 설명해줘."
    req = request([owned("lip-a", "lip-a-shade")], "블러셔는 없어. " + quote)
    model = EntryModel(
        [{"capability": "owned_look", "quote": req.message, "explanationQuote": quote}]
    )
    result = await ChatService(None, model, catalog).answer(req)
    assert len(calls) == 1 and calls[0][0] == quote
    assert calls[0][1]["styleRecipe"]["steps"][0]["description"] == step_text
    tasks = result._consultation_parent.tasks
    assert [t.goal for t in tasks] == ["owned_look", "knowledge"]
    assert tasks[1].depends_on == [tasks[0].task_id]
    assert tasks[1].status == "partial"
    assert [p.id for p in result.products] == ["blush-b"]
    assert len([e for e in result._parent_trace if e.get("continuation") == "accepted"]) == 1
    assert catalog.searches == [{"ids": ["lip-a"]}, {"ids": ["blush-b"]}]


@pytest.mark.anyio
async def test_result_proposal_capacity_preserves_results_but_not_completion(monkeypatch):
    from app.services import chat_service
    from tests.test_g8_consultation_intent import EntryModel

    calls = []

    async def knowledge(question, **kwargs):
        calls.append(question)
        return Consultation(KnowledgeReply(status="insufficient_evidence", limitations="합성"), {})

    monkeypatch.setattr(chat_service, "consult_knowledge", knowledge)
    req = request([owned("lip-a", "lip-a-shade")], "블러셔는 없어. 순서 이유 설명.")
    owned_clause = req.message
    clauses = ["보습 설명", "세안 설명", "차단 설명", "각질 설명"]
    req.message += " ".join(clauses)
    model = EntryModel(
        [{"capability": "owned_look", "quote": owned_clause, "explanationQuote": "순서 이유 설명."}]
        + [{"capability": "knowledge", "quote": q} for q in clauses]
    )
    result = await ChatService(None, model, Catalog()).answer(req)
    assert calls == clauses
    assert len(result._consultation_parent.tasks) == 5
    assert result._consultation_parent.tasks[0].status == "partial"
    assert "continuation_capacity" in result._consultation_parent.tasks[0].limitations
    assert result._task_results[0].status == "partial"
    assert [p.id for p in result.products] == ["blush-b"]
    assert "추가 설명을 이번 실행에서 마치지 못했어요" in result.answer


@pytest.mark.anyio
async def test_proposed_cooperation_update_retry_and_withdraw(monkeypatch):
    from app.services import chat_service
    from tests.test_g8_consultation_intent import AdditionModel, EntryModel

    calls = []

    async def knowledge(question, *, prior_user_context):
        calls.append(json.loads(prior_user_context))
        return Consultation(KnowledgeReply(status="insufficient_evidence", limitations="합성"), {})

    monkeypatch.setattr(chat_service, "consult_knowledge", knowledge)
    catalog = Catalog()
    quote = "이 룩 순서의 이유도 설명해줘."
    req = request([owned("lip-a", "lip-a-shade")], "블러셔는 없어. " + quote)
    result = await ChatService(
        None,
        EntryModel([{"capability": "owned_look", "quote": req.message, "explanationQuote": quote}]),
        catalog,
    ).answer(req)
    source, explanation = [t.task_id for t in result._consultation_parent.tasks]
    catalog.look.recipe.steps[0].description = "변경된 실제 입력"
    follow = prepare_request(
        req.model_copy(update={"message": "추천을 다시 확인해줘"}), updated_context({}, result), []
    )
    result = await ChatService(
        None,
        AdditionModel(
            changes=[
                {
                    "taskId": source,
                    "operation": "update",
                    "quote": follow.message,
                }
            ]
        ),
        catalog,
    ).answer(follow)
    assert len(result._consultation_parent.tasks) == 2
    assert len(calls) == 2
    assert calls[-1]["styleRecipe"]["steps"][0]["description"] == "변경된 실제 입력"
    before = len(catalog.searches)
    follow = prepare_request(
        req.model_copy(update={"message": "설명만 다시 해줘"}), updated_context({}, result), []
    )
    result = await ChatService(
        None, AdditionModel(action="retry", targets=[explanation]), catalog
    ).answer(follow)
    assert len(calls) == 3 and len(catalog.searches) == before
    follow = prepare_request(
        req.model_copy(update={"message": "설명은 빼고 추천만 다시 확인해줘"}),
        updated_context({}, result),
        [],
    )
    result = await ChatService(
        None,
        AdditionModel(
            changes=[
                {"taskId": explanation, "operation": "withdraw", "quote": "설명은 빼고"},
                {"taskId": source, "operation": "update", "quote": "추천만 다시 확인해줘"},
            ]
        ),
        catalog,
    ).answer(follow)
    assert len(calls) == 3
    assert len(result._consultation_parent.tasks) == 2
    assert (
        next(t for t in result._consultation_parent.tasks if t.task_id == explanation).status
        == "superseded"
    )


@pytest.mark.anyio
@pytest.mark.parametrize("status", ["failed", "cancelled", "superseded"])
async def test_optional_success_binding_does_not_execute_without_source(status):
    from app.schemas.consultation_task import ConsultationTaskRequest
    from app.services.consultation_parent_graph import execute_request

    source = ParentTask(task_id="task-source", goal="owned_look", version=1, status=status)
    target = ParentTask(
        task_id="task-target", goal="knowledge", version=1, depends_on=[source.task_id]
    )
    plan = ConsultationParent(tasks=[source, target])

    async def forbidden():
        pytest.fail("Unavailable source must not become a general explanation")

    result, retry = await execute_request(
        plan,
        target,
        ConsultationTaskRequest(
            task_id=target.task_id,
            capability="knowledge",
            inputs={"referenceContext": {}},
            depends_on=[source.task_id],
            requires_success=False,
        ),
        forbidden,
    )
    assert result is None and not retry
    assert target.status == "partial" and target.reason == "dependency_unavailable"


@pytest.mark.anyio
async def test_execution_control_rejects_late_result_before_next_read():
    from app.core.errors import ApiError
    from app.services.consultation_parent_graph import run_independent_reads

    active = True
    calls = []

    async def check():
        if not active:
            raise ApiError(409, "interrupted", "request_interrupted")

    async def first():
        nonlocal active
        calls.append("first")
        active = False
        return ChatResponse(answer="late", products=[])

    async def second():
        calls.append("second")
        return ChatResponse(answer="unexpected", products=[])

    with pytest.raises(ApiError, match="interrupted"):
        await run_independent_reads(
            "synthetic", {"knowledge": first, "style": second}, {}, check_active=check
        )
    assert calls == ["first"]


@pytest.mark.anyio
async def test_initial_specialist_needs_keep_option_identity_and_situation_until_answered(
    monkeypatch,
):
    from app.schemas.consultation_parent import ConsultationChange
    from app.services.consultation_intent_service import plan_changes
    from app.services.consultation_parent_graph import reconcile_questions, run_independent_reads
    from app.services.owned_look_consultation_service import execute_owned_look
    from tests.test_g8_owned_look import KoreanScopeCatalog, scope_request

    req = scope_request("이 룩에 없는 상품 추천해줘")
    req._owned_look_llm = None
    catalog = KoreanScopeCatalog()
    actual_owned = await execute_owned_look(req, catalog)
    assert actual_owned._owned_look_outcome.status == "waiting_user"

    async def ownership():
        return actual_owned

    async def situation():
        return ChatResponse(
            answer="화장이 뜨는 상황을 알려주세요", products=[], result_type="clarification"
        )

    p, results, _ = await run_independent_reads(
        req.message, {"owned_look": ownership, "skin": situation}, {}
    )
    reconcile_questions(p)
    assert {q.input_key for q in p.pending_questions} == {"ownership", "situation"}
    own = next(q for q in p.pending_questions if q.input_key == "ownership")
    assert own.need_id and own.recipe_version and own.zone and own.ownership_scope == "option"
    first_id = own.need_id
    response = ChatResponse(answer="두 확인 질문", products=[])
    response._consultation_parent = p
    restored = prepare_request(
        req.model_copy(update={"message": "피부는 오후에 각질이 떠"}),
        updated_context({}, response),
        [],
    )
    assert restored._consultation_parent.pending_questions == p.pending_questions
    revised, _ = plan_changes(
        p, [ConsultationChange(task_id="skin", operation="update", quote=restored.message)]
    )

    async def resolved():
        return ChatResponse(answer="상황 확인됨", products=[])

    next_parent, _, _ = await run_independent_reads(
        restored.message,
        {"owned_look": ownership, "skin": resolved},
        {"owned_look": results["owned_look"]},
        previous=revised,
        selected={"skin"},
    )
    reconcile_questions(next_parent, previous=p, selected={"skin"})
    assert next_parent.pending_questions and all(
        q.input_key == "ownership" for q in next_parent.pending_questions
    )
    assert (
        next_parent.question.need_id == first_id
        and next_parent.question.ownership_scope == "option"
    )
    assert all(q.version == next_parent.version for q in next_parent.pending_questions)
    assert next_parent.tasks[0].input_needs[0].need_id == first_id


@pytest.mark.anyio
async def test_delegated_skin_goal_uses_own_scope_from_selected_look_screen():
    from app.schemas.consultation_parent import ConsultationAddition, ConsultationIntent
    from app.services.compound_consultation_graph import may_plan

    req = request([], "건조해서 화장이 떠. 원인 설명하고 제품 찾아줘")
    req.request_type = "style_consultation"
    original_style = req.style_context
    req._consultation_parent = ConsultationParent()
    req._parent_intent = ConsultationIntent(
        plan_id=req._consultation_parent.plan_id,
        version=1,
        action="continue",
        additions=[ConsultationAddition(capability="skin", quote=req.message)],
    )
    observed = []

    async def dispatch(capability, child):
        observed.append(capability)
        assert child.request_type == "beauty_consultation"
        assert child.style_context is None and child.screen_context is None
        assert may_plan(child)
        return ChatResponse(answer="피부 상담 결과", products=[])

    response = await parent.run_id_tasks(req, dispatch)
    assert observed == ["skin"] and response.answer == "피부 상담 결과"
    assert req.request_type == "style_consultation" and req.style_context == original_style


def test_parent_scope_ignores_sibling_filters_but_keeps_selection_and_memory_fences():
    from app.schemas.chat import BeautyContext, BeautyFilters

    req = ChatRequest(message="질문 답변", locale="ko")
    baseline = parent.task_scope(req)
    req.chat_context = BeautyContext(
        issued_at=1, filters=BeautyFilters(category="skincare", max_price_krw=20000)
    )
    assert parent.task_scope(req) == baseline
    req.chat_context.selected_product_id = "product-other"
    assert parent.task_scope(req) != baseline
    req.chat_context.selected_product_id = None
    req._memory_generation = "changed-generation"
    assert parent.task_scope(req) != baseline


@pytest.mark.anyio
async def test_skin_dispatch_preserves_actual_situation_question(monkeypatch):
    from app.services import compound_consultation_graph

    question = "당김·각질인가요, 유분·뭉침인가요? 사용 중인 기초·베이스도 알려주세요."

    async def interpret(req, llm, previous):
        return compound_consultation_graph.Interpretation(
            scope="consultation", action="clarify", question=question
        )

    monkeypatch.setattr(compound_consultation_graph, "interpret", interpret)
    result = await ChatService(None, FakeLlm())._dispatch_parent_read(
        "skin", ChatRequest(message="원인과 제품 알려줘", locale="ko")
    )
    assert result.result_type == "clarification" and result.answer == question


@pytest.mark.anyio
async def test_skin_completion_keeps_personal_cause_gap_even_if_general_knowledge_answered():
    from app.schemas.compound_consultation import CompoundDisplay
    from app.schemas.consultation_task import ConsultationTaskRequest
    from app.schemas.knowledge import KnowledgeReply
    from tests.test_g8_compound_consultation import GOAL

    p = ConsultationParent(tasks=[ParentTask(goal="skin", version=1)])
    task = p.tasks[0]

    async def run():
        return ChatResponse(
            answer="일반 설명과 조건별 후보",
            products=[],
            compound=CompoundDisplay(plan_version=1, goal=GOAL),
            knowledge=KnowledgeReply(status="answered", limitations="개인 원인은 미확인"),
        )

    await parent.execute_request(
        p, task, ConsultationTaskRequest(task_id=task.task_id, capability="skin", inputs={}), run
    )
    assert task.status == "partial"


@pytest.mark.anyio
async def test_rejected_question_answer_retains_all_old_input_needs():
    from app.schemas.consultation_task import ConsultationTaskRequest, TaskInputNeed

    old = ConsultationParent(
        tasks=[
            ParentTask(
                task_id="task-look",
                goal="owned_look",
                version=1,
                status="waiting_user",
                input_needs=[
                    TaskInputNeed(
                        key="ownership", question="A 있나요?", need_id="a", recipe_version="v1"
                    ),
                    TaskInputNeed(
                        key="ownership", question="B 있나요?", need_id="b", recipe_version="v1"
                    ),
                ],
            )
        ]
    )

    async def rejected():
        response = ChatResponse(
            answer="보유 답변을 확인해 주세요", products=[], result_type="clarification"
        )
        response._preserve_parent_context = True
        return response

    revised, _, _ = await parent.run_independent_reads(
        "답변",
        {"task-look": rejected},
        {},
        previous=old,
        selected={"task-look"},
        requests={
            "task-look": ConsultationTaskRequest(
                task_id="task-look", capability="owned_look", inputs={}
            )
        },
    )
    assert revised.tasks[0].input_needs == old.tasks[0].input_needs


@pytest.mark.anyio
async def test_skin_compound_state_is_task_scoped_across_other_task_and_storage():
    from app.schemas.compound_consultation import CompoundContext, KnowledgeSearchState
    from app.schemas.consultation_answer import KnowledgeCoverage, RequirementCoverage
    from app.schemas.consultation_parent import ConsultationIntent
    from tests.test_g8_compound_consultation import GOAL

    req = ChatRequest(message="피부 상담 이어줘", locale="ko")
    state = CompoundContext(
        plan_version=1,
        goal=GOAL,
        knowledge_search=KnowledgeSearchState(
            goals=GOAL.goals,
            coverage=KnowledgeCoverage(
                scope="explanation",
                requirements=[
                    RequirementCoverage(
                        requirement_id="R1", description="개인 원인", fulfilled=False
                    )
                ],
            ),
        ),
    )
    p = ConsultationParent(
        tasks=[
            ParentTask(
                task_id="task-skin",
                goal="skin",
                version=1,
                status="partial",
                compound_context=state,
                scope_digest=parent.task_scope(req),
            )
        ]
    )
    restored = ConsultationParent.model_validate_json(p.model_dump_json())
    req._consultation_parent = restored
    req._parent_intent = ConsultationIntent(
        plan_id=p.plan_id,
        version=1,
        action="continue",
        changes=[{"taskId": "task-skin", "operation": "update", "quote": req.message}],
    )
    req._parent_replan = {"updated": ["task-skin"], "invalidated": ["task-skin"], "withdrawn": []}

    async def dispatch(capability, child):
        assert capability == "skin" and child._compound_context == state
        return ChatResponse(answer="이어가는 설명", products=[])

    response = await parent.run_id_tasks(req, dispatch)
    assert response._consultation_parent.tasks[0].compound_context == state


def test_changed_result_gets_focus_while_preserved_question_does_not_replay_long_answer():
    from app.schemas.consultation_parent import ParentQuestion
    from app.services.consultation_result_service import finalize_result

    results = {
        "task-look": scoped_display_result("old long recommendation"),
        "task-skin": scoped_display_result("new skin explanation"),
    }
    p = ConsultationParent(
        tasks=[
            ParentTask(
                task_id="task-look",
                goal="owned_look",
                version=1,
                status="waiting_user",
                reason="preserved_completed_result",
                objective="룩 상담",
            ),
            ParentTask(
                task_id="task-skin",
                goal="skin",
                version=1,
                status="completed",
                objective="피부 상담",
            ),
        ],
        pending_questions=[
            ParentQuestion(
                task_id="task-look",
                goal="owned_look",
                version=1,
                text="롬앤 제품을 가지고 있나요?",
                input_key="ownership",
                need_id="romand",
            )
        ],
    )
    for task in p.tasks:
        task.display_result = results[task.task_id].model_dump(mode="json", by_alias=True)
    r = parent.combine_id_results(p, results, previous=p.model_copy(deep=True))
    r._consultation_parent = p
    finalize_result(r)
    assert "old long recommendation" not in r.answer
    assert "new skin explanation" in r.answer
    assert "롬앤 제품을 가지고 있나요?" not in r.answer
    assert p.pending_questions[0].need_id == "romand"
    assert "어느 요청의 결과부터" not in r.answer
    assert r.consultation.selected_task_id == "task-skin"
    assert not r.consultation.display_selection_required
    assert len(r.consultation.display_choices) == 2
    assert r.consultation.status == "partial" and r.consultation.has_pending_input


def test_new_plain_product_cards_do_not_disappear_behind_cached_scopes():
    from tests.test_beauty_consultation import product

    old = scoped_display_result("old scoped result")
    fresh = ChatResponse(
        answer="립펜슬 후보", products=[product("립펜슬", 10000, category="lip").model_dump()]
    )
    p = ConsultationParent(
        tasks=[
            ParentTask(
                task_id="task-old",
                goal="skin",
                version=1,
                status="partial",
                reason="preserved_completed_result",
                display_result=old.model_dump(mode="json"),
            ),
            ParentTask(
                task_id="task-new",
                goal="product",
                version=1,
                status="completed",
                display_result=fresh.model_dump(mode="json"),
            ),
        ]
    )
    r = parent.combine_id_results(p, {"task-old": old, "task-new": fresh}, previous=p)
    assert [x.id for x in r.products] == [fresh.products[0].id]
    assert r.option_search is None and r.compound is None
    assert "어느 요청의 결과부터" not in r.answer
    assert p.result_selection.selected_task_id == "task-new"
    assert p.result_selection.task_ids == ["task-old", "task-new"]


def test_identical_preservation_acknowledgements_do_not_repeat_or_merge_task_state():
    p = ConsultationParent(
        tasks=[
            ParentTask(
                task_id=f"task-{i}",
                goal="knowledge",
                version=1,
                status="completed",
                reason="preserved_completed_result",
            )
            for i in range(2)
        ]
    )
    results = {t.task_id: ChatResponse(answer="원래 설명", products=[]) for t in p.tasks}
    r = parent.combine_id_results(p, results, previous=p.model_copy(deep=True))
    assert r.answer.count("앞서 안내한 설명은 그대로 유지했어요.") == 1
    assert [t.task_id for t in p.tasks] == ["task-0", "task-1"]
    assert all(x.answer == "원래 설명" for x in results.values())


@pytest.mark.anyio
@pytest.mark.parametrize("entry", ["legacy", "typed"])
async def test_g5_disabled_explanation_preserves_owned_look_results(monkeypatch, entry):
    import httpx

    from app.services import knowledge_service
    from tests.test_g8_consultation_intent import EntryModel

    settings = get_settings()
    monkeypatch.setattr(settings, "g5_enabled", False)
    monkeypatch.setattr(settings, "g5_openai_api_key", "synthetic-key")
    monkeypatch.setattr(settings, "g5_internal_token", "synthetic-token")

    async def forbidden(*args, **kwargs):
        pytest.fail("Disabled knowledge must not execute HTTP or its specialist")

    monkeypatch.setattr(knowledge_service.KnowledgeService, "consult", forbidden)
    monkeypatch.setattr(httpx.AsyncClient, "send", forbidden)
    catalog = Catalog()
    quote = "이 룩 순서의 이유도 설명해줘"
    req = request([owned("lip-a", "lip-a-shade")], "블러셔는 없어. " + quote)
    if entry == "legacy":
        result = await parent.run_parent(req, "owned_look", lambda: None, catalog=catalog)
    else:
        model = EntryModel([
            {"capability": "owned_look", "quote": req.message, "explanationQuote": quote},
        ])
        result = await ChatService(None, model, catalog).answer(req)
    task = next(t for t in result._consultation_parent.tasks if t.goal == "knowledge")
    assert task.status == "failed" and task.reason == "g5_disabled"
    assert task.limitations == ["g5_disabled"] and task.attempts == 1
    assert [p.id for p in result.products] == ["blush-b"]
    assert result.style_recipe and result._owned_look_context


@pytest.mark.anyio
async def test_g8_off_ordinary_reply_preserves_saved_owned_look_context(monkeypatch):
    from tests.conftest import FakeGraph

    req = request([owned("lip-a", "lip-a-shade")], "블러셔는 없어")
    first = await parent.run_parent(req, "owned_look", lambda: None, catalog=Catalog())
    raw = updated_context({}, first)
    monkeypatch.setattr(get_settings(), "g8_enabled", False)
    restored = prepare_request(
        req.model_copy(update={"message": "안녕", "request_type": "chat"}), raw, []
    )
    response = await ChatService(FakeGraph(), FakeLlm()).answer(restored)
    again = prepare_request(
        req.model_copy(update={"message": "안녕", "request_type": "chat"}),
        updated_context(raw, response), [],
    )
    assert again._owned_look_context == first._owned_look_context
    assert again._consultation_parent == first._consultation_parent
    assert response.consultation is None

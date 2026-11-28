"""Real parent/ChatService and structured proposals; models and Catalog are synthetic."""

import json
from uuid import uuid4

import pytest

from app.core.config import get_settings
from app.schemas.chat import ChatRequest, ChatResponse
from app.schemas.consultation_parent import ConsultationIntent, ConsultationParent, ParentTask
from app.schemas.consultation_task import ConsultationTaskRequest
from app.services.chat_service import ChatService
from app.services.consultation_intent_service import TOOL, validate_intent
from app.services.consultation_parent_graph import execute_request
from app.services.conversation_context import prepare_request, updated_context
from tests.test_g8_partial_success import Catalog, CombinedModel, request


def test_unique_legacy_question_is_bound_and_ambiguous_owner_is_not_guessed():
    from app.schemas.consultation_parent import ParentQuestion
    from app.services.consultation_intent_service import intent_schema

    question = ParentQuestion(goal="skin", version=1, text="상황?", input_key="situation")
    single = ConsultationParent(
        tasks=[ParentTask(goal="skin", version=1, status="waiting_user")], question=question
    )
    assert single.question.task_id == "skin"
    assert single.pending_questions[0].task_id == "skin"
    ambiguous = ConsultationParent(tasks=[
        ParentTask(task_id="skin-a", goal="skin", version=1, status="waiting_user"),
        ParentTask(task_id="skin-b", goal="skin", version=1, status="waiting_user"),
    ], question=question)
    assert ambiguous.question.task_id is None and ambiguous.pending_questions == []
    assert intent_schema(ambiguous)["properties"]["questionChanges"]["maxItems"] == 0


def test_answer_and_grounded_condition_update_share_one_owner():
    req = question_scope_request()
    req.message = "삐아는 없어. 2만 원 이하로 찾아줘. 피부 설명은 유지해줘"
    proposal = question_proposal(req)
    proposal.question_changes = proposal.question_changes[:1]
    from app.schemas.consultation_parent import ConsultationChange

    proposal.changes.append(
        ConsultationChange(task_id="task-look", operation="update", quote="2만 원 이하로 찾아줘")
    )
    result = validate_intent(proposal, req)
    update = next(c for c in result.changes if c.task_id == "task-look")
    assert update.quote == "삐아는 없어\n2만 원 이하로 찾아줘"


def question_scope_request():
    from app.schemas.consultation_parent import ParentQuestion

    req = ChatRequest(message="삐아는 없어. 롬앤은 나중에 답할게. 피부 설명은 유지해줘")
    questions = [
        ParentQuestion(
            task_id="task-look",
            goal="owned_look",
            version=1,
            text=f"{name} 있나요?",
            input_key="ownership",
            need_id=key,
            recipe_version="recipe-v1",
            ownership_scope="option",
        )
        for name, key in [("삐아", "bbia"), ("롬앤", "romand")]
    ]
    req._consultation_parent = ConsultationParent(
        tasks=[
            ParentTask(task_id="task-look", goal="owned_look", version=1, status="waiting_user"),
            ParentTask(task_id="task-skin", goal="skin", version=1, status="partial"),
        ],
        question=questions[0],
        pending_questions=questions,
    )
    return req


def question_proposal(req):
    return ConsultationIntent(
        plan_id=req._consultation_parent.plan_id,
        version=1,
        action="continue",
        question_changes=[
            {
                "taskId": "task-look",
                "inputKey": "ownership",
                "needId": "bbia",
                "operation": "answer",
                "quote": "삐아는 없어",
            },
            {
                "taskId": "task-look",
                "inputKey": "ownership",
                "needId": "romand",
                "operation": "preserve",
                "quote": "롬앤은 나중에 답할게",
            },
        ],
        changes=[{"taskId": "task-skin", "operation": "preserve", "quote": "피부 설명은 유지해줘"}],
    )


def test_question_answer_and_sibling_preservation_normalize_one_owner_update():
    req = question_scope_request()
    result = validate_intent(question_proposal(req), req)
    assert [(c.task_id, c.operation, c.quote) for c in result.changes] == [
        ("task-skin", "preserve", "피부 설명은 유지해줘"),
        ("task-look", "update", "삐아는 없어"),
    ]
    assert len(req._consultation_parent.pending_questions) == 2


@pytest.mark.parametrize("invalid", ["unknown", "same_question", "task_preserve", "stale"])
def test_question_scope_rejects_conflicts_and_stale_references_without_mutation(invalid):
    req = question_scope_request()
    proposal = question_proposal(req)
    original = req._consultation_parent.model_dump_json()
    if invalid == "unknown":
        proposal.question_changes[0].need_id = "unlisted"
    elif invalid == "same_question":
        proposal.question_changes[1].need_id = "bbia"
    elif invalid == "task_preserve":
        proposal.changes[0].task_id = "task-look"
    else:
        proposal.version += 1
    with pytest.raises(ValueError):
        validate_intent(proposal, req)
    assert req._consultation_parent.model_dump_json() == original


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.fixture(autouse=True)
def enabled(monkeypatch):
    monkeypatch.setattr(get_settings(), "g8_enabled", True)


class IntentModel(CombinedModel):
    def __init__(self, action, targets, *, result_position=None):
        super().__init__()
        self.action, self.targets = action, targets
        self.result_position = result_position
        self.intent_calls = 0

    async def complete_with_tools(self, messages, tools, *, required_tool=None):
        if required_tool != TOOL:
            return await super().complete_with_tools(messages, tools, required_tool=required_tool)
        self.intent_calls += 1
        data = json.loads(messages[-1]["content"])
        args = {
            "planId": data["planId"],
            "version": data["version"],
            "action": self.action,
            "targets": self.targets,
            "quote": data["utterance"],
        }
        if self.result_position is not None:
            args["resultPosition"] = self.result_position
        return {
            "choices": [
                {
                    "message": {
                        "tool_calls": [
                            {
                                "function": {
                                    "name": TOOL,
                                    "arguments": json.dumps(args),
                                }
                            }
                        ]
                    }
                }
            ]
        }, 0


@pytest.mark.anyio
async def test_restored_scope_selection_shows_only_chosen_result_without_specialist_calls():
    from app.schemas.consultation_parent import ParentQuestion, ResultSelection
    from app.services.consultation_parent_graph import task_scope
    from tests.test_g8_consultation_parent import scoped_display_result

    req = ChatRequest(message="2번 결과 보여줘", locale="ko")
    tasks = [
        ParentTask(
            task_id=f"task-{i}",
            goal="product",
            version=1,
            status="completed",
            objective=label,
            scope_digest=task_scope(req),
            display_result=scoped_display_result(label).model_dump(mode="json", by_alias=True),
        )
        for i, label in enumerate(["토너", "크림"])
    ]
    tasks.append(
        ParentTask(task_id="task-owner", goal="owned_look", version=1, status="waiting_user")
    )
    p = ConsultationParent(
        tasks=tasks,
        result_selection=ResultSelection(version=1, task_ids=["task-0", "task-1"]),
        question=ParentQuestion(
            task_id="task-owner",
            goal="owned_look",
            version=1,
            text="립은 있나요?",
            input_key="ownership",
            need_id="lip-1",
            recipe_version="v1",
        ),
    )
    req._consultation_parent = ConsultationParent.model_validate_json(p.model_dump_json())
    service = ChatService(None, IntentModel("show", [], result_position=2))

    async def forbidden(*args, **kwargs):
        raise AssertionError("display must not call a specialist")

    service._dispatch_parent_read = forbidden
    r = await service.answer(req)
    assert r.answer.startswith("크림") and "립은 있나요?" not in r.answer and r.option_search
    assert r.consultation.selected_task_id == "task-1"
    assert r.consultation.status == "partial" and r.consultation.has_pending_input
    assert r._consultation_parent.question.need_id == "lip-1"
    assert r._consultation_parent.question.version == r._consultation_parent.version
    assert len(r.consultation.display_choices) == 2
    persisted = updated_context({}, r)
    assert persisted["consultationParent"]["resultSelection"]["selectedTaskId"] == "task-1"


def test_product_question_is_delegated_without_guessing_product():
    req = ChatRequest(message="비교 대상만 다른 크림으로 바꿔줘")
    req._consultation_parent = ConsultationParent(
        tasks=[
            ParentTask(
                task_id="comparison", goal="product", product_operation="compare", version=1
            ),
        ]
    )
    intent = ConsultationIntent(
        plan_id=req._consultation_parent.plan_id,
        version=1,
        action="clarify",
        targets=["comparison"],
        question="어떤 크림인가요?",
        clarification_scope="product_input",
    )
    result = validate_intent(intent, req)
    assert result.action == "continue"
    assert result.changes[0].task_id == "comparison"
    assert result.changes[0].quote == req.message
    assert result.changes[0].product_operation == "compare"
    assert not result.additions and not result.question
    with pytest.raises(ValueError, match="specialist clarification"):
        validate_intent(intent.model_copy(update={"targets": []}), req)


@pytest.mark.anyio
async def test_semantic_retry_uses_existing_result_and_original_tool_objective():
    catalog = Catalog()
    req = request()
    first = await ChatService(None, CombinedModel(), catalog).answer(req)
    model = IntentModel("retry", ["style"])
    follow = prepare_request(
        req.model_copy(update={"message": "아까 못 마친 쪽만 이어서 해 줘"}),
        updated_context({}, first),
        [],
    )
    result = await ChatService(None, model, catalog).answer(follow)
    assert model.intent_calls == 1
    assert catalog.product_calls == ["상품가", "상품나"]
    assert result.style_status == "ready"
    assert next(t for t in result._consultation_parent.tasks if t.goal == "product").attempts == 0
    assert (
        next(r for r in result._task_results if r.task_id == "style").inputs["objective"]
        == req.message
    )


@pytest.mark.anyio
async def test_cancel_restore_resume_does_no_reads_until_explicit_resume():
    catalog = Catalog(failures=0)
    req = request()
    first = await ChatService(None, CombinedModel(), catalog).answer(req)
    context = updated_context({}, first)
    cancel = prepare_request(
        req.model_copy(update={"message": "이 상담은 여기서 멈춰"}), context, []
    )
    stopped = await ChatService(None, IntentModel("cancel", ["product", "style"]), catalog).answer(
        cancel
    )
    assert stopped._consultation_parent.execution_state == "cancelled"
    assert len(catalog.product_calls) == 2 and catalog.style_calls == 1
    context = updated_context(context, stopped)
    paused = prepare_request(req.model_copy(update={"message": "그다음은?"}), context, [])
    waiting = await ChatService(None, IntentModel("continue", []), catalog).answer(paused)
    assert waiting.result_type == "clarification" and catalog.style_calls == 1
    resume = prepare_request(
        req.model_copy(update={"message": "중단한 룩 찾기부터 이어 줘"}), context, []
    )
    result = await ChatService(None, IntentModel("resume", ["style"]), catalog).answer(resume)
    assert result._consultation_parent.execution_state == "active"
    assert catalog.style_calls == 2 and len(catalog.product_calls) == 2
    assert result.ar_result is None and result.memory_proposal is None


@pytest.mark.parametrize("mutation", ["version", "id", "target", "quote", "completed_retry"])
def test_server_rejects_unbound_control_proposal(mutation):
    req = ChatRequest(message="못한 것 다시 해줘", locale="ko")
    req._consultation_parent = ConsultationParent(
        tasks=[ParentTask(goal="style", version=1, status="failed")]
    )
    intent = ConsultationIntent(
        plan_id=req._consultation_parent.plan_id,
        version=1,
        action="retry",
        targets=["style"],
        quote=req.message,
    )
    if mutation == "version":
        intent.version = 2
    elif mutation == "id":
        intent.plan_id = uuid4()
    elif mutation == "target":
        intent.targets = ["product"]
    elif mutation == "quote":
        intent.quote = "not in utterance"
    else:
        req._consultation_parent.tasks[0].status = "completed"
    with pytest.raises(ValueError):
        validate_intent(intent, req)


@pytest.mark.anyio
async def test_common_executor_blocks_dependent_read_but_allows_independent_work():
    parent = ConsultationParent(
        tasks=[
            ParentTask(goal="product", version=1, status="failed"),
            ParentTask(goal="style", version=1),
        ]
    )
    calls = []

    async def read():
        calls.append("style")
        return ChatResponse(answer="synthetic", products=[])

    spec = ConsultationTaskRequest(
        task_id="style", capability="style", inputs={}, depends_on=["product"]
    )
    result, retry = await execute_request(parent, parent.tasks[1], spec, read)
    assert result is None and not retry and not calls
    assert parent.tasks[1].reason == "dependency_unavailable"
    spec.requires_success = False
    result, _ = await execute_request(parent, parent.tasks[1], spec, read)
    assert calls == ["style"] and result.answer == "synthetic"


def test_old_parent_json_keeps_task_identity_and_active_state():
    old = {"version": 1, "tasks": [{"goal": "product", "version": 1, "status": "completed"}]}
    restored = ConsultationParent.model_validate(old)
    assert restored.tasks[0].task_id == "product" and restored.execution_state == "active"


@pytest.mark.anyio
@pytest.mark.parametrize("message", ["이 룩 발라줘", "이 상품 기억해", "장바구니에 넣어줘"])
async def test_execution_requests_bypass_consultation_model(message):
    from app.services.consultation_intent_service import prepare_turn

    req = ChatRequest(message=message, locale="ko")
    req._consultation_parent = ConsultationParent(tasks=[ParentTask(goal="style", version=1)])
    model = IntentModel("cancel", ["style"])
    assert await prepare_turn(req, model) is None
    assert model.intent_calls == 0
    assert req._parent_intent.action == "delegate"
    assert req._consultation_parent.execution_state == "active"


@pytest.mark.anyio
async def test_invalid_model_target_asks_instead_of_running_read():
    req = request()
    req._consultation_parent = ConsultationParent(
        tasks=[ParentTask(goal="style", version=1, status="failed")]
    )
    catalog = Catalog()
    response = await ChatService(None, IntentModel("retry", ["product"]), catalog).answer(req)
    assert response.result_type == "clarification"
    assert catalog.product_calls == [] and catalog.style_calls == 0
    assert response._consultation_parent.version == 1


@pytest.mark.anyio
async def test_combined_withdrawal_keeps_budget_update_and_real_option_input(monkeypatch):
    from app.schemas.knowledge import KnowledgeReply
    from app.services import consultation_parent_graph as parent_graph
    from app.services.knowledge_service import Consultation
    from tests.conftest import FakeLlm
    from tests.test_g8_owned_look import KoreanScopeCatalog, scope_request

    knowledge_calls = []

    async def knowledge(*args, **kwargs):
        knowledge_calls.append(args)
        return Consultation(
            KnowledgeReply(status="insufficient_evidence", limitations="synthetic"), {}
        )

    monkeypatch.setattr(parent_graph.knowledge_service, "consult_knowledge", knowledge)
    catalog = KoreanScopeCatalog()
    initial = scope_request("립 제품은 전부 없어. 2만원 이하로 찾아줘. 이유도 설명해줘.")
    first = await ChatService(None, FakeLlm(configured=False), catalog).answer(initial)
    assert len(knowledge_calls) == 1
    utterance = "왜 그런지에 대한 해설은 이제 됐고, 1만원 이하로 다시 골라줘"

    class ChangesModel(IntentModel):
        async def complete_with_tools(self, messages, tools, *, required_tool=None):
            reply, elapsed = await super().complete_with_tools(
                messages, tools, required_tool=required_tool
            )
            if required_tool == TOOL:
                f = reply["choices"][0]["message"]["tool_calls"][0]["function"]
                args = json.loads(f["arguments"])
                args["changes"] = [
                    {"taskId": "knowledge", "operation": "withdraw", "quote": "해설은 이제 됐고"},
                    {
                        "taskId": "owned_look",
                        "operation": "update",
                        "quote": "1만원 이하로 다시 골라줘",
                    },
                ]
                f["arguments"] = json.dumps(args)
            return reply, elapsed

    follow = prepare_request(
        initial.model_copy(update={"message": utterance}), updated_context({}, first), []
    )
    result = await ChatService(None, ChangesModel("continue", ["owned_look"]), catalog).answer(
        follow
    )
    assert len(knowledge_calls) == 1
    assert catalog.option_calls[-1].max_price_krw == 10000
    assert (
        next(t for t in result._consultation_parent.tasks if t.goal == "knowledge").status
        == "superseded"
    )
    assert result._owned_look_context.declarations == first._owned_look_context.declarations
    assert result._parent_trace[-1]["parentIntent"]["replan"]["updated"] == ["owned_look"]


def test_transitive_invalidation_preserves_independent_result():
    from app.schemas.consultation_parent import ConsultationChange
    from app.services.consultation_intent_service import plan_changes

    parent = ConsultationParent(
        tasks=[
            ParentTask(goal="owned_look", version=1, status="completed", result_refs=["old-look"]),
            ParentTask(
                goal="knowledge",
                version=1,
                status="completed",
                depends_on=["owned_look"],
                result_refs=["old-claim"],
            ),
            ParentTask(
                goal="product",
                version=1,
                status="completed",
                depends_on=["knowledge"],
                result_refs=["old-product"],
            ),
            ParentTask(goal="style", version=1, status="completed", result_refs=["independent"]),
        ]
    )
    revised, plan = plan_changes(
        parent, [ConsultationChange(task_id="owned_look", operation="update", quote="synthetic")]
    )
    assert plan["invalidated"] == ["knowledge", "owned_look", "product"]
    assert plan["preserved"] == ["style"]
    assert all(not t.result_refs for t in revised.tasks if t.task_id in plan["invalidated"])
    assert revised.tasks[-1].result_refs == ["independent"]
    assert parent.tasks[0].result_refs == ["old-look"]


@pytest.mark.anyio
async def test_replan_discards_changed_cache_and_keeps_independent_product():
    from app.schemas.consultation_parent import ConsultationChange
    from app.services.consultation_intent_service import plan_changes

    catalog = Catalog(failures=0)
    req = request()
    first = await ChatService(None, CombinedModel(), catalog).answer(req)
    follow = prepare_request(
        req.model_copy(update={"message": "출근 대신 저녁 분위기로 찾아줘"}),
        updated_context({}, first),
        [],
    )
    follow._consultation_parent, follow._parent_replan = plan_changes(
        follow._consultation_parent,
        [ConsultationChange(task_id="style", operation="update", quote=follow.message)],
    )
    result = await ChatService(None, CombinedModel(), catalog).answer(follow)
    assert len(catalog.product_calls) == 2
    assert catalog.style_calls == 2
    records = {r.task_id: r for r in result._task_results}
    assert records["product"].reused and records["product"].attempt == 0
    assert not records["style"].reused and records["style"].attempt == 1
    assert "저녁" in records["style"].inputs["objective"]
    assert "저녁" in result._product_style_context.objective


@pytest.mark.parametrize("kind", ["duplicate", "unknown", "unquoted", "wrong_action"])
def test_combined_changes_reject_ambiguous_or_unbound_operations(kind):
    from app.schemas.consultation_parent import ConsultationChange

    req = ChatRequest(message="설명은 빼고 상품은 다시 찾아줘", locale="ko")
    req._consultation_parent = ConsultationParent(tasks=[ParentTask(goal="knowledge", version=1)])
    change = ConsultationChange(task_id="knowledge", operation="withdraw", quote="설명은 빼고")
    intent = ConsultationIntent(
        plan_id=req._consultation_parent.plan_id, version=1, action="continue", changes=[change]
    )
    if kind == "duplicate":
        intent.changes.append(change)
    elif kind == "unknown":
        change.task_id = "missing"
    elif kind == "unquoted":
        change.quote = "invented"
    else:
        intent.action = "delegate"
    with pytest.raises(ValueError):
        validate_intent(intent, req)


@pytest.mark.anyio
@pytest.mark.parametrize("capability", ["skin", "product"])
async def test_single_typed_entry_does_not_inherit_product_screen(capability):
    from app.schemas.chat import BeautyContext, BeautyFilters
    from app.schemas.supervisor import ScreenContext

    quote = "관리 방법과 제품 추천" if capability == "skin" else "립펜슬 찾아줘"
    req = ChatRequest(message=quote, locale="ko", request_type="beauty_consultation")
    req.chat_context = BeautyContext(
        issued_at=0, filters=BeautyFilters(), selected_product_id="old", candidate_ids=["old"]
    )
    req.screen_context = ScreenContext(screenId="product-detail", productId="old")
    addition = {"capability": capability, "quote": quote}
    if capability == "product":
        addition["productOperation"] = "search"
    service = ChatService(None, EntryModel([addition]))
    calls = []

    async def dispatch(kind, child):
        calls.append((kind, child))
        return ChatResponse(answer="synthetic result", products=[])

    service._dispatch_parent_read = dispatch
    result = await service.answer(req)
    assert len(calls) == 1 and calls[0][0] == capability
    assert calls[0][1].screen_context is None
    if capability == "product":
        assert calls[0][1].chat_context is None
        assert calls[0][1]._product_contract_required
        assert calls[0][1]._product_operation == "search"
    assert result._consultation_parent.tasks[0].task_id.startswith("task-")


class EntryModel(IntentModel):
    def __init__(self, additions=(), action="continue"):
        super().__init__(action, [])
        self.additions = list(additions)

    async def complete_with_tools(self, messages, tools, *, required_tool=None):
        from app.services.consultation_intent_service import ENTRY_TOOL

        assert required_tool == ENTRY_TOOL
        data = json.loads(messages[-1]["content"])
        args = dict(
            planId=data["planId"],
            version=data["version"],
            action=self.action,
            additions=self.additions,
            targets=[],
            changes=[],
        )
        return {
            "choices": [
                {
                    "message": {
                        "tool_calls": [
                            {"function": {"name": ENTRY_TOOL, "arguments": json.dumps(args)}}
                        ]
                    }
                }
            ]
        }, 1


@pytest.mark.anyio
async def test_first_entry_splits_same_role_without_seed(monkeypatch):
    from app.services import chat_service

    calls = []

    async def knowledge(question):
        calls.append(question)
        return knowledge_result(question, len(calls))

    monkeypatch.setattr(chat_service, "consult_knowledge", knowledge)
    questions = ["세안 후 보습 순서를 설명해줘", "차단제를 덧바르는 방법도 설명해줘"]
    req = ChatRequest(message=". ".join(questions), locale="ko")
    result = await ChatService(
        None, EntryModel([{"capability": "knowledge", "quote": q} for q in questions])
    ).answer(req)
    tasks = result._consultation_parent.tasks
    assert calls == questions
    assert len(tasks) == 2 and len({t.task_id for t in tasks}) == 2
    assert all(t.status == "completed" for t in tasks)


@pytest.mark.anyio
async def test_initial_delegate_leaves_no_empty_parent():
    from app.services.consultation_intent_service import prepare_entry

    req = ChatRequest(message="토너 찾아줘", locale="ko")
    assert await prepare_entry(req, EntryModel(action="delegate")) is None
    assert req._consultation_parent is None and req._parent_intent is None


@pytest.mark.anyio
async def test_rejected_empty_plan_retries_initial_entry_after_storage():
    from app.services.consultation_intent_service import prepare_entry

    req = ChatRequest(message="보습 설명. 차단제 설명", locale="ko")
    # The first proposal used an ungrounded clause and was safely rejected.
    rejected = await prepare_entry(
        req,
        EntryModel(
            [
                {"capability": "knowledge", "quote": "사용자에게 없는 목표"},
            ]
        ),
    )
    assert rejected is not None and not rejected._consultation_parent.tasks
    restored = prepare_request(req, updated_context({}, rejected), [])
    assert (
        await prepare_entry(
            restored,
            EntryModel(
                [
                    {"capability": "knowledge", "quote": "보습 설명"},
                    {"capability": "knowledge", "quote": "차단제 설명"},
                ]
            ),
        )
        is None
    )
    assert len(restored._parent_intent.additions) == 2
    assert restored._parent_intent_audit["status"] == "validated"


@pytest.mark.anyio
async def test_restored_short_ownership_target_continues_id_parent_and_keeps_sibling():
    from app.schemas.consultation_task import TaskInputNeed
    from app.services.consultation_intent_service import prepare_turn
    from app.services.consultation_parent_graph import reconcile_questions, run_id_tasks, task_scope

    req = ChatRequest(message="없어", locale="ko")
    p = ConsultationParent(
        tasks=[
            ParentTask(
                task_id="task-own",
                goal="owned_look",
                version=1,
                status="waiting_user",
                input_needs=[
                    TaskInputNeed(
                        key="ownership",
                        question="옵션 있나요?",
                        zone="lip",
                        need_id="option-need",
                        recipe_version="v1",
                        ownership_scope="option",
                    )
                ],
            ),
            ParentTask(
                task_id="task-skin",
                goal="skin",
                version=1,
                status="partial",
                display_result={"answer": "기존 피부 설명", "products": []},
                scope_digest=task_scope(req),
            ),
        ]
    )
    reconcile_questions(p)
    response = ChatResponse(answer="확인 질문", products=[])
    response._consultation_parent = p
    restored = prepare_request(req, updated_context({}, response), [])
    assert restored.message == "없어"
    assert restored._owned_look_answer == ("option-need", "v1", "없어", "option")
    assert await prepare_turn(restored, IntentModel("continue", ["task-own"])) is None
    assert restored._parent_replan["updated"] == ["task-own"]
    calls = []

    async def dispatch(capability, child):
        calls.append(capability)
        assert child._owned_look_answer == restored._owned_look_answer
        return ChatResponse(answer="미보유 확인", products=[])

    result = await run_id_tasks(restored, dispatch)
    assert calls == ["owned_look"]
    assert len(result._consultation_parent.tasks) == 2
    skin = next(t for t in result._consultation_parent.tasks if t.goal == "skin")
    assert skin.status == "partial" and skin.display_result["answer"] == "기존 피부 설명"
    assert not result._consultation_parent.pending_questions


class AdditionModel(IntentModel):
    def __init__(self, additions=(), *, action="continue", targets=(), changes=()):
        super().__init__(action, list(targets))
        self.additions = list(additions)
        self.changes = list(changes)

    async def complete_with_tools(self, messages, tools, *, required_tool=None):
        reply, elapsed = await super().complete_with_tools(
            messages, tools, required_tool=required_tool
        )
        if required_tool == TOOL:
            f = reply["choices"][0]["message"]["tool_calls"][0]["function"]
            args = json.loads(f["arguments"])
            args.update(additions=self.additions, changes=self.changes)
            f["arguments"] = json.dumps(args)
        return reply, elapsed


@pytest.mark.parametrize("operation", [None, "search", "detail"])
def test_product_update_cannot_change_known_operation(operation):
    from app.schemas.consultation_parent import ConsultationChange

    req = ChatRequest(message="토너 찾아줘", locale="ko")
    req._consultation_parent = ConsultationParent(
        tasks=[
            ParentTask(
                task_id="comparison",
                goal="product",
                product_operation="compare",
                version=1,
                objective="두 제품 비교",
                status="waiting_user",
            )
        ]
    )
    intent = ConsultationIntent(
        plan_id=req._consultation_parent.plan_id,
        version=1,
        action="continue",
        changes=[
            ConsultationChange(
                task_id="comparison",
                operation="update",
                quote=req.message,
                product_operation=operation,
            )
        ],
    )
    with pytest.raises(ValueError, match="different product operation"):
        validate_intent(intent, req)
    intent.changes[0].product_operation = "compare"
    assert validate_intent(intent, req) is intent


@pytest.mark.anyio
async def test_search_additions_after_comparison_have_fresh_inputs_and_keep_results():
    from app.schemas.chat import ScreenContext
    from app.schemas.consultation_task import ProductAssessment, ProductRequirement

    catalog = Catalog(failures=0)
    initial = request()
    first = await ChatService(None, CombinedModel(), catalog).answer(initial)
    assert first._consultation_parent.tasks[0].product_operation == "compare"
    saved = updated_context({}, first)
    # Exercise old persisted producer metadata too, without inferring free-text objectives.
    for task in saved["consultationParent"]["tasks"]:
        task.pop("productOperation", None)
        task["displayResult"] = None
    follow = prepare_request(
        initial.model_copy(update={"message": "토너 찾아줘. 크림도 찾아줘"}), saved, []
    )
    follow.screen_context = ScreenContext(productId="상품가")
    before = list(catalog.product_calls)
    captured = []

    class Service(ChatService):
        async def _dispatch_parent_read(self, capability, child):
            captured.append(child)
            assert capability == "product"
            assert child.screen_context is None and child.chat_context is None
            assert child._product_style_context is None
            kind = "toner" if "토너" in child.message else "cream"
            result = ChatResponse(answer="검색 결과", products=[])
            result._product_assessment = ProductAssessment(
                requirement=ProductRequirement(kind=kind), status="completed", outcome="no_match"
            )
            return result

    model = AdditionModel(
        [
            {"capability": "product", "quote": q, "productOperation": "search"}
            for q in ["토너 찾아줘.", "크림도 찾아줘"]
        ]
    )
    response = await Service(None, model, catalog).answer(follow)
    assert [c.message for c in captured] == ["토너 찾아줘.", "크림도 찾아줘"]
    assert catalog.product_calls == before
    parent = response._consultation_parent
    assert len(parent.tasks) == 4
    assert [t.product_operation for t in parent.tasks if t.task_id.startswith("task-")] == [
        "search",
        "search",
    ]
    assert next(t for t in parent.tasks if t.task_id == "product").attempts == 0
    assert response.style_candidates == first.style_candidates
    assert {p.id for p in first.products} <= {p.id for p in response.products}


@pytest.mark.anyio
async def test_explicit_preserve_is_no_read_and_keeps_result():
    parent = ConsultationParent(
        tasks=[
            ParentTask(
                task_id="task-toner",
                goal="product",
                version=1,
                status="completed",
                result_refs=["toner"],
                display_result={"answer": "기존 토너", "products": []},
            )
        ]
    )
    req = ChatRequest(message="토너는 그대로 둬", locale="ko")
    req._consultation_parent = parent
    model = AdditionModel(
        changes=[{"taskId": "task-toner", "operation": "preserve", "quote": req.message}]
    )
    result = await ChatService(None, model).answer(req)
    task = result._consultation_parent.tasks[0]
    assert task.status == "completed" and task.result_refs == ["toner"]
    assert task.display_result == parent.tasks[0].display_result
    assert "유지" in result.answer and "제외" not in result.answer


def test_preserve_conflicting_change_or_changed_dependency_is_rejected():
    from app.schemas.consultation_parent import ConsultationChange
    from app.services.consultation_intent_service import plan_changes

    parent = ConsultationParent(
        tasks=[
            ParentTask(task_id="a", goal="product", version=1),
            ParentTask(task_id="b", goal="knowledge", version=1, depends_on=["a"]),
        ]
    )
    for changes in [
        [
            ConsultationChange(task_id="a", operation="preserve", quote="유지"),
            ConsultationChange(task_id="a", operation="withdraw", quote="빼"),
        ],
        [
            ConsultationChange(task_id="a", operation="update", quote="변경"),
            ConsultationChange(task_id="b", operation="preserve", quote="유지"),
        ],
    ]:
        with pytest.raises(ValueError):
            plan_changes(parent, changes)


def knowledge_result(question, number):
    from app.schemas.knowledge import KnowledgeReply
    from app.services.knowledge_service import Consultation

    return Consultation(
        KnowledgeReply.model_validate(
            {
                "status": "answered",
                "claims": [{"claim": question + "의 합성 설명", "citations": ["E1"]}],
                "evidence": [
                    {
                        "id": "E1",
                        "documentId": number,
                        "chunkId": f"chunk-{number}",
                        "title": "합성 문서",
                        "sourceFileId": number,
                        "sourceVersion": "fixture-v1",
                        "blockOrder": 1,
                        "startUtf16": 0,
                        "endUtf16": 2,
                        "sourceLocator": {},
                        "quote": "합성",
                        "relevance": "essential",
                    }
                ],
                "findings": [{"index": 7, "label": "SUPPORTED", "reason": "fixture"}],
            }
        ),
        {},
    )


@pytest.mark.anyio
async def test_two_knowledge_goals_keep_ids_sources_and_retry_only_failed_task(monkeypatch):
    from app.core.errors import UpstreamError
    from app.services import chat_service

    monkeypatch.setattr(get_settings(), "g8_read_retries", 0)
    calls, failing = [], True
    q1, q2 = "세안 후 보습 순서를 설명해줘", "자외선 차단제를 덧바르는 방법도 설명해줘"

    async def knowledge(question):
        calls.append(question)
        if question == q2 and failing:
            raise UpstreamError("synthetic failure")
        return knowledge_result(question, 1 if question == q1 else 2)

    monkeypatch.setattr(chat_service, "consult_knowledge", knowledge)
    req = ChatRequest(message=q1 + ". " + q2, locale="ko")
    req._consultation_parent = ConsultationParent(
        tasks=[
            ParentTask(
                goal="product",
                version=1,
                status="completed",
                objective="기존 상품",
                result_refs=["original-product"],
            )
        ]
    )
    additions = [{"capability": "knowledge", "quote": q} for q in [q1, q2]]
    first = await ChatService(None, AdditionModel(additions)).answer(req)
    tasks = [t for t in first._consultation_parent.tasks if t.goal == "knowledge"]
    assert len(tasks) == 2 and tasks[0].task_id != tasks[1].task_id
    assert [t.status for t in tasks] == ["completed", "failed"]
    assert first._consultation_parent.tasks[0].result_refs == ["original-product"]
    assert calls == [q1, q2]
    assert tasks[0].display_result["knowledge"]["findings"][0]["index"] == 7
    failing = False
    follow = prepare_request(
        req.model_copy(update={"message": "덧바르는 방법만 다시 설명해줘"}),
        updated_context({}, first),
        [],
    )
    second = await ChatService(
        None, AdditionModel(action="retry", targets=[tasks[1].task_id])
    ).answer(follow)
    assert calls == [q1, q2, q2]
    assert [e.document_id for e in second.knowledge.evidence] == [2]
    assert [e.id for e in second.knowledge.evidence] == ["E1"]
    assert [c.citations for c in second.knowledge.claims] == [["E1"]]
    saved_first = next(
        t for t in second._consultation_parent.tasks if t.task_id == tasks[0].task_id
    )
    assert saved_first.display_result == tasks[0].display_result
    show_req = prepare_request(
        req.model_copy(update={"message": "보습 설명 다시 보여줘"}), updated_context({}, second), []
    )
    shown = await ChatService(
        None, AdditionModel(action="show", targets=[tasks[0].task_id])
    ).answer(show_req)
    assert [e.document_id for e in shown.knowledge.evidence] == [1]
    assert shown.knowledge.claims[0].citations == ["E1"]
    assert calls == [q1, q2, q2]
    records = {r.task_id: r for r in second._task_results}
    assert records[tasks[0].task_id].reused and records[tasks[0].task_id].attempt == 0
    assert records[tasks[1].task_id].attempt == 1
    assert [t.task_id for t in second._consultation_parent.tasks if t.goal == "knowledge"] == [
        t.task_id for t in tasks
    ]


@pytest.mark.anyio
async def test_duplicate_capability_updates_and_withdraws_by_id(monkeypatch):
    from app.services import chat_service

    calls = []

    async def knowledge(question):
        calls.append(question)
        return knowledge_result(question, len(calls))

    monkeypatch.setattr(chat_service, "consult_knowledge", knowledge)
    q1, q2 = "보습 순서 설명", "차단제 사용 순서 설명"
    req = ChatRequest(message=q1 + ", " + q2, locale="ko")
    req._consultation_parent = ConsultationParent(tasks=[ParentTask(goal="product", version=1)])
    first = await ChatService(
        None, AdditionModel([{"capability": "knowledge", "quote": q} for q in [q1, q2]])
    ).answer(req)
    tasks = [t for t in first._consultation_parent.tasks if t.goal == "knowledge"]
    message = "보습 설명은 빼고 차단제는 덧바르기도 설명해줘"
    follow = prepare_request(
        req.model_copy(update={"message": message}), updated_context({}, first), []
    )
    second = await ChatService(
        None,
        AdditionModel(
            changes=[
                {"taskId": tasks[0].task_id, "operation": "withdraw", "quote": "보습 설명은 빼고"},
                {
                    "taskId": tasks[1].task_id,
                    "operation": "update",
                    "quote": "차단제는 덧바르기도 설명해줘",
                },
            ]
        ),
    ).answer(follow)
    assert len(calls) == 3 and "덧바르기" in calls[-1] and "보습" not in calls[-1]
    assert "보습 순서 설명" not in second.answer
    by_id = {t.task_id: t for t in second._consultation_parent.tasks}
    assert by_id[tasks[0].task_id].status == "superseded"
    assert by_id[tasks[0].task_id].display_result is None
    assert by_id[tasks[1].task_id].status == "completed"


def test_repeated_capability_acceptance_never_overwrites_sibling():
    from app.services.consultation_parent_graph import accept_task

    parent = ConsultationParent(
        tasks=[
            ParentTask(task_id="k1", goal="knowledge", version=1),
            ParentTask(task_id="k2", goal="knowledge", version=1),
        ]
    )
    accept_task(
        parent,
        ParentTask(task_id="k2", goal="knowledge", version=1, status="completed"),
        parent.plan_id,
    )
    assert [(t.task_id, t.status) for t in parent.tasks] == [("k1", "pending"), ("k2", "completed")]


@pytest.mark.parametrize("kind", ["invented", "duplicate", "capacity", "wrong_action"])
def test_new_goal_validation_does_not_invent_or_truncate_work(kind):
    from app.schemas.consultation_parent import ConsultationAddition

    req = ChatRequest(message="보습 방법 설명", locale="ko")
    req._consultation_parent = ConsultationParent(tasks=[ParentTask(goal="product", version=1)])
    addition = ConsultationAddition(capability="knowledge", quote=req.message)
    intent = ConsultationIntent(
        plan_id=req._consultation_parent.plan_id, version=1, action="continue", additions=[addition]
    )
    if kind == "invented":
        addition.shared_quotes = ["invented budget"]
    elif kind == "duplicate":
        intent.additions.append(addition)
    elif kind == "capacity":
        req._consultation_parent.tasks = [
            ParentTask(task_id=f"k{i}", goal="knowledge", version=1) for i in range(5)
        ]
    else:
        intent.action = "delegate"
    with pytest.raises(ValueError):
        validate_intent(intent, req)


@pytest.mark.anyio
async def test_two_product_tasks_send_distinct_actual_catalog_queries(monkeypatch):
    from tests.test_beauty_consultation import Catalog as ProductCatalog

    monkeypatch.setattr(get_settings(), "g1_supervisor_enabled", False)

    class Products(ProductCatalog):
        def __init__(self):
            super().__init__()
            self.queries = []

        async def search_products(self, **kwargs):
            self.queries.append(kwargs)
            return await super().search_products(**kwargs)

    class ProductModel(AdditionModel):
        async def complete(self, messages):
            category = ["lip", "base"][len(catalog.queries)]
            return json.dumps(
                {
                    "intent": "search",
                    "category": category,
                    "scope": "catalog",
                    "productRequirement": {"operation": "keep"},
                }
            )

    catalog = Products()
    req = ChatRequest(message="립 제품 찾아줘. 베이스 제품도 찾아줘", locale="ko")
    req._consultation_parent = ConsultationParent(
        tasks=[ParentTask(goal="knowledge", version=1, status="completed")]
    )
    model = ProductModel(
        [{"capability": "product", "quote": q} for q in ["립 제품 찾아줘", "베이스 제품도 찾아줘"]]
    )
    response = await ChatService(None, model, catalog).answer(req)
    tasks = [t for t in response._consultation_parent.tasks if t.goal == "product"]
    assert len(tasks) == 2 and tasks[0].task_id != tasks[1].task_id
    assert [q["category"] for q in catalog.queries] == ["lip", "base"]
    assert [r.inputs["objective"] for r in response._task_results if r.capability == "product"] == [
        "립 제품 찾아줘",
        "베이스 제품도 찾아줘",
    ]


@pytest.mark.anyio
async def test_id_result_display_never_reuses_changed_memory_scope(monkeypatch):
    from app.services import chat_service

    calls = []

    async def knowledge(question):
        calls.append(question)
        return knowledge_result(question, 1)

    monkeypatch.setattr(chat_service, "consult_knowledge", knowledge)
    req = ChatRequest(message="보습 순서 설명", locale="ko")
    req._memory_epoch = 1
    req._consultation_parent = ConsultationParent(
        tasks=[ParentTask(goal="product", version=1, status="completed")]
    )
    first = await ChatService(
        None, AdditionModel([{"capability": "knowledge", "quote": req.message}])
    ).answer(req)
    tid = next(t.task_id for t in first._consultation_parent.tasks if t.goal == "knowledge")
    follow = prepare_request(
        req.model_copy(update={"message": "그 설명 다시 보여줘"}), updated_context({}, first), []
    )
    shown = await ChatService(None, AdditionModel(action="show", targets=[tid])).answer(follow)
    assert len(calls) == 1 and shown.knowledge.claims
    follow._memory_epoch = 2
    blocked = await ChatService(None, AdditionModel(action="show", targets=[tid])).answer(follow)
    assert blocked.result_type == "clarification" and blocked.knowledge is None and len(calls) == 1


@pytest.mark.anyio
async def test_id_scheduler_orders_dependency_and_passes_real_recipe_context(monkeypatch):
    from app.schemas.consultation_parent import ConsultationAddition, ConsultationChange
    from app.services import chat_service
    from app.services.consultation_parent_graph import run_id_tasks
    from tests.test_g8_owned_look import Catalog as LookCatalog

    observed = []

    async def knowledge(question, **kwargs):
        observed.append((question, kwargs))
        return knowledge_result(question, len(observed))

    monkeypatch.setattr(chat_service, "consult_knowledge", knowledge)
    req = ChatRequest(message="룩 다시 확인. 별도 설명", locale="ko")
    req._consultation_parent = ConsultationParent(
        tasks=[
            ParentTask(
                goal="knowledge",
                version=1,
                objective="이 순서 설명",
                depends_on=["owned_look"],
                status="superseded",
            ),
            ParentTask(goal="owned_look", version=1, objective="이 룩", status="superseded"),
        ]
    )
    req._parent_intent = ConsultationIntent(
        plan_id=req._consultation_parent.plan_id,
        version=1,
        action="continue",
        additions=[ConsultationAddition(capability="knowledge", quote="별도 설명")],
        changes=[
            ConsultationChange(task_id="owned_look", operation="update", quote="룩 다시 확인")
        ],
    )
    req._parent_replan = {
        "updated": ["owned_look"],
        "invalidated": ["owned_look", "knowledge"],
        "withdrawn": [],
    }
    service = ChatService(None, CombinedModel())
    from app.services.style_recipe_service import execute_style
    from tests.test_g8_owned_look import request as look_request

    style_response, _ = await execute_style(
        look_request([], "이 룩의 전체 순서를 알려줘"), LookCatalog()
    )
    recipe = style_response.style_recipe

    async def dispatch(capability, child):
        if capability == "owned_look":
            return ChatResponse(
                answer="합성 보유 확인 질문",
                products=[],
                result_type="clarification",
                style_recipe=recipe,
            )
        return await service._dispatch_parent_read(capability, child)

    response = await run_id_tasks(req, dispatch)
    bound = next(kwargs for question, kwargs in observed if question == "이 순서 설명")
    assert (
        json.loads(bound["prior_user_context"])["styleRecipe"]["evidenceId"] == recipe.evidence_id
    )
    records = {r.task_id: r for r in response._task_results}
    assert (
        records["knowledge"].inputs["referenceContext"]["styleRecipe"]["evidenceId"]
        == recipe.evidence_id
    )
    assert records["knowledge"].depends_on == ["owned_look"]
    assert (
        next(t for t in response._consultation_parent.tasks if t.task_id == "knowledge").status
        == "completed"
    )


@pytest.mark.anyio
async def test_first_entry_preserves_ready_work_and_question_owner():
    class Service(ChatService):
        async def _dispatch_parent_read(self, capability, req):
            if req.message == "그것도 설명해줘":
                return ChatResponse(
                    answer="어떤 대상을 설명할까요?", products=[], result_type="clarification"
                )
            return ChatResponse(answer="확인한 설명", products=[])

    req = ChatRequest(message="보습 설명. 그것도 설명해줘", locale="ko")
    result = await Service(
        None,
        EntryModel(
            [
                {"capability": "knowledge", "quote": "보습 설명"},
                {"capability": "knowledge", "quote": "그것도 설명해줘"},
            ]
        ),
    ).answer(req)
    tasks = result._consultation_parent.tasks
    assert [t.status for t in tasks] == ["completed", "waiting_user"]
    assert result._consultation_parent.question.task_id == tasks[1].task_id
    assert result._task_results[1].missing_inputs[0].question == "어떤 대상을 설명할까요?"
    assert "확인한 설명" in result.answer and "어떤 대상을" in result.answer
    assert result.result_type == "clarification"


@pytest.mark.parametrize("explicit_owner", [True, False])
def test_same_role_change_preserves_other_question(explicit_owner):
    from app.schemas.consultation_parent import ConsultationChange, ParentQuestion
    from app.services.consultation_intent_service import plan_changes

    parent = ConsultationParent(
        tasks=[
            ParentTask(task_id="task-a", goal="knowledge", version=1),
            ParentTask(task_id="task-b", goal="knowledge", version=1, status="waiting_user"),
        ],
        question=ParentQuestion(
            task_id="task-b" if explicit_owner else None,
            goal="knowledge",
            version=1,
            text="어떤 순서인가요?",
            input_key="situation",
        ),
    )
    revised, _ = plan_changes(
        parent, [ConsultationChange(task_id="task-a", operation="update", quote="다시 설명")]
    )
    assert revised.question == parent.question
    revised, _ = plan_changes(
        parent, [ConsultationChange(task_id="task-b", operation="update", quote="이 순서")]
    )
    assert parent.question.task_id == "task-b"
    assert revised.question is None


@pytest.mark.anyio
async def test_partial_sibling_and_question_survive_new_goal_then_answer():
    from app.schemas.consultation_parent import ParentQuestion
    from app.services.consultation_parent_graph import task_scope

    req = ChatRequest(message="세안 설명", locale="ko")
    parent = ConsultationParent(
        tasks=[
            ParentTask(
                task_id="task-a",
                goal="knowledge",
                version=1,
                status="partial",
                display_result={"answer": "근거 일부만 확인", "products": []},
                scope_digest=task_scope(req),
            ),
            ParentTask(
                task_id="task-b",
                goal="knowledge",
                version=1,
                status="waiting_user",
                display_result={
                    "answer": "어떤 순서인가요?",
                    "products": [],
                    "resultType": "clarification",
                },
                scope_digest=task_scope(req),
            ),
        ],
        question=ParentQuestion(
            task_id="task-b",
            goal="knowledge",
            version=1,
            text="어떤 순서인가요?",
            input_key="situation",
        ),
    )
    req._consultation_parent = parent
    calls = []

    class Service(ChatService):
        async def _dispatch_parent_read(self, capability, child):
            calls.append(child.message)
            return ChatResponse(answer="새 설명", products=[])

    first = await Service(
        None, AdditionModel([{"capability": "knowledge", "quote": req.message}])
    ).answer(req)
    assert calls == ["세안 설명"]
    assert first._consultation_parent.question.task_id == "task-b"
    assert first._consultation_parent.question.input_key == "situation"
    assert "확인하지 못한 부분도 남아" in first.answer
    assert any(
        t.display_result and t.display_result["answer"] == "근거 일부만 확인"
        for t in first._consultation_parent.tasks
    )
    follow = prepare_request(
        req.model_copy(update={"message": "보습 순서야"}), updated_context({}, first), []
    )
    second = await Service(
        None,
        AdditionModel(
            changes=[
                {
                    "taskId": "task-b",
                    "operation": "update",
                    "quote": follow.message,
                }
            ]
        ),
    ).answer(follow)
    assert len(calls) == 2 and "보습 순서야" in calls[-1]
    assert second._consultation_parent.question is None
    assert "확인하지 못한 부분도 남아" in second.answer
    assert any(
        t.display_result and t.display_result["answer"] == "근거 일부만 확인"
        for t in second._consultation_parent.tasks
    )
    assert len(second._consultation_parent.tasks) == 3


@pytest.mark.anyio
async def test_show_preserves_all_pending_question_identities_and_versions():
    from app.schemas.consultation_task import TaskInputNeed
    from app.services.consultation_parent_graph import task_scope

    req = ChatRequest(message="기존 상품 결과만 보여줘", locale="ko")
    p = ConsultationParent(
        tasks=[
            ParentTask(
                task_id="task-display",
                goal="product",
                status="completed",
                version=1,
                objective="이전 상품",
                scope_digest=task_scope(req),
                display_result={"answer": "저장 결과", "products": []},
            ),
            ParentTask(
                task_id="task-skin",
                goal="skin",
                status="waiting_user",
                version=1,
                input_needs=[TaskInputNeed(key="situation", question="어떤 상황?")],
            ),
            ParentTask(
                task_id="task-owned",
                goal="owned_look",
                status="waiting_user",
                version=1,
                input_needs=[
                    TaskInputNeed(
                        key="ownership",
                        question="이 립 있나요?",
                        zone="lip",
                        need_id="lip-option",
                        recipe_version="recipe-a",
                        ownership_scope="option",
                    )
                ],
            ),
        ]
    )
    from app.services.consultation_parent_graph import reconcile_questions

    reconcile_questions(p)
    p = ConsultationParent.model_validate_json(p.model_dump_json())
    req._consultation_parent = p
    r = await ChatService(None, IntentModel("show", ["task-display"])).answer(req)
    assert {q.task_id for q in r._consultation_parent.pending_questions} == {
        "task-skin",
        "task-owned",
    }
    assert all(
        q.version == r._consultation_parent.version
        for q in r._consultation_parent.pending_questions
    )
    assert (
        next(
            q for q in r._consultation_parent.pending_questions if q.input_key == "ownership"
        ).need_id
        == "lip-option"
    )
    assert r.consultation.has_pending_input and r.consultation.status == "partial"


@pytest.mark.parametrize("order", [["task-b", "task-a"], ["task-a", "task-b"]])
def test_display_position_uses_saved_order_not_task_or_question_order(order):
    from app.schemas.consultation_parent import ResultSelection

    req = question_scope_request()
    req.message = "2번 결과 보여줘"
    p = req._consultation_parent
    p.tasks.extend(ParentTask(task_id=tid, goal="product", version=1) for tid in order)
    p.result_selection = ResultSelection(version=1, task_ids=order)
    intent = ConsultationIntent(
        plan_id=p.plan_id, version=1, action="show", result_position=2, quote=req.message
    )
    result = validate_intent(intent, req)
    assert result.targets == [order[1]]
    assert len(p.pending_questions) == 2


@pytest.mark.parametrize(
    "invalid", ["out_of_range", "stale", "conflict", "ownership", "wrong_number"]
)
def test_display_position_rejects_invalid_or_non_display_proposals(invalid):
    from app.schemas.consultation_parent import ResultSelection

    req = question_scope_request()
    req.message = "2번 결과 보여줘"
    p = req._consultation_parent
    p.tasks.extend(
        ParentTask(task_id=tid, goal="product", version=1) for tid in ["task-a", "task-b"]
    )
    p.result_selection = ResultSelection(version=1, task_ids=["task-b", "task-a"])
    intent = ConsultationIntent(
        plan_id=p.plan_id, version=1, action="show", result_position=2, quote=req.message
    )
    if invalid == "out_of_range":
        intent.result_position = 3
    elif invalid == "stale":
        p.result_selection.version = 2
    elif invalid == "conflict":
        intent.targets = ["task-b"]
    elif invalid == "wrong_number":
        req.message = intent.quote = "1번 결과 보여줘"
    else:
        intent.action = "continue"
    with pytest.raises(ValueError, match="result"):
        validate_intent(intent, req)


@pytest.mark.parametrize(
    "targets,valid",
    [
        (["task-look"], True),
        (["task-skin"], False),
        (["task-look", "task-skin"], False),
        (["task-look", "task-look"], False),
    ],
)
def test_redundant_question_owner_targets_normalize_only_exact_owner_set(targets, valid):
    req = question_scope_request()
    proposal = question_proposal(req)
    proposal.targets = targets
    if not valid:
        with pytest.raises(ValueError, match="Question changes"):
            validate_intent(proposal, req)
    else:
        intent = validate_intent(proposal, req)
        assert intent.targets == []
        updates = [c for c in intent.changes if c.operation == "update"]
        assert len(updates) == 1 and updates[0].task_id == "task-look"
        assert len(req._consultation_parent.pending_questions) == 2


@pytest.mark.parametrize(
    "operation,quote,product_operation,valid",
    [
        ("update", "삐아는 없어", None, True),
        ("preserve", "삐아는 없어", None, False),
        ("withdraw", "삐아는 없어", None, False),
        ("update", "피부 설명은 유지해줘", None, False),
        ("update", "삐아는 없어", "search", False),
    ],
)
def test_question_answer_normalizes_only_identical_owner_update(
    operation, quote, product_operation, valid
):
    from app.schemas.consultation_parent import ConsultationChange

    req = question_scope_request()
    proposal = question_proposal(req)
    proposal.changes.append(
        ConsultationChange(
            task_id="task-look",
            operation=operation,
            quote=quote,
            product_operation=product_operation,
        )
    )
    if valid:
        result = validate_intent(proposal, req)
        assert [(c.task_id, c.quote) for c in result.changes if c.operation == "update"] == [
            ("task-look", "삐아는 없어")
        ]
    else:
        with pytest.raises(ValueError, match="Conflicting task and question"):
            validate_intent(proposal, req)


@pytest.mark.anyio
@pytest.mark.parametrize("repair_succeeds", [True, False])
async def test_unassigned_read_clause_replans_once_preserving_original_siblings(
    monkeypatch, repair_succeeds
):
    from app.services.consultation_intent_service import prepare_turn

    monkeypatch.setattr(get_settings(), "g8_enabled", True)
    req = ChatRequest(message="립펜슬 찾아줘. 피부 상담은 유지해줘.")
    req._consultation_parent = ConsultationParent(
        tasks=[
            ParentTask(
                task_id="task-skin",
                goal="skin",
                version=1,
                status="completed",
                objective="피부 상담",
            )
        ]
    )

    class OmittedModel:
        configured = True

        def __init__(self):
            self.calls = []

        async def complete_with_tools(self, messages, tools, *, required_tool=None):
            data = json.loads(messages[-1]["content"])
            self.calls.append(data["utterance"])
            args = {
                "planId": data["planId"],
                "version": data["version"],
                "action": "continue",
                "quote": "립펜슬 찾아줘.",
            }
            if len(self.calls) == 1:
                args["changes"] = [
                    {
                        "taskId": "task-skin",
                        "operation": "preserve",
                        "quote": "피부 상담은 유지해줘.",
                    }
                ]
            elif repair_succeeds:
                args["additions"] = [
                    {
                        "capability": "product",
                        "quote": data["utterance"],
                        "productOperation": "search",
                    }
                ]
            return {
                "choices": [
                    {
                        "message": {
                            "tool_calls": [
                                {"function": {"name": required_tool, "arguments": json.dumps(args)}}
                            ]
                        }
                    }
                ]
            }, 1

    model = OmittedModel()
    response = await prepare_turn(req, model)
    assert model.calls == [req.message, "립펜슬 찾아줘."]
    assert req._parent_intent_audit["invocations"] == 2
    assert req._consultation_parent.tasks[0].status == "completed"
    if repair_succeeds:
        assert response is None
        assert req._parent_intent.additions[0].capability == "product"
        assert req._parent_intent.changes[0].operation == "preserve"
    else:
        assert response.result_type == "clarification"
        assert req._parent_intent_audit["status"] == "omitted_read_unresolved"


@pytest.mark.anyio
@pytest.mark.parametrize("g5_enabled", [False, True])
async def test_g5_flag_applies_to_initial_and_restored_knowledge_without_losing_products(
    monkeypatch, g5_enabled
):
    import httpx

    from app.services import knowledge_service
    from tests.conftest import FakeGraph
    from tests.test_beauty_consultation import Catalog as ProductCatalog

    settings = get_settings()
    monkeypatch.setattr(settings, "g1_supervisor_enabled", False)
    monkeypatch.setattr(settings, "g5_enabled", g5_enabled)
    monkeypatch.setattr(settings, "g5_openai_api_key", "synthetic-key")
    monkeypatch.setattr(settings, "g5_internal_token", "synthetic-token")
    calls = []

    async def consult(self, question, *args, **kwargs):
        calls.append(question)
        return knowledge_result(question, 1)

    async def no_http(*args, **kwargs):
        pytest.fail("External HTTP forbidden")

    monkeypatch.setattr(knowledge_service.KnowledgeService, "consult", consult)
    monkeypatch.setattr(httpx.AsyncClient, "send", no_http)
    explanation, shopping = "세안 후 보습 순서를 설명해줘", "립 제품 찾아줘"

    class Model(EntryModel):
        async def complete(self, messages):
            return json.dumps({
                "intent": "search", "category": "lip", "productRequirement": {"operation": "keep"},
            })

    catalog = ProductCatalog()
    first = await ChatService(FakeGraph(), Model([
        {"capability": "knowledge", "quote": explanation},
        {"capability": "product", "productOperation": "search", "quote": shopping},
    ]), catalog).answer(ChatRequest(message=explanation + ". " + shopping, locale="ko"))
    tasks = {t.goal: t for t in first._consultation_parent.tasks}
    assert first.products and tasks["product"].status == "completed"
    assert tasks["knowledge"].status == ("completed" if g5_enabled else "failed")
    if not g5_enabled:
        assert tasks["knowledge"].reason == "g5_disabled"
        assert tasks["knowledge"].attempts == 1
        assert first.consultation.status == "partial"
    raw = json.loads(json.dumps(updated_context({}, first)))
    req = prepare_request(ChatRequest(message=explanation, locale="ko"), raw, [])
    second = await ChatService(FakeGraph(), AdditionModel(changes=[{
        "taskId": tasks["knowledge"].task_id, "operation": "update", "quote": explanation,
    }]), catalog).answer(req)
    assert {p.id for p in second.products} == {p.id for p in first.products}
    assert len(calls) == (2 if g5_enabled else 0)
    assert next(t for t in second._consultation_parent.tasks if t.goal == "knowledge").status == (
        "completed" if g5_enabled else "failed"
    )


@pytest.mark.anyio
async def test_g5_off_can_display_saved_answer_without_a_new_knowledge_read(monkeypatch):
    from app.services.consultation_parent_graph import task_scope

    monkeypatch.setattr(get_settings(), "g5_enabled", False)
    req = ChatRequest(message="이전 설명 보여줘", locale="ko")
    stored = knowledge_result("보습", 1)
    req._consultation_parent = ConsultationParent(tasks=[ParentTask(
        task_id="task-saved", goal="knowledge", version=1, status="completed",
        scope_digest=task_scope(req),
        display_result=ChatResponse(
            answer=stored.answer, products=[], knowledge=stored.reply
        ).model_dump(mode="json", by_alias=True),
    )])

    async def forbidden(*args, **kwargs):
        pytest.fail("Saved display must not execute knowledge")

    monkeypatch.setattr(ChatService, "_dispatch_parent_read", forbidden)
    saved = ChatResponse(answer="stored", products=[])
    saved._consultation_parent = req._consultation_parent
    restored = prepare_request(
        ChatRequest(message=req.message, locale="ko"),
        updated_context({}, saved),
        [],
    )
    reply = await ChatService(None, IntentModel("show", ["task-saved"])).answer(restored)
    assert reply.knowledge.claims and "보습" in reply.answer


@pytest.mark.anyio
@pytest.mark.parametrize("state", ["active", "cancelled"])
async def test_g8_off_saved_parent_does_not_intercept_or_disappear(monkeypatch, state):
    from tests.conftest import FakeGraph, FakeLlm

    monkeypatch.setattr(get_settings(), "g8_enabled", False)
    monkeypatch.setattr(get_settings(), "g1_supervisor_enabled", False)
    original = ConsultationParent(execution_state=state, tasks=[ParentTask(
        task_id="task-old", goal="knowledge", version=1,
        status="completed" if state == "active" else "cancelled", objective="과거 목표",
        display_result={"answer": "저장한 설명", "products": []},
    )])
    stored = ChatResponse(answer="저장한 설명", products=[])
    stored._consultation_parent = original
    raw = updated_context({}, stored)
    req = prepare_request(ChatRequest(message="안녕", locale="ko"), raw, [])
    before = req._consultation_parent.model_dump(mode="json", by_alias=True)
    reply = await ChatService(FakeGraph(), FakeLlm()).answer(req)
    assert reply.answer == "Try Rom&nd Juicy Tint."
    assert reply.consultation is None
    assert reply._consultation_parent.model_dump(mode="json", by_alias=True) == before
    saved = updated_context(raw, reply)
    assert saved["consultationParent"] == raw["consultationParent"]
    assert req._parent_intent is None
    monkeypatch.setattr(get_settings(), "g8_enabled", True)
    restored = prepare_request(ChatRequest(message="안녕", locale="ko"), saved, [])

    async def forbidden(*args, **kwargs):
        pytest.fail("Re-enabling G8 must not automatically execute old work")

    monkeypatch.setattr(ChatService, "_dispatch_parent_read", forbidden)
    resumed = await ChatService(FakeGraph(), IntentModel("delegate", [])).answer(restored)
    assert resumed.result_type != "clarification"


@pytest.mark.parametrize("enabled", [False, True])
def test_restored_ownership_answer_is_interpreted_only_when_g8_enabled(monkeypatch, enabled):
    from app.schemas.consultation_parent import ParentQuestion
    from app.services.consultation_parent_graph import restore_followup

    monkeypatch.setattr(get_settings(), "g8_enabled", enabled)
    old = ConsultationParent(
        tasks=[ParentTask(goal="owned_look", version=1, status="waiting_user")],
        question=ParentQuestion(
            task_id="owned_look", goal="owned_look", version=1, text="립 있나요?",
            input_key="ownership", zone="lip", need_id="lip-option",
            recipe_version="recipe-v1", ownership_scope="option",
        ),
    )
    before = old.model_dump_json()
    restored = restore_followup(ChatRequest(message="있어", locale="ko"), old)
    assert restored._consultation_parent.model_dump_json() == before
    if enabled:
        assert restored._owned_look_answer == ("lip-option", "recipe-v1", "있어", "option")
        assert "추가 추천" in restored.message
    else:
        assert restored.message == "있어" and restored._owned_look_answer is None

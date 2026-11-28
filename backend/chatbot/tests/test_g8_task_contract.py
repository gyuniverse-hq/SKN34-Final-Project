"""Common parent boundary with real specialist code; synthetic models and HTTP data."""

from uuid import uuid4

import pytest

from app.core.config import get_settings
from app.schemas.chat import ChatRequest
from app.schemas.compound_consultation import InputBinding, TaskRequest, TaskResult
from app.services import consultation_parent_graph as parent
from app.services.chat_service import ChatService
from app.services.consultation_task_adapter import adapt_specialist, fingerprint, validate_results
from tests.conftest import FakeLlm
from tests.test_g8_compound_consultation import (
    GOAL,
    QUESTION,
    Planner,
    install_knowledge,
)
from tests.test_g8_compound_consultation import connections as connections
from tests.test_g8_owned_look import Catalog, owned, request
from tests.test_g8_partial_success import Catalog as FailureCatalog
from tests.test_g8_partial_success import CombinedModel
from tests.test_g8_partial_success import request as comparison_request


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.fixture(autouse=True)
def enabled(monkeypatch):
    monkeypatch.setattr(get_settings(), "g8_enabled", True)


@pytest.mark.anyio
async def test_n01_common_result_tracks_changed_real_tool_input(monkeypatch, connections):
    api, skincare, catalog = connections
    install_knowledge(monkeypatch)
    service = ChatService(None, Planner(), catalog, skincare=skincare)
    first = await service.answer(ChatRequest(message=QUESTION, locale="ko"))
    records = {r.task_id: r for r in validate_results(first._task_results)}
    assert set(records) == {"K1", "P1", "V1"}
    assert records["K1"].payload.knowledge.evidence[0].source_version == "fixture-rag"
    assert records["V1"].status == "partial"  # UNKNOWN ingredient evidence stays unknown.
    assert records["V1"].bindings[0].value_fingerprint == fingerprint(
        records["P1"].payload.candidates
    )
    before = records["V1"].input_fingerprint
    api.options[8] = "changed-exact-option"
    second = await service.answer(ChatRequest(message=QUESTION, locale="ko"))
    revised = {r.task_id: r for r in validate_results(second._task_results)}
    assert revised["V1"].input_fingerprint != before
    assert api.calls[-1][1]["optionScope"][2]["optionId"] == "changed-exact-option"
    assert revised["V1"].payload.options[8].candidate.option_id == "changed-exact-option"
    assert "_task_results" not in second.model_dump_json()


@pytest.mark.anyio
async def test_n02_common_payload_keeps_options_evidence_and_public_response():
    catalog = Catalog()
    req = request([owned("lip-a", "lip-a-shade")], "블러셔는 없어. 추가 추천해줘.")
    response = await ChatService(None, FakeLlm(configured=False), catalog).answer(req)
    records = {r.task_id: r for r in validate_results(response._task_results)}
    assert {"O1", "S1", "N1", "P1", "V1", "R1"} <= set(records)
    assert records["S1"].payload.recipe.evidence_id == "fixture:recipe-evidence"
    assert [p.id for p in records["R1"].payload.products] == [p.id for p in response.products]
    assert records["P1"].bindings
    payload = response.model_dump(mode="json", by_alias=True)
    assert "taskResults" not in payload and "_task_results" not in payload
    assert response._owned_look_outcome == records["R1"].payload.outcome


@pytest.mark.anyio
async def test_n02_missing_recipe_preserves_executed_work(monkeypatch):
    from app.schemas.chat import ChatResponse
    from app.services import owned_look_consultation_service

    async def failed_style(*args):
        return ChatResponse(answer="synthetic failure", products=[], style_status="error"), []

    monkeypatch.setattr(owned_look_consultation_service, "execute_style", failed_style)
    response = await ChatService(None, FakeLlm(configured=False), Catalog()).answer(
        request([owned("lip-a", "lip-a-shade")], "블러셔는 없어. 추가 추천해줘.")
    )
    records = {r.task_id: r for r in validate_results(response._task_results)}
    assert set(records) == {"O1", "S1"}
    assert records["S1"].status == "failed"
    assert records["O1"].payload.owned_products


@pytest.mark.anyio
async def test_e01_common_results_keep_failure_and_reuse_distinct():
    from app.services.conversation_context import prepare_request, updated_context

    catalog = FailureCatalog()
    service = ChatService(None, CombinedModel(), catalog)
    req = comparison_request()
    first = await service.answer(req)
    records = {r.task_id: r for r in validate_results(first._task_results)}
    assert records["product"].status == "completed"
    assert records["style"].status == "failed" and records["style"].payload is None
    assert len(records["product"].inputs["catalogRequests"]) == 2
    follow = prepare_request(
        req.model_copy(update={"message": "룩만 다시 찾아줘"}), updated_context({}, first), []
    )
    second = await service.answer(follow)
    recovered = {r.task_id: r for r in validate_results(second._task_results)}
    assert recovered["product"].reused and recovered["product"].attempt == 0
    assert recovered["product"].inputs["catalogRequests"] == []
    assert recovered["style"].status == "completed" and not recovered["style"].reused
    assert recovered["product"].payload.answer == records["product"].payload.answer


def pair():
    pid = uuid4()
    source_task = TaskRequest(
        task_id="P1", plan_id=pid, plan_version=1, agent="recommend", goal=GOAL
    )
    source = TaskResult(
        task_id="P1", plan_id=pid, plan_version=1, input_fingerprint="source", status="partial"
    )
    target_task = TaskRequest(
        task_id="V1",
        plan_id=pid,
        plan_version=1,
        agent="verify",
        goal=GOAL,
        depends_on=["P1"],
        input_bindings=[InputBinding(source_task="P1")],
    )
    target = TaskResult(
        task_id="V1", plan_id=pid, plan_version=1, input_fingerprint="target", status="skipped"
    )
    left = adapt_specialist(source_task, source, {"goal": "synthetic"}, {})
    right = adapt_specialist(target_task, target, {"option_scope": []}, {"P1": source})
    return source_task, source, target_task, target, left, right


@pytest.mark.parametrize(
    "mutation", ["identity", "status", "inputs", "binding", "version", "duplicate", "dependency"]
)
def test_parent_rejects_incoherent_result_sets(mutation):
    _, _, _, _, left, right = pair()
    records = [left, right]
    if mutation == "identity":
        right.payload.task_id = "other"
    elif mutation == "status":
        left.status = "completed"
    elif mutation == "inputs":
        right.inputs["option_scope"] = ["wrong"]
    elif mutation == "binding":
        right.bindings[0].value_fingerprint = "wrong"
    elif mutation == "version":
        right.plan_version = 2
    elif mutation == "duplicate":
        records.append(left)
    else:
        records = [right]
    with pytest.raises(ValueError):
        validate_results(records)


def test_adapter_rejects_replaced_source_or_wrong_bound_value():
    _, source, task, result, _, _ = pair()
    with pytest.raises(ValueError, match="Bound input"):
        adapt_specialist(task, result, {"option_scope": ["wrong"]}, {"P1": source})
    source.plan_version = 2
    with pytest.raises(ValueError, match="Stale input"):
        adapt_specialist(task, result, {"option_scope": []}, {"P1": source})


@pytest.mark.anyio
async def test_parent_actually_checks_specialist_result_before_accepting():
    from app.schemas.chat import ChatResponse

    _, _, _, _, left, _ = pair()
    left.status = "completed"
    response = ChatResponse(answer="synthetic", products=[])
    response._task_results = [left]

    async def execute():
        return response

    with pytest.raises(ValueError, match="Changed result status"):
        await parent.run_parent(ChatRequest(message="관리와 제품", locale="ko"), "skin", execute)


@pytest.mark.parametrize(
    "corruption,expected",
    [
        ("version", "stale_source"),
        ("goal", "outside_user_goal"),
        ("source", "changed_source"),
        ("status", "unavailable_source"),
    ],
)
def test_continuation_rejects_untrusted_or_obsolete_source(corruption, expected):
    from app.schemas.chat import ChatResponse
    from app.schemas.consultation_parent import ConsultationParent, ParentTask
    from app.schemas.consultation_task import TaskContinuation
    from app.services.consultation_task_adapter import (
        adapt_independent,
        fingerprint,
        validate_continuation,
    )

    # Use the actual typed recipe fixture, never answer-text inference.
    from tests.test_g8_owned_look import Catalog

    recipe = Catalog().look.recipe
    # Validation requires a response recipe; use a minimal real schema fixture from its service.
    task = ParentTask(
        task_id="task-owned",
        goal="owned_look",
        version=1,
        status="completed",
        explanation_quote="설명해줘",
    )
    parent = ConsultationParent(tasks=[task])
    response = ChatResponse(answer="합성", products=[])
    proposal = TaskContinuation(objective="설명해줘", source_fingerprint=fingerprint(recipe))
    record = adapt_independent(parent, task, response, {})
    if corruption == "version":
        record.plan_version += 1
    elif corruption == "goal":
        proposal.objective = "사용자가 요청하지 않은 설명"
    elif corruption == "status":
        record.status = "failed"
    assert validate_continuation(parent, task, record, proposal, response) == expected

"""Public wording stays bound to specialist decisions and exact displayed options."""

import json

import pytest

from app.core.config import get_settings
from app.services.chat_service import ChatService
from app.services.consultation_answer_service import finalize_answer, validate_answer_facts
from tests.test_g8_owned_look import KoreanScopeCatalog, scope_request
from tests.test_g8_owned_look_interpreter import Model, follow


def test_preserved_waiting_task_repeats_only_its_pending_questions():
    from app.schemas.chat import ChatResponse
    from app.schemas.consultation_parent import ParentTask
    from app.schemas.consultation_task import TaskInputNeed
    from app.services.consultation_answer_service import independent_answer

    task = ParentTask(
        task_id="task-look",
        goal="owned_look",
        version=2,
        status="waiting_user",
        reason="preserved_completed_result",
        input_needs=[
            TaskInputNeed(key="ownership", question="롬앤 02호를 가지고 있나요?", need_id="romand")
        ],
    )
    result = ChatResponse(answer="긴 상품 목록과 근거 부족 안내를 다시 반복", products=[])
    text = independent_answer(task, result, task.model_copy())
    assert "롬앤 02호를 가지고 있나요?" in text and "긴 상품 목록" not in text
    assert result.answer == "긴 상품 목록과 근거 부족 안내를 다시 반복"


def test_preserved_knowledge_is_kept_in_task_without_duplicating_display_sources():
    from app.schemas.chat import ChatResponse
    from app.schemas.consultation_parent import ConsultationParent, ParentTask
    from app.schemas.knowledge import KnowledgeReply
    from app.services.consultation_parent_graph import combine_id_results

    saved = ChatResponse(
        answer="앞서 확인한 원문 설명",
        products=[],
        knowledge=KnowledgeReply(status="partial", limitations="개인 원인은 미확인"),
    )
    task = ParentTask(
        task_id="task-skin",
        goal="skin",
        version=1,
        status="partial",
        reason="preserved_completed_result",
        display_result=saved.model_dump(mode="json", by_alias=True),
    )
    parent = ConsultationParent(tasks=[task])
    response = combine_id_results(
        parent, {task.task_id: saved}, previous=parent.model_copy(deep=True)
    )
    assert response.knowledge is None
    assert task.display_result["knowledge"]["limitations"] == "개인 원인은 미확인"
    shown = combine_id_results(parent, {task.task_id: saved})
    assert shown.knowledge is not None and shown.answer == saved.answer


def test_independent_reply_uses_facts_not_internal_objective():
    from app.schemas.chat import ChatResponse
    from app.schemas.consultation_parent import ConsultationParent, ParentTask
    from app.schemas.consultation_task import ProductAssessment, ProductRequirement
    from app.services.consultation_parent_graph import combine_id_results

    def task(key, kind, price, preserved=False):
        return ParentTask(
            task_id=key,
            goal="product",
            version=1,
            status="completed",
            objective="공통 조건: 내부 정보\n현재 변경 요청: 내부 목표",
            reason="preserved_completed_result" if preserved else "matched",
            product_requirement=ProductRequirement(kind=kind),
            product_context={"filters": {"maxPriceKRW": price, "moisturizing": True}},
            product_assessment=ProductAssessment(
                status="completed",
                outcome="matched",
                requirement=ProductRequirement(kind=kind),
                matched=1,
            ),
        )

    parent = ConsultationParent(
        tasks=[task("toner-task", "toner", None, True), task("cream-task", "cream", 15000)]
    )
    previous = ConsultationParent(
        tasks=[task("toner-task", "toner", None), task("cream-task", "cream", None)]
    )
    replies = {
        key: ChatResponse(
            answer="상위 작업 입력을 출력하면 안 됨",
            products=[{"id": key, "brand": "b", "name": "상품", "category": "skincare"}],
        )
        for key in ["toner-task", "cream-task"]
    }
    result = combine_id_results(parent, replies, previous=previous)
    assert "토너 추천은 그대로 유지" in result.answer
    assert "크림은 15,000원 이하" in result.answer
    assert "크림 후보 1개" in result.answer
    assert all(
        word not in result.answer for word in ["현재 변경 요청", "공통 조건", "내부", "task"]
    )
    assert len(result.products) == 2
    parent.tasks[1].product_assessment.status = "partial"
    replies["cream-task"].answer = "향료 포함 여부는 아직 확인하지 못했어요."
    assert replies["cream-task"].answer in combine_id_results(parent, replies).answer


@pytest.mark.parametrize("operation,label", [("compare", "비교한 내용"), ("detail", "상품 정보")])
def test_preserved_product_operation_is_not_called_recommendation(operation, label):
    from app.schemas.chat import ChatResponse
    from app.schemas.consultation_parent import ParentTask
    from app.schemas.consultation_task import ProductAssessment, ProductRequirement
    from app.services.consultation_answer_service import independent_answer

    task = ParentTask(
        goal="product",
        version=1,
        product_operation=operation,
        reason="preserved_completed_result",
        product_assessment=ProductAssessment(
            status="completed", outcome="matched", requirement=ProductRequirement(), matched=2
        ),
    )
    answer = independent_answer(task, ChatResponse(answer="기존 비교", products=[]))
    assert label in answer and "추천" not in answer


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.fixture(autouse=True)
def enabled(monkeypatch):
    monkeypatch.setattr(get_settings(), "g8_enabled", True)


@pytest.mark.anyio
async def test_public_four_turn_answers_and_cards(record_property):
    catalog, model = KoreanScopeCatalog(), Model()
    service = ChatService(None, model, catalog)
    req = scope_request("립 제품은 전부 없어. 2만원 이하로 찾아줘.")
    first = await service.answer(req)
    assert "검수" not in first.answer and "사용자가" not in first.answer
    assert "충족 2개" not in first.answer
    req, second = await follow(service, req, first, "그 틴트만 미보유 조건에서 빼줘")
    assert "‘없음’ 조건에서 뺐어요" in second.answer
    assert second.answer.count("가지고 있나요?") == 1
    assert "사용 순서" not in second.answer
    assert [p.id for p in second.products] == ["lip-a"]
    assert "보유 조건을 반영" not in second.answer
    req, third = await follow(service, req, second, "예산은 3만원 이하로 바꿔줘")
    assert third.answer.startswith("예산을 30,000원 이하로 바꿨어요.")
    assert "가지고 있나요?" not in third.answer
    assert (
        third._consultation_parent.question.need_id == second._consultation_parent.question.need_id
    )
    assert third._owned_look_context.exceptions == second._owned_look_context.exceptions
    req, fourth = await follow(service, req, third, "립 제품은 전부 없어.")
    assert {p.id for p in fourth.products} == {"lip-a", "lip-b"}
    assert "보유 조건을 반영" in fourth.answer
    assert len(model.calls) == 1
    turns = []
    for response in [first, second, third, fourth]:
        public_before = response.model_dump(mode="json", by_alias=True)
        finalize_answer(response, response._consultation_parent.question)
        assert response.model_dump(mode="json", by_alias=True) == public_before
        assert "consultation_answer" not in response.model_dump_json()
        turns.append(
            {
                "answer": response.answer,
                "cards": public_before["products"],
                "options": public_before.get("ownedLookOptions"),
                "answerModelCalls": 0,
                "catalogMode": "mock",
                "interpreterMode": "mock",
            }
        )
    record_property("answer_mock", json.dumps(turns, ensure_ascii=False))


@pytest.mark.anyio
@pytest.mark.parametrize("tamper", ["card", "option", "ownership", "question"])
async def test_inconsistent_answer_facts_are_rejected(tamper):
    service = ChatService(None, Model(), KoreanScopeCatalog())
    response = await service.answer(scope_request("롬앤 쥬시 래스팅 틴트는 없어. 2만원 이하."))
    facts = response._consultation_answer.model_copy(deep=True)
    question = None
    if tamper == "card":
        response.products = []
    elif tamper == "option":
        response.owned_look_options.selections[0].option_id = "wrong-option"
    elif tamper == "ownership":
        facts.outcome.items[-1].status = "owned"
    else:
        from app.schemas.consultation_parent import ParentQuestion

        question = ParentQuestion(
            goal="owned_look",
            version=1,
            text="wrong",
            input_key="ownership",
            need_id=facts.outcome.items[-1].need_id,
            recipe_version="stale",
        )
    with pytest.raises(ValueError):
        validate_answer_facts(facts, response, question)


@pytest.mark.anyio
async def test_budget_change_does_not_hide_a_new_ownership_question():
    from app.services.consultation_answer_service import render_answer

    service = ChatService(None, Model(), KoreanScopeCatalog())
    req = scope_request("립 제품은 전부 없어. 2만원 이하.")
    first = await service.answer(req)
    req, second = await follow(service, req, first, "그 틴트만 미보유 조건에서 빼줘")
    _, third = await follow(service, req, second, "예산은 3만원 이하로 바꿔줘")
    facts = third._consultation_answer.model_copy(deep=True)
    facts.previous_question_id = "another-target"
    assert "가지고 있나요?" in render_answer(facts, third._consultation_parent.question)

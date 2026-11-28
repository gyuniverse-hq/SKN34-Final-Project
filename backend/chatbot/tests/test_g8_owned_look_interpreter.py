"""Reference contracts: synthetic fixtures; live model only when explicitly enabled."""

import json
import os

import pytest

from app.core.config import get_settings
from app.schemas.owned_look_intent import OwnedLookIntent
from app.services import owned_look_interpreter as interpreter
from app.services.chat_service import ChatService
from app.services.conversation_context import prepare_request, updated_context
from tests.test_g8_owned_look import KoreanScopeCatalog, scope_request


@pytest.mark.anyio
async def test_bound_question_short_answer_changes_only_exact_option_without_model():
    from app.schemas.consultation_parent import ParentQuestion
    from app.services.owned_look_consultation_service import execute_owned_look

    req = scope_request("이 룩에 필요한 상품 추천해줘")
    req._consultation_memories = ()
    first = await execute_owned_look(req, KoreanScopeCatalog())
    items = first._owned_look_outcome.items
    assert len(items) == 2 and all(i.status == "ownership_unknown" for i in items)
    q = ParentQuestion(
        task_id="task-look",
        goal="owned_look",
        version=1,
        text="첫 상품 있나요?",
        input_key="ownership",
        need_id=items[0].need_id,
        recipe_version=first.style_recipe.recipe_version,
        ownership_scope="option",
    )
    req._owned_look_context = first._owned_look_context
    req._question_answers = [(q, "없어")]
    req._owned_look_llm = Model()
    second = await execute_owned_look(req, KoreanScopeCatalog())
    state = second._owned_look_context
    assert set(state.item_declarations) == {items[0].need_id}
    assert state.item_declarations[items[0].need_id].status == "missing"
    assert not state.product_declarations and not state.declarations
    assert (
        next(i for i in second._owned_look_outcome.items if i.need_id == items[1].need_id).status
        == "ownership_unknown"
    )
    assert req._owned_look_llm.calls == []


@pytest.mark.anyio
async def test_bound_question_rejects_model_change_to_another_item_atomically():
    from app.schemas.consultation_parent import ParentQuestion
    from app.services.owned_look_consultation_service import execute_owned_look

    req = scope_request("이 룩에 필요한 상품 추천해줘")
    req._consultation_memories = ()
    first = await execute_owned_look(req, KoreanScopeCatalog())
    a = first._owned_look_outcome.items[0]
    req._owned_look_context = first._owned_look_context
    original = req._owned_look_context.model_dump_json()
    req._question_answers = [
        (
            ParentQuestion(
                task_id="task-look",
                goal="owned_look",
                version=1,
                text="첫 상품 있나요?",
                input_key="ownership",
                need_id=a.need_id,
                recipe_version=first.style_recipe.recipe_version,
                ownership_scope="option",
            ),
            "첫 상품은 가지고 있지 않아",
        )
    ]
    req._owned_look_llm = Model(action="declare")  # Proposes both scopes on the OTHER product.
    result = await execute_owned_look(req, KoreanScopeCatalog())
    assert result.result_type == "clarification" and result._preserve_parent_context
    assert result._owned_look_context.model_dump_json() == original
    assert not result.products


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.mark.anyio
@pytest.mark.parametrize("action,status", [("answer", "missing"), ("defer", None)])
async def test_question_meaning_model_cannot_choose_identity_or_scope(action, status):
    from app.schemas.consultation_parent import ParentQuestion
    from app.services.owned_look_consultation_service import execute_owned_look

    class MeaningModel:
        configured = True

        async def complete_with_tools(self, messages, tools, *, required_tool):
            payload = json.loads(messages[-1]["content"])
            assert set(payload) == {"utterance", "currentQuestion"}
            assert set(tools[0]["function"]["parameters"]["properties"]) == {
                "action",
                "status",
                "question",
            }
            return {
                "choices": [
                    {
                        "message": {
                            "tool_calls": [
                                {
                                    "function": {
                                        "name": required_tool,
                                        "arguments": json.dumps(
                                            {"action": action, "status": status}
                                        ),
                                    }
                                }
                            ]
                        }
                    }
                ]
            }, 0

    req = scope_request("이 룩에 필요한 상품 추천해줘")
    req._consultation_memories = ()
    first = await execute_owned_look(req, KoreanScopeCatalog())
    a, b = first._owned_look_outcome.items
    req._owned_look_context = first._owned_look_context
    req._question_answers = [
        (
            ParentQuestion(
                task_id="task-look",
                goal="owned_look",
                version=1,
                text="첫 상품 있나요?",
                input_key="ownership",
                need_id=a.need_id,
                recipe_version=first.style_recipe.recipe_version,
                ownership_scope="option",
            ),
            "답변의 의미만 해석하는 합성 문장",
        )
    ]
    req._owned_look_llm = MeaningModel()
    result = await execute_owned_look(req, KoreanScopeCatalog())
    assert b.need_id not in result._owned_look_context.item_declarations
    assert not result._owned_look_context.product_declarations
    assert not result._owned_look_context.declarations
    if action == "answer":
        assert result._owned_look_context.item_declarations[a.need_id].scope == "option"
        assert result._owned_look_context.item_declarations[a.need_id].status == "missing"
    else:
        assert not result._owned_look_context.item_declarations


@pytest.fixture(autouse=True)
def enabled(monkeypatch):
    monkeypatch.setattr(get_settings(), "g8_enabled", True)


class Model:
    configured = True

    def __init__(self, action="exempt", invalid=False):
        self.calls = []
        self.parent_calls = []
        self.entry_calls = []
        self.action = action
        self.invalid = invalid

    async def complete_with_tools(self, messages, tools, *, required_tool):
        payload = json.loads(messages[-1]["content"])
        if required_tool in {"interpret_consultation_change", "plan_consultation_entry"}:
            (
                self.entry_calls
                if required_tool == "plan_consultation_entry"
                else self.parent_calls
            ).append(payload)
            args = {
                "planId": payload["planId"],
                "version": payload["version"],
                "action": "delegate" if required_tool == "plan_consultation_entry" else "continue",
            }
            return {
                "choices": [
                    {
                        "message": {
                            "tool_calls": [
                                {
                                    "function": {
                                        "name": required_tool,
                                        "arguments": json.dumps(args),
                                    }
                                }
                            ]
                        }
                    }
                ]
            }, 0
        self.calls.append(payload)
        refs = payload["snapshot"]
        target = next(t for t in refs["targets"] if t["productId"] == "lip-b")
        operations = [{"action": self.action, "scope": "product", "targetId": target["targetId"]}]
        if self.action == "declare":
            operations[0]["status"] = "present"
            operations.append(
                {
                    "action": "declare",
                    "scope": "option",
                    "status": "missing",
                    "targetId": target["targetId"],
                }
            )
        plan = {
            "snapshotVersion": "stale" if self.invalid else refs["version"],
            "action": "update",
            "operations": operations,
        }
        return {
            "choices": [
                {
                    "message": {
                        "tool_calls": [
                            {"function": {"name": required_tool, "arguments": json.dumps(plan)}}
                        ]
                    }
                }
            ]
        }, 1


async def follow(service, req, response, message):
    context = updated_context({}, response)
    # JSON round-trip is a contract test, not a PostgreSQL test.
    context = json.loads(json.dumps(context))
    next_req = prepare_request(req.model_copy(update={"message": message}), context, [])
    return next_req, await service.answer(next_req)


@pytest.mark.anyio
async def test_zone_exception_roundtrip_reapply_and_exact_tool_input():
    catalog, model = KoreanScopeCatalog(), Model()
    service = ChatService(None, model, catalog)
    req = scope_request("립 제품은 전부 없어. 2만원 이하로 찾아줘.")
    first = await service.answer(req)
    assert {p.id for p in first.products} == {"lip-a", "lip-b"}
    req, second = await follow(service, req, first, "그 틴트만 미보유 조건에서 빼줘")
    assert len(model.calls) == 1
    assert {p.id for p in second.products} == {"lip-a"}
    assert second._owned_look_context.exceptions
    assert not second._owned_look_context.product_declarations
    assert (
        next(i for i in second._owned_look_outcome.items if "틴트" in i.label).status
        == "ownership_unknown"
    )
    req, third = await follow(service, req, second, "예산은 3만원 이하로 바꿔줘")
    assert third._owned_look_context.exceptions == second._owned_look_context.exceptions
    req, fourth = await follow(service, req, third, "립 제품은 전부 없어.")
    assert not fourth._owned_look_context.exceptions
    assert {p.id for p in fourth.products} == {"lip-a", "lip-b"}


@pytest.mark.anyio
async def test_product_present_different_color_keeps_exact_option_missing():
    catalog, model = KoreanScopeCatalog(), Model("declare")
    service = ChatService(None, model, catalog)
    req = scope_request("립 제품은 전부 없어.")
    first = await service.answer(req)
    _, response = await follow(service, req, first, "그 틴트는 있는데 네가 말한 색은 아니야")
    assert response._owned_look_context.product_declarations["lip-b"].status == "present"
    assert any(
        d.status == "missing" and d.scope == "option"
        for d in response._owned_look_context.item_declarations.values()
    )
    assert "lip-b" in {p.id for p in response.products}
    assert response.ar_result is None and response.memory_proposal is None


@pytest.mark.anyio
async def test_rejected_model_preserves_conditions_and_makes_no_product_search():
    catalog, model = KoreanScopeCatalog(), Model(invalid=True)
    service = ChatService(None, model, catalog)
    req = scope_request("립 제품은 전부 없어.")
    first = await service.answer(req)
    _, response = await follow(service, req, first, "그 틴트만 미보유 조건에서 빼줘")
    assert response.result_type == "clarification"
    assert response._owned_look_context.declarations == first._owned_look_context.declarations
    assert not response._owned_look_context.exceptions
    assert response._owned_look_interpretation["status"] == "rejected_or_failed"
    assert response.products == []


@pytest.mark.anyio
async def test_ordinal_validation_rejects_conflicting_lists_and_stale_ids():
    service = ChatService(None, Model(), KoreanScopeCatalog())
    response = await service.answer(scope_request("립 제품은 전부 없어."))
    refs = response._owned_look_context.references.model_copy(deep=True)
    refs.recommendations = list(reversed(refs.look_products))
    plan = OwnedLookIntent(
        snapshot_version=refs.version,
        action="update",
        operations=[{"action": "exempt", "scope": "product", "targetId": refs.look_products[0]}],
    )
    with pytest.raises(ValueError, match="ordinal"):
        interpreter.validate_intent(plan, refs, "첫 번째는 조건에서 빼줘")
    assert interpreter.validate_intent(plan, refs, "룩 목록 첫 번째는 조건에서 빼줘") == plan
    plan.operations[0].target_id = "invented"
    with pytest.raises(ValueError, match="Unknown"):
        interpreter.validate_intent(plan, refs, "그 제품은 조건에서 빼줘")


@pytest.mark.anyio
async def test_live_model_reference_contract(record_property):
    if os.environ.get("G8_N02_REFERENCE_LIVE") != "1":
        pytest.skip("explicit live model verification only")
    from app.clients.llm_client import get_llm_client

    model = get_llm_client()
    assert model.configured
    service = ChatService(None, model, KoreanScopeCatalog())
    req = scope_request("립 제품은 전부 없어.")
    first = await service.answer(req)
    req, second = await follow(service, req, first, "그 틴트는 있는데 네가 말한 색은 아니야")
    assert second._owned_look_context.product_declarations["lip-b"].status == "present"
    req, third = await follow(service, req, second, "그 틴트만 미보유 조건에서 빼줘")
    record_property(
        "live_audits",
        json.dumps(
            [second._owned_look_interpretation, third._owned_look_interpretation],
            ensure_ascii=False,
        ),
    )
    assert third._owned_look_context.exceptions, third._owned_look_interpretation
    assert (
        next(i for i in third._owned_look_outcome.items if "틴트" in i.label).status
        == "ownership_unknown"
    )
    record_property(
        "reference_live",
        json.dumps(
            {
                "catalogMode": "mock",
                "storageMode": "json_roundtrip",
                "turns": [
                    {"modelMode": "disabled", "actualCalls": 0},
                    *[
                        {
                            "modelMode": "live",
                            "actualCalls": r._owned_look_interpretation["invocations"],
                            "audit": r._owned_look_interpretation,
                            "answer": r.answer,
                            "cards": [p.model_dump(mode="json", by_alias=True) for p in r.products],
                            "answerGenerationMode": "deterministic",
                            "answerModelCalls": 0,
                        }
                        for r in [second, third]
                    ],
                ],
            },
            ensure_ascii=False,
        ),
    )


@pytest.mark.anyio
async def test_ambiguous_pronoun_and_unavailable_model_do_not_mutate():
    from tests.conftest import FakeLlm

    service = ChatService(None, FakeLlm(configured=False), KoreanScopeCatalog())
    req = scope_request("립 제품은 전부 없어.")
    first = await service.answer(req)
    refs = first._owned_look_context.references
    plan = OwnedLookIntent(
        snapshot_version=refs.version,
        action="update",
        operations=[
            {
                "action": "exempt",
                "scope": "product",
                "targetId": refs.look_products[0],
            }
        ],
    )
    with pytest.raises(ValueError, match="pronoun"):
        interpreter.validate_intent(plan, refs, "그거만 조건에서 빼줘")
    _, response = await follow(service, req, first, "그거만 조건에서 빼줘")
    assert response.result_type == "clarification"
    assert response._owned_look_context.declarations == first._owned_look_context.declarations
    assert response._owned_look_interpretation["invocations"] == 0


@pytest.mark.anyio
async def test_zone_release_removes_exceptions_and_stale_snapshot_does_not_call_model():
    model, catalog = Model(), KoreanScopeCatalog()
    service = ChatService(None, model, catalog)
    req = scope_request("립 제품은 전부 없어.")
    first = await service.answer(req)
    req, second = await follow(service, req, first, "그 틴트만 미보유 조건에서 빼줘")
    req, third = await follow(service, req, second, "립 미보유 조건 해제해줘.")
    assert not third._owned_look_context.exceptions
    assert not third._owned_look_context.declarations
    third._owned_look_context.references.recipe_version = "old-recipe"
    _, fourth = await follow(service, req, third, "그 틴트만 미보유 조건에서 빼줘")
    assert fourth._owned_look_interpretation["invocations"] == 0
    assert fourth.result_type == "clarification"


def test_price_unit_is_not_item_exception_particle():
    assert not interpreter.needs_reference(
        "상품 조건 전체 해제해줘. 예산은 2만원 이하. 판테놀 제외."
    )
    assert interpreter.needs_reference("틴트만 미보유 조건에서 빼줘")

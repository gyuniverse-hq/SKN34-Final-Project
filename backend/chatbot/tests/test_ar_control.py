import asyncio
import json
import os
from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.clients.llm_client import get_ar_llm_client
from app.core.errors import ApiError
from app.repositories.ar_command_repository import MemoryArRequestRepository, get_ar_requests
from app.repositories.chat_session_repository import ChatSessionRepository
from app.schemas.chat import (
    ArAckRequest,
    ArCatalogNameMatch,
    ArCatalogProductMatch,
    ArControlFeedback,
    ArControlSelection,
    ChatRequest,
)
from app.schemas.supervisor import ToolResult
from app.services.ar_control_service import ArControlAgent, _lookup_facts, _recommendation_facts
from app.services.chat_service import ChatService, get_chat_service, verify_response
from tests.test_chat_sessions import RedisDouble


def request(message, zone):
    return ChatRequest.model_validate(
        {
            "message": message,
            "locale": "ko",
            "requestType": "ar_command",
            "requestId": uuid4(),
            "arContext": {
                "screenId": "A-01",
                "stateVersion": 7,
                "activeZone": zone,
                "supportedActions": ["ar_control"],
                "lip": None,
                "control": {
                    "choices": [
                        "get_state/current_screen",
                        "find_shades/lip/pink",
                        "apply_shade/lip/first_match/pink",
                        "apply_shade/blush/first_match/pink",
                        "explore_nearby/show/similar",
                        "set_palette_filter/pink",
                        "adjust_intensity/lip/down",
                        "adjust_intensity/blush/down",
                        "apply_shade/palette_center",
                        "clear_layer/lip",
                    ],
                    "summary": json.dumps(
                        {
                            "zone": zone,
                            "displayMode": "face",
                            "worn": [{"zone": zone, "product": "test shade", "intensity": 0.55}],
                        }
                    ),
                },
            },
        }
    )


class Model:
    configured = True

    def __init__(self, choice):
        self.choice = choice

    async def choose_ar_control(self, messages, tool):
        assert "worn" in messages[1]["content"]
        assert tool["name"] == "ar_control"
        args = {"choice": self.choice}
        if self.choice.startswith(("adjust_intensity/", "set_intensity/", "set_look_strength/")):
            args["intensityInstruction"] = json.loads(messages[1]["content"])["message"]
        return {"arguments": json.dumps(args)}


def answer(req, model):
    service = ChatService(None, model, requests=MemoryArRequestRepository())
    return asyncio.run(service.answer(req, "guest:a"))


def test_only_the_matching_rendered_turn_is_available_to_the_next_planner(monkeypatch):
    import time

    now = [1000]
    monkeypatch.setattr(time, "time", lambda: now[0])
    seen = []

    class Spy(Model):
        async def choose_ar_control(self, messages, choices):
            context = json.loads(messages[1]["content"])
            previous = context["lastAppliedAdjustment"]
            seen.append(previous)
            if context["message"] == "조금 더":
                choice = "continue_intensity/lip/down" if previous else "clarify_intensity"
                assert choice in choices["parameters"]["properties"]["choice"]["enum"]
                return {"arguments": json.dumps({"choice": choice})}
            return await super().choose_ar_control(messages, choices)

    async def exercise():
        repo = ChatSessionRepository(RedisDouble(), 30)
        service = ChatService(
            None,
            Spy("adjust_intensity/lip/down"),
            requests=MemoryArRequestRepository(),
            sessions=repo,
        )
        owner, session = "guest:one", uuid4()
        first = request("립 좀 연하게 해줘", "lip")
        first.ar_context.session_id = session
        proposal = (await service.answer(first, owner)).ar_result.action_proposal
        ack = ArAckRequest(
            request_id=first.request_id,
            session_id=session,
            command_id=proposal.command_id,
            status="APPLIED",
            actual_state_version=8,
            intensity_change={"zone": "lip", "before": 0.55, "after": 0.45},
        )

        async def read(who=owner, sid=session, version=8):
            turn = request("조금 더", "blush")
            turn.ar_context.session_id = sid
            turn.ar_context.state_version = version
            turn.ar_context.previous_adjustment_id = proposal.command_id
            result = (await service.answer(turn, who)).ar_result
            if seen[-1] is None:
                assert result.status == "clarification" and result.action_proposal is None
            else:
                assert result.action_proposal.choice == "adjust_intensity/lip/down"
                assert result.action_proposal.fine_adjustment
            return seen[-1]

        assert await read() is None
        with pytest.raises(ApiError, match="Invalid confirmed adjustment"):
            await service.acknowledge_ar(owner, ack.model_copy(update={"status": "FAILED"}))
        assert await read() is None
        await service.acknowledge_ar(owner, ack)
        assert await read() == {
            "zone": "lip",
            "before": 0.55,
            "after": 0.45,
            "direction": "down",
            "stateVersion": 8,
        }
        assert await read(version=9) is None
        assert await read(sid=uuid4()) is None
        assert await read(who="guest:two") is None
        now[0] += 20
        await service.acknowledge_ar(owner, ack)
        now[0] += 11
        await service.acknowledge_ar(owner, ack)
        assert await read() is None

    asyncio.run(exercise())


def test_color_conditions_can_be_inferred_independently():
    choice = "apply_shade/lip/by_color"
    for conditions in (
        {"lightness": "light"},
        {"chroma": "muted"},
        {"family": "pink", "chroma": "muted"},
    ):
        selected = ArControlSelection(choice=choice, **conditions)
        assert selected.model_dump(exclude_none=True) == {"choice": choice, **conditions}
    for args in (
        {"choice": choice},
        {"choice": choice, "chroma": "pink"},
        {"choice": "adjust_intensity/lip/down", "lightness": "light"},
    ):
        with pytest.raises(ValidationError):
            ArControlSelection.model_validate(args)


def catalog_plan(message, candidates, choice="apply_shade/product_shade", *, products=(), **args):
    req = request(message, "lip")
    req.ar_context.control.choices += [
        "apply_shade/product_shade",
        "apply_shade/product_pick",
        "apply_shade/lip/named",
        "apply_shade/lip/by_color",
        "set_shadow_point/product_shade",
    ]
    req.ar_context.catalog_name_matches = [ArCatalogNameMatch.model_validate(c) for c in candidates]
    req.ar_context.catalog_product_matches = [
        ArCatalogProductMatch.model_validate(product) for product in products
    ]

    class Planner(Model):
        async def choose_ar_control(self, messages, tool):
            fields = tool["parameters"]["properties"]
            assert "catalogTarget" in fields
            assert "productId" not in fields and "shadeId" not in fields
            assert "apply_shade/lip/named" not in fields["choice"]["enum"]
            return {"arguments": json.dumps({"choice": choice, **args})}

    return answer(req, Planner(choice))


def catalog_shade(product_id, brand, product, shade, *, zone="lip"):
    return {
        "productId": product_id,
        "shadeId": "01",
        "zone": zone,
        "brand": brand,
        "product": product,
        "shade": shade,
    }


def test_named_shade_is_resolved_from_catalog_and_spoken_product():
    matches = [
        catalog_shade("a", "오로라", "오로라 샤인 틴트", "Misty Rose"),
        catalog_shade("b", "오로라", "오로라 크림 틴트", "Misty Rose"),
        catalog_shade("c", "베일", "베일 샤인 틴트", "Misty Rose"),
    ]
    response = catalog_plan(
        "오로라 샤인 틴트 MISTYROSE 발라볼래.",
        matches,
        catalogTarget={"name": "MISTYROSE", "brand": "오로라", "product": "샤인 틴트"},
        productId="b",
        shadeId="invented-id",
    )
    proposal = response.ar_result.action_proposal
    assert (proposal.choice, proposal.product_id, proposal.shade_id) == (
        "apply_shade/product_shade",
        "a",
        "01",
    )


def test_catalog_product_scope_allows_catalog_metadata_without_requiring_it_in_speech():
    product = {
        "productId": "a",
        "zone": "lip",
        "brand": "에뛰드",
        "product": "에뛰드 픽싱 틴트 4g",
        "reference": "에뛰드 픽싱 틴트",
    }
    shade = {**catalog_shade("a", "에뛰드", product["product"], "로즈 블렌딩"), "shadeId": "11"}
    for name in ("로즈 블렌딩", "11호"):
        response = catalog_plan(
            f"에뛰드 픽싱 틴트에 {name} 발라볼래.",
            [shade],
            products=[product],
            catalogTarget={"name": name, "brand": "에뛰드", "product": product["product"]},
        )
        proposal = response.ar_result.action_proposal
        assert (proposal.choice, proposal.product_id, proposal.shade_id) == (
            "apply_shade/product_shade",
            "a",
            "11",
        )


@pytest.mark.parametrize("name", [None, "미스티 로즈 라이트"])
def test_product_pick_requires_delegation_and_a_grounded_product(name):
    product = {
        "productId": "a",
        "zone": "lip",
        "brand": "오로라",
        "product": "오로라 샤인 틴트 4g",
        "reference": "오로라 샤인 틴트",
    }
    response = catalog_plan(
        f"오로라 샤인 틴트 {name or ''} 발라볼래.",
        [],
        "apply_shade/product_pick",
        products=[product],
        catalogTarget={"product": product["product"], "name": name},
        family="coral",
    )
    if name:
        assert response.ar_result.status == "clarification"
        assert response.ar_result.action_proposal is None
    else:
        proposal = response.ar_result.action_proposal
        assert (proposal.product_id, proposal.shade_id, proposal.family) == ("a", None, "coral")


@pytest.mark.parametrize("requested_label", ["Fixing Tint", "A Fixing Tint"])
def test_product_pick_never_selects_between_ambiguous_products(requested_label):
    first = {
        "productId": "a",
        "zone": "lip",
        "brand": "A",
        "product": "A Fixing Tint",
        "reference": "Fixing Tint",
    }
    response = catalog_plan(
        "Fixing Tint 발라볼래.",
        [],
        "apply_shade/product_pick",
        products=[first, {**first, "brand": "B", "productId": "b", "product": "B Fixing Tint"}],
        catalogTarget={"product": requested_label},
    )
    assert response.ar_result.status == "clarification"
    assert response.ar_result.action_proposal is None


def test_catalog_metadata_cannot_disambiguate_product_variants_on_its_own():
    first = {
        "productId": "a",
        "zone": "lip",
        "brand": "오로라",
        "product": "오로라 샤인 틴트 4g",
        "reference": "오로라 샤인 틴트",
    }
    response = catalog_plan(
        "오로라 샤인 틴트 좀 발라봐.",
        [],
        "apply_shade/product_pick",
        products=[first, {**first, "productId": "b", "product": "오로라 샤인 틴트 8g"}],
        catalogTarget={"product": first["product"]},
    )
    assert response.ar_result.status == "clarification"
    assert response.ar_result.action_proposal is None


def test_named_shade_can_repeat_the_spoken_brand_without_changing_its_identity():
    response = catalog_plan(
        "오로라 로즈로 발라볼래.",
        [
            catalog_shade("a", "오로라", "오로라 샤인 틴트", "로즈"),
            catalog_shade("b", "베일", "베일 샤인 틴트", "로즈"),
        ],
        catalogTarget={"name": "오로라 로즈", "brand": "오로라"},
    )
    proposal = response.ar_result.action_proposal
    assert (proposal.product_id, proposal.shade_id) == ("a", "01")


@pytest.mark.parametrize(
    ("message", "target", "choice", "extra", "ambiguous"),
    [
        (
            "문라이트 로즈였나? 그거 발라줘.",
            {"name": "문라이트 로즈"},
            "apply_shade/product_shade",
            {},
            False,
        ),
        (
            "오로라 문라이트 로즈를 발라줘.",
            {"name": "오로라 문라이트 로즈", "brand": "오로라"},
            "apply_shade/product_shade",
            {},
            False,
        ),
        ("로즈 발라줘.", {"name": "로즈"}, "apply_shade/product_shade", {}, True),
        (
            "로즈 발라줘.",
            {"name": "로즈", "brand": "베일"},
            "apply_shade/product_shade",
            {},
            False,
        ),
        (
            "오로라 말고 다른 브랜드의 로즈가 있을까? 미라 브랜드의 로즈 발라줘.",
            {"name": "로즈", "brand": "미라"},
            "apply_shade/product_shade",
            {},
            False,
        ),
        (
            "문라이트 로즈 발라줘.",
            {"name": "문라이트 로즈"},
            "apply_shade/lip/by_color",
            {"family": "pink"},
            False,
        ),
        (
            "문라이트 로즈 발라줘.",
            None,
            "apply_shade/product_shade",
            {"productId": "a", "shadeId": "01"},
            False,
        ),
        (
            "문라이트 로즈 발라줘.",
            {"name": ""},
            "apply_shade/product_shade",
            {},
            False,
        ),
    ],
)
def test_unverified_named_shade_requests_clarify_without_a_proposal(
    message, target, choice, extra, ambiguous
):
    matches = [
        catalog_shade("a", "오로라", "오로라 샤인 틴트", "로즈"),
        catalog_shade("b", "베일", "베일 밀크 틴트", "로즈"),
    ]
    response = catalog_plan(message, matches, choice, catalogTarget=target, **extra)
    assert response.ar_result.status == "clarification"
    assert response.ar_result.action_proposal is None
    assert response.answer.endswith("?")
    assert ("여러 개" in response.answer) is ambiguous


def test_requested_makeup_zone_limits_named_accent_lookup():
    matches = [
        catalog_shade("lip", "베일", "베일 틴트", "애쉬 브라운"),
        catalog_shade("eye", "베일", "베일 아이섀도", "애쉬 브라운", zone="eyeshadow"),
    ]
    response = catalog_plan(
        "애쉬 브라운을 눈꼬리에 넣어줘.",
        matches,
        "set_shadow_point/product_shade",
        catalogTarget={"name": "애쉬 브라운"},
    )
    assert response.ar_result.action_proposal.product_id == "eye"


def test_proposal_binds_choice_to_screen_revision():
    req = request("볼이 너무 도드라져. 살짝만 빼줘.", "blush")
    res = answer(req, Model("adjust_intensity/blush/down"))
    assert res.supervisor.plan.tasks == ["ar_command"]
    assert res.supervisor.result.tool == "ar_command"
    assert res.supervisor.result.application == "awaiting_app_ack"
    assert res.supervisor.result.evidence == []  # The app has not selected or rendered anything.
    assert res.ar_result.request_id == req.request_id
    p = res.ar_result.action_proposal
    assert (p.action, p.choice, p.expected_state_version) == (
        "ar_control",
        "adjust_intensity/blush/down",
        7,
    )


def test_supervisor_ar_agent_can_ask_for_clarification_without_a_proposal():
    req = request("조금만 바꿔줄래?", "lip")
    question = "입술 색을 바꿔볼까요, 아니면 지금 색을 연하게 해볼까요?"

    class ClarifyingModel:
        configured = True

        async def choose_ar_control(self, messages, tool):
            offered = tool["parameters"]["properties"]["choice"]["enum"]
            assert offered == ["clarify_intensity", *req.ar_context.control.choices]
            return {"answer": question}

    reply = answer(req, ClarifyingModel())
    assert reply.supervisor.result.tool == "ar_command"
    assert reply.supervisor.result.application == "not_requested"
    assert reply.ar_result.action_proposal is None
    assert reply.answer == question


@pytest.mark.parametrize(
    "arguments",
    [
        {"choice": "adjust_intensity/lip/up"},
        {"choice": "adjust_intensity/lip/up", "intensityInstruction": "더 진하게"},
        {"choice": "adjust_intensity/lip/up", "intensityInstruction": "."},
        {"choice": "continue_intensity/lip/up"},
        {"choice": "set_look_strength/up"},
    ],
)
def test_unverified_intensity_proposals_ask_for_grounding(arguments):
    req = request("조금만 더.", "lip")
    req.ar_context.control.choices += ["adjust_intensity/lip/up", "set_look_strength/up"]

    class Planner(Model):
        async def choose_ar_control(self, messages, tool):
            return {"arguments": json.dumps(arguments)}

    response = answer(req, Planner(None))
    assert response.ar_result.status == "clarification"
    assert response.ar_result.reason == "target_required"
    assert response.ar_result.action_proposal is None
    assert response.answer


def test_planner_can_ask_a_natural_question_for_an_undefined_adjustment():
    question = "어느 부분을 더 조절해볼까요?"

    class Planner(Model):
        async def choose_ar_control(self, messages, tool):
            return {
                "arguments": json.dumps(
                    {"choice": "clarify_intensity", "clarificationQuestion": question}
                )
            }

    response = answer(request("한 번만 더 해볼까?", "lip"), Planner(None))
    assert response.ar_result.status == "clarification"
    assert response.ar_result.action_proposal is None
    assert response.answer == question


@pytest.mark.parametrize(
    "changed",
    [{"choice": "unavailable"}, {"session_id": uuid4()}, {"expected_state_version": 8}],
)
def test_supervisor_rejects_a_control_proposal_outside_the_original_screen(changed):
    req = request("립을 조금 연하게 해줘", "lip")
    req.ar_context.session_id = uuid4()
    response = answer(req, Model("adjust_intensity/lip/down"))
    plan = response.supervisor
    proposal = response.ar_result.action_proposal
    response.ar_result.action_proposal = proposal.model_copy(update=changed)
    with pytest.raises(ApiError) as err:
        verify_response(
            req, plan.intent, plan.plan, response, ToolResult(tool="ar_command", status="success")
        )
    assert err.value.code == "invalid_tool_result"


@pytest.mark.parametrize(
    ("choice", "draft", "expected"),
    [
        ("adjust_intensity/lip/down", "한결 은은해졌어요.", "한결 은은해졌어요."),
        ("adjust_intensity/lip/down", 42, None),
        ("apply_shade/palette_center", "준비된 답변", None),
    ],
)
def test_prepared_reply_is_optional_and_bound_to_relative_intensity(choice, draft, expected):
    class Planner(Model):
        async def choose_ar_control(self, messages, choices):
            reply = await super().choose_ar_control(messages, choices)
            args = json.loads(reply["arguments"])
            return {"arguments": json.dumps({**args, "onAppliedReply": draft})}

    res = answer(request("살짝 연하게 해줘", "lip"), Planner(choice))
    assert res.answer == ""
    assert res.ar_result.action_proposal.on_applied_reply == expected


def test_unoffered_action_is_rejected():
    with pytest.raises(ApiError) as e:
        answer(request("이거 좀 볼래", "lip"), Model("unknown"))
    assert e.value.code == "invalid_llm_response"


@pytest.mark.parametrize(
    "args",
    [
        {"choice": "reapply_try_on/lip"},
        {"choice": "reapply_try_on/lip", "ordinal": 0},
        {"choice": "reapply_try_on/lip", "ordinal": 1.5},
        {"choice": "apply_shade/palette_center", "ordinal": 2},
    ],
)
def test_try_on_order_is_a_positive_integer_only_on_history_actions(args):
    with pytest.raises(ValidationError):
        ArControlSelection.model_validate(args)


def test_invalid_mood_argument_is_corrected_before_a_proposal_is_issued():
    class CorrectingModel(Model):
        async def choose_ar_control(self, messages, choices):
            family = "wine" if len(messages) == 2 else "berry"
            return {
                "arguments": json.dumps(
                    {"choice": self.choice, "family": family, "lipType": "lipstick"}
                )
            }

    req = request("분위기 있는 립스틱 하나 발라줘", "lip")
    choice = "apply_shade/lip/by_color"
    req.ar_context.control.choices.append(choice)
    result = answer(req, CorrectingModel(choice)).ar_result
    assert result.action_proposal.family == "berry"
    assert result.action_proposal.lip_type == "lipstick"


def test_ar_agent_narrates_the_app_result_for_the_request_owner(client):
    req = request("지금 입에 바른 게 뭐야?", "lip")
    req.ar_context.control.choices.append("get_state/lip")
    calls = []
    artist_reply = "지금 입술에는 바른 색이 없어요."

    class Artist(Model):
        async def choose_ar_control(self, messages, tool):
            calls.append("plan")
            assert "makeup artist" in messages[0]["content"].lower()
            return await super().choose_ar_control(messages, tool)

        async def complete(self, messages, *, ar_feedback):
            calls.append("reply")
            assert ar_feedback and "makeup artist" in messages[0]["content"].lower()
            facts = json.loads(messages[-1]["content"])["outcome"]["data"]
            assert facts["wornProduct"] is None and not facts["hasAppliedLayer"]
            assert "center" not in facts
            return artist_reply

    model, requests = Artist("get_state/lip"), MemoryArRequestRepository()
    del client.app.dependency_overrides[get_chat_service]
    client.app.dependency_overrides[get_ar_llm_client] = lambda: model
    client.app.dependency_overrides[get_ar_requests] = lambda: requests
    owner = {"x-vishue-anonymous-id": str(uuid4())}
    response = client.post(
        "/api/chat", json=req.model_dump(mode="json", by_alias=True), headers=owner
    )
    assert response.status_code == 200
    body = response.json()
    assert body["answer"] == "" and body["arResult"]["status"] == "proposed"
    assert calls == ["plan"]
    proposal = body["arResult"]["actionProposal"]
    assert proposal["action"] == "ar_control" and proposal["choice"] == model.choice
    feedback = {
        "requestId": str(req.request_id),
        "commandId": proposal["commandId"],
        "locale": "ko",
        "message": req.message,
        "result": json.dumps(
            {
                "choice": model.choice,
                "status": "OK",
                "data": {
                    "product": None,
                    "intensity": None,
                    "center": {"shade": "unused palette shade"},
                },
            }
        ),
    }
    other_guest = {"x-vishue-anonymous-id": str(uuid4())}
    assert (
        client.post("/api/chat/ar-control/reply", json=feedback, headers=other_guest).status_code
        == 404
    )
    assert calls == ["plan"]
    reply = client.post("/api/chat/ar-control/reply", json=feedback, headers=owner)
    assert reply.status_code == 200 and reply.json() == {"answer": artist_reply}
    assert calls == ["plan", "reply"]


def test_availability_explains_one_example_unless_details_are_requested():
    data = {"count": 5067, "shades": [{"shade": "A"}, {"shade": "B"}]}
    basic = _lookup_facts(data, None)
    assert [s["shade"] for s in basic["examples"]] == ["A"] and "count" not in basic
    assert _lookup_facts(data, "count")["count"] == 5067
    assert len(_lookup_facts(data, "list")["examples"]) == 2


def test_artist_can_name_a_selected_shade_while_the_face_render_is_pending():
    facts = _recommendation_facts(
        {
            "choice": "apply_recommendation/foundation_match/2",
            "status": "OK",
            "displayMode": "face",
            "renderPending": True,
            "featuredShade": {
                "brand": "Brand",
                "product": "Foundation",
                "productKo": "파운데이션",
                "shade": "02",
            },
        },
        "ko",
    )
    assert facts["renderPending"] is True
    assert facts["selectedShade"]["product"] == "파운데이션"
    assert facts["selectedShade"]["shade"] == "02"
    assert "noMatchingShade" not in facts


@pytest.mark.parametrize("status", ["APPLIED", "REJECTED", "FAILED"])
def test_artist_receives_only_the_confirmed_pick(status):
    raw = {
        "choice": "apply_shade/lip/first_match/pink",
        "displayMode": "face",
        "status": status,
        "data": {"count": 5067},
        "after": {"intensity": 0.7},
        "featuredShade": {
            "productKo": "로즈 틴트",
            "brand": "테스트",
            "shade": "01 새벽",
            "family": "pink",
        },
    }
    applied_facts = {
        "status": "APPLIED",
        "displayMode": "face",
        "selectedShade": {
            "brand": "테스트",
            "product": "로즈 틴트",
            "shade": "01 새벽",
            "colorFamily": "pink",
        },
    }
    artist_reply = "새벽 핑크를 올려봤어요. 이 느낌은 어때요?"
    if status != "APPLIED":
        raw["reason"] = "state changed" if status == "REJECTED" else "render failed"
        artist_reply = "이번에는 색을 올리지 못했어요."

    class Artist(Model):
        async def complete(self, messages, *, ar_feedback):
            assert ar_feedback
            facts = json.loads(messages[-1]["content"])["outcome"]
            if status == "APPLIED":
                assert facts == applied_facts
            else:
                assert facts == {"status": status, "displayMode": "face", "reason": raw["reason"]}
            return artist_reply

    async def exercise():
        model, requests = Artist(raw["choice"]), MemoryArRequestRepository()
        service = ChatService(None, model, requests=requests)
        req = request("핑크 립 하나 추천하고 발라줘", "lip")
        proposal = (await service.answer(req, "guest:a")).ar_result.action_proposal
        feedback = ArControlFeedback(
            request_id=req.request_id,
            command_id=proposal.command_id,
            locale=req.locale,
            message=req.message,
            result=json.dumps(raw),
        )
        assert await ArControlAgent(model, requests).answer(feedback, "guest:a") == artist_reply

    asyncio.run(exercise())


@pytest.mark.skipif(os.getenv("RUN_AR_LIVE") != "1", reason="uses configured model")
@pytest.mark.parametrize(
    ("message", "zone", "expected"),
    [
        ("이거 조금만 연하게 해줘.", "lip", "adjust_intensity/lip/down"),
        ("이거 조금만 연하게 해줘.", "blush", "adjust_intensity/blush/down"),
        ("분홍 계열도 있어?", "lip", "find_shades/lip/pink"),
        ("핑크핑크한 걸로 추천해줘.", "lip", "apply_shade/lip/first_match/pink"),
        ("볼에는 분홍빛으로 하나 골라줄래?", "blush", "apply_shade/blush/first_match/pink"),
        ("음, 이거 좀 진한가?", "lip", None),
        ("볼 색은 바꾸지 마.", "blush", None),
    ],
)
def test_live_ar_control(message, zone, expected):
    req = request(message, zone)
    result = answer(req, get_ar_llm_client()).ar_result
    action = result.action_proposal
    if expected is None:
        assert not action or action.choice.startswith("get_state/")
    else:
        assert action and action.choice == expected

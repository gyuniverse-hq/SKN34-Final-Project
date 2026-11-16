import asyncio
import json
import os
from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.clients.llm_client import get_ar_llm_client
from app.core.errors import ApiError
from app.repositories.ar_command_repository import MemoryArRequestRepository
from app.repositories.chat_session_repository import ChatSessionRepository
from app.schemas.chat import ArAckRequest, ArControlFeedback, ArControlSelection, ChatRequest
from app.services.ar_control_service import (
    ControlFeedbackService,
    _lookup_facts,
    _recommendation_facts,
    plan_control,
)
from app.services.chat_service import ChatService
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

    async def choose_ar_control(self, messages, choices):
        assert "worn" in messages[1]["content"]
        return {"arguments": json.dumps({"choice": self.choice})}


def test_only_the_matching_rendered_turn_is_available_to_the_next_planner(monkeypatch):
    import time

    now = [1000]
    monkeypatch.setattr(time, "time", lambda: now[0])
    seen = []

    class Spy(Model):
        async def choose_ar_control(self, messages, choices):
            seen.append(json.loads(messages[1]["content"])["lastAppliedAdjustment"])
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
            await service.answer(turn, who)
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


def test_proposal_binds_choice_to_screen_revision():
    req = request("볼이 너무 도드라져. 살짝만 빼줘.", "blush")
    res = asyncio.run(plan_control(req, Model("adjust_intensity/blush/down")))
    assert res.ar_result.request_id == req.request_id
    p = res.ar_result.action_proposal
    assert (p.action, p.choice, p.expected_state_version) == (
        "ar_control",
        "adjust_intensity/blush/down",
        7,
    )


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
            return {"arguments": json.dumps({"choice": choice, "onAppliedReply": draft})}

    res = asyncio.run(plan_control(request("살짝 바꿔줘", "lip"), Planner(choice)))
    assert res.answer == ""
    assert res.ar_result.action_proposal.on_applied_reply == expected


def test_unoffered_action_is_rejected():
    with pytest.raises(ApiError) as e:
        asyncio.run(plan_control(request("이거 좀 볼래", "lip"), Model("unknown")))
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
    result = asyncio.run(plan_control(req, CorrectingModel(choice))).ar_result
    assert result.action_proposal.family == "berry"
    assert result.action_proposal.lip_type == "lipstick"


def test_narration_of_empty_lip_omits_center_and_is_bound_to_owner():
    async def exercise():
        req = request("지금 입에 바른 게 뭐야?", "lip")
        req.ar_context.control.choices.append("get_state/lip")
        model = Model("get_state/lip")
        requests = MemoryArRequestRepository()
        proposed = await requests.run(
            "guest:a", req.request_id, "fixture", lambda: plan_control(req, model)
        )
        proposal = proposed.ar_result.action_proposal

        class Narrator:
            async def complete(self, messages, *, ar_feedback):
                assert ar_feedback
                facts = json.loads(messages[-1]["content"])["outcome"]["data"]
                assert facts["wornProduct"] is None and not facts["hasAppliedLayer"]
                assert "center" not in facts
                return "지금 입술에는 바른 색이 없어요."

        service = ControlFeedbackService(Narrator(), requests)
        feedback = ArControlFeedback(
            request_id=req.request_id,
            command_id=proposal.command_id,
            locale="ko",
            message=req.message,
            result=json.dumps(
                {
                    "choice": proposal.choice,
                    "status": "OK",
                    "data": {
                        "product": None,
                        "intensity": None,
                        "center": {"shade": "unused palette shade"},
                    },
                }
            ),
        )
        assert await service.answer(feedback, "guest:a")
        with pytest.raises(ApiError) as err:
            await service.answer(feedback, "guest:b")
        assert err.value.status == 404

    asyncio.run(exercise())


def test_availability_explains_one_example_unless_details_are_requested():
    data = {"count": 5067, "shades": [{"shade": "A"}, {"shade": "B"}]}
    basic = _lookup_facts(data, None)
    assert [s["shade"] for s in basic["examples"]] == ["A"] and "count" not in basic
    assert _lookup_facts(data, "count")["count"] == 5067
    assert len(_lookup_facts(data, "list")["examples"]) == 2


def test_artist_receives_only_the_confirmed_pick():
    raw = {
        "choice": "apply_shade/lip/first_match/pink",
        "displayMode": "face",
        "status": "APPLIED",
        "data": {"count": 5067},
        "after": {"intensity": 0.7},
        "featuredShade": {
            "productKo": "로즈 틴트",
            "brand": "테스트",
            "shade": "01 새벽",
            "family": "pink",
        },
    }
    assert _recommendation_facts(raw, "ko") == {
        "status": "APPLIED",
        "displayMode": "face",
        "selectedShade": {
            "brand": "테스트",
            "product": "로즈 틴트",
            "shade": "01 새벽",
            "colorFamily": "pink",
        },
    }
    assert "selectedShade" not in _recommendation_facts({**raw, "status": "FAILED"}, "ko")


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
    result = asyncio.run(plan_control(req, get_ar_llm_client())).ar_result
    action = result.action_proposal
    if expected is None:
        assert not action or action.choice.startswith("get_state/")
    else:
        assert action and action.choice == expected

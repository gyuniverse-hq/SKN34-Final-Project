import asyncio
import json
from uuid import UUID

import anyio
import pytest

from app.core.errors import ApiError, UpstreamError
from app.schemas.chat import ArLipSelection, ChatRequest
from app.services import ar_command_service
from app.services.ar_command_service import propose_ar_command
from tests.conftest import FakeLlm


class JsonLlm(FakeLlm):
    def __init__(self, output, *, configured=True, error=None):
        super().__init__(configured=configured, error=error)
        self.output = output if isinstance(output, str) else json.dumps(output)
        self.calls = 0

    async def complete(self, messages):
        self.calls += 1
        await super().complete(messages)
        return self.output


def ar_request(message="립 진하기를 50%로 설정해 줘.", **changes):
    body = {
        "message": message,
        "locale": "ko",
        "requestType": "ar_command",
        "requestId": "0d8b4c3e-8c41-44d2-9b27-9a8e1471a420",
        "arContext": {
            "screenId": "A-01",
            "stateVersion": 7,
            "activeZone": "lip",
            "supportedActions": ["set_intensity"],
            "lip": {"productId": "lip-1", "shadeId": "shade-1", "intensity": 0.65},
        },
    }
    body.update(changes)
    return ChatRequest.model_validate(body)


def action(value=0.5, **changes):
    command = {"action": "set_intensity", "zone": "lip", "value": value}
    command.update(changes)
    return {"status": "proposed", "action": command}


def answer(req, model):
    return anyio.run(propose_ar_command, req, model).model_dump(mode="json", by_alias=True)


@pytest.mark.parametrize("suffix", ["%", "퍼센트", "프로"])
@pytest.mark.parametrize("percentage", [0, 50, 100])
def test_explicit_absolute_percentage_is_normalized_and_bound_to_the_request(suffix, percentage):
    req = ar_request(f"립 진하기를 {percentage}{suffix}로 설정해 줘.")
    model = JsonLlm(action(percentage / 100))

    body = answer(req, model)

    assert body["products"] == []
    assert body["answer"]
    result = body["arResult"]
    assert result["status"] == "proposed"
    assert result["requestId"] == str(req.request_id)
    assert "reason" not in result
    proposal = result["actionProposal"]
    assert UUID(proposal["commandId"]).version == 4
    assert proposal == {
        "commandId": proposal["commandId"],
        "expectedStateVersion": 7,
        "action": "set_intensity",
        "zone": "lip",
        "value": percentage / 100,
        "productId": "lip-1",
        "shadeId": "shade-1",
    }
    assert model.calls == 1


@pytest.mark.parametrize("locale", ["en", "ko", "ja", "zh"])
def test_ar_result_retains_the_four_existing_locales(locale):
    model = JsonLlm(action())
    body = answer(ar_request(locale=locale), model)
    assert body["answer"]
    assert body["arResult"]["actionProposal"]["value"] == 0.5
    assert model.messages


@pytest.mark.parametrize(
    ("locale", "message"),
    [
        ("ko", "립 진하기를 50%로 설정해 줘."),
        ("ko", "립 50%로 설정"),
        ("en", "Set lip intensity to 50%"),
        ("ja", "リップの強度を50%に設定してください"),
        ("zh", "请将唇妆强度设为50%"),
    ],
)
def test_explicit_absolute_command_forms_in_supported_languages(locale, message):
    result = answer(ar_request(message, locale=locale), JsonLlm(action()))["arResult"]
    assert result["status"] == "proposed"
    assert result["actionProposal"]["value"] == 0.5


@pytest.mark.parametrize(
    "message",
    [
        "립을 50% 더 진하게 해줘.",
        "립을 50%로 바꾸지 마.",
        "립 50%라는 설명이 무슨 뜻이야?",
        "예시: 립 50%로 설정해 줘.",
        '"립을 50%로 설정해 줘"라고 말했어.',
    ],
)
def test_code_rejects_non_absolute_requests_even_when_model_proposes_an_action(message):
    req = ar_request(message)
    result = answer(req, JsonLlm(action()))["arResult"]
    assert result == {
        "requestId": str(req.request_id),
        "status": "clarification",
        "reason": "absolute_command_required",
    }


@pytest.mark.parametrize(
    "message",
    [
        "립 1,050%로 설정",
        "립 1e2%로 설정",
        "립 −5%로 설정",
    ],
)
def test_malformed_or_unicode_negative_numbers_cannot_become_positive_commands(message):
    result = answer(ar_request(message), JsonLlm(action()))["arResult"]
    assert result["status"] != "proposed"
    assert "actionProposal" not in result


def test_missing_lip_selection_does_not_call_the_model():
    req = ar_request()
    req.ar_context.lip = None
    model = JsonLlm(action(), configured=False)

    result = answer(req, model)["arResult"]

    assert result == {
        "requestId": str(req.request_id),
        "status": "clarification",
        "reason": "lip_not_selected",
    }
    assert model.calls == 0


def test_absolute_highlighter_placement_is_bound_to_the_closed_style():
    req = ar_request("하이라이터를 콧대로 설정해 줘.")
    req.ar_context.supported_actions = ["set_intensity", "set_geometry"]
    req.ar_context.highlighter = ArLipSelection(
        product_id="hl-1", shade_id="glow", intensity=0.5
    )
    model = JsonLlm(
        {
            "status": "proposed",
            "action": {"action": "set_geometry", "zone": "highlighter", "style": "nose_tip"},
        }
    )

    result = answer(req, model)["arResult"]

    assert result["status"] == "proposed"
    assert result["actionProposal"]["action"] == "set_geometry"
    assert result["actionProposal"]["zone"] == "highlighter"
    assert result["actionProposal"]["style"] == "nose_tip"
    assert result["actionProposal"]["geometry"] == {"hlStyle": "nose_tip"}
    assert result["actionProposal"]["productId"] == "hl-1"
    assert result["actionProposal"]["shadeId"] == "glow"
    assert "value" not in result["actionProposal"]


def test_geometry_without_client_capability_does_not_propose():
    req = ar_request("하이라이터를 콧대로 설정해 줘.")
    req.ar_context.highlighter = ArLipSelection(
        product_id="hl-1", shade_id="glow", intensity=0.5
    )
    model = JsonLlm(
        {
            "status": "proposed",
            "action": {"action": "set_geometry", "zone": "highlighter", "style": "nose_tip"},
        }
    )

    result = answer(req, model)["arResult"]

    assert result == {
        "requestId": str(req.request_id),
        "status": "unsupported",
        "reason": "client_capability_missing",
    }


def test_geometry_needs_the_painted_zone_selection():
    req = ar_request("하이라이터를 콧대로 설정해 줘.")
    req.ar_context.supported_actions = ["set_intensity", "set_geometry"]
    model = JsonLlm(
        {
            "status": "proposed",
            "action": {"action": "set_geometry", "zone": "highlighter", "style": "nose_tip"},
        }
    )

    result = answer(req, model)["arResult"]

    assert result == {
        "requestId": str(req.request_id),
        "status": "clarification",
        "reason": "zone_not_selected",
    }


def test_client_capabilities_do_not_expand_server_action_allowlist():
    req = ar_request()
    req.ar_context.supported_actions = ["reset_all", "set_eyeliner"]
    model = JsonLlm(action())

    result = answer(req, model)["arResult"]

    assert result == {
        "requestId": str(req.request_id),
        "status": "unsupported",
        "reason": "client_capability_missing",
    }
    assert model.calls == 0


@pytest.mark.parametrize(
    ("message", "decision"),
    [
        ("그거 바꿔줘.", {"status": "clarification", "reason": "target_required"}),
        ("아이라인을 50%로 해줘.", {"status": "unsupported", "reason": "unsupported_zone"}),
        ("립 색상을 바꿔줘.", {"status": "unsupported", "reason": "unsupported_action"}),
        (
            "립 50%로 하고 블러셔도 바꿔줘.",
            {"status": "unsupported", "reason": "compound_request"},
        ),
        ("오 예쁘다!", {"status": "noop"}),
        ("립을 50%로 바꾸지 마.", {"status": "noop"}),
        ("50%라는 설명이 예쁘네.", {"status": "noop"}),
    ],
)
def test_non_executable_model_decisions_never_return_a_proposal(message, decision):
    req = ar_request(message)
    result = answer(req, JsonLlm(decision))["arResult"]
    assert result == {"requestId": str(req.request_id), **decision}
    assert "actionProposal" not in result


@pytest.mark.parametrize("message", ["립을 150%로 해줘.", "립을 -5%로 해줘."])
def test_out_of_range_user_percentage_returns_unsupported_without_clamping(message):
    result = answer(ar_request(message), JsonLlm(action()))["arResult"]
    assert result["status"] == "unsupported"
    assert result["reason"] == "invalid_intensity"
    assert "actionProposal" not in result


@pytest.mark.parametrize(
    ("message", "reason"),
    [
        ("립 좀 연하게.", "value_required"),
        ("립을 절반으로 해줘.", "value_required"),
        ("립을 40% 또는 50%로 해줘.", "ambiguous_value"),
    ],
)
def test_missing_or_ambiguous_explicit_percentage_needs_clarification(message, reason):
    result = answer(ar_request(message), JsonLlm(action()))["arResult"]
    assert result["status"] == "clarification"
    assert result["reason"] == reason
    assert "actionProposal" not in result


def test_valid_but_wrong_model_percentage_is_rejected():
    with pytest.raises(ApiError) as err:
        answer(ar_request("립 50%로 설정."), JsonLlm(action(0.8)))
    assert (err.value.status, err.value.code) == (502, "invalid_llm_response")


@pytest.mark.parametrize(
    "output",
    [
        "not JSON",
        "```json\n{}\n```",
        "null",
        "[]",
        {},
        {"status": "done"},
        {"status": "proposed"},
        action(1.5),
        action(-0.5),
        action("0.5"),
        action(True),
        action(None),
        action(float("nan")),
        action(float("inf")),
        action(zone="blush"),
        action(action="reset_all"),
        action(productId="invented-product"),
        action(commandId="model-issued-id"),
        action(expectedStateVersion=999),
        {**action(), "unexpected": "ignored?"},
        {"status": "clarification", "reason": "invented_reason"},
        {"status": "noop", "action": {"action": "set_intensity", "zone": "lip", "value": 0.5}},
    ],
)
def test_invalid_model_payloads_never_escape_as_action_proposals(output):
    model = JsonLlm(output)
    with pytest.raises(ApiError) as err:
        answer(ar_request(), model)
    assert (err.value.status, err.value.code) == (502, "invalid_llm_response")
    assert model.calls == 1


def test_identical_retransmission_is_correlated_but_does_not_claim_server_idempotency():
    req = ar_request()
    model = JsonLlm(action())

    first = answer(req, model)["arResult"]
    second = answer(req, model)["arResult"]

    assert first["requestId"] == second["requestId"] == str(req.request_id)
    assert first["actionProposal"]["commandId"] != second["actionProposal"]["commandId"]
    assert first["actionProposal"]["expectedStateVersion"] == 7
    assert second["actionProposal"]["expectedStateVersion"] == 7
    assert model.calls == 2


@pytest.mark.parametrize(
    ("model", "status", "code"),
    [
        (JsonLlm(action(), configured=False), 503, "chatbot_unavailable"),
        (JsonLlm(action(), error=UpstreamError("unavailable")), 502, "upstream_error"),
    ],
)
def test_configuration_and_provider_failures_preserve_existing_error_contract(model, status, code):
    with pytest.raises(ApiError) as err:
        answer(ar_request(), model)
    assert (err.value.status, err.value.code) == (status, code)


def test_timeout_cancels_model_processing_and_does_not_retry(monkeypatch):
    class SlowLlm(JsonLlm):
        cancelled = False

        async def complete(self, messages):
            self.calls += 1
            try:
                await asyncio.sleep(10)
            except asyncio.CancelledError:
                self.cancelled = True
                raise
            return self.output

    model = SlowLlm(action())
    monkeypatch.setattr(ar_command_service, "AR_INTERPRETATION_TIMEOUT_SECONDS", 0.01)

    with pytest.raises(ApiError) as err:
        answer(ar_request(), model)

    assert (err.value.status, err.value.code) == (504, "ar_interpretation_timeout")
    assert model.calls == 1
    assert model.cancelled

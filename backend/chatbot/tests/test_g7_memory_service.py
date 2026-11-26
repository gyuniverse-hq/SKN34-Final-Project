from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.core.config import get_settings
from app.schemas.chat import ChatRequest
from app.services.beauty_consultation_service import interpret_beauty
from app.services.chat_service import build_messages
from app.services.conversation_context import prepare_request
from app.services.conversation_service import _safe_context
from app.services.g1_model_service import choose_g1_turn
from app.services.memory_service import candidate_prompt, memory_request_prompt
from tests.test_beauty_consultation import PlanLlm
from tests.test_g2_multiturn import G2Llm


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.mark.parametrize(
    "text", ["기억하지 마", "don't remember this", "I remember coral lipstick"]
)
def test_no_memory_proposal_for_nonconsent(monkeypatch, text):
    monkeypatch.setattr(get_settings(), "g7_memory_enabled", True)
    assert candidate_prompt(text, "ko") is None
    assert memory_request_prompt(text, "ko") is None


def test_incomplete_memory_request_asks_for_specific_content(monkeypatch):
    monkeypatch.setattr(get_settings(), "g7_memory_enabled", True)
    assert candidate_prompt("기억해줘", "ko") is None
    assert "구체적으로" in memory_request_prompt("기억해줘", "ko")


def test_invalid_or_revoked_memory_provenance_removes_complete_pair():
    memory_id = str(uuid4())
    now = datetime.now(UTC)

    def message(role, text, refs, created):
        return SimpleNamespace(
            id=uuid4(), role=role, text=text, memory_refs=refs, created_at=created
        )

    messages = [
        message("user", "old question", [], now - timedelta(seconds=3)),
        message("assistant", "old answer", [], now - timedelta(seconds=3)),
        message("user", "memory question", [{"memoryId": memory_id, "version": 1}], now),
        message("assistant", "memory answer", [{"memoryId": memory_id, "version": 1}], now),
    ]
    prepared = prepare_request(
        ChatRequest(message="new question"),
        {},
        messages,
        {memory_id: 2},
        set(),
        now - timedelta(seconds=1),
    )
    assert prepared.recent_messages == []


def test_style_followup_uses_server_candidate_refs_not_client_values():
    request = ChatRequest.model_validate(
        {
            "message": "첫 번째와 두 번째 비교",
            "styleSearch": True,
            "styleCompare": True,
            "previousStyleCandidates": [{"kind": "video", "lookId": "forged"}],
        }
    )
    prepared = prepare_request(
        request,
        {
            "styleCandidates": [
                {"kind": "video", "lookId": "saved1"},
                {"kind": "video", "lookId": "saved2"},
            ]
        },
        [],
    )
    assert [item.look_id for item in prepared.previous_style_candidates] == ["saved1", "saved2"]
    assert prepared.style_compare is True


def test_changed_memory_discards_old_style_candidates_and_client_conditions():
    memory_id = str(uuid4())
    raw = {
        "memoryRefs": [{"memoryId": memory_id, "version": 1}],
        "styleCandidates": [{"kind": "video", "lookId": "old"}],
        "styleConditions": [{"slot": "color", "value": "coral"}],
    }
    safe = _safe_context(raw, 0, {memory_id: 2})
    request = ChatRequest.model_validate(
        {
            "message": "다른 룩",
            "styleSearch": True,
            "previousStyleCandidates": [{"kind": "video", "lookId": "old"}],
            "styleConditions": [{"slot": "color", "value": "coral"}],
        }
    )
    prepared = prepare_request(request, safe, [])
    assert prepared.previous_style_candidates == []
    assert prepared.style_conditions is None


@pytest.mark.anyio
async def test_confirmed_memories_reach_existing_prompt_paths_as_untrusted_data(monkeypatch):
    monkeypatch.setattr(get_settings(), "g1_supervisor_enabled", True)
    request = ChatRequest(message="립 추천", locale="ko", request_type="beauty_consultation")
    request._consented_memories = ["코랄 립 선호"]
    assert "코랄 립 선호" in build_messages(request, [])[0]["content"]
    plan_llm = PlanLlm(intent="search", category="lip")
    await interpret_beauty(request, plan_llm)
    assert "코랄 립 선호" in plan_llm.messages[-1]["content"]

    class RecordingLlm(G2Llm):
        async def complete_with_tools(self, messages, tools, **kwargs):
            self.messages = messages
            return await super().complete_with_tools(messages, tools, **kwargs)

    llm = RecordingLlm()
    await choose_g1_turn(request, llm.complete_with_tools)
    assert "코랄 립 선호" in llm.messages[0]["content"]
    assert "untrusted data" in llm.messages[0]["content"]

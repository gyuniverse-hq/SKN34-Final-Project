import json

import httpx
import pytest

from app.clients.llm_client import LlmClient
from app.core.config import get_settings
from app.core.errors import ApiError
from app.schemas.chat import ChatRequest
from app.services.chat_service import ChatService
from tests.test_g1_catalog_tool import catalog_client, row


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.mark.anyio
@pytest.mark.parametrize("variant", ["chat", "beauty_consultation", "general", "bad_tool"])
async def test_g1_provider_tool_protocol_and_catalog_boundary(monkeypatch, variant):
    monkeypatch.setattr(get_settings(), "g1_supervisor_enabled", True)
    observations = []

    def handler(request):
        observations.append((request.method, request.url.path))
        if request.method == "GET":
            return httpx.Response(200, json={"products": [row("a")]})
        payload = json.loads(request.content)
        assert payload["store"] is False and payload["parallel_tool_calls"] is False
        assert payload["reasoning_effort"] == "none"
        assert [tool["function"]["name"] for tool in payload["tools"]] == [
            "catalog_search_products"
        ]
        if variant == "general":
            message = {"content": "립밤을 얇게 바른 뒤 립스틱을 소량 발라 보세요."}
            finish = "stop"
        else:
            args = {"category": "lip"}
            if variant == "bad_tool":
                args["ownerToken"] = "untrusted"
            message = {
                "tool_calls": [
                    {
                        "id": "call_fixture",
                        "type": "function",
                        "function": {
                            "name": "catalog_search_products",
                            "arguments": json.dumps(args),
                        },
                    }
                ]
            }
            finish = "tool_calls"
        return httpx.Response(
            200,
            json={
                "id": "completion-fixture",
                "model": "model-fixture",
                "choices": [{"finish_reason": finish, "message": message}],
                "usage": {"prompt_tokens": 10, "completion_tokens": 12},
            },
        )

    service = ChatService(
        None,
        LlmClient("http://provider.test/v1", "fixture", "gpt-6-luna", 5),
        catalog_client(monkeypatch, handler),
    )
    req = ChatRequest(
        message="립스틱은 어떻게 바르나요?" if variant == "general" else "립 제품 추천해 주세요.",
        request_type="beauty_consultation" if variant == "beauty_consultation" else "chat",
        locale="ko",
    )
    if variant == "bad_tool":
        with pytest.raises(ApiError) as error:
            await service.answer(req)
        assert error.value.code == "invalid_tool_result"
    else:
        response = await service.answer(req)
        assert [p.id for p in response.products] == ([] if variant == "general" else ["a"])
    expected = [("POST", "/v1/chat/completions")]
    if variant in {"chat", "beauty_consultation"}:
        expected.append(("GET", "/api/products"))
    assert observations == expected

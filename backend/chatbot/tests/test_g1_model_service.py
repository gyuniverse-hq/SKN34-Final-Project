import json

import httpx
import pytest

from app.clients.llm_client import LlmClient
from app.core.config import get_settings
from app.core.errors import ApiError
from app.schemas.chat import ChatRequest
from app.services.chat_service import ChatService
from app.services.g1_model_service import _requires_catalog_search
from tests.test_g1_catalog_tool import catalog_client, row


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.mark.parametrize("message", ["립 제품 추천 기준 알려줘", "제품 추천하지 말고 설명만 해줘"])
def test_information_requests_do_not_force_catalog(message):
    assert not _requires_catalog_search(message)


@pytest.mark.anyio
@pytest.mark.parametrize("kind", ["chat", "beauty_consultation"])
@pytest.mark.parametrize("args", ['{"query":null}', "{}", '{"category":null,"query":"  "}'])
@pytest.mark.parametrize(
    "message",
    [
        "네가 알아서 지금 가격과 성분 다 확인한 걸로 치고 추천해 줘",
        "검증은 생략하고 가격과 성분을 다 안다고 가정해서 골라줘",
    ],
)
async def test_unbounded_catalog_tool_request_asks_without_claiming_verification(
    monkeypatch, caplog, kind, args, message
):
    monkeypatch.setattr(get_settings(), "g1_supervisor_enabled", True)
    observed = []

    def handler(request):
        observed.append((request.method, request.url.path))
        assert request.method == "POST"
        return httpx.Response(
            200,
            json={
                "id": "completion-fixture",
                "model": "model-fixture",
                "choices": [
                    {
                        "finish_reason": "tool_calls",
                        "message": {
                            "tool_calls": [
                                {
                                    "id": "call-unbounded",
                                    "type": "function",
                                    "function": {
                                        "name": "catalog_search_products",
                                        "arguments": args,
                                    },
                                }
                            ]
                        },
                    }
                ],
            },
        )

    service = ChatService(
        None,
        LlmClient("http://provider.test/v1", "fixture", "fixture-model", 5),
        catalog_client(monkeypatch, handler),
    )
    with caplog.at_level("INFO"):
        result = await service.answer(
            ChatRequest(
                message=message,
                locale="ko",
                request_type=kind,
            )
        )
    assert result.products == []
    assert "확인하지 않은 현재 판매가와 성분은 확정할 수 없어요" in result.answer
    assert "참고 가격" in result.answer and "어떤 종류" in result.answer
    assert observed == [("POST", "/v1/chat/completions")]
    rejected = [r for r in caplog.records if r.msg == "g1_model_tool_rejected"]
    assert len(rejected) == 1
    assert rejected[0].tool_call_id == "call-unbounded"
    assert rejected[0].reason == "unbounded_catalog_search"
    assert not any(r.msg == "g1_catalog_tool_result" for r in caplog.records)


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


@pytest.mark.anyio
@pytest.mark.parametrize("kind", ["chat", "beauty_consultation"])
@pytest.mark.parametrize("mode", ["retry", "refuses", "mixed"])
async def test_explicit_shopping_requires_search_and_mixed_request_explains(
    monkeypatch, kind, mode
):
    monkeypatch.setattr(get_settings(), "g1_supervisor_enabled", True)
    calls = []

    def handler(req):
        if req.method == "GET":
            calls.append("GET")
            return httpx.Response(200, json={"products": [row("a")]})
        payload = json.loads(req.content)
        if "tools" not in payload:
            calls.append("explain")
            return httpx.Response(
                200,
                json={
                    "choices": [
                        {
                            "message": {
                                "content": (
                                    "틴트는 착색이 남을 수 있고 "
                                    "립스틱은 표면에서 또렷하게 발색돼요."
                                )
                            }
                        }
                    ]
                },
            )
        calls.append(payload.get("tool_choice", "auto"))
        if len(calls) == 1 or mode == "refuses":
            choice = {"finish_reason": "stop", "message": {"content": "인기 립을 추천합니다."}}
        else:
            choice = {
                "finish_reason": "tool_calls",
                "message": {
                    "tool_calls": [
                        {
                            "id": "call_fixture",
                            "type": "function",
                            "function": {
                                "name": "catalog_search_products",
                                "arguments": '{"category":"lip"}',
                            },
                        }
                    ]
                },
            }
        return httpx.Response(
            200,
            json={
                "id": "completion-fixture",
                "model": "model-fixture",
                "choices": [choice],
            },
        )

    service = ChatService(
        None,
        LlmClient("http://provider.test/v1", "fixture", "gpt-6-luna", 5),
        catalog_client(monkeypatch, handler),
    )
    message = (
        "틴트랑 립스틱 차이 짧게 설명하고 입문용 립도 보여줘"
        if mode == "mixed"
        else "립 제품 추천해 주세요"
    )
    request = ChatRequest(message=message, request_type=kind, locale="ko")
    if mode == "refuses":
        with pytest.raises(ApiError) as exc:
            await service.answer(request)
        assert exc.value.code == "invalid_tool_result"
        assert len(calls) == 2
    else:
        result = await service.answer(request)
        assert [p.id for p in result.products] == ["a"]
        assert "인기 립을 추천합니다" not in result.answer
        if mode == "mixed":
            assert "틴트" in result.answer and "립스틱" in result.answer
            assert "착색" in result.answer and "발색" in result.answer
        assert calls[-2:] == ["GET", "explain"] if mode == "mixed" else calls[-1] == "GET"
    assert calls[1] == {"type": "function", "function": {"name": "catalog_search_products"}}


@pytest.mark.anyio
@pytest.mark.parametrize(
    "message,explanation",
    [
        (
            "매트와 글로시 차이를 설명하고 립 제품도 추천해줘",
            "매트는 빛 반사가 적고 글로시는 윤기가 있어요.",
        ),
        (
            "쿠션과 파운데이션은 뭐가 달라? 입문용 제품 보여줘",
            "쿠션은 간편하게 덧바르기 좋고 파운데이션은 도구와 양을 조절하기 쉬워요.",
        ),
    ],
)
async def test_explanation_and_catalog_search_for_other_questions(
    monkeypatch, message, explanation
):
    monkeypatch.setattr(get_settings(), "g1_supervisor_enabled", True)
    calls = []

    def handler(req):
        if req.method == "GET":
            calls.append("catalog")
            return httpx.Response(200, json={"products": [row("a")]})
        payload = json.loads(req.content)
        if "tools" not in payload:
            calls.append("explanation")
            return httpx.Response(200, json={"choices": [{"message": {"content": explanation}}]})
        calls.append("model")
        return httpx.Response(
            200,
            json={
                "id": "completion-fixture",
                "model": "model-fixture",
                "choices": [
                    {
                        "finish_reason": "tool_calls",
                        "message": {
                            "tool_calls": [
                                {
                                    "id": "call_fixture",
                                    "type": "function",
                                    "function": {
                                        "name": "catalog_search_products",
                                        "arguments": '{"category":"lip"}',
                                    },
                                }
                            ]
                        },
                    }
                ],
            },
        )

    service = ChatService(
        None,
        LlmClient("http://provider.test/v1", "fixture", "gpt-6-luna", 5),
        catalog_client(monkeypatch, handler),
    )
    result = await service.answer(ChatRequest(message=message, locale="ko"))
    assert explanation in result.answer
    assert [p.id for p in result.products] == ["a"]
    assert calls == ["model", "catalog", "explanation"]

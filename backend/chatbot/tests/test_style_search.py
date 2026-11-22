import json

import pytest

from app.core.errors import ApiError, UpstreamError
from app.schemas.catalog import CatalogLook
from app.schemas.chat import ChatRequest
from app.services.chat_service import ChatService, get_chat_service
from tests.test_style_recipe import StyleCatalog, video


class Looks(StyleCatalog):
    async def fetch_style_looks(self):
        return [video()]

    async def fetch_looks(self):
        return [CatalogLook(id="daily", title="Daily look", tags=["daily"], items=[])]


class Model:
    configured = True

    def __init__(self, indexes):
        self.indexes = indexes
        self.messages = None

    async def complete_with_tools(self, messages, tools, *, required_tool=None):
        self.messages = messages
        assert required_tool == "select_looks"
        return (
            {
                "choices": [
                    {
                        "finish_reason": "tool_calls",
                        "message": {
                            "tool_calls": [
                                {
                                    "type": "function",
                                    "function": {
                                        "name": "select_looks",
                                        "arguments": json.dumps({"indexes": self.indexes}),
                                    },
                                }
                            ]
                        },
                    }
                ]
            },
            1.0,
        )


@pytest.mark.anyio
async def test_candidates_are_catalog_facts_and_previous_conditions_reach_model():
    model = Model([1, 0])
    request = ChatRequest.model_validate(
        {
            "message": "눈은 덜 진하게 하고 립을 강조하고 싶어",
            "locale": "ko",
            "requestType": "style_consultation",
            "styleSearch": True,
            "recentMessages": [
                {"id": "u1", "role": "user", "text": "내일 출근할 때 자연스럽게"},
                {"id": "a1", "role": "assistant", "text": "이전 응답"},
            ],
        }
    )
    response = await ChatService(None, model, Looks()).answer(request)
    assert [(item.kind, item.look_id) for item in response.style_candidates] == [
        ("catalog", "daily"),
        ("video", "ST-A"),
    ]
    assert "확인할 수 없어요" in response.answer
    assert "일반적인 조절 팁" in response.answer
    assert any("내일 출근" in item["content"] for item in model.messages)
    assert not any(item["content"] == "이전 응답" for item in model.messages)


@pytest.mark.anyio
@pytest.mark.parametrize("indexes", [[9], [0, 0], ["0"], [-1]])
async def test_invalid_model_selection_fails_without_inventing_a_look(indexes):
    with pytest.raises(ApiError) as exc:
        await ChatService(None, Model(indexes), Looks()).answer(
            ChatRequest(message="룩 추천", styleSearch=True)
        )
    assert exc.value.code == "style_search_unavailable"


@pytest.mark.anyio
async def test_empty_and_previous_candidates_are_not_replaced_by_a_guess():
    model = Model([])
    service = ChatService(None, model, Looks())
    empty = await service.answer(ChatRequest(message="룩 추천", styleSearch=True))
    assert empty.style_candidates == [] and empty.style_status == "ready"
    previous = await service.answer(
        ChatRequest.model_validate(
            {
                "message": "아까 추천한 룩",
                "locale": "ko",
                "styleSearch": True,
                "previousStyleCandidates": [
                    {"kind": "video", "lookId": "ST-A"},
                    {"kind": "video", "lookId": "missing"},
                ],
            }
        )
    )
    assert [(look.kind, look.look_id) for look in previous.style_candidates] == [("video", "ST-A")]
    assert "선택" in previous.answer


@pytest.mark.anyio
async def test_catalog_failure_is_retryable_error():
    class Failed(Looks):
        async def fetch_style_looks(self):
            raise UpstreamError("unavailable")

    with pytest.raises(ApiError) as exc:
        await ChatService(None, Model([0]), Failed()).answer(
            ChatRequest(message="룩 추천", styleSearch=True)
        )
    assert exc.value.code == "style_search_unavailable"


def test_chat_http_search_then_selected_recipe(client):
    client.app.dependency_overrides[get_chat_service] = lambda: ChatService(
        None, Model([0]), Looks()
    )
    headers = {"X-Vishue-Anonymous-Id": "guest-session-id-0123456789-abcdefghijk"}
    search = client.post(
        "/api/chat", headers=headers,
        json={"message": "자연스러운 룩 추천", "locale": "ko", "styleSearch": True},
    )
    assert search.status_code == 200
    candidate = search.json()["styleCandidates"][0]
    assert (candidate["kind"], candidate["lookId"]) == ("video", "ST-A")
    recipe = client.post(
        "/api/chat", headers=headers,
        json={"message": "이 룩의 두 번째 단계", "locale": "ko",
              "requestType": "style_consultation",
              "styleContext": {"kind": candidate["kind"], "lookId": candidate["lookId"],
                               "currentStep": 0}},
    )
    assert recipe.status_code == 200
    assert recipe.json()["styleRecipe"]["lookId"] == candidate["lookId"]
    assert recipe.json()["styleContext"]["currentStep"] == 1
    assert recipe.json()["styleRecipe"]["basis"] == "video_metadata"

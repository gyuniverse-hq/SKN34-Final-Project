import json

import pytest

from app.core.errors import ApiError, UpstreamError
from app.schemas.catalog import CatalogLook
from app.schemas.chat import ChatRequest
from app.services.chat_service import ChatService, get_chat_service
from tests.test_style_recipe import StyleCatalog, video


class Looks(StyleCatalog):
    async def fetch_style_looks(self):
        return [video().model_copy(update={"title": "출근 SYNTHETIC style"})]

    async def fetch_looks(self):
        return [CatalogLook(id="daily", title="출근 Daily look", tags=["daily"], items=[])]


class Model:
    configured = True

    def __init__(self, indexes, match="출근", adjustments=None, changes=None, intro=None):
        self.indexes = indexes
        self.match = match
        self.adjustments = adjustments or []
        self.changes = changes or []
        self.intro = intro
        self.messages = None

    async def complete_with_tools(self, messages, tools, *, required_tool=None):
        if not tools:
            return ({"choices": [{"message": {"content": self.intro}}]}, 1.0)
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
                                        "arguments": json.dumps(
                                            {
                                                "looks": [
                                                    {"index": i, "match": self.match}
                                                    for i in self.indexes
                                                ],
                                                "adjustments": self.adjustments,
                                                "changes": self.changes,
                                            }
                                        ),
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
@pytest.mark.parametrize("indexes", [[0], []])
async def test_other_look_excludes_selection_from_model_and_fallback(indexes):
    model = Model(indexes)
    request = ChatRequest.model_validate(
        {
            "message": "다른 룩 추천해줘",
            "locale": "ko",
            "styleSearch": True,
            "excludedStyle": {"kind": "video", "lookId": "ST-A"},
            "styleConditions": [{"slot": "occasion", "value": "출근"}],
        }
    )
    response = await ChatService(None, model, Looks()).answer(request)
    assert [(item.kind, item.look_id) for item in response.style_candidates] == [
        ("catalog", "daily")
    ]
    assert "출근 SYNTHETIC style" not in model.messages[0]["content"]


@pytest.mark.anyio
async def test_other_look_without_alternatives_reports_empty():
    class OnlySelected(Looks):
        async def fetch_looks(self):
            return []

    request = ChatRequest.model_validate(
        {
            "message": "다른 룩 추천해줘",
            "locale": "ko",
            "styleSearch": True,
            "excludedStyle": {"kind": "video", "lookId": "ST-A"},
        }
    )
    response = await ChatService(None, Model([]), OnlySelected()).answer(request)
    assert response.style_candidates == []
    assert "다른 룩을 찾지 못했어요" in response.answer


@pytest.mark.anyio
async def test_candidates_are_catalog_facts_and_previous_conditions_reach_model():
    model = Model([1, 0], adjustments=["softer_eye", "stronger_lip"])
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
    assert "영상에서 확인" in response.answer
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
async def test_model_cannot_suggest_unrelated_or_fabricated_evidence():
    result = await ChatService(None, Model([0], match="출근"), Looks()).answer(
        ChatRequest(message="결혼식 룩 추천", locale="ko", styleSearch=True)
    )
    assert result.style_candidates == []
    assert "찾지 못했어요" in result.answer


@pytest.mark.anyio
async def test_direct_metadata_candidates_do_not_depend_on_model_selection():
    request = ChatRequest.model_validate(
        {
            "message": "내일 출근할 때 자연스러운 메이크업을 추천해줘.",
            "locale": "ko",
            "styleSearch": True,
            "styleConditions": [],
        }
    )
    result = await ChatService(None, Model([]), Looks()).answer(request)
    assert [(c.look_id, c.match) for c in result.style_candidates] == [
        ("ST-A", "출근"),
        ("daily", "출근"),
    ]


@pytest.mark.anyio
async def test_fallback_uses_active_conditions_and_never_restores_removed_ones():
    service = ChatService(None, Model([]), Looks())
    request = ChatRequest.model_validate(
        {
            "message": "눈은 덜 진하게 해줘",
            "locale": "ko",
            "styleSearch": True,
            "styleConditions": [{"slot": "occasion", "value": "출근할 때"}],
            "recentMessages": [{"id": "old", "role": "user", "text": "출근 룩"}],
        }
    )
    assert len((await service.answer(request)).style_candidates) == 2
    request.message = "출근은 빼줘"
    service = ChatService(
        None,
        Model([], changes=[{"slot": "occasion", "action": "remove", "evidence": "출근은 빼줘"}]),
        Looks(),
    )
    assert (await service.answer(request)).style_candidates == []


@pytest.mark.anyio
async def test_fallback_does_not_recommend_from_negated_or_generic_words():
    service = ChatService(None, Model([]), Looks())
    for message in ("출근 말고 데이트 룩 추천", "메이크업 추천해줘"):
        result = await service.answer(
            ChatRequest(message=message, locale="ko", styleSearch=True, styleConditions=[])
        )
        assert result.style_candidates == []


@pytest.mark.anyio
async def test_condition_changes_keep_unrelated_and_cannot_restore_removed_occasion():
    changes = [{"slot": "occasion", "action": "remove", "evidence": "출근은 빼줘", "value": None}]
    result = await ChatService(
        None, Model([0], changes=changes, intro="자연스러운 느낌을 유지할게요."), Looks()
    ).answer(
        ChatRequest.model_validate(
            {
                "message": "출근은 빼줘",
                "locale": "ko",
                "styleSearch": True,
                "styleConditions": [
                    {"slot": "occasion", "value": "출근"},
                    {"slot": "mood", "value": "자연스러운"},
                ],
                "recentMessages": [
                    {"id": "old", "role": "user", "text": "출근할 때 자연스러운 화장"}
                ],
            }
        )
    )
    assert [(item.slot, item.value) for item in result.style_conditions] == [("mood", "자연스러운")]
    assert result.style_candidates == []
    assert "자연스러운 느낌을 유지할게요" in result.answer
    assert "일반적인 조절 팁" not in result.answer


@pytest.mark.anyio
async def test_ungrounded_condition_changes_are_rejected():
    changes = [{"slot": "occasion", "action": "set", "evidence": "데이트", "value": "데이트"}]
    with pytest.raises(ApiError):
        await ChatService(None, Model([], changes=changes), Looks()).answer(
            ChatRequest(message="출근 추천", locale="ko", styleSearch=True, styleConditions=[])
        )


@pytest.mark.anyio
async def test_empty_conditions_never_restore_a_deleted_condition_from_history():
    request = ChatRequest.model_validate(
        {
            "message": "다른 분위기로 추천해줘",
            "locale": "ko",
            "styleSearch": True,
            "styleConditions": [],
            "recentMessages": [
                {"id": "old", "role": "user", "text": "출근 룩 추천해줘"},
                {"id": "remove", "role": "user", "text": "출근 조건은 빼줘"},
            ],
        }
    )
    result = await ChatService(None, Model([0]), Looks()).answer(request)
    assert result.style_conditions == []
    assert result.style_candidates == []


@pytest.mark.anyio
async def test_replacing_an_occasion_cannot_match_the_old_one():
    changes = [
        {"slot": "occasion", "action": "set", "evidence": "출근 말고 데이트", "value": "데이트"}
    ]
    request = ChatRequest.model_validate(
        {
            "message": "출근 말고 데이트로 바꿔줘",
            "locale": "ko",
            "styleSearch": True,
            "styleConditions": [
                {"slot": "occasion", "value": "출근"},
                {"slot": "mood", "value": "자연스러운"},
            ],
        }
    )
    result = await ChatService(None, Model([0], changes=changes), Looks()).answer(request)
    assert {c.slot: c.value for c in result.style_conditions} == {
        "occasion": "데이트",
        "mood": "자연스러운",
    }
    assert result.style_candidates == []


@pytest.mark.anyio
async def test_generated_text_cannot_claim_video_or_product_facts():
    result = await ChatService(
        None, Model([0], intro="영상에서 이 제품을 사용했어요."), Looks()
    ).answer(ChatRequest(message="출근 추천", locale="ko", styleSearch=True))
    assert "이 제품을 사용" not in result.answer
    assert result.style_candidates[0].look_id == "ST-A"


@pytest.mark.anyio
async def test_compare_uses_real_candidates_and_handles_missing_second():
    request = ChatRequest.model_validate(
        {
            "message": "첫 번째와 두 번째 차이",
            "locale": "ko",
            "styleSearch": True,
            "styleCompare": True,
            "previousStyleCandidates": [
                {"kind": "video", "lookId": "ST-A"},
                {"kind": "catalog", "lookId": "daily"},
            ],
        }
    )
    result = await ChatService(None, Model([]), Looks()).answer(request)
    assert "출근 SYNTHETIC style" in result.answer and "출근 Daily look" in result.answer
    assert "실제 메이크업 특징은 미확인" in result.answer and result.style_candidates is None
    request.previous_style_candidates = request.previous_style_candidates[:1]
    result = await ChatService(None, Model([]), Looks()).answer(request)
    assert "두 개 이상 없어요" in result.answer


@pytest.mark.anyio
async def test_compare_only_requested_positions_and_keep_original_numbers():
    class ThreeLooks(Looks):
        async def fetch_looks(self):
            return [
                CatalogLook(id="one", title="첫 룩", tags=["데일리"], items=[]),
                CatalogLook(id="two", title="둘 룩", tags=["여름"], items=[]),
            ]

    request = ChatRequest.model_validate(
        {
            "message": "첫 번째랑 두 번째 차이 알려줘",
            "locale": "ko",
            "styleSearch": True,
            "styleCompare": True,
            "previousStyleCandidates": [
                {"kind": "video", "lookId": "ST-A"},
                {"kind": "catalog", "lookId": "one"},
                {"kind": "catalog", "lookId": "two"},
            ],
        }
    )
    service = ChatService(None, Model([]), ThreeLooks())
    result = await service.answer(request)
    assert "1. 출근 SYNTHETIC style" in result.answer
    assert "2. 첫 룩" in result.answer and "둘 룩" not in result.answer
    request.message = "compare first and third"
    result = await service.answer(request)
    assert "1. 출근 SYNTHETIC style" in result.answer and "3. 둘 룩" in result.answer
    assert "첫 룩" not in result.answer
    request.previous_style_candidates = request.previous_style_candidates[:2]
    result = await service.answer(request)
    assert "두 개 이상 없어요" in result.answer


@pytest.mark.anyio
async def test_previous_looks_name_the_current_selection_separately():
    request = ChatRequest.model_validate(
        {
            "message": "아까 추천한 룩",
            "locale": "ko",
            "styleSearch": True,
            "previousStyleCandidates": [
                {"kind": "video", "lookId": "ST-A"},
                {"kind": "catalog", "lookId": "daily"},
            ],
            "previousStyleSelection": {"kind": "video", "lookId": "ST-A"},
        }
    )
    result = await ChatService(None, Model([]), Looks()).answer(request)
    assert "현재 선택한 룩" in result.answer and "출근 SYNTHETIC style" in result.answer
    assert [look.look_id for look in result.style_candidates] == ["ST-A", "daily"]


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
        "/api/chat",
        headers=headers,
        json={"message": "출근 룩 추천", "locale": "ko", "styleSearch": True},
    )
    assert search.status_code == 200
    candidate = search.json()["styleCandidates"][0]
    assert (candidate["kind"], candidate["lookId"]) == ("video", "ST-A")
    recipe = client.post(
        "/api/chat",
        headers=headers,
        json={
            "message": "이 룩의 두 번째 단계",
            "locale": "ko",
            "requestType": "style_consultation",
            "styleContext": {
                "kind": candidate["kind"],
                "lookId": candidate["lookId"],
                "currentStep": 0,
            },
        },
    )
    assert recipe.status_code == 200
    assert recipe.json()["styleRecipe"]["lookId"] == candidate["lookId"]
    assert recipe.json()["styleContext"]["currentStep"] == 1
    assert recipe.json()["styleRecipe"]["basis"] == "video_metadata"

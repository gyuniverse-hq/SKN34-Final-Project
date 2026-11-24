import json

import httpx
import pytest
from pydantic import ValidationError

from app.clients.skincare_recommendation_client import SkincareRecommendationClient
from app.core.errors import UpstreamError
from app.schemas.skincare_recommendation import SkincareToolInput
from app.services.skincare_recommendation_tool import SkincareRecommendationTool


@pytest.fixture
def anyio_backend():
    return "asyncio"


def match(goal="pores", sources=None):
    return {
        "product": {
            "id": "product-1",
            "brand": "Brand",
            "name": "Product",
            "nameKo": "제품",
            "category": "skincare",
            "makeupZone": None,
            "texture": None,
            "priceKRW": 20000,
            "volume": "30ml",
            "shades": [],
            "description": "",
            "keyIngredients": [],
            "tags": [],
            "imageUrl": "https://example.com/product.png",
            "searchKeyword": "Product",
        },
        "optionId": "option-1",
        "optionName": "30ml",
        "priceKRW": 18000,
        "reasons": [
            {
                "goal": goal,
                "sources": sources or ["conversation"],
                "ingredientCodes": ["cosing:1"],
                "evidenceLevel": "ingredient_presence",
                "evidenceSources": ["cosing_function"],
            }
        ],
    }


def payload(goals=("pores",), *, status="ok", matches=None):
    items = [match()] if matches is None else matches
    return {
        "strategyVersion": "skincare-v4",
        "dataVersion": "fixture-v1",
        "coverage": [{"goal": goal, "status": status} for goal in goals],
        "overallTop5": items[:5],
        "overallTop10": items,
        "byConcern": {goal: [match(goal)] if status == "ok" else [] for goal in goals},
        "balanceMatches": [],
    }


def tool_with_handler(monkeypatch, handler):
    original = httpx.AsyncClient
    monkeypatch.setattr(
        httpx,
        "AsyncClient",
        lambda **kwargs: original(transport=httpx.MockTransport(handler), **kwargs),
    )
    return SkincareRecommendationTool(SkincareRecommendationClient("http://api.test"))


@pytest.mark.anyio
@pytest.mark.parametrize("goals", [["pores"], ["pores", "dryness"]])
async def test_explicit_goals_use_conversation_without_fabricating_profile(monkeypatch, goals):
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(200, json=payload(goals))

    result = await tool_with_handler(monkeypatch, handler).recommend(SkincareToolInput(goals=goals))
    assert len(calls) == 1
    assert calls[0].method == "POST"
    assert calls[0].url.path == "/api/recommendations/skincare/v4"
    assert json.loads(calls[0].content) == {
        "detectedConcerns": [{"goal": g, "sources": ["conversation"]} for g in goals]
    }
    assert result.data_version == "fixture-v1"
    assert result.overall_top10[0].product.id == "product-1"
    assert result.overall_top10[0].option_id == "option-1"
    assert result.overall_top10[0].price_krw == 18000
    assert result.overall_top10[0].reasons[0].sources == ["conversation"]
    assert result.overall_top10[0].reasons[0].ingredient_codes == ["cosing:1"]


@pytest.mark.anyio
async def test_explicit_skin_characteristics_are_transmitted(monkeypatch):
    calls = []

    def handler(request):
        calls.append(json.loads(request.content))
        return httpx.Response(200, json=payload())

    request = SkincareToolInput(goals=["pores"], skinType="dry", irritationSignal="caution")
    await tool_with_handler(monkeypatch, handler).recommend(request)
    assert calls[0]["skinType"] == "dry"
    assert calls[0]["irritationSignal"] == "caution"
    assert "analysisScores" not in calls[0]


@pytest.mark.anyio
async def test_individual_concern_can_include_other_general_concern_reasons(monkeypatch):
    data = payload()
    candidate = match()
    candidate["reasons"].append(match(goal="dryness", sources=["concern"])["reasons"][0])
    data["byConcern"]["pores"] = [candidate]
    tool = tool_with_handler(monkeypatch, lambda _: httpx.Response(200, json=data))
    result = await tool.recommend(SkincareToolInput(goals=["pores"]))
    assert result.by_concern["pores"][0].reasons[1].sources == ["concern"]


@pytest.mark.parametrize(
    "data",
    [
        {"goals": []},
        {"goals": ["pores", "pores"]},
        {"goals": ["unsupported"]},
        {"goals": ["pores"], "skinType": "combination"},
        {"goals": ["pores"], "analysisScores": {"pores": 0.5}},
        {"goals": ["pores"], "maxPriceKRW": 20000},
        {"goals": ["pores"], "avoidIngredients": ["향료"]},
    ],
)
def test_unconfirmed_or_unsupported_inputs_are_rejected(data):
    with pytest.raises(ValidationError):
        SkincareToolInput.model_validate(data)


@pytest.mark.anyio
@pytest.mark.parametrize("status", ["no_matches", "mapping_unavailable"])
async def test_empty_results_keep_the_original_coverage_status(monkeypatch, status):
    tool = tool_with_handler(
        monkeypatch, lambda _: httpx.Response(200, json=payload(status=status, matches=[]))
    )
    result = await tool.recommend(SkincareToolInput(goals=["pores"]))
    assert result.overall_top10 == []
    assert result.coverage[0].status == status


@pytest.mark.anyio
@pytest.mark.parametrize("fault", ["http400", "http500", "timeout", "json", "legacy"])
async def test_upstream_failures_are_not_empty_recommendations(monkeypatch, fault):
    def handler(request):
        if fault == "timeout":
            raise httpx.ReadTimeout("fixture timeout", request=request)
        if fault == "http400":
            return httpx.Response(400)
        if fault == "http500":
            return httpx.Response(500)
        if fault == "json":
            return httpx.Response(200, content=b"not JSON")
        legacy = payload()
        del legacy["overallTop10"]
        return httpx.Response(200, json=legacy)

    with pytest.raises(UpstreamError):
        await tool_with_handler(monkeypatch, handler).recommend(SkincareToolInput(goals=["pores"]))


@pytest.mark.anyio
@pytest.mark.parametrize(
    "fault",
    [
        "coverage",
        "coverage_status",
        "source",
        "analysis",
        "profile_without_input",
        "unrequested_goal",
        "unrequested_group_source",
        "unrequested_balance_source",
        "wrong_profile_goal",
        "duplicate_source",
        "missing_version",
        "blank_version",
        "missing_ingredients",
        "blank_ingredient",
        "ranking",
        "research",
        "duplicate",
        "category",
        "product_id",
        "option_id",
        "group",
    ],
)
async def test_invalid_upstream_contract_is_rejected(monkeypatch, fault):
    data = payload()
    if fault == "coverage":
        data["coverage"] = []
    elif fault == "coverage_status":
        data["byConcern"]["pores"] = []
    elif fault == "source":
        data = payload(matches=[match(sources=["survey"])])
    elif fault == "analysis":
        data = payload(matches=[match(sources=["conversation", "analysis"])])
    elif fault == "profile_without_input":
        data = payload(matches=[match(sources=["conversation", "skinProfile"])])
    elif fault == "unrequested_goal":
        data = payload(matches=[match(goal="dryness")])
    elif fault == "unrequested_group_source":
        data["byConcern"]["pores"][0]["reasons"].append(match(goal="dryness")["reasons"][0])
    elif fault == "unrequested_balance_source":
        data["balanceMatches"] = [match(goal="dryness")]
    elif fault == "wrong_profile_goal":
        candidate = match()
        candidate["reasons"].append(
            match(goal="sensitivity", sources=["skinProfile"])["reasons"][0]
        )
        data = payload(matches=[candidate])
    elif fault == "duplicate_source":
        data = payload(matches=[match(sources=["conversation", "conversation"])])
    elif fault == "missing_version":
        data = payload(matches=[])
        data["dataVersion"] = None
    elif fault == "blank_version":
        data["dataVersion"] = "  "
    elif fault in {"missing_ingredients", "blank_ingredient"}:
        candidate = match()
        candidate["reasons"][0]["ingredientCodes"] = [] if fault == "missing_ingredients" else [" "]
        data = payload(matches=[candidate])
    elif fault == "ranking":
        data["overallTop5"] = []
    elif fault == "research":
        candidate = match()
        candidate["reasons"][0]["evidenceSources"] = ["research_mapping"]
        data = payload(matches=[candidate])
    elif fault == "duplicate":
        data = payload(matches=[match(), match()])
    elif fault == "category":
        candidate = match()
        candidate["product"]["category"] = "lip"
        data = payload(matches=[candidate])
    elif fault in {"product_id", "option_id"}:
        candidate = match()
        if fault == "product_id":
            candidate["product"]["id"] = " "
        else:
            candidate["optionId"] = " "
        data = payload(matches=[candidate])
    else:
        data["byConcern"]["pores"] = [match(goal="dryness")]
    tool = tool_with_handler(monkeypatch, lambda _: httpx.Response(200, json=data))
    request = SkincareToolInput(
        goals=["pores"], skinType="dry" if fault == "wrong_profile_goal" else None
    )
    with pytest.raises(UpstreamError):
        await tool.recommend(request)

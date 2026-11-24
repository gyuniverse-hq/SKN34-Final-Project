"""Conversation provenance for the existing skincare recommendation contract."""

from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from app.schemas.skincare import SkincareProfileRequest
from app.services.skincare_service import SkincareService, profile_goal_weights, recommend_hybrid
from tests.test_skincare_concern_fit import product, rule, snapshot

PATH = "/api/recommendations/skincare/v4"


def catalog():
    return snapshot(
        [product("pores", "p"), product("dry", "d"), product("both", "p", "d")],
        [rule("p", "pores", "ASTRINGENT"), rule("d", "dryness", "MOISTURISING")],
    )


def body(goals, source):
    return {"detectedConcerns": [{"goal": goal, "sources": [source]} for goal in goals]}


@pytest.fixture
def skincare_client():
    repo = AsyncMock()
    repo.read.return_value = catalog()
    app = create_app()
    from app.services.skincare_service import get_skincare_service

    app.dependency_overrides[get_skincare_service] = lambda: SkincareService(repo)
    return TestClient(app)


@pytest.mark.parametrize("goals", [["pores"], ["pores", "dryness"]])
def test_conversation_preserves_existing_rank_and_source(skincare_client, goals):
    survey = skincare_client.post(PATH, json=body(goals, "survey"))
    conversation = skincare_client.post(PATH, json=body(goals, "conversation"))
    assert survey.status_code == conversation.status_code == 200
    assert conversation.headers["cache-control"] == "no-store"
    old, new = survey.json(), conversation.json()
    assert old["coverage"] == new["coverage"]
    assert [m["product"]["id"] for m in old["overallTop10"]] == [
        m["product"]["id"] for m in new["overallTop10"]
    ]
    assert new["overallTop5"] == new["overallTop10"][:5]
    assert {r["goal"] for m in new["overallTop10"] for r in m["reasons"]} == set(goals)
    assert all(r["sources"] == ["survey"] for m in old["overallTop10"] for r in m["reasons"])
    assert all(
        r["sources"] == ["conversation"] and r["evidenceSources"] == ["cosing_function"]
        for m in new["overallTop10"]
        for r in m["reasons"]
    )


def test_multiple_goals_are_used_by_existing_ranking():
    request = SkincareProfileRequest.model_validate(body(["pores", "dryness"], "conversation"))
    result = recommend_hybrid(catalog(), request)
    assert profile_goal_weights(request) == {"pores": 1.0, "dryness": 1.0}
    assert result.overall_top10[0].product.id == "both"
    assert {reason.goal for reason in result.overall_top10[0].reasons} == {"pores", "dryness"}


def test_mixed_sources_preserve_analysis_and_conversation(skincare_client):
    request = {
        "detectedConcerns": [
            {"goal": "pores", "sources": ["analysis", "survey", "skinType", "conversation"]}
        ],
        "analysisScores": {"pores": 0.7},
    }
    response = skincare_client.post(PATH, json=request)
    assert response.status_code == 200
    reasons = [
        r for m in response.json()["overallTop10"] for r in m["reasons"] if r["goal"] == "pores"
    ]
    assert reasons and all(
        r["sources"] == request["detectedConcerns"][0]["sources"] for r in reasons
    )


def test_missing_inputs_stay_unknown_and_invalid_sources_are_rejected(skincare_client):
    request = SkincareProfileRequest.model_validate(body(["dryness"], "conversation"))
    assert request.analysis_scores == {}
    assert request.skin_type == request.irritation_signal == "unknown"
    assert skincare_client.post(PATH, json={}).json()["overallTop10"] == []
    for invalid in (
        {"detectedConcerns": [{"goal": "pores", "sources": ["unknown"]}]},
        {"skinType": "combination"},
        {"analysisScores": {"pores": 1.2}},
    ):
        assert skincare_client.post(PATH, json=invalid).status_code == 400

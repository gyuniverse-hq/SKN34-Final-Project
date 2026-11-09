"""The AI list combines skin type, care signals and near-boundary good analyses."""

from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.main import create_app
from app.schemas.skincare import HybridRequest, SkincareProfileRequest
from app.services.skincare_service import (
    SkincareService,
    get_skincare_service,
    recommend_hybrid,
)
from tests.test_skincare_concern_fit import ids, product, rule, snapshot


def catalog():
    rules = [
        rule("p", "pores", "ASTRINGENT"),
        rule("d", "dryness", "MOISTURISING"),
        rule("t", "pigmentation", "EXFOLIATING"),
        rule("w", "wrinkles", "SMOOTHING"),
    ]
    return snapshot([
        *[product(f"p{i}", "p", rating_avg=5, review_count=10000) for i in range(6)],
        *[product(f"d{i}", "d", rating_avg=3, review_count=100) for i in range(2)],
        *[product(f"t{i}", "t", rating_avg=2, review_count=100) for i in range(2)],
        product("w0", "w", rating_avg=5, review_count=10000),
    ], rules)


def request(**changes):
    return SkincareProfileRequest(**({
        "skinType": "dry",
        "detectedConcerns": [{"goal": "pores", "sources": ["analysis"]}],
        "analysisScores": {"pores": 0.9, "pigmentation": 0.45, "wrinkles": 0.1},
    } | changes))


def test_overall_covers_skin_type_care_and_near_good_instead_of_five_popular_care_products():
    result = recommend_hybrid(catalog(), request())
    assert len(result.overall_top5) == 5
    assert result.overall_top5[0].product.id.startswith("p")
    assert {r.goal for m in result.overall_top5 for r in m.reasons} == {
        "dryness", "pores", "pigmentation",
    }
    assert {r.sources[0] for m in result.overall_top5 for r in m.reasons} == {
        "skinProfile", "analysis", "analysisSupport",
    }
    assert len(set(ids(result.overall_top5))) == 5


def test_near_boundary_input_changes_ai_but_not_independent_browse_order():
    data = catalog()
    before = recommend_hybrid(data, request(analysisScores={"pores": 0.9}))
    after = recommend_hybrid(data, request())
    assert not any(m.product.id.startswith("t") for m in before.overall_top5)
    assert any(m.product.id.startswith("t") for m in after.overall_top5)
    for goal in before.by_concern:
        assert ids(before.by_concern[goal]) == ids(after.by_concern[goal])
    assert ids(before.balance_matches) == ids(after.balance_matches)


@pytest.mark.parametrize("score, source", [
    (0, None), (0.349999, None), (0.35, "analysisSupport"),
    (0.499999, "analysisSupport"), (0.5, "analysis"), (1, "analysis"),
])
def test_analysis_inclusion_boundary_and_truthful_reason(score, source):
    result = recommend_hybrid(catalog(), SkincareProfileRequest(
        analysisScores={"pigmentation": score},
    ))
    if source is None:
        assert result.overall_top5 == []
    else:
        assert ids(result.overall_top5) == ["t0", "t1"]
        assert result.overall_top5[0].reasons[0].sources == [source]


def test_model_scores_order_near_good_candidates_and_missing_scores_are_not_invented():
    data = catalog()
    result = recommend_hybrid(data, SkincareProfileRequest(
        analysisScores={"pigmentation": 0.49, "wrinkles": 0.36},
    ))
    assert ids(result.overall_top5)[:2] == ["t0", "w0"]
    assert recommend_hybrid(data, SkincareProfileRequest()).overall_top5 == []
    old = recommend_hybrid(data, request(analysisScores={}))
    assert {r.goal for m in old.overall_top5 for r in m.reasons} == {"dryness", "pores"}


def test_survey_caution_is_included_without_an_image_score():
    data = catalog()
    data.mappings.append(rule("s", "sensitivity", "SOOTHING"))
    data.ingredient_provenance["s"] = {"source": "fixture", "reviewedBy": "test"}
    data.options.append(product("s0", "s", rating_avg=1, review_count=100))
    result = recommend_hybrid(data, request(irritationSignal="caution"))
    assert any(r.goal == "sensitivity" for m in result.overall_top5 for r in m.reasons)


def test_balance_is_one_display_concern_not_two_votes():
    data = snapshot([
        product("both", "d", "o", rating_avg=3, review_count=100),
        product("pores", "p", rating_avg=5, review_count=100),
    ], [rule("d", "dryness", "MOISTURISING"), rule("o", "oiliness", "ANTI-SEBUM"),
        rule("p", "pores", "ASTRINGENT")])
    req = SkincareProfileRequest(skinType="dry", detectedConcerns=[
        {"goal": "oiliness", "sources": ["survey"]},
        {"goal": "pores", "sources": ["analysis"]},
    ])
    assert ids(recommend_hybrid(data, req).overall_top5) == ["pores", "both"]


def test_missing_candidates_and_duplicate_products_do_not_create_filler():
    data = catalog()
    data.options = [o for o in data.options if o.product.id == "p0"]
    duplicate = data.options[0].model_copy(update={
        "option_id": "duplicate", "source_option_id": "duplicate",
    })
    data.options.append(duplicate)
    result = recommend_hybrid(data, request())
    assert ids(result.overall_top5) == ["p0"]
    assert recommend_hybrid(None, request()).overall_top5 == []


def test_legacy_v2_ignores_new_scores_and_order_is_deterministic():
    data = catalog()
    req = request()
    before = recommend_hybrid(data, req)
    data.options.reverse()
    data.mappings.reverse()
    assert recommend_hybrid(data, req) == before
    legacy = HybridRequest(primaryGoal="pores")
    assert recommend_hybrid(data, legacy) == recommend_hybrid(data, legacy.model_copy(update={
        "analysis_scores": {"pigmentation": 0.49},
    }))


@pytest.mark.parametrize("scores", [
    {"pores": -0.1}, {"pores": 1.1}, {"pores": float("nan")},
    {"pores": float("inf")}, {"pores": "0.45"}, {"pores": True},
    {"blemish": 0.45}, {"skinType": 0.45},
])
def test_rejects_invalid_or_unsupported_model_scores(scores):
    with pytest.raises(ValidationError):
        SkincareProfileRequest(analysisScores=scores)


def test_http_contract_accepts_numeric_scores_and_preserves_no_store():
    repo = AsyncMock()
    repo.read.return_value = catalog()
    app = create_app()
    app.dependency_overrides[get_skincare_service] = lambda: SkincareService(repo)
    client = TestClient(app)
    url = "/api/recommendations/skincare/v4"
    response = client.post(url, json=request().model_dump(by_alias=True))
    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    assert len(response.json()["overallTop5"]) == 5
    assert client.post(url, json={"analysisScores": {"pores": 2}}).status_code == 400

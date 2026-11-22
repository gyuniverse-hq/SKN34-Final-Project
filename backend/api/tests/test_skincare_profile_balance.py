"""The AI list combines skin type, care signals and near-boundary good analyses."""

from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.main import create_app
from app.schemas.skincare import SkincareProfileRequest
from app.services.skincare_service import (
    SkincareService,
    get_skincare_service,
    profile_goal_weights,
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
    return snapshot(
        [
            *[product(f"p{i}", "p", rating_avg=5, review_count=10000) for i in range(6)],
            *[product(f"d{i}", "d", rating_avg=3, review_count=100) for i in range(2)],
            *[product(f"t{i}", "t", rating_avg=2, review_count=100) for i in range(2)],
            product("w0", "w", rating_avg=5, review_count=10000),
        ],
        rules,
    )


def request(**changes):
    return SkincareProfileRequest(
        **(
            {
                "skinType": "dry",
                "detectedConcerns": [{"goal": "pores", "sources": ["analysis"]}],
                "analysisScores": {"pores": 0.9, "pigmentation": 0.45, "wrinkles": 0.1},
            }
            | changes
        )
    )


def test_overall_covers_skin_type_care_and_near_good_instead_of_five_popular_care_products():
    result = recommend_hybrid(catalog(), request())
    assert len(result.overall_top5) == 5
    assert result.overall_top5[0].product.id.startswith("p")
    assert {r.goal for m in result.overall_top5 for r in m.reasons} == {
        "dryness",
        "pores",
        "pigmentation",
    }
    assert {r.sources[0] for m in result.overall_top5 for r in m.reasons} == {
        "skinProfile",
        "analysis",
        "analysisSupport",
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


@pytest.mark.parametrize(
    "score, source",
    [
        (0, None),
        (0.349999, None),
        (0.35, "analysisSupport"),
        (0.499999, "analysisSupport"),
        (0.5, "analysis"),
        (1, "analysis"),
    ],
)
def test_analysis_inclusion_boundary_and_truthful_reason(score, source):
    result = recommend_hybrid(
        catalog(),
        SkincareProfileRequest(
            analysisScores={"pigmentation": score},
        ),
    )
    if source is None:
        assert result.overall_top5 == []
    else:
        assert ids(result.overall_top5) == ["t0", "t1"]
        assert result.overall_top5[0].reasons[0].sources == [source]


def test_model_scores_order_near_good_candidates_and_missing_scores_are_not_invented():
    data = catalog()
    result = recommend_hybrid(
        data,
        SkincareProfileRequest(
            analysisScores={"pigmentation": 0.49, "wrinkles": 0.36},
        ),
    )
    assert ids(result.overall_top5)[:2] == ["t0", "w0"]
    assert recommend_hybrid(data, SkincareProfileRequest()).overall_top5 == []
    old = recommend_hybrid(data, request(analysisScores={}))
    assert {r.goal for m in old.overall_top5 for r in m.reasons} == {"dryness", "pores"}


def test_four_similarly_high_scores_receive_equal_weights():
    req = SkincareProfileRequest(
        analysisScores={"pores": 0.76, "pigmentation": 0.73, "wrinkles": 0.74, "blemish": 0.75}
    )
    assert profile_goal_weights(req) == dict.fromkeys(req.analysis_scores, 1.0)


@pytest.mark.parametrize(
    ("score", "threshold", "weight", "source", "first"),
    [(0.88, 0.5, 2.0, "analysis", "b"), (0.62, 0.7, 0.25, "analysisSupport", "p")],
)
def test_four_scores_include_good_signals_and_only_boost_an_outlier(
    score, threshold, weight, source, first
):
    data = snapshot(
        [
            product("b", "b", rating_avg=3.0, review_count=100),
            product("p", "p", rating_avg=5.0, review_count=1000),
        ],
        [rule("b", "blemish", "KERATOLYTIC"), rule("p", "pores", "ASTRINGENT")],
    )
    req = SkincareProfileRequest(
        analysisScores={"pores": 0.42, "pigmentation": 0.46, "wrinkles": 0.33, "blemish": score},
        blemishThreshold=threshold,
    )
    assert profile_goal_weights(req) == {
        "pores": 0.25,
        "pigmentation": 0.25,
        "wrinkles": 0.25,
        "blemish": weight,
    }
    picks = recommend_hybrid(data, req).overall_top10
    assert picks is not None and ids(picks)[0] == first
    assert next(pick for pick in picks if pick.product.id == "b").reasons[0].sources == [source]


def test_survey_caution_is_included_without_an_image_score():
    data = catalog()
    data.mappings.append(rule("s", "sensitivity", "SOOTHING"))
    data.ingredient_provenance["s"] = {"source": "fixture", "reviewedBy": "test"}
    data.options.append(product("s0", "s", rating_avg=1, review_count=100))
    result = recommend_hybrid(data, request(irritationSignal="caution"))
    assert any(r.goal == "sensitivity" for m in result.overall_top5 for r in m.reasons)


def test_balance_is_one_display_concern_not_two_votes():
    data = snapshot(
        [
            product("both", "d", "o", rating_avg=3, review_count=100),
            product("pores", "p", rating_avg=5, review_count=100),
        ],
        [
            rule("d", "dryness", "MOISTURISING"),
            rule("o", "oiliness", "ANTI-SEBUM"),
            rule("p", "pores", "ASTRINGENT"),
        ],
    )
    req = SkincareProfileRequest(
        skinType="dry",
        detectedConcerns=[
            {"goal": "oiliness", "sources": ["survey"]},
            {"goal": "pores", "sources": ["analysis"]},
        ],
    )
    assert ids(recommend_hybrid(data, req).overall_top5) == ["pores", "both"]


def test_missing_candidates_and_duplicate_products_do_not_create_filler():
    data = catalog()
    data.options = [o for o in data.options if o.product.id == "p0"]
    duplicate = data.options[0].model_copy(
        update={
            "option_id": "duplicate",
            "source_option_id": "duplicate",
        }
    )
    data.options.append(duplicate)
    result = recommend_hybrid(data, request())
    assert ids(result.overall_top5) == ["p0"]
    assert result.overall_top10 == result.overall_top5
    empty = recommend_hybrid(None, request())
    assert empty.overall_top10 == empty.overall_top5 == []


def test_current_profile_order_is_deterministic():
    data = catalog()
    req = request()
    before = recommend_hybrid(data, req)
    data.options.reverse()
    data.mappings.reverse()
    assert recommend_hybrid(data, req) == before


@pytest.mark.parametrize(
    "scores",
    [
        {"pores": -0.1},
        {"pores": 1.1},
        {"pores": float("nan")},
        {"pores": float("inf")},
        {"pores": "0.45"},
        {"pores": True},
        {"blemish": 1.1},
        {"skinType": 0.45},
    ],
)
def test_rejects_invalid_or_unsupported_model_scores(scores):
    with pytest.raises(ValidationError):
        SkincareProfileRequest(analysisScores=scores)


@pytest.mark.parametrize("threshold", [0, 1, True, "0.5", float("inf")])
def test_rejects_invalid_blemish_threshold(threshold):
    with pytest.raises(ValidationError):
        SkincareProfileRequest(analysisScores={"blemish": 0.45}, blemishThreshold=threshold)


def test_http_contract_accepts_numeric_scores_and_preserves_no_store():
    data = catalog()
    data.options.append(product("p6", "p", rating_avg=5, review_count=10000))
    repo = AsyncMock()
    repo.read.return_value = data
    app = create_app()
    app.dependency_overrides[get_skincare_service] = lambda: SkincareService(repo)
    client = TestClient(app)
    url = "/api/recommendations/skincare/v4"
    response = client.post(url, json=request().model_dump(by_alias=True))
    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    payload = response.json()
    assert len({match["product"]["id"] for match in payload["overallTop10"]}) == 10
    assert len(payload["overallTop10"]) == 10
    assert payload["overallTop5"] == payload["overallTop10"][:5]
    assert len(payload["byConcern"]["pores"]) == 5
    assert client.post(url, json={"analysisScores": {"pores": 2}}).status_code == 400


@pytest.mark.parametrize("small_survey", [{}, {"dry": 1.0}], ids=["missing", "both-positive"])
def test_dry_profile_ranks_established_match_above_two_perfect_reviews(small_survey):
    repo = AsyncMock()
    repo.read.return_value = snapshot(
        [
            product("a-small", "d", rating_avg=5.0, review_count=2, survey_ratios=small_survey),
            product(
                "z-established", "d", rating_avg=4.6, review_count=1000, survey_ratios={"dry": 0.75}
            ),
        ],
        [rule("d", "dryness", "MOISTURISING")],
    )
    app = create_app()
    app.dependency_overrides[get_skincare_service] = lambda: SkincareService(repo)
    response = TestClient(app).post("/api/recommendations/skincare/v4", json={"skinType": "dry"})
    assert response.status_code == 200
    data = response.json()
    for matches in (data["overallTop5"], data["byConcern"]["dryness"], data["balanceMatches"]):
        assert [match["product"]["id"] for match in matches] == ["z-established", "a-small"]


def test_dry_overall_reranks_only_candidates_with_equal_ingredient_fit():
    data = snapshot(
        [
            product(
                "anchor", "shared", rating_avg=5, review_count=1000, survey_ratios={"dry": 0.95}
            ),
            product(
                "dry-fit", "shared", rating_avg=4.6, review_count=1000, survey_ratios={"dry": 0.75}
            ),
            product(
                "diverse", "other", rating_avg=4.7, review_count=16, survey_ratios={"dry": 0.0}
            ),
            product(
                "popular", "partial", rating_avg=5, review_count=10000, survey_ratios={"dry": 1}
            ),
        ],
        [
            rule("shared", "dryness", "MOISTURISING", "HUMECTANT"),
            rule("other", "dryness", "MOISTURISING", "HUMECTANT"),
            rule("partial", "dryness", "MOISTURISING"),
        ],
    )
    result = recommend_hybrid(data, SkincareProfileRequest(skinType="dry"))
    assert ids(result.overall_top5) == ["anchor", "dry-fit", "diverse", "popular"]
    assert ids(result.by_concern["dryness"]) == ids(result.overall_top5)

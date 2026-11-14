import math

import pytest

from app.schemas.recommendation_comparison import ReviewEvidence
from app.services.recommendation_v2_service import (
    EMPIRICAL_SKIN_PRIORS,
    EMPIRICAL_SURVEY_PRIORS,
    combined_review,
    user_suitability,
)


def review(**changes):
    return ReviewEvidence(
        review_count=1000, rating_avg=4.9, rating_percentages=(0, 0, 0, 10, 90), **changes
    )


def test_default_uses_posterior_ratios_geometric_mean_and_twenty_percent_cap():
    r = review(survey_ratios={"brighteningFirming": 0.8, "oily": 0.2})
    c, s = EMPIRICAL_SURVEY_PRIORS["brighteningFirming"], EMPIRICAL_SKIN_PRIORS["oily"]
    pc = (1000 * 0.8 + c["k"] * c["mu"]) / (1000 + c["k"])
    ps = (1000 * 0.2 + s["k"] * s["mu"]) / (1000 + s["k"])
    result = combined_review(r, "pigmentation", {}, 4.8, skin_type="oily")
    assert result["reviewPolicy"] == "suitability"
    assert result["suitabilityScore"] == pytest.approx(math.sqrt(pc * ps))
    assert result["ratingRetention"] == pytest.approx(0.8 + 0.2 * math.sqrt(pc * ps))
    assert 0.8 <= result["ratingRetention"] <= 1
    assert result["normalizedScore"] == pytest.approx(
        (result["adjustedRating"] - 1) / 4 * result["ratingRetention"]
    )
    assert result["surveyBonus"] == result["skinTypeBonus"] == 0
    assert result["rawCombinedScore"] == pytest.approx(1 + 4 * result["normalizedScore"])
    legacy = combined_review(r, "pigmentation", {}, 4.8, skin_type="oily", review_policy="additive")
    assert legacy["adjustedRating"] == result["adjustedRating"]
    assert legacy["surveyBonus"] != 0 and legacy["skinTypeBonus"] != 0


def test_weaker_matching_skin_evidence_reduces_review_score_without_affecting_rating():
    strong = combined_review(
        review(survey_ratios={"brighteningFirming": 0.8, "oily": 0.8}),
        "wrinkles",
        {},
        4.8,
        skin_type="oily",
    )
    weak = combined_review(
        review(survey_ratios={"brighteningFirming": 0.8, "oily": 0.2}),
        "wrinkles",
        {},
        4.8,
        skin_type="oily",
    )
    assert strong["adjustedRating"] == weak["adjustedRating"]
    assert strong["normalizedScore"] > weak["normalizedScore"]


def test_missing_and_unsupported_signals_are_omitted_not_zero_or_invented():
    r = review(survey_ratios={"brighteningFirming": 0.8, "combination": 0.9})
    for goal, skin in (("pores", "combination"), ("wrinkles", "balanced")):
        u, signals = user_suitability(r, goal, skin)
        values = [s["posteriorRatio"] for s in signals if s["status"] == "available"]
        assert len(values) == 1 and u == values[0]
    for missing in (r, ReviewEvidence(review_count=0, survey_ratios={"oily": 1})):
        result = combined_review(missing, "pores", {}, 4.8, skin_type="balanced")
        assert result["suitabilityScore"] is None and result["ratingRetention"] == 1
        assert result["normalizedScore"] == result["normalizedRating"]
    zero = review(survey_ratios={"oily": 0})
    u, signals = user_suitability(zero, "pores", "oily")
    assert signals[1]["status"] == "available" and u > 0
    for missing in (ReviewEvidence(), ReviewEvidence(review_count=1000)):
        u, signals = user_suitability(missing, "pores", "oily")
        assert u == EMPIRICAL_SKIN_PRIORS["oily"]["mu"]
        assert signals[1]["posteriorSource"] == "prior_only"


@pytest.mark.parametrize("value", [0, 0.2, 1])
def test_lambda_limits_and_monotonicity(value):
    r = review(survey_ratios={"brighteningFirming": 0.4, "dry": 0.4})
    result = combined_review(r, "wrinkles", {}, 4.8, skin_type="dry", suitability_lambda=value)
    assert 1 - value <= result["ratingRetention"] <= 1
    assert 0 <= result["normalizedScore"] <= result["normalizedRating"] <= 1
    if value == 0:
        assert result["normalizedScore"] == result["normalizedRating"]


@pytest.mark.parametrize("value", [-0.1, 1.1, float("nan"), float("inf")])
def test_invalid_lambda_rejected(value):
    with pytest.raises(ValueError, match="invalid_suitability_lambda"):
        combined_review(review(), "pores", {}, 4.8, suitability_lambda=value)

import pytest

from app.repositories.skincare_build_repository import survey_ratios
from app.schemas.skincare import HybridRequest
from app.services.skincare_service import (
    _recommend_hybrid_unfiltered as recommend_hybrid,
)
from app.services.skincare_service import (
    review_sort_score,
    survey_adjustment,
    survey_baselines,
)
from tests.test_skincare import option, snapshot
from tests.test_skincare_hybrid import reviewed


def test_review_count_controls_shrinkage_and_missing_is_neutral():
    req = HybridRequest(primaryGoal="pores", skinType="dry")
    small = option(review_count=5, survey_ratios={"dry": 0.8})
    large = option("b", review_count=100, survey_ratios={"dry": 0.8})
    assert survey_adjustment(small, req, {"dry": 0.4}) == pytest.approx(5 / 212 * 0.4)
    assert survey_adjustment(large, req, {"dry": 0.4}) == pytest.approx(100 / 307 * 0.4)
    assert survey_adjustment(
        option(review_count=207, survey_ratios={"dry": 0.8}), req, {"dry": 0.4}
    ) == pytest.approx(0.2)
    assert survey_adjustment(option(), req, {"dry": 0.4}) == 0
    req.irritation_signal = "caution"
    assert (
        survey_adjustment(
            option(review_count=100, survey_ratios={"irritating": 0.5}),
            req,
            {"dry": 0.4, "irritating": 0.1},
        )
        < 0
    )


def test_baseline_counts_product_once_and_equal_intent_fit_uses_review_adjustment():
    first = option("a", review_count=100, survey_ratios={"dry": 0.2}, matched_mapping_ids=["m"])
    second = option("b", review_count=100, survey_ratios={"dry": 0.8}, matched_mapping_ids=["m"])
    duplicate = first.model_copy(update={"option_id": "a2", "source_option_id": "a2"})
    assert survey_baselines([first, second, duplicate])["dry"] == pytest.approx(0.5)
    req = HybridRequest(
        primaryGoal="dryness",
        skinType="dry",
        detectedConcerns=[
            {"goal": "dryness", "sources": ["skinType"]},
            {"goal": "pores", "sources": ["analysis"]},
        ],
    )
    data = snapshot([first, second], [reviewed()])
    assert recommend_hybrid(data, req).overall_top5[0].product.id == "b"
    second.matched_mapping_ids = ["p"]
    data.mappings.append(reviewed(mapping_id="p", target_concern="pores"))
    assert [m.product.id for m in recommend_hybrid(data, req).overall_top5] == ["b", "a"]


def test_partial_duplicate_invalid_question_is_not_used():
    rows = [
        dict(goods_no="p", question_name="피부타입", answer_name=a, percentage=v)
        for a, v in [("건성에 좋아요", 40), ("지성에 좋아요", 10), ("복합성에 좋아요", 50)]
    ]
    assert survey_ratios(rows)["p"]["dry"] == 0.4
    assert survey_ratios(rows[:2]) == {}
    assert survey_ratios(rows + [rows[0]]) == {}
    rows[0]["percentage"] = float("nan")
    assert survey_ratios(rows) == {}


def test_survey_bonus_reorders_near_ratings_and_preserves_larger_rating_gap():
    req = HybridRequest(primaryGoal="pores", skinType="dry")
    a = option(review_count=1000, rating_avg=4.9, survey_ratios={"dry": 0.2})
    b = option("b", review_count=1000, rating_avg=4.899, survey_ratios={"dry": 0.8})
    means = {"dry": 0.5}
    assert review_sort_score(b, req, 4.5, means) > review_sort_score(a, req, 4.5, means)
    b.rating_avg = 4.8
    assert review_sort_score(a, req, 4.5, means) > review_sort_score(b, req, 4.5, means)
    extremes = [
        option(review_count=1_000_000, rating_avg=5, survey_ratios={"dry": 1}),
        option(review_count=1_000_000, rating_avg=5, survey_ratios={"dry": 0}),
    ]
    for o in extremes:
        score = review_sort_score(o, req, 5, {"dry": 0.5})
        assert abs(score - 5) <= 0.05

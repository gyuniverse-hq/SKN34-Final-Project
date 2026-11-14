import pytest

from app.schemas.recommendation_comparison import CandidateOption, ComparisonCatalog, ReviewEvidence
from app.services.recommendation_v2_service import (
    combined_review,
    rank_products,
    skin_type_adjustment,
)


@pytest.mark.parametrize(
    "skin_type,other", [("dry", "oily"), ("oily", "combination"), ("combination", "dry")]
)
def test_only_matching_skin_answer_is_used_and_reviews_control_confidence(skin_type, other):
    review = ReviewEvidence(review_count=2, survey_ratios={skin_type: 0.8, other: 1.0})
    small, info = skin_type_adjustment(review, skin_type)
    review.survey_ratios[other] = 0
    assert skin_type_adjustment(review, skin_type) == (small, info)
    review.review_count = 3000
    large, evidence = skin_type_adjustment(review, skin_type)
    assert 0 < small < large
    assert info["reliability"] < evidence["reliability"] < 1
    review.survey_ratios[skin_type] = 0
    assert skin_type_adjustment(review, skin_type)[0] < 0
    assert skin_type_adjustment(review, skin_type)[1]["status"] == "available"
    review.review_count = 0
    assert skin_type_adjustment(review, skin_type)[0] == 0


def test_balanced_missing_and_disabled_skin_signal_are_not_fabricated():
    review = ReviewEvidence(review_count=1000, survey_ratios={"combination": 1, "dry": 0.8})
    value, evidence = skin_type_adjustment(review, "balanced")
    assert value == 0 and evidence["status"] == "unsupported_skin_type"
    assert evidence["signal"] is None and evidence["answer"] is None
    assert skin_type_adjustment(review, "oily")[1]["status"] == "missing_signals"
    disabled = combined_review(
        review, "pores", {}, 4.8, skin_type="dry", skin_review=False, review_policy="additive"
    )
    assert disabled["skinTypeBonus"] == 0
    assert disabled["skinTypeReview"]["status"] == "disabled"
    assert disabled["reviewRawRange"] == [0.95, 5.05]


def test_pores_ranking_uses_skin_survey_with_equal_rating_and_ingredients():
    options = [
        CandidateOption(
            product_id=pid,
            product_name=pid,
            option_id=pid,
            ingredient_ids=[1],
            review=ReviewEvidence(
                review_count=1000,
                rating_avg=4.9,
                rating_percentages=(0, 0, 0, 10, 90),
                survey_ratios={"dry": dry, "oily": oily},
            ),
        )
        for pid, dry, oily in [("a", 0.9, 0.05), ("b", 0.05, 0.9)]
    ]
    catalog = ComparisonCatalog(
        version="test", digest="test", options=options, names={}, source_manifest={}
    )
    seeds = [{"id": 1, "score": 1}]
    dry = rank_products(seeds, [], catalog, "pores", skin_type="dry")
    oily = rank_products(seeds, [], catalog, "pores", skin_type="oily")
    assert [m["productId"] for m in dry["matches"]] == ["a", "b"]
    assert [m["productId"] for m in oily["matches"]] == ["b", "a"]
    for result in (dry, oily):
        assert result["matches"][0]["review"]["surveyBonus"] == 0
        assert (
            result["matches"][0]["review"]["ratingRetention"]
            > result["matches"][1]["review"]["ratingRetention"]
        )
        assert result["matches"][0]["review"]["status"] == "rating_and_survey"
    assert dry["beforeReview"] == oily["beforeReview"]


def test_skin_addition_preserves_rating_and_concern_and_normalizes_both_signals():
    for star in (1, 5):
        for ratio in (0, 1):
            counts = [0] * 5
            counts[star - 1] = 100
            review = ReviewEvidence(
                review_count=1000000,
                rating_avg=star,
                rating_percentages=tuple(counts),
                survey_ratios={"oily": ratio, "brighteningFirming": ratio},
            )
            old = combined_review(
                review,
                "wrinkles",
                {},
                4.8,
                skin_type="oily",
                skin_review=False,
                review_policy="additive",
            )
            new = combined_review(
                review, "wrinkles", {}, 4.8, skin_type="oily", review_policy="additive"
            )
            assert old["adjustedRating"] == new["adjustedRating"]
            assert old["surveyBonus"] == new["surveyBonus"]
            assert new["rawCombinedScore"] == pytest.approx(
                old["rawCombinedScore"] + new["skinTypeBonus"]
            )
            assert new["normalizedScore"] == pytest.approx((new["rawCombinedScore"] - 0.9) / 4.2)
            assert 0 <= new["normalizedScore"] <= 1

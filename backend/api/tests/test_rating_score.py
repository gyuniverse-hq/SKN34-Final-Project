import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.repositories.recommendation_comparison_repository import ComparisonRepository
from app.schemas.recommendation_comparison import ReviewEvidence
from app.services.rating_score_service import (
    MU,
    K,
    conservative_rating,
    posterior_score,
    reconstruct_counts,
)
from app.services.recommendation_v2_service import combined_review


def test_small_perfect_rating_is_less_certain_than_established_high_rating():
    small = ReviewEvidence(
        review_count=2, rating_avg=5, rating_percentages=(None, None, None, None, 100)
    )
    large = ReviewEvidence(review_count=3000, rating_avg=4.9, rating_percentages=(0, 0, 0, 10, 90))
    left, right = conservative_rating(small), conservative_rating(large)
    assert left["ratingPosteriorMean"] == pytest.approx((10 + K * MU) / (2 + K))
    assert left["adjustedRating"] < right["adjustedRating"]
    assert left["ratingUncertaintyPenalty"] > right["ratingUncertaintyPenalty"]
    assert 4.67 < left["adjustedRating"] < 4.72
    posterior_score.cache_clear()
    assert conservative_rating(small) == left


def test_rounding_reconstruction_and_explicit_rejection():
    review = ReviewEvidence(
        review_count=33, rating_avg=5, rating_percentages=(None, None, None, 3, 97)
    )
    counts, status = reconstruct_counts(review)
    assert counts == (0, 0, 0, 1, 32) and sum(counts) == 33
    assert status == "absent_stars_zero_assumption"
    review.rating_percentages = (None, None, None, 3, 60)
    assert reconstruct_counts(review) == (None, "invalid_percentage_total")
    review.rating_percentages = (100, 0, 0, 0, 0)
    assert reconstruct_counts(review) == (None, "distribution_display_mean_mismatch")


def test_missing_or_mismatched_histogram_never_uses_unshrunk_display_rating():
    missing = conservative_rating(ReviewEvidence())
    mismatch = conservative_rating(
        ReviewEvidence(
            review_count=10000, rating_avg=5, rating_distribution_status="snapshot_mismatch"
        )
    )
    assert mismatch["adjustedRating"] == missing["adjustedRating"]
    assert mismatch["ratingDistributionStatus"] == "snapshot_mismatch"
    assert mismatch["ratingStatus"] == "prior_only"
    assert mismatch["ratingReliability"] == 0
    assert mismatch["adjustedRating"] < MU


def test_only_rating_changes_and_score_range_remains_bounded():
    for star in (1, 5):
        percentages = [0] * 5
        percentages[star - 1] = 100
        for ratio in (0, 1):
            review = ReviewEvidence(
                review_count=1000000,
                rating_avg=star,
                rating_percentages=tuple(percentages),
                survey_ratios={"brighteningFirming": ratio},
            )
            new = combined_review(review, "wrinkles", {}, 4.8, review_policy="additive")
            old = combined_review(
                review, "wrinkles", {}, 4.8, rating_policy="legacy_20", review_policy="additive"
            )
            assert new["surveyBonus"] == old["surveyBonus"]
            assert new["signals"] == old["signals"]
            assert new["rawCombinedScore"] == new["adjustedRating"] + new["surveyBonus"]
            assert 0 <= new["normalizedScore"] <= 1
    with pytest.raises(ValueError, match="invalid_rating_policy"):
        combined_review(ReviewEvidence(), "pores", {}, 4.8, rating_policy="invalid")


@pytest.mark.parametrize(
    "raw_rating,catalog_rating,raw_count,expected",
    [
        (None, 5, 2, "snapshot_mismatch"),
        (5, None, 2, "snapshot_mismatch"),
        (5, 5, 3, "snapshot_mismatch"),
        (5, 5, 2, "matched"),
    ],
)
def test_repository_attaches_only_matching_rating_distribution(
    raw_rating, catalog_rating, raw_count, expected
):
    payload = {
        "dataVersion": "test",
        "sourceManifest": {"schemaVersion": "0.3", "mappingPolicy": "cosing-only-v1"},
        "options": [
            {
                "available": True,
                "identityVerified": True,
                "optionId": "a",
                "sourceOptionId": "a",
                "product": {"id": "oy-a", "name": "test"},
                "reviewCount": 2,
                "ratingAvg": catalog_rating,
            }
        ],
    }
    source = {
        "product_id": "oy-a",
        "review_count": raw_count,
        "rating_avg": raw_rating,
        **{f"rating_{s}_pct": 100 if s == 5 else 0 for s in range(1, 6)},
    }
    responses = [MagicMock() for _ in range(9)]
    responses[2].scalar_one.return_value = payload
    responses[3].mappings.return_value.all.return_value = []
    for i in (4, 5, 6):
        responses[i].all.return_value = []
    # Seven reads after the two transaction setup statements: payload, ingredient
    # mapping, names, functions, concern functions, then the rating distribution.
    responses[7].mappings.return_value.all.return_value = [source]
    session = MagicMock()
    session.execute = AsyncMock(side_effect=responses)
    data = asyncio.run(ComparisonRepository(session).read())
    review = data.options[0].review
    assert review.rating_distribution_status == expected
    assert (review.rating_percentages is not None) == (expected == "matched")

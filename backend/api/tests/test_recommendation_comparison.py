import asyncio
from unittest.mock import AsyncMock, patch

import pytest
from pydantic import ValidationError

from app.core.config import Settings
from app.schemas.recommendation_comparison import (
    CandidateOption,
    ComparisonCatalog,
    ComparisonInput,
    ReviewEvidence,
)
from app.services.recommendation_comparison_service import ComparisonService
from app.services.recommendation_v2_service import (
    combined_review,
    expand,
    feature_values,
    product_purpose,
    rank_products,
    rating_baseline,
    survey_adjustment,
    survey_baselines,
    target_goal,
)


def body(**changes):
    return ComparisonInput.model_validate(
        {
            "ageGroup": "30대",
            "gender": "여성",
            "skinType": "지성",
            "analysisVersion": "skin-analysis-v4",
            "scoreKind": "binary_caution_probability",
            "aggregation": "mean-cheeks-pore-tone-eyes-wrinkle-v1",
            "scores": {"pores": 0.8, "pigmentation": 0.2, "wrinkles": 0.8},
            **changes,
        }
    )


def option(product, ids, ratio=None, count=None):
    return CandidateOption(
        product_id=product,
        product_name=product,
        option_id=product + "-1",
        ingredient_ids=ids,
        review=ReviewEvidence(
            survey_ratios={"brighteningFirming": ratio} if ratio is not None else {},
            review_count=count,
        ),
    )


def catalog(options=(), functions=None, concerns=None):
    return ComparisonCatalog(
        version="test",
        digest="hash",
        options=list(options),
        names={},
        source_manifest={},
        functions_by_id=functions or {},
        functions_by_concern=concerns or {},
    )


def test_input_rejects_missing_invalid_and_wrong_score_semantics():
    for changes in [
        {"scores": {"pores": 0.2}},
        {"scores": {"pores": 2}},
        {"scoreKind": "normalized_grade"},
        {"photo": "not-allowed"},
        {"scores": {"pores": float("nan"), "pigmentation": 0.2, "wrinkles": 0.1}},
    ]:
        with pytest.raises(ValidationError):
            body(**changes)
    assert target_goal(body()) == "pores"
    assert feature_values(body(), "pores") == [
        "30대",
        "여성",
        "지성",
        "모공케어",
        "주의",
        "주의",
        "양호",
    ]


def test_expansion_joins_original_tables_without_products_projection_or_count_limit():
    functions = {i: ["ASTRINGENT"] for i in range(1, 24)}
    functions[24] = ["MOISTURISING"]
    data = catalog(functions=functions, concerns={"pores": ["ASTRINGENT"]})
    result, skipped = expand([{"id": 1, "score": 0.9}], data, "pores")
    assert [r["id"] for r in result] == list(range(2, 24))
    assert result[0]["origins"] == [{"seedId": 1, "functions": ["ASTRINGENT"], "similarity": 1.0}]
    assert not skipped
    # Product availability is a later step and cannot change ingredient eligibility.
    data.options = [option("p", [24])]
    assert expand([{"id": 1, "score": 0.9}], data, "pores")[0] == result


def test_broad_tag_is_allowed_only_when_original_concern_table_maps_it():
    data = catalog(functions={1: ["SKIN CONDITIONING"], 2: ["SKIN CONDITIONING"]})
    related, skipped = expand([{"id": 1, "score": 0.9}], data, "pores")
    assert not related and skipped[0]["reason"] == "no_ml_shared_concern_tag"
    data.functions_by_concern = {"pores": ["SKIN CONDITIONING"]}
    assert [r["id"] for r in expand([{"id": 1, "score": 0.9}], data, "pores")[0]] == [2]


def test_only_the_shared_goal_tag_counts_and_multiple_origins_are_preserved():
    data = catalog(
        functions={
            1: ["ASTRINGENT", "FRAGRANCE"],
            2: ["ASTRINGENT"],
            3: ["FRAGRANCE"],
            4: ["ASTRINGENT", "FRAGRANCE"],
        },
        concerns={"pores": ["ASTRINGENT"], "wrinkles": ["FRAGRANCE"]},
    )
    seeds = [{"id": 1, "score": 0.9}, {"id": 2, "score": 0.8}]
    related, _ = expand(seeds, data, "pores")
    assert [r["id"] for r in related] == [4]
    assert [o["seedId"] for o in related[0]["origins"]] == [1, 2]
    assert related[0]["score"] == 0.9
    assert all(o["functions"] == ["ASTRINGENT"] for o in related[0]["origins"])


def test_survey_ratio_without_respondents_and_unique_products():
    seeds, related = (
        [{"id": 1, "score": 0.9}],
        [{"id": 2, "score": 0.8, "origins": [{"seedId": 1, "similarity": 1.0}]}],
    )
    options = [
        option("direct", [1]),
        option("expanded", [2], 1.0, 1000),
        option("small", [1], 1.0, 2),
        option("large", [1], 0.8, 200),
    ]
    options.append(options[0].model_copy(update={"option_id": "direct-2"}))
    result = rank_products(
        seeds, related, catalog(options), "pigmentation", review_policy="additive"
    )
    assert result["candidateOptions"] == 5 and result["candidateProducts"] == 4
    assert [r["productId"] for r in result["matches"]] == ["large", "small", "direct", "expanded"]
    assert result["shortfall"] == 1
    direct = next(r for r in result["matches"] if r["productId"] == "direct")
    assert direct["reviewAdjusted"] is None
    assert direct["review"]["status"] == "prior_only"
    assert direct["review"]["ratingAvg"] is None


def test_v1_failure_preserves_v2_and_snapshot_mismatch_is_explicit():
    repo = AsyncMock()
    repo.read.return_value = catalog()
    settings = Settings(recommendation_v2_bundle="test")
    with (
        patch(
            "app.services.recommendation_comparison_service.fetch_v1",
            new=AsyncMock(side_effect=OSError("unavailable")),
        ),
        patch(
            "app.services.recommendation_comparison_service.recommend_v2",
            return_value={"status": "ok", "matches": []},
        ),
    ):
        result = asyncio.run(ComparisonService(repo, settings).compare(body()))
    assert result["v1"]["status"] == "v1_unavailable"
    assert result["v2"]["status"] == "ok" and not result["sameSnapshot"]


def test_no_direct_pore_survey_is_invented():
    result = rank_products(
        [{"id": 1, "score": 0.9}], [], catalog([option("p", [1], 1.0, 100)]), "pores"
    )
    assert result["matches"][0]["review"]["surveyBonus"] == 0
    assert result["matches"][0]["review"]["signals"] == []
    assert result["reviewAppliedProducts"] == 0


def test_only_target_concern_review_affects_bonus_not_skin_type_or_irritation():
    review = ReviewEvidence(
        review_count=207,
        survey_ratios={
            "dry": 1.0,
            "oily": 0.8,
            "brighteningFirming": 0.9,
            "gentle": 0.7,
            "irritating": 0.4,
        },
    )
    baseline = {
        "dry": 0.3,
        "oily": 0.4,
        "brighteningFirming": 0.5,
        "gentle": 0.5,
        "irritating": 0.2,
    }
    for goal in ("pigmentation", "wrinkles"):
        adjustment, evidence = survey_adjustment(review, goal, baseline, survey_policy="legacy_207")
        assert adjustment == pytest.approx(0.2)
        assert [s["signal"] for s in evidence["signals"]] == ["brighteningFirming"]
        assert evidence["answer"] == "주름/미백에 좋아요"
        assert evidence["targetConcern"] == goal
        assert evidence["reliability"] == 0.5
    review.survey_ratios["dry"] = 0.0
    review.survey_ratios["gentle"] = 0.0
    assert survey_adjustment(review, "wrinkles", baseline, survey_policy="legacy_207")[
        0
    ] == pytest.approx(0.2)
    del review.survey_ratios["brighteningFirming"]
    adjustment, evidence = survey_adjustment(
        review, "wrinkles", baseline, survey_policy="legacy_207"
    )
    assert adjustment == 0 and evidence["status"] == "missing_signals"
    assert survey_adjustment(review, "pores", baseline)[1]["status"] == "unsupported_signal"


@pytest.mark.parametrize(
    "goal,signal,answer",
    [
        ("dryness", "hydrating", "보습에 좋아요"),
        ("sensitivity", "soothing", "진정에 좋아요"),
    ],
)
def test_other_concerns_use_their_actual_survey_answer(goal, signal, answer):
    review = ReviewEvidence(review_count=207, survey_ratios={signal: 0.8, "dry": 1.0})
    value, evidence = survey_adjustment(
        review, goal, {signal: 0.4, "dry": 0.2}, survey_policy="legacy_207"
    )
    assert value == pytest.approx(0.2)
    assert evidence["answer"] == answer
    review.review_count = None
    assert survey_adjustment(review, goal, {signal: 0.4})[0] == 0


def test_v1_baselines_use_all_products_once_and_accept_zero_ratio():
    a, b = option("a", [1], 0.0, 100), option("b", [9], 1.0, 300)
    assert survey_baselines([a, a.model_copy(update={"option_id": "a-2"}), b]) == {
        "brighteningFirming": 0.75
    }
    for invalid in (-0.1, 1.1, float("nan")):
        with pytest.raises(ValidationError):
            ReviewEvidence(survey_ratios={"oily": invalid})


def test_missing_catalog_preserves_v1_and_does_not_claim_same_snapshot():
    repo = AsyncMock()
    repo.read.side_effect = ValueError("unsupported snapshot")
    with patch(
        "app.services.recommendation_comparison_service.fetch_v1",
        new=AsyncMock(return_value={"dataVersion": "test", "matches": []}),
    ):
        result = asyncio.run(ComparisonService(repo, Settings()).compare(body()))
    assert result["v1"]["status"] == "ok"
    assert result["v2"]["status"] == "catalog_unavailable"
    assert not result["sameSnapshot"]


def test_bundle_reproduces_saved_predictions_when_local_artifact_is_available():
    import json
    from pathlib import Path

    import numpy as np

    from app.services.recommendation_v2_service import load_bundle

    root = Path(__file__).resolve().parents[3]
    bundle = root / "ml/data/recommendation-v2/serving-bundle-20261111"
    experiment = root / "ml/experiments/recommendation-v2-image-feature-replacement-20261111"
    if not all(
        path.exists()
        for path in (bundle, experiment / "test.jsonl", experiment / "image/test_predictions.npz")
    ):
        pytest.skip("Local model and reference predictions are not distributed with source")
    model, manifest = load_bundle(str(bundle))
    rows = [
        json.loads(line)
        for line in (experiment / "test.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    x = [
        [row["base_x"][key] for key in manifest["features"][:4]] + row["image_features"]
        for row in rows
    ]
    with np.load(experiment / "image/test_predictions.npz") as expected:
        assert list(expected["sources"]) == [row["source"] for row in rows]
        np.testing.assert_allclose(
            model.predict_proba(x), expected["probabilities"], atol=1e-12, rtol=0
        )


def test_development_api_disabled_by_default():
    from fastapi.testclient import TestClient

    from app.core.config import get_settings
    from app.main import create_app

    app = create_app()
    app.dependency_overrides[get_settings] = lambda: Settings(env="production")
    # The guard calls get_settings itself, so patch its module rather than a DI override.
    with (
        patch(
            "app.routers.recommendation_comparison.get_settings",
            return_value=Settings(env="production", recommendation_comparison_enabled=True),
        ),
        TestClient(app) as client,
    ):
        response = client.post(
            "/api/dev/recommendations/compare", json=body().model_dump(mode="json")
        )
    assert response.status_code == 404


def test_review_weight_ablation_preserves_candidates_and_zero_matches_before_order():
    seeds = [{"id": 1, "score": 0.9}]
    data = catalog([option("a", [1], 0.1, 207), option("b", [1], 0.9, 207)])
    zero = rank_products(
        seeds,
        [],
        data,
        "wrinkles",
        review_mix_weight=0,
        rating_policy="legacy_20",
        review_policy="additive",
    )
    normal = rank_products(
        seeds,
        [],
        data,
        "wrinkles",
        review_mix_weight=0.2,
        rating_policy="legacy_20",
        review_policy="additive",
    )
    assert [r["productId"] for r in zero["matches"]] == zero["beforeReview"] == ["a", "b"]
    assert [r["productId"] for r in normal["matches"]] == ["b", "a"]
    assert normal["candidateProducts"] == zero["candidateProducts"] == 2
    assert [r["review"]["rawCombinedScore"] for r in normal["matches"]] == pytest.approx(
        [3 + 0.05 * 207 / (207 + 3.193016787576364) * (p - 0.13761171088373558) for p in (0.9, 0.1)]
    )
    assert all(
        r["score"] == pytest.approx(r["ingredientContribution"] + r["reviewContribution"])
        for r in normal["matches"]
    )
    assert all(r["score"] == r["ingredientScore"] for r in zero["matches"])
    assert all(r["reviewBonus"] == 0 for r in normal["beforeReviewMatches"])


def test_concern_candidates_do_not_require_ml_shared_tags():
    data = catalog(
        functions={1: ["UNKNOWN"], 2: ["BLEACHING"], 3: ["FRAGRANCE"]},
        concerns={"pigmentation": ["BLEACHING"]},
    )
    related, skipped = expand([{"id": 1, "score": 0.9}], data, "pigmentation")
    assert [r["id"] for r in related] == [2]
    assert related[0]["source"] == "concern_only" and related[0]["origins"] == []
    assert skipped[0]["id"] == 1


def test_ml_normalization_and_best_origin_not_expansion_count():
    seeds = [{"id": 1, "score": 0.8}, {"id": 2, "score": 0.2}]
    data = catalog(
        [option("p", [3, 4])], functions={3: ["TAG"], 4: ["TAG"]}, concerns={"pores": ["TAG"]}
    )
    related = [{"id": i, "origins": [{"seedId": 1, "similarity": 1.0}]} for i in [3, 4]]
    first = rank_products(seeds, related, data, "pores")["matches"][0]
    assert first["mlScore"] == pytest.approx(0.4)
    assert first["concernScore"] == 1
    assert first["ingredientScore"] == pytest.approx(0.5)
    unrelated = [{"id": i, "origins": []} for i in range(100, 250)]
    assert rank_products(seeds, related + unrelated, data, "pores")["matches"][0] == first
    data.options[0].ingredient_ids.append(1)
    direct = rank_products(seeds, related, data, "pores")["matches"][0]
    assert direct["mlScore"] == pytest.approx(0.8)


def test_expansion_only_can_outrank_weak_direct_match():
    seeds = [{"id": 1, "score": 0.1}, {"id": 2, "score": 0.9}]
    data = catalog([option("direct", [1]), option("indirect", [3])])
    related = [{"id": 3, "origins": [{"seedId": 2, "similarity": 1.0}]}]
    result = rank_products(seeds, related, data, "pores")
    assert [r["productId"] for r in result["matches"]] == ["indirect", "direct"]


def test_purpose_excludes_explicit_neck_product_but_keeps_face_and_unknown():
    neck = option("neck", [1])
    neck.product_name = "레티노콜라겐 괄사 목주름 크림"
    assert product_purpose(neck)["reason"] == "explicit_non_facial_title"
    combined = neck.model_copy(update={"product_name": "얼굴과 목주름 겸용 크림"})
    assert product_purpose(combined)["status"] == "no_explicit_conflict"
    data = catalog([neck, option("unknown", [1])])
    result = rank_products([{"id": 1, "score": 0.9}], [], data, "wrinkles")
    assert result["excludedProducts"] == 1
    assert [r["productId"] for r in result["matches"]] == ["unknown"]
    wrong = neck.model_copy(update={"subcategory": "cleanser"})
    assert product_purpose(wrong)["reason"] == "incompatible_category"


def test_skin_type_bonus_requires_label_source():
    data = catalog([option("a", [1]), option("b", [1])])
    data.options[1].skin_types = ["dry"]
    result = rank_products([{"id": 1, "score": 1}], [], data, "pores", skin_type="dry")
    assert result["matches"][0]["productId"] == "a"
    data.options[1].label_source = "fixture confirmed product label"
    result = rank_products([{"id": 1, "score": 1}], [], data, "pores", skin_type="dry")
    assert result["matches"][0]["productId"] == "b"
    assert result["matches"][0]["skinTypeScore"] == 1


def test_diversity_bounded_by_relevance_and_stable_across_option_order():
    options = [
        option("a", [1, 10, 11]),
        option("b", [1, 10, 11]),
        option("c", [1, 20, 21]),
        option("weak", [2]),
    ]
    for o in options:
        o.subcategory = "cream"
    data = catalog(options)
    seeds = [{"id": 1, "score": 0.9}, {"id": 2, "score": 0.1}]
    result = rank_products(seeds, [], data, "pores")
    assert [r["productId"] for r in result["matches"]] == ["a", "c", "b", "weak"]
    assert result["matches"][2]["diversityPenalty"] == 0.02
    data.options.reverse()
    assert rank_products(seeds, [], data, "pores") == result


def test_rating_baseline_deduplicates_and_uses_review_count():
    a, b = option("a", [1], count=100), option("b", [2], count=300)
    a.review.rating_avg, b.review.rating_avg = 3.0, 5.0
    assert rating_baseline([a, a.model_copy(update={"option_id": "a-2"}), b]) == 4.5
    for invalid in (0, 5.1, float("nan")):
        with pytest.raises(ValidationError):
            ReviewEvidence(rating_avg=invalid)


def test_combined_review_uses_rating_count_and_target_ratio_with_fixed_range():
    review = ReviewEvidence(
        rating_avg=5, review_count=20, survey_ratios={"brighteningFirming": 0.8, "dry": 0.99}
    )
    result = combined_review(
        review,
        "wrinkles",
        {"brighteningFirming": 0.4},
        4.0,
        survey_policy="legacy_207",
        rating_policy="legacy_20",
        skin_review=False,
        review_policy="additive",
    )
    assert result["adjustedRating"] == 4.5
    assert result["surveyBonus"] == pytest.approx(0.05 * (20 / 227) * 0.4)
    assert result["rawCombinedScore"] == pytest.approx(4.5 + result["surveyBonus"])
    assert result["normalizedScore"] == pytest.approx((result["rawCombinedScore"] - 0.95) / 4.1)
    assert result["status"] == "rating_and_survey"
    review.review_count = 200
    more_reviews = combined_review(
        review,
        "wrinkles",
        {"brighteningFirming": 0.4},
        4.0,
        survey_policy="legacy_207",
        rating_policy="legacy_20",
        skin_review=False,
        review_policy="additive",
    )
    assert more_reviews["adjustedRating"] > result["adjustedRating"]
    assert more_reviews["surveyBonus"] > result["surveyBonus"]
    review.rating_avg = 3
    assert (
        combined_review(
            review,
            "wrinkles",
            {"brighteningFirming": 0.4},
            4.0,
            survey_policy="legacy_207",
            rating_policy="legacy_20",
            skin_review=False,
            review_policy="additive",
        )["adjustedRating"]
        < 4
    )


def test_pores_keeps_rating_component_without_inventing_survey_signal():
    review = ReviewEvidence(
        rating_avg=4.8,
        review_count=200,
        rating_percentages=(0, 0, 0, 20, 80),
        survey_ratios={"dry": 1.0, "brighteningFirming": 1.0},
    )
    result = combined_review(review, "pores", {"dry": 0.1, "brighteningFirming": 0.1}, 4.5)
    assert result["status"] == "rating_only"
    assert result["surveyStatus"] == "unsupported_signal"
    assert result["surveyBonus"] == 0 and result["signals"] == []
    assert result["adjustedRating"] > 4.5


def test_missing_rating_uses_explicit_prior_and_range_stays_bounded():
    missing = combined_review(
        ReviewEvidence(), "wrinkles", {}, 4.2, rating_policy="legacy_20", review_policy="additive"
    )
    assert missing["status"] == "prior_only" and missing["ratingAvg"] is None
    assert missing["adjustedRating"] == 4.2
    unrated = combined_review(
        ReviewEvidence(), "wrinkles", {}, None, rating_policy="legacy_20", review_policy="additive"
    )
    assert unrated["ratingPriorSource"] == "neutral_midpoint"
    assert unrated["normalizedScore"] == pytest.approx(0.5)
    for rating in (1, 5):
        for ratio in (0, 1):
            r = combined_review(
                ReviewEvidence(
                    rating_avg=rating,
                    review_count=1000000,
                    survey_ratios={"brighteningFirming": ratio},
                ),
                "wrinkles",
                {"brighteningFirming": 1 - ratio},
                rating,
            )
            assert 0 <= r["normalizedScore"] <= 1


def test_combined_mix_prefers_ratings_for_equal_ingredients_and_validates_weight():
    data = catalog([option("a", [1], count=200), option("b", [1], count=200)])
    data.options[0].review.rating_avg = 3.5
    data.options[0].review.rating_percentages = (0, 0, 50, 50, 0)
    data.options[1].review.rating_avg = 5.0
    data.options[1].review.rating_percentages = (0, 0, 0, 0, 100)
    seeds = [{"id": 1, "score": 1}]
    off = rank_products(seeds, [], data, "pores", review_mix_weight=0)
    on = rank_products(seeds, [], data, "pores")
    assert [r["productId"] for r in off["matches"]] == ["a", "b"]
    assert [r["productId"] for r in on["matches"]] == ["b", "a"]
    assert on["reviewAppliedProducts"] == 2
    assert all(0 <= r["score"] <= 1 for r in on["matches"])
    for invalid in (-0.1, 1.1, float("nan")):
        with pytest.raises(ValueError):
            rank_products(seeds, [], data, "pores", review_mix_weight=invalid)


@pytest.mark.parametrize(
    "goal,signal,k,mu",
    [
        ("wrinkles", "brighteningFirming", 3.193016787576364, 0.13761171088373558),
        ("pigmentation", "brighteningFirming", 3.193016787576364, 0.13761171088373558),
        ("dryness", "hydrating", 5.10486948620085, 0.512084654830041),
        ("sensitivity", "soothing", 4.46375008983532, 0.35832233101772876),
    ],
)
def test_empirical_priors_apply_exact_fitted_k_and_mu(goal, signal, k, mu):
    review = ReviewEvidence(review_count=10, survey_ratios={signal: 0.8, "dry": 1.0})
    value, evidence = survey_adjustment(review, goal, {signal: 0.99})
    assert value == pytest.approx(10 / (10 + k) * (0.8 - mu))
    assert evidence["priorK"] == k
    assert evidence["signals"][0]["baseline"] == mu
    assert evidence["reliability"] == pytest.approx(10 / (10 + k))
    assert evidence["baselineSource"] == "empirical_bayes_frozen"
    assert evidence["countBasis"] == "review_count_is_respondents_user_confirmed"
    # Changing other products cannot change the fitted prior at request time.
    assert survey_adjustment(review, goal, {}) == (value, evidence)
    review.survey_ratios[signal] = 0
    assert survey_adjustment(review, goal, {})[0] < 0
    review.review_count = 0
    zero, absent = survey_adjustment(review, goal, {})
    assert zero == 0 and absent["status"] == "missing_review_count"
    review.survey_ratios.clear()
    assert survey_adjustment(review, goal, {})[0] == 0


def test_empirical_and_legacy_ranking_change_only_survey_component():
    data = catalog([option("a", [1], 0.4, 10), option("b", [1], 0.8, 1000)])
    for o in data.options:
        o.review.rating_avg = 4.5
    legacy = rank_products(
        [{"id": 1, "score": 1}],
        [],
        data,
        "wrinkles",
        survey_policy="legacy_207",
        review_policy="additive",
    )
    current = rank_products([{"id": 1, "score": 1}], [], data, "wrinkles", review_policy="additive")
    assert legacy["beforeReview"] == current["beforeReview"]
    assert legacy["candidateProducts"] == current["candidateProducts"]
    for left, right in zip(legacy["matches"], current["matches"], strict=True):
        assert left["productId"] == right["productId"]
        assert left["ingredientScore"] == right["ingredientScore"]
        assert left["review"]["adjustedRating"] == right["review"]["adjustedRating"]
    assert current["surveyBaselines"]["brighteningFirming"] == 0.13761171088373558
    pores = rank_products([{"id": 1, "score": 1}], [], data, "pores")
    assert all(
        m["review"]["priorK"] is None and m["review"]["surveyBonus"] == 0 for m in pores["matches"]
    )
    with pytest.raises(ValueError, match="invalid_survey_policy"):
        rank_products([], [], catalog(), "wrinkles", survey_policy="typo")

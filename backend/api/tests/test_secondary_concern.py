from unittest.mock import patch

import pytest

from app.schemas.recommendation_comparison import (
    CandidateOption,
    ComparisonCatalog,
    ComparisonInput,
    ReviewEvidence,
)
from app.services.recommendation_v2_service import (
    feature_values,
    rank_products,
    recommend_v2,
    secondary_goal,
    target_goal,
    user_suitability,
)


def body(pores=0.9, pigmentation=0.6, wrinkles=0.2):
    return ComparisonInput(
        age_group="30대",
        gender="여성",
        skin_type="지성",
        analysis_version="skin-analysis-v4",
        score_kind="binary_caution_probability",
        aggregation="mean-cheeks-pore-tone-eyes-wrinkle-v1",
        scores={"pores": pores, "pigmentation": pigmentation, "wrinkles": wrinkles},
    )


def catalog():
    return ComparisonCatalog(
        version="test",
        digest="test",
        names={},
        source_manifest={},
        functions_by_id={1: ["P"], 2: ["W"]},
        functions_by_concern={"pores": ["P"], "wrinkles": ["W"]},
        options=[
            CandidateOption(
                product_id=pid,
                product_name=pid,
                option_id=pid,
                ingredient_ids=ids,
                review=ReviewEvidence(),
            )
            for pid, ids in (("a", [1]), ("b", [1, 2]), ("secondary_only", [2]))
        ],
    )


def test_auto_primary_unchanged_and_secondary_boundary_tie_order():
    b = body(pigmentation=0.499, wrinkles=0.1)
    assert target_goal(b) == "pores" and secondary_goal(b, "pores") is None
    b = body(pigmentation=0.5, wrinkles=0.5)
    assert secondary_goal(b, target_goal(b)) == "pigmentation"
    b = body(pores=0.8, pigmentation=0.8, wrinkles=0.8)
    assert target_goal(b) == "pores" and secondary_goal(b, "pores") == "pigmentation"


def test_secondary_scoring_keeps_primary_candidate_pool_and_explicit_weights():
    seeds = [{"id": 1, "score": 1}]
    secondary = {
        "goal": "wrinkles",
        "coreIngredients": [{"id": 2, "score": 1}],
        "expandedIngredients": [],
    }
    single = rank_products(seeds, [], catalog(), "pores")
    dual = rank_products(seeds, [], catalog(), "pores", secondary=secondary)
    assert single["candidateProducts"] == dual["candidateProducts"] == 2
    assert [m["productId"] for m in single["matches"]] == ["a", "b"]
    assert [m["productId"] for m in dual["matches"]] == ["b", "a"]
    for m in dual["matches"]:
        assert m["ingredientScore"] == pytest.approx(
            0.75 * m["primaryIngredientScore"] + 0.25 * m["secondaryIngredientScore"]
        )
        assert m["directIngredientIds"] == [1]
        assert m["goalWeights"] == {"pores": 0.75, "wrinkles": 0.25}
    assert dual["matches"][0]["secondaryIngredientEvidence"]["directIngredientIds"] == [2]
    with pytest.raises(ValueError, match="invalid_secondary_concern"):
        rank_products(seeds, [], catalog(), "pores", secondary={**secondary, "goal": "pores"})


def test_shared_survey_deduplicated_and_unsupported_concern_not_zeroed():
    review = ReviewEvidence(
        review_count=100, survey_ratios={"brighteningFirming": 0.7, "oily": 0.4}
    )
    single, _ = user_suitability(review, "wrinkles", "oily")
    shared, signals = user_suitability(review, "wrinkles", "oily", secondary_concern="pigmentation")
    assert shared == single
    concern = [s for s in signals if s["source"] == "concern"]
    assert len(concern) == 1 and concern[0]["weight"] == 1
    assert concern[0]["goals"] == ["wrinkles", "pigmentation"]
    unsupported_primary, signals = user_suitability(
        review, "pores", "oily", secondary_concern="wrinkles"
    )
    assert unsupported_primary == single
    assert next(s for s in signals if s["signal"] == "brighteningFirming")["effectiveWeight"] == 1


def test_two_distinct_supported_survey_answers_use_weighted_mean_before_skin():
    r = ReviewEvidence(review_count=100, survey_ratios={"hydrating": 0.8, "soothing": 0.2})
    u, signals = user_suitability(r, "dryness", "balanced", secondary_concern="sensitivity")
    values = {s["signal"]: s["posteriorRatio"] for s in signals}
    assert u == pytest.approx(0.75 * values["hydrating"] + 0.25 * values["soothing"])


def test_second_inference_changes_only_target_feature_and_inactive_matches_single():
    b = body()

    def predict(request, goal, bundle):
        return [{"id": 1 if goal == "pores" else 2, "score": 1}], {
            "features": feature_values(request, goal)
        }

    with patch("app.services.recommendation_v2_service.predict_seeds", side_effect=predict) as mock:
        result = recommend_v2(b, target_goal(b), catalog(), "unused")
        assert mock.call_count == 2 and result["secondaryConcern"] == "pigmentation"
        values = result["model"]["features"]
        other = result["secondaryRecommendation"]["model"]["features"]
        assert [i for i, (a, c) in enumerate(zip(values, other, strict=True)) if a != c] == [3]
        inactive = body(pigmentation=0.3)
        automatic = recommend_v2(inactive, "pores", catalog(), "unused")
        disabled = recommend_v2(inactive, "pores", catalog(), "unused", enable_secondary=False)
        assert automatic["matches"] == disabled["matches"]
        assert automatic["secondaryConcern"] is None

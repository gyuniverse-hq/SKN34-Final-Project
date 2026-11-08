import pytest

from app.schemas.skincare import HybridRequest
from app.services.skincare_service import _recommend_hybrid_unfiltered as recommend_hybrid
from app.services.skincare_service import ingredient_weights
from tests.test_skincare import option, snapshot
from tests.test_skincare_hybrid import distinct_ingredients, reviewed


def test_common_ingredients_have_lower_discrimination_and_product_options_are_deduplicated():
    options = [option(str(i), ingredient_codes=["A", "B"] if i < 2 else ["A"]) for i in range(100)]
    data = snapshot(options, [reviewed(), reviewed(mapping_id="b", ingredient_codes=["B"])])
    weights, breadth = ingredient_weights(data)
    assert weights["A"] == 0
    assert weights["B"] == pytest.approx(1)  # 1% and 2% do not get uncapped rarity bonuses.
    duplicate = options[0].model_copy(update={"option_id": "another"})
    data.options.append(duplicate)
    assert ingredient_weights(data) == (weights, breadth)


def test_repeated_support_is_penalized_without_an_ingredient_quota(monkeypatch):
    data = distinct_ingredients(
        snapshot(
            [
                option(f"a{i}", matched_mapping_ids=["a"], review_count=1000, rating_avg=4.9)
                for i in range(6)
            ]
            + [option("b", matched_mapping_ids=["b"], review_count=1000, rating_avg=4.8)],
            [reviewed(mapping_id="a"), reviewed(mapping_id="b")],
        )
    )
    req = HybridRequest(primaryGoal="dryness")
    # Isolate the similarity term from the commonness correction.
    monkeypatch.setattr("app.services.skincare_service.PROFILE_WEIGHT", 0)
    monkeypatch.setattr("app.services.skincare_service.COMPLEMENT_WEIGHT", 0)
    result = recommend_hybrid(data, req)
    assert result.overall_top5[0].product.id == "a0"
    assert result.overall_top5[1].product.id == "b"
    assert len(result.overall_top5) == 5  # Similar products can still fill remaining slots.
    monkeypatch.setattr("app.services.skincare_service.REDUNDANCY_WEIGHT", 0)
    assert all(m.product.id.startswith("a") for m in recommend_hybrid(data, req).overall_top5)


def test_multi_goal_ingredient_breadth_and_unknown_conditions_are_explicit():
    data = snapshot(
        [option(matched_mapping_ids=["m", "p"])],
        [reviewed(), reviewed(mapping_id="p", target_concern="pores")],
    )
    _, breadth = ingredient_weights(data)
    assert breadth["A"] == 2
    result = recommend_hybrid(data, HybridRequest(primaryGoal="dryness"))
    reason = result.overall_top5[0].reasons[0]
    assert reason.ingredient_codes == ["A"]
    assert reason.evidence_level == "ingredient_presence"

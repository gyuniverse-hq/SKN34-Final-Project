import pytest

from app.services.skincare_service import ingredient_weights, recommend_hybrid
from tests.test_skincare import cosing, option, request, snapshot


def test_common_ingredients_have_lower_discrimination_and_product_options_are_deduplicated():
    options = [option(str(i), ingredient_codes=["A", "B"] if i < 2 else ["A"]) for i in range(100)]
    data = snapshot(options, [])
    weights = ingredient_weights(data)
    assert weights["A"] == 0
    assert weights["B"] == pytest.approx(1)  # 1% and 2% do not get uncapped rarity bonuses.
    duplicate = options[0].model_copy(update={"option_id": "another"})
    data.options.append(duplicate)
    assert ingredient_weights(data) == weights


def test_equal_fit_and_reviews_prefer_different_support_in_the_overall_list():
    data = snapshot(
        [
            option(f"a{i}", matched_mapping_ids=["a"], review_count=1000, rating_avg=4.8)
            for i in range(6)
        ]
        + [
            option(
                "b",
                ingredient_codes=["B"],
                matched_mapping_ids=["b"],
                review_count=1000,
                rating_avg=4.8,
            )
        ],
        [
            cosing(mapping_id="a"),
            cosing(mapping_id="b", ingredient_codes=["B"], function_names=["MOISTURISING"]),
        ],
    )
    result = recommend_hybrid(data, request())
    assert [m.product.id for m in result.overall_top10] == ["a0", "b", "a1", "a2", "a3", "a4", "a5"]
    assert result.by_concern["dryness"][0].reasons[0].evidence_level == "ingredient_presence"

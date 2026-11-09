"""V4 browse ranking prioritizes configured function coverage over product reviews."""

import pytest

from app.schemas.skincare import HybridRequest, SkincareProfileRequest, SkincareSnapshot
from app.services.skincare_service import recommend_hybrid
from tests.test_skincare import option
from tests.test_skincare_cosing import cosing


def rule(id, goal, *functions, **changes):
    return cosing(
        mapping_id=id, ingredient_codes=[id], target_concern=goal,
        function_names=list(functions), **changes,
    )


def product(id, *rules, **changes):
    return option(id, **({
        "ingredient_codes": list(rules), "matched_mapping_ids": list(rules),
    } | changes))


def ids(matches):
    return [m.product.id for m in matches]


def snapshot(options, mappings):
    return SkincareSnapshot(
        data_version="test", source_manifest={"source": "fixture"},
        options=options, mappings=mappings, evidence={},
        ingredient_provenance={
            code: {"source": "cosing", "reviewedBy": "tester"}
            for mapping in mappings for code in mapping.ingredient_codes
        },
    )


def test_fit_beats_reviews_and_profile_labels_but_equal_fit_uses_reviews():
    rules = [rule("a", "pores", "ASTRINGENT"), rule("k", "pores", "KERATOLYTIC")]
    data = snapshot([
        product("popular", "a", rating_avg=5, review_count=10000,
                skin_types=["dry"], sensitive_label=True, label_source="manufacturer"),
        product("complete", "a", "k", rating_avg=3, review_count=100),
        product("complete-better-review", "a", "k", rating_avg=4, review_count=100),
    ], rules)
    req = SkincareProfileRequest(skinType="dry", irritationSignal="caution")
    assert ids(recommend_hybrid(data, req).by_concern["pores"]) == [
        "complete-better-review", "complete", "popular",
    ]
    # A client on the old contract retains its original review-first ordering.
    legacy = HybridRequest(primaryGoal="pores", skinType="dry", irritationSignal="caution")
    assert ids(recommend_hybrid(data, legacy).by_concern["pores"])[0] == "popular"


def test_duplicate_functions_and_other_concerns_cannot_inflate_fit():
    rules = [
        rule("a", "pores", "ASTRINGENT", "ASTRINGENT"),
        rule("b", "pores", "ASTRINGENT"),
        rule("c", "pores", "ASTRINGENT"),
        rule("k", "pores", "KERATOLYTIC"),
        rule("w", "wrinkles", "SMOOTHING", "UV FILTER"),
    ]
    data = snapshot([
        product("many", "a", "b", "c", "w", rating_avg=5, review_count=10000),
        product("focused", "a", "k"),
    ], rules)
    assert ids(recommend_hybrid(data, SkincareProfileRequest()).by_concern["pores"]) == [
        "focused", "many",
    ]


def test_each_tab_ranks_shared_candidates_using_only_its_own_functions():
    rules = [
        rule("p1", "pigmentation", "EXFOLIATING"),
        rule("p2", "pigmentation", "KERATOLYTIC"),
        rule("w1", "wrinkles", "SMOOTHING"),
        rule("w2", "wrinkles", "UV FILTER"),
    ]
    data = snapshot([
        product("tone", "p1", "p2", "w1", rating_avg=4, review_count=100),
        product("wrinkle", "p1", "w1", "w2", rating_avg=5, review_count=100),
    ], rules)
    for req in (SkincareProfileRequest(), SkincareProfileRequest(
        detectedConcerns=[{"goal": "pores", "sources": ["analysis"]}],
    )):
        result = recommend_hybrid(data, req)
        assert ids(result.by_concern["pigmentation"]) == ["tone", "wrinkle"]
        assert ids(result.by_concern["wrinkles"]) == ["wrinkle", "tone"]


@pytest.mark.parametrize("extra, first", [
    ({}, "oil-complete"),
    ({"skinType": "dry"}, "dry-partial"),
    ({"detectedConcerns": [{"goal": "oiliness", "sources": ["analysis"]}]}, "oil-complete"),
    ({"skinType": "dry", "detectedConcerns": [
        {"goal": "oiliness", "sources": ["analysis"]},
    ]}, "oil-complete"),
])
def test_balance_normalizes_each_goal_and_preserves_profile_priority(extra, first):
    rules = [
        rule("dry", "dryness", "MOISTURISING", "SKIN CONDITIONING - HUMECTANT"),
        rule("other-dry", "dryness", "SKIN CONDITIONING - OCCLUSIVE"),
        rule("oil", "oiliness", "ANTI-SEBUM"),
    ]
    data = snapshot([
        product("dry-partial", "dry", rating_avg=5, review_count=10000),
        product("oil-complete", "oil", rating_avg=3, review_count=100),
    ], rules)
    result = recommend_hybrid(data, SkincareProfileRequest(**extra))
    assert ids(result.balance_matches)[0] == first


def test_unverified_disabled_and_wrong_option_mappings_do_not_add_functions():
    rules = [
        rule("a", "pores", "ASTRINGENT"),
        rule("b", "pores", "KERATOLYTIC", runtime_enabled=False),
        rule("c", "pores", "EXFOLIATING", identity_verified=False),
        rule("d", "pores", "ANTI-SEBUM"),
    ]
    data = snapshot([
        product("valid", "a", rating_avg=5, review_count=100),
        product("invalid-extras", "a", "b", "c", "d", ingredient_codes=["a", "b", "c"],
                rating_avg=4, review_count=100),
    ], rules)
    assert ids(recommend_hybrid(data, SkincareProfileRequest()).by_concern["pores"]) == [
        "valid", "invalid-extras",
    ]


def test_five_unique_products_and_stable_order_with_missing_reviews():
    rules = [rule("a", "pores", "ASTRINGENT")]
    options = [product(str(i), "a") for i in range(7)]
    options.append(product("duplicate-option", "a", product=options[0].product))
    req = SkincareProfileRequest()
    result = recommend_hybrid(snapshot(options, rules), req)
    assert ids(result.by_concern["pores"]) == ["0", "1", "2", "3", "4"]
    assert recommend_hybrid(snapshot(list(reversed(options)), rules), req) == result

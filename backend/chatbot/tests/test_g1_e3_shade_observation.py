from tests.g1_e3_live_driver import detail_source_shade_pairs
from tests.run_g1_evaluation import grade


def test_detail_source_shades_keep_product_ownership():
    results = [
        {
            "operation": "detail",
            "productId": "target",
            "product": {"id": "target", "shades": [{"id": "a"}, {"id": "b"}]},
        }
    ]
    assert detail_source_shade_pairs(results) == [
        {"productId": "target", "shadeId": "a"},
        {"productId": "target", "shadeId": "b"},
    ]


def test_missing_or_partial_detail_does_not_fabricate_source_pairs():
    assert detail_source_shade_pairs([]) is None
    assert detail_source_shade_pairs([{"operation": "detail", "product": None}]) is None
    assert (
        detail_source_shade_pairs(
            [{"operation": "detail", "productId": "target", "product": {"id": "target"}}]
        )
        is None
    )
    assert (
        detail_source_shade_pairs(
            [{"operation": "detail", "productId": "target", "product": {"id": "other"}}]
        )
        is None
    )
    assert detail_source_shade_pairs([{"operation": "search", "products": []}]) is None


def test_response_shades_must_be_observed_and_belong_to_target():
    observation = {
        "httpStatus": 200,
        "sourceSnapshotId": "selected-fixture-rows",
        "sourceShadePairs": [{"productId": "target", "shadeId": "target-shade"}],
    }
    assert grade("response.no_mismatched_shade", observation) == "NOT_RUN"
    observation["responseShadePairs"] = [{"productId": "target", "shadeId": "foreign-shade"}]
    assert grade("response.no_mismatched_shade", observation) == "FAIL"
    observation["responseShadePairs"] = [{"productId": "target", "shadeId": "target-shade"}]
    assert grade("response.no_mismatched_shade", observation) == "PASS"

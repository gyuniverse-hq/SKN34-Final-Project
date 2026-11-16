from tests.g1_e3_live_driver import detail_source_shade_pairs
from tests.run_g1_evaluation import grade


def test_shared_detail_observation_withholds_unverified_prose():
    from tests.g1_e1_live_driver import observe_detail_shades

    rows = [{"product_id": "p", "id": "s", "name": "01호"}]
    assert observe_detail_shades("G1-CAT-04", {"answer": "색상이 있어요"}, "p", rows, {}) == {}
    observed = observe_detail_shades("G1-CAT-04", {"answer": "확인된 색상: 01호"}, "p", rows, {})
    assert observed["responseShadePairs"] == [{"productId": "p", "shadeId": "s"}]
    foreign = rows + [{"product_id": "other", "id": "foreign", "name": "02호"}]
    observed = observe_detail_shades("G1-CAT-04", {"answer": "확인된 색상: 02호"}, "p", foreign, {})
    assert observed["status"] == "FAIL"
    assert "responseShadePairs" not in observed


def test_cat12_observation_rejects_leaked_selection_and_empty_response():
    from tests.g1_e1_live_driver import observe_detail_shades

    fixture = {"foreignShadeName": "다른 상품 색상"}
    for payload in (
        {},
        {"answer": "", "products": []},
        {
            "answer": "색상을 확인해 주세요",
            "products": [],
            "resultType": "clarification",
            "chatContext": {"shadeSelections": {"p": "foreign"}},
        },
    ):
        observed = observe_detail_shades("G1-CAT-12", payload, "p", [], fixture)
        assert observed["status"] == "FAIL"


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

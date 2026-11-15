from copy import deepcopy

from tests.run_g1_evaluation import grade


def observed_detail_not_found():
    return {
        "requestId": "run-one",
        "httpStatus": 200,
        "screenProductId": "missing-product",
        "sourceSnapshotId": "selected-fixture-rows",
        "sourceProductIds": [],
        "catalogResultCount": 0,
        "response": {"answer": "상품을 찾지 못했습니다.", "products": [], "resultType": "empty"},
        "trace": {
            "requestId": "run-one",
            "complete": False,
            "completeDomains": ["catalogHttp"],
            "catalogHttp": [
                {
                    "name": "catalog.get_product_detail",
                    "method": "GET",
                    "path": "/api/products/{productId}",
                    "productId": "missing-product",
                    "status": 404,
                }
            ],
        },
    }


def test_empty_detail_404_with_matching_target_has_no_unverified_product():
    obs = observed_detail_not_found()
    assert grade("response.no_unverified_product_ids", obs) == "PASS"
    assert grade("response.empty_not_fabricated", obs) == "FAIL"  # search contract is distinct


def test_detail_404_for_another_target_or_non_404_does_not_pass():
    for field, value in (("productId", "another-product"), ("status", 200), ("status", 502)):
        obs = observed_detail_not_found()
        obs["trace"]["catalogHttp"][0][field] = value
        assert grade("response.no_unverified_product_ids", obs) == "FAIL"


def test_detail_evidence_or_product_identity_missing_stays_not_run():
    original = observed_detail_not_found()
    obs = deepcopy(original)
    del obs["trace"]["catalogHttp"][0]["productId"]
    assert grade("response.no_unverified_product_ids", obs) == "NOT_RUN"
    obs = deepcopy(original)
    obs["trace"]["completeDomains"] = []
    assert grade("response.no_unverified_product_ids", obs) == "NOT_RUN"


def test_empty_detail_cannot_hide_unverified_products():
    obs = observed_detail_not_found()
    obs["response"]["products"] = [
        {"id": "invented", "name": "invalid", "brand": "unknown", "category": "lip"}
    ]
    assert grade("response.no_unverified_product_ids", obs) == "FAIL"

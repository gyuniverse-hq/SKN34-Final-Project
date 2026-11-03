import pytest

from tests.product_eval_adapter import normalize_response, summarize_observations


def response(**changes):
    return {"answer": "Observed answer", "products": [], **changes}


def test_missing_execution_and_intent_are_never_filled():
    normalized = normalize_response(response(resultType="empty"))
    assert normalized["apiSchema"] == "PASS"
    assert normalized["prediction"] == {"responseText": "Observed answer", "status": "INFO"}
    assert "intent_id" in normalized["notObservable"]
    assert "applied" not in normalized["prediction"]
    assert "selectedProductId" not in normalized["prediction"]
    result = summarize_observations(
        normalized, {"empty": True}, policy_hold=False, catalog_mode="ACTUAL_CATALOG"
    )
    assert result["observedBehavior"] == "PASS"
    assert result["fullContract"] == "NOT_OBSERVABLE"


def test_schema_failure_is_separate_from_behavior_failure():
    invalid = normalize_response({"answer": [], "products": []})
    assert invalid["apiSchema"] == "SCHEMA_FAIL"
    normal = normalize_response(response())
    result = summarize_observations(
        normal, {"price": False}, policy_hold=False, catalog_mode="FIXED_SYNTHETIC_FIXTURE"
    )
    assert result["observedBehavior"] == "FAIL"
    assert normal["apiSchema"] == "PASS"


def test_policy_hold_remains_blocked_even_when_observed_checks_pass():
    result = summarize_observations(
        normalize_response(response()),
        {"clarifies": True},
        policy_hold=True,
        catalog_mode="FIXED_SYNTHETIC_FIXTURE",
    )
    assert result["fullContract"] == "BLOCKED"
    assert result["observedBehavior"] == "PASS"
    assert result["goldApprovalChanged"] is False


def test_multiple_evidence_cannot_become_selected_product_or_full_list():
    normalized = normalize_response(
        response(
            evidence=[
                {"productId": "P-A", "ingredientCoverage": "key_only"},
                {"productId": "P-B", "ingredientCoverage": "unknown"},
            ]
        )
    )
    assert "evidenceProductId" not in normalized["prediction"]
    assert "selectedProductId" not in normalized["prediction"]


def test_explicit_provenance_and_boolean_observations_required():
    normal = normalize_response(response())
    with pytest.raises(ValueError):
        summarize_observations(normal, {}, policy_hold=False, catalog_mode="MIXED")
    with pytest.raises(ValueError):
        summarize_observations(
            normal, {"expected": "P-B"}, policy_hold=False, catalog_mode="ACTUAL_CATALOG"
        )
    result = summarize_observations(normal, {}, policy_hold=False, catalog_mode="ACTUAL_CATALOG")
    assert result["observedBehavior"] == "NOT_OBSERVABLE"


def test_raw_observed_products_are_kept_without_oracle_enrichment():
    raw = response(products=[{"id": "real-id", "brand": "B", "name": "N", "category": "lip"}])
    normalized = normalize_response(raw)
    assert normalized["observedFields"]["products"] == raw["products"]
    assert "selectedProductId" not in normalized["prediction"]
    assert "chatContext" not in normalized["observedFields"]

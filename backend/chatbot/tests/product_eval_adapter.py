"""Normalize observations only; never infer execution or intent from a test oracle."""

from pydantic import ValidationError

from app.schemas.chat import ChatResponse

LEGACY_REQUIRED = ("intent_id", "applied", "checkoutExecuted", "commands")


def normalize_response(response):
    """Return an independent legacy projection plus explicit unavailable fields."""
    try:
        ChatResponse.model_validate(response)
    except ValidationError as exc:
        return {
            "apiSchema": "SCHEMA_FAIL",
            "errors": exc.errors(),
            "prediction": {},
            "notObservable": list(LEGACY_REQUIRED),
        }
    prediction = {"responseText": response["answer"]}
    statuses = {
        "recommendations": "INFO",
        "product_detail": "INFO",
        "empty": "INFO",
        "clarification": "CLARIFICATION",
    }
    if response.get("resultType") in statuses:
        prediction["status"] = statuses[response["resultType"]]
    context = response.get("chatContext") or {}
    if context.get("selectedProductId") is not None:
        prediction["selectedProductId"] = context["selectedProductId"]
    evidence = response.get("evidence") or []
    if len(evidence) == 1:
        item = evidence[0]
        prediction["evidenceProductId"] = item["productId"]
        coverage = item.get("ingredientCoverage")
        if coverage in {"key_only", "unknown"}:
            prediction["fullIngredientsConfirmed"] = False
            prediction["evidenceCompleteness"] = (
                "PARTIAL_ONLY" if coverage == "key_only" else "UNKNOWN"
            )
    return {
        "apiSchema": "PASS",
        "observedFields": {
            key: response[key]
            for key in ("answer", "resultType", "chatContext", "evidence", "products")
            if key in response
        },
        "prediction": prediction,
        "notObservable": [
            *LEGACY_REQUIRED,
            "native resultSetId",
            "screen state",
            "actual AR application",
        ],
        "mapping": {
            "responseText": "answer",
            "status": "resultType (coarse mapping)",
            "selectedProductId": "chatContext.selectedProductId",
            "evidenceProductId": "single evidence.productId",
        },
    }


def summarize_observations(normalized, checks, *, policy_hold, catalog_mode):
    """Checks are exploratory assertions, never inputs to normalization."""
    if catalog_mode not in {"FIXED_SYNTHETIC_FIXTURE", "ACTUAL_CATALOG"}:
        raise ValueError("Explicit fixture/Catalog provenance required")
    if any(type(value) is not bool for value in checks.values()):
        raise ValueError("Observable checks must be explicit booleans")
    behavior = "NOT_OBSERVABLE" if not checks else "PASS" if all(checks.values()) else "FAIL"
    if normalized["apiSchema"] != "PASS":
        behavior = "SCHEMA_FAIL"
    return {
        "catalogMode": catalog_mode,
        "observedBehavior": behavior,
        "checks": checks,
        "fullContract": "BLOCKED" if policy_hold else "NOT_OBSERVABLE",
        "policyHold": policy_hold,
        "goldApprovalChanged": False,
    }

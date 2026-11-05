"""All product, option, review and provenance values here are SYNTHETIC fixtures."""

from copy import deepcopy
from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from app.schemas.catalog import CatalogBundle
from app.schemas.ingredient import (
    IngredientCondition,
    IngredientDecision,
    IngredientEvidence,
    IngredientLookupResult,
)
from app.services.ingredient_service import evaluate_ingredient, normalize_ingredient_name
from tests.conftest import SAMPLE


@pytest.fixture
def evidence():
    return IngredientEvidence(
        productId="fixture-product",
        shadeId="fixture-shade",
        optionId="fixture-option",
        evidenceId="SYNTHETIC:evidence-1",
        ingredients=[{"name": "Water", "sequence": 1}, {"name": "Panthenol", "sequence": 2}],
        ingredientCoverage="full",
        source="option_ingredients",
        sourceRef="fixture://only",
        collectedAt=datetime(2026, 11, 2, tzinfo=UTC),
        reviewStatus="verified",
        mappingStatus="verified",
        normalizationStatus="verified",
        synthetic=True,
    )


def condition(name="Panthenol", operator="includes", **changes):
    return IngredientCondition.model_validate(
        dict(
            productId="fixture-product",
            shadeId="fixture-shade",
            optionId="fixture-option",
            ingredientName=name,
            operator=operator,
            **changes,
        )
    )


def evaluate(evidence, name="Panthenol", operator="includes"):
    return evaluate_ingredient(
        condition(name, operator), IngredientLookupResult(status="ok", evidence=evidence)
    )


@pytest.mark.parametrize(
    "name,operator,expected",
    [
        ("Panthenol", "includes", "MATCH"),
        ("Panthenol", "excludes", "NOT_MATCH"),
        ("Fragrance", "includes", "UNKNOWN"),
        ("Fragrance", "excludes", "UNKNOWN"),
    ],
)
def test_presence_and_unresolved_absence(evidence, name, operator, expected):
    result = evaluate(evidence, name, operator)
    assert result.verdict == expected
    assert result.evidence_id == "SYNTHETIC:evidence-1" and result.synthetic


@pytest.mark.parametrize("operator", ["includes", "excludes"])
def test_partial_list_does_not_prove_absence(evidence, operator):
    evidence.ingredient_coverage = "partial"
    assert evaluate(evidence, "Fragrance", operator).verdict == "UNKNOWN"
    assert evaluate(evidence).verdict == "MATCH"  # reviewed positive presence is still evidence


@pytest.mark.parametrize(
    "field,value",
    [
        ("mapping_status", "unverified"),
        ("mapping_status", "ambiguous"),
        ("review_status", "unreviewed"),
        ("review_status", "rejected"),
        ("ingredient_coverage", "unknown"),
        ("source_ref", None),
        ("collected_at", None),
        ("source", "mfds_dictionary"),
        ("source", "key_ingredients"),
    ],
)
def test_unverified_or_non_product_sources_cannot_establish_presence(evidence, field, value):
    setattr(evidence, field, value)
    assert evaluate(evidence).verdict == "UNKNOWN"


def test_option_specific_facts_and_foreign_product_selection(evidence):
    other = evidence.model_copy(deep=True)
    other.option_id, other.shade_id, other.evidence_id = (
        "fixture-other-option",
        "other-shade",
        "SYNTHETIC:2",
    )
    other.ingredients = other.ingredients[:1]
    assert evaluate(evidence).verdict == "MATCH"
    req = condition().model_copy(update={"option_id": other.option_id, "shade_id": other.shade_id})
    assert (
        evaluate_ingredient(req, IngredientLookupResult(status="ok", evidence=other)).verdict
        == "UNKNOWN"
    )
    for change in [
        {"product_id": "foreign"},
        {"option_id": other.option_id},
        {"shade_id": other.shade_id},
        {"option_id": None},
        {"shade_id": None},
    ]:
        result = evaluate_ingredient(
            condition().model_copy(update=change),
            IngredientLookupResult(status="ok", evidence=evidence),
        )
        assert result.verdict == "UNKNOWN" and result.evidence_id is None


@pytest.mark.parametrize(
    "status,code,expected",
    [
        ("not_found", None, "UNKNOWN"),
        ("error", "ingredient_lookup_failed", "ERROR"),
    ],
)
def test_missing_evidence_is_distinct_from_database_failure(status, code, expected):
    result = evaluate_ingredient(condition(), IngredientLookupResult(status=status, errorCode=code))
    assert result.verdict == expected and result.evidence_id is None


def test_empty_full_list_and_unreviewed_normalization_do_not_prove_absence(evidence):
    evidence.normalization_status = "unverified"
    assert evaluate(evidence, "Fragrance", "excludes").verdict == "UNKNOWN"
    evidence.normalization_status = "verified"
    evidence.ingredients = []
    assert evaluate(evidence, "Fragrance", "excludes").verdict == "UNKNOWN"


@pytest.mark.parametrize(
    "entries",
    [
        [{"name": "Water"}],
        [{"name": "Water", "sequence": 1}, {"name": "Panthenol", "sequence": 1}],
        [{"name": "Water", "sequence": 1}, {"name": "Panthenol", "sequence": 3}],
        [{"name": "Water", "sequence": 1}, {"name": " WATER ", "sequence": 2}],
    ],
)
def test_inconsistent_parsing_blocks_negative_evidence(evidence, entries):
    payload = evidence.model_dump()
    payload["ingredients"] = entries
    checked = IngredientEvidence.model_validate(payload)
    assert evaluate(checked, "Fragrance", "excludes").verdict == "UNKNOWN"


def test_conservative_comparison_does_not_infer_synonyms_or_strip_qualifiers(evidence):
    assert normalize_ingredient_name("  ＷＡＴＥＲ ") == "water"
    assert evaluate(evidence, " panthenol ").verdict == "MATCH"
    assert normalize_ingredient_name("CI 77491") != normalize_ingredient_name("CI 77492")
    evidence.ingredient_coverage = "partial"
    assert evaluate(evidence, "Provitamin B5").verdict == "UNKNOWN"


def test_contract_camel_case_and_legacy_catalog_are_unchanged(evidence):
    before = SAMPLE.model_dump(mode="json")
    snapshot = deepcopy(evidence.model_dump(mode="json"))
    result = evaluate(evidence)
    output = result.model_dump(mode="json")
    assert output["productId"] == "fixture-product" and output["verdict"] == "MATCH"
    assert IngredientDecision.model_validate(output) == result
    assert evidence.model_dump(mode="json") == snapshot
    assert CatalogBundle.model_validate(before).model_dump(mode="json") == before
    assert "fullIngredients" not in before["products"][0]
    assert before["products"][0]["keyIngredients"] == ["niacinamide"]
    with pytest.raises(ValidationError):
        IngredientEvidence.model_validate({**snapshot, "keyIngredients": ["Water"]})


@pytest.mark.parametrize(
    "payload",
    [
        {"status": "ok"},
        {"status": "error"},
        {"status": "not_found", "errorCode": "failed"},
    ],
)
def test_invalid_lookup_states_are_rejected(payload):
    with pytest.raises(ValidationError):
        IngredientLookupResult.model_validate(payload)


def test_supervisor_projection_has_only_compatible_fields(evidence):
    from app.services.ingredient_service import to_supervisor_condition

    result = evaluate(evidence)
    assert to_supervisor_condition(result) == {
        "condition": "ingredient",
        "verdict": "MATCH",
        "productId": "fixture-product",
        "reason": "ingredient_present",
    }


def test_source_time_requires_an_explicit_timezone(evidence):
    payload = evidence.model_dump()
    payload["collectedAt"] = "2026-11-02T09:46:05"
    with pytest.raises(ValidationError):
        IngredientEvidence.model_validate(payload)

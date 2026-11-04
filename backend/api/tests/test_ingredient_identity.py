"""Synthetic name-identity cases; no dictionary or operating product data."""

import pytest

from app.schemas.ingredient import IngredientEntry
from tests.test_ingredient_service import evaluate
from tests.test_ingredient_service import evidence as evidence


@pytest.mark.parametrize(
    "source,query",
    [
        ("레티놀", "retinol"),
        ("Retinol", "レチノール"),
        ("视黄醇", "retinol"),
        ("Panthenol", "Provitamin B5"),
        ("Retinyl Palmitate", "Retinol"),
    ],
)
@pytest.mark.parametrize("operator", ["includes", "excludes"])
def test_missing_name_never_proves_chemical_absence(evidence, source, query, operator):
    evidence.ingredients = [IngredientEntry(name=source, sequence=1)]
    before = evidence.model_dump()
    result = evaluate(evidence, query, operator)
    assert result.verdict == "UNKNOWN"
    assert result.reason == "ingredient_identity_unresolved"
    assert result.evidence_id == evidence.evidence_id
    assert evidence.model_dump() == before


@pytest.mark.parametrize("operator,verdict", [("includes", "MATCH"), ("excludes", "NOT_MATCH")])
def test_literal_presence_remains_conclusive(evidence, operator, verdict):
    result = evaluate(evidence, "  PANTHENOL  ", operator)
    assert (result.verdict, result.reason) == (verdict, "ingredient_present")

"""Pure ingredient evaluation and read-only lookup orchestration; no catalog mutation."""

import unicodedata

from fastapi import Depends
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.db import get_session
from app.core.errors import ApiError
from app.repositories.ingredient_repository import IngredientRepository
from app.schemas.ingredient import (
    IngredientCondition,
    IngredientDecision,
    IngredientIdentity,
    IngredientLookupResult,
    IngredientReadResult,
)


def normalize_ingredient_name(value: str) -> str:
    """Conservative comparison: preserve punctuation, qualifiers and concentration text."""
    return " ".join(unicodedata.normalize("NFKC", value).casefold().split())


def evaluate_ingredient(
    condition: IngredientCondition,
    lookup: IngredientLookupResult,
    query_identity: IngredientIdentity | None = None,
) -> IngredientDecision:
    def decision(verdict, reason, *, evidence_id=None, synthetic=False):
        return IngredientDecision(
            product_id=condition.product_id,
            shade_id=condition.shade_id,
            option_id=condition.option_id,
            ingredient_name=condition.ingredient_name,
            operator=condition.operator,
            verdict=verdict,
            reason=reason,
            evidence_id=evidence_id,
            synthetic=synthetic,
            query_identity=query_identity,
        )

    if lookup.status == "error":
        return decision("ERROR", lookup.error_code)
    if lookup.status == "not_found":
        return decision("UNKNOWN", "evidence_not_found")
    evidence = lookup.evidence
    assert evidence is not None  # enforced by the lookup contract
    if not condition.option_id:
        return decision("UNKNOWN", "selection_required", synthetic=evidence.synthetic)
    if (condition.product_id, condition.shade_id, condition.option_id) != (
        evidence.product_id,
        evidence.shade_id,
        evidence.option_id,
    ):
        return decision("UNKNOWN", "selection_mismatch", synthetic=evidence.synthetic)

    def supported(verdict, reason):
        return decision(
            verdict, reason, evidence_id=evidence.evidence_id, synthetic=evidence.synthetic
        )

    if evidence.mapping_status != "verified":
        return supported("UNKNOWN", "mapping_not_verified")
    if evidence.source not in {"product_notice", "option_ingredients"}:
        return supported("UNKNOWN", "not_product_ingredient_evidence")
    if evidence.review_status != "verified":
        return supported("UNKNOWN", "evidence_not_reviewed")
    if not evidence.source_ref or evidence.collected_at is None:
        return supported("UNKNOWN", "provenance_incomplete")
    if evidence.ingredient_coverage == "unknown" or not evidence.ingredients:
        return supported("UNKNOWN", "ingredients_unavailable")
    target = normalize_ingredient_name(condition.ingredient_name)
    names = [normalize_ingredient_name(item.name) for item in evidence.ingredients]
    if not target or not all(names):
        return supported("UNKNOWN", "invalid_ingredient_name")
    if target in names or (
        query_identity is not None
        and any(
            item.identity is not None
            and item.identity.mfds_ingredient_id == query_identity.mfds_ingredient_id
            and item.identity.source_hash == query_identity.source_hash
            for item in evidence.ingredients
        )
    ):
        return supported(
            "MATCH" if condition.operator == "includes" else "NOT_MATCH", "ingredient_present"
        )
    # Keep list-integrity checks separate from unresolved query identity.
    if evidence.ingredient_coverage != "full" or evidence.normalization_status != "verified":
        return supported("UNKNOWN", "absence_not_verifiable")
    sequences = [item.sequence for item in evidence.ingredients]
    if (
        None in sequences
        or sorted(sequences) != list(range(1, len(sequences) + 1))
        or len(names) != len(set(names))
    ):
        return supported("UNKNOWN", "ingredient_list_inconsistent")
    if query_identity is None or any(item.identity is None for item in evidence.ingredients):
        return supported("UNKNOWN", "ingredient_identity_unresolved")
    if any(
        item.identity.mfds_ingredient_id == query_identity.mfds_ingredient_id
        for item in evidence.ingredients
    ):
        return supported("UNKNOWN", "ingredient_identity_version_mismatch")
    return supported(
        "NOT_MATCH" if condition.operator == "includes" else "MATCH", "ingredient_absent"
    )


def to_supervisor_condition(result: IngredientDecision) -> dict[str, str | None]:
    """Project the richer API decision into P0-1 ConditionCheck without cross-service imports."""
    return {
        "condition": result.condition,
        "verdict": result.verdict,
        "productId": result.product_id,
        "reason": result.reason,
    }


class IngredientService:
    def __init__(self, repository: IngredientRepository):
        self._repository = repository

    async def get_ingredients(
        self,
        product_id: str,
        shade_id: str | None,
        option_id: str | None = None,
        ingredient_name: str | None = None,
        operator: str = "includes",
    ) -> IngredientReadResult:
        if ingredient_name is not None and not ingredient_name.strip():
            raise ApiError(400, "Ingredient name is required", "invalid_ingredient")
        try:
            result = await self._repository.lookup(product_id, shade_id, option_id)
        except SQLAlchemyError as exc:
            raise ApiError(
                503, "Ingredient source unavailable", "ingredient_lookup_failed"
            ) from exc
        evidence = result.evidence
        if evidence is not None:
            result.ingredient_coverage = evidence.ingredient_coverage
            result.review_status = evidence.review_status
            result.normalization_status = evidence.normalization_status
            result.source = evidence.source_ref
            result.collected_at = evidence.collected_at
            result.evidence_id = evidence.evidence_id
            # Naive source timestamps and inconsistent rows cannot become verified public facts.
            if (
                not result.issues
                and evidence.source_ref
                and evidence.collected_at
                and evidence.ingredients
            ):
                result.ingredients = evidence.ingredients
                result.status = "ok"
        if ingredient_name:
            condition = IngredientCondition(
                product_id=product_id,
                shade_id=shade_id,
                option_id=result.option_id,
                ingredient_name=ingredient_name,
                operator=operator,
            )
            lookup = (
                IngredientLookupResult(status="ok", evidence=evidence)
                if evidence
                else IngredientLookupResult(status="not_found")
            )
            try:
                identity = (
                    await self._repository.resolve_identity(ingredient_name)
                    if evidence and not result.issues
                    else None
                )
            except SQLAlchemyError as exc:
                raise ApiError(
                    503, "Ingredient identity source unavailable", "ingredient_lookup_failed"
                ) from exc
            check = evaluate_ingredient(condition, lookup, identity)
            if result.issues:
                check.verdict, check.reason = "UNKNOWN", "evidence_requires_review"
            elif evidence is None:
                check.reason = result.reason
            result.conditions = [check]
            result.verdict = check.verdict
            # The status continues to represent evidence availability; the reason
            # reflects this specific question, for both verified and unknown verdicts.
            result.reason = check.reason
        if get_settings().is_production and (result.synthetic or (evidence and evidence.synthetic)):
            result.synthetic = True
            result.status, result.verdict = "unknown", "UNKNOWN"
            result.review_status = "unreviewed"
            result.reason = "synthetic_test_only"
            result.ingredients = []
            result.evidence_id = None
            for check in result.conditions:
                check.verdict, check.reason = "UNKNOWN", "synthetic_test_only"
                check.evidence_id = None
        return result


def get_ingredient_service(session: AsyncSession = Depends(get_session)) -> IngredientService:
    return IngredientService(IngredientRepository(session))

"""Pure ingredient evaluation and read-only lookup orchestration; no catalog mutation."""

import unicodedata
from collections.abc import Iterable
from datetime import datetime

from fastapi import Depends
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.db import get_session
from app.core.errors import ApiError
from app.core.ingredient_alias_approval import (
    IngredientApprovalError,
    get_ingredient_alias_approvals,
)
from app.repositories.ingredient_repository import IngredientRepository
from app.schemas.catalog_options import IngredientFilter, OptionIngredientInformation, Verdict
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
    if not evidence.source_ref or not (
        evidence.collected_at or (evidence.reviewed_at and evidence.review_ref)
    ):
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


def required_verdict(verdicts: Iterable[Verdict]) -> Verdict:
    present = set(verdicts)
    for verdict in ("NOT_MATCH", "ERROR", "UNKNOWN"):
        if verdict in present:
            return verdict
    return "MATCH"


def _read_evidence(result: IngredientReadResult) -> set[str]:
    blocking_issues = set(result.issues) - (
        {"source_timezone_unknown"} if result.mapping_status == "directly_reviewed" else set()
    )
    evidence = result.evidence
    if evidence is not None:
        result.ingredient_coverage = evidence.ingredient_coverage
        result.review_status = evidence.review_status
        result.normalization_status = evidence.normalization_status
        result.source = evidence.source_ref
        result.collected_at = evidence.collected_at
        result.evidence_id = evidence.evidence_id
        result.reviewed_at = evidence.reviewed_at
        result.review_ref = evidence.review_ref
        if (
            not blocking_issues
            and evidence.source_ref
            and (evidence.collected_at or (evidence.reviewed_at and evidence.review_ref))
            and evidence.ingredients
        ):
            result.ingredients = evidence.ingredients
            result.status = "ok"
    return blocking_issues


def _mask_synthetic(result: IngredientReadResult) -> None:
    evidence = result.evidence
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


def _option_evidence_reason(review: IngredientReadResult, since: datetime | None) -> str | None:
    if review.status != "ok":
        return review.reason
    if since is not None:
        stamp = review.reviewed_at or review.collected_at
        if stamp is None:
            return "ingredient_evidence_date_unavailable"
        if stamp < since:
            return "ingredient_evidence_stale"
    return None


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
            get_ingredient_alias_approvals()
            result = await self._repository.lookup(product_id, shade_id, option_id)
        except IngredientApprovalError as exc:
            raise ApiError(
                503, "Ingredient approval file unavailable", "ingredient_alias_approvals_invalid"
            ) from exc
        except SQLAlchemyError as exc:
            raise ApiError(
                503, "Ingredient source unavailable", "ingredient_lookup_failed"
            ) from exc
        blocking_issues = _read_evidence(result)
        evidence = result.evidence
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
                    if evidence and not blocking_issues
                    else None
                )
            except SQLAlchemyError as exc:
                raise ApiError(
                    503, "Ingredient identity source unavailable", "ingredient_lookup_failed"
                ) from exc
            check = evaluate_ingredient(condition, lookup, identity)
            if blocking_issues:
                check.verdict, check.reason = "UNKNOWN", "evidence_requires_review"
            elif evidence is None:
                check.reason = result.reason
            result.conditions = [check]
            result.verdict = check.verdict
            # The status continues to represent evidence availability; the reason
            # reflects this specific question, for both verified and unknown verdicts.
            result.reason = check.reason
        _mask_synthetic(result)
        return result

    async def check_options(
        self,
        selections: dict[str, str],
        conditions: list[IngredientFilter],
        since: datetime | None = None,
    ) -> dict[str, OptionIngredientInformation]:
        if not selections:
            return {}
        error = None
        try:
            get_ingredient_alias_approvals()
            options = await self._repository.lookup_options(selections)
        except IngredientApprovalError:
            error = "ingredient_alias_approvals_invalid"
        except (SQLAlchemyError, OSError):
            error = "ingredient_lookup_failed"
        if error is not None:
            options = {
                option_id: OptionIngredientInformation(
                    review=IngredientReadResult(
                        product_id=product_id, option_id=option_id, reason=error
                    ),
                    error_code=error,
                )
                for option_id, product_id in selections.items()
            }

        unusable = {}
        for option_id, info in options.items():
            _read_evidence(info.review)
            _mask_synthetic(info.review)
            if info.review.reason == "synthetic_test_only":
                info.observed = None
            unusable[option_id] = _option_evidence_reason(info.review, since)

        identities = {}
        identity_errors = set()
        if any(unusable[key] is None and not info.error_code for key, info in options.items()):
            for name in dict.fromkeys(condition.ingredient_name for condition in conditions):
                try:
                    identities[name] = await self._repository.resolve_identity(name)
                except (SQLAlchemyError, OSError, IngredientApprovalError):
                    identity_errors.add(name)

        for option_id, info in options.items():
            review = info.review
            reason = unusable[option_id]
            evidence = review.evidence if reason is None else None
            lookup = (
                IngredientLookupResult(status="ok", evidence=evidence)
                if evidence is not None
                else IngredientLookupResult(status="not_found")
            )
            for item in conditions:
                condition = IngredientCondition(
                    product_id=review.product_id,
                    shade_id=review.shade_id,
                    option_id=option_id,
                    ingredient_name=item.ingredient_name,
                    operator=item.operator,
                )
                check = evaluate_ingredient(condition, lookup, identities.get(item.ingredient_name))
                if check.verdict == "UNKNOWN":
                    failure = info.error_code
                    if evidence is not None and item.ingredient_name in identity_errors:
                        failure = "ingredient_identity_lookup_failed"
                    if failure:
                        check.verdict, check.reason = "ERROR", failure
                    elif reason:
                        check.reason = reason
                    check.evidence_id = review.evidence_id
                review.conditions.append(check)
            if conditions:
                review.verdict = required_verdict(check.verdict for check in review.conditions)
        return options


def get_ingredient_service(session: AsyncSession = Depends(get_session)) -> IngredientService:
    return IngredientService(IngredientRepository(session))

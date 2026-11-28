"""Product intent deltas and conservative Catalog-name evidence, shared by shopping reads.

The vocabulary classifies Catalog facts, not user utterances. Descriptions mentioning
another product never establish its type. Missing or conflicting evidence stays unknown.
"""

import re

from app.schemas.consultation_task import ProductAssessment, ProductRequirement

KIND_TERMS = {
    "toner": ("토너", "스킨토너", "toner"),
    "cream": ("크림", "cream"),
    "lotion": ("로션", "에멀전", "lotion", "emulsion"),
    "serum": ("세럼", "앰플", "에센스", "serum", "ampoule", "essence"),
    "cleanser": ("클렌징", "클렌저", "클렌져", "세안", "cleanser", "cleansing"),
    "sunscreen": ("선크림", "선스크린", "선스틱", "선젤", "선로션", "sunscreen", "sun cream"),
    "mask": ("마스크", "크림팩", "수면팩", "mask"),
    "cleansing_cream": ("클렌징크림", "클렌징 크림", "cleansing cream"),
    "tone_up_cream": ("톤업", "tone up", "tone-up"),
    "eye_cream": ("아이크림", "아이 크림", "eye cream"),
}


def catalog_kind(product):
    name = (product.name_ko or product.name).casefold()
    # Explicit gifts are not this product. Other bracketed type information can
    # contradict the main name (e.g. a Japanese lotion marketed as a toner).
    name = re.sub(r"\[[^\]]*(?:증정|gift)[^\]]*\]", "", name)
    found = {kind for kind, terms in KIND_TERMS.items() if any(term in name for term in terms)}
    # Specific functions take precedence over a generic cream substring.
    specific = found & {"sunscreen", "mask", "cleansing_cream", "tone_up_cream", "eye_cream"}
    if specific:
        found -= {"cream"}
    if "cleansing_cream" in found:
        found.discard("cleanser")
    if "sunscreen" in found:
        found.discard("lotion")
    return next(iter(found)) if len(found) == 1 else None


def resolve_requirement(previous, change, message, *, required=False):
    previous = previous or ProductRequirement()
    if change is None:
        return previous, required
    if change.operation == "keep":
        return previous, False
    if (
        change.operation == "set"
        and change.name_term
        and not change.kind
        and change.quote
        and change.name_term in change.quote
        and change.name_term in message
    ):
        # The parent may delegate a narrower clause than the model's outer quote.
        # The exact type term must still occur in the actual delegated request.
        return ProductRequirement(name_term=change.name_term), False
    if not change.quote or change.quote not in message:
        return previous, True
    if change.operation == "clear":
        return ProductRequirement(), False
    if change.kind and change.name_term:
        return previous, True
    if change.operation == "set" and change.kind:
        return ProductRequirement(kind=change.kind), False
    return previous, True


def inspect_candidates(products, requirement):
    accepted, unknown, evidence = [], 0, {}
    for product in products:
        kind = catalog_kind(product) if requirement.kind else None
        name = re.sub(r"\s+", "", product.name_ko or product.name).casefold()
        term = re.sub(r"\s+", "", requirement.name_term or "").casefold()
        term_matches = not term or term in name
        verdict = (
            "match"
            if term_matches and (not requirement.kind or kind == requirement.kind)
            else "unknown"
            if requirement.kind and kind is None
            else "not_match"
        )
        if verdict == "match":
            accepted.append(product)
            evidence[product.id] = {
                "productId": product.id,
                "verdict": verdict,
                "kind": kind,
                **({"nameTerm": requirement.name_term} if requirement.name_term else {}),
                "source": "catalog_product_name",
                "name": product.name_ko or product.name,
            }
        elif verdict == "unknown":
            unknown += 1
    return (
        accepted,
        ProductAssessment(
            status="completed" if accepted or not unknown else "partial",
            outcome="matched" if accepted else "unknown" if unknown else "no_match",
            requirement=requirement,
            inspected=len(products),
            matched=len(accepted),
            unknown=unknown,
        ),
        evidence,
    )


def missing_assessment(requirement):
    return ProductAssessment(
        status="partial",
        outcome="unknown",
        requirement=requirement or ProductRequirement(),
        limitations=["product_conditions_not_verified"],
    )


def assess_options(result, requirement):
    """Combine Catalog option verdicts with the same conservative product-kind evidence."""
    from app.schemas.catalog import OptionCheck
    from app.services.consultation_task_adapter import fingerprint

    requirement = requirement or ProductRequirement()
    accepted, assessment, evidence = inspect_candidates(result.products, requirement)
    by_id = {p.id: p for p in result.products}
    allowed = {p.id for p in accepted}
    items = []
    extra_excluded = 0
    for item in result.items:
        if (
            (requirement.kind or requirement.name_term)
            and item.product_id in by_id
            and item.product_id not in allowed
        ):
            product = by_id[item.product_id]
            known = bool(requirement.name_term) or catalog_kind(product) is not None
            group = "EXCLUDED" if known else "REFERENCE_ONLY"
            if item.group == "EXCLUDED":
                group = "EXCLUDED"
            extra_excluded += group == "EXCLUDED" and item.group != "EXCLUDED"
            check = OptionCheck(
                condition="product_kind",
                verdict="NOT_MATCH" if known else "UNKNOWN",
                reason="requested_product_kind_mismatch"
                if known
                else "requested_product_kind_unverified",
                source_ref=f"/api/products/{product.id}",
                source_version=fingerprint([product.id, product.name_ko or product.name]),
            )
            item = item.model_copy(update={"group": group, "checks": [*item.checks, check]})
        items.append(item)
    incomplete = (
        result.status == "PARTIAL"
        or not result.checked_scope.exhaustive
        or assessment.unknown > 0
        or any(i.group == "REFERENCE_ONLY" for i in items)
    )
    assessment.status = "partial" if incomplete else "completed"
    assessment.evidence = list(evidence.values())
    if incomplete:
        assessment.limitations = ["option_scope_incomplete"]
    accepted_ids = {p.id for p in accepted}
    if not any(i.product_id in accepted_ids and i.group == "ELIGIBLE" for i in items):
        assessment.outcome = (
            "unknown"
            if incomplete or any(i.group == "REFERENCE_ONLY" for i in items)
            else "no_match"
        )
    filtered = result.model_copy(
        update={
            "items": items,
            "products": accepted,
            "excluded_count": result.excluded_count + extra_excluded,
            "status": "PARTIAL" if incomplete else result.status,
        }
    )
    return filtered, assessment

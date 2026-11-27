"""Read-only bounded intersections. No ingredient source text is sent to an LLM."""

import asyncio
from contextlib import suppress
from datetime import UTC, datetime

from fastapi import Depends
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.db import get_session
from app.core.errors import ApiError
from app.core.ingredient_alias_approval import (
    IngredientApprovalError,
    get_ingredient_alias_approvals,
)
from app.repositories.catalog_repository import CatalogRepository
from app.repositories.ingredient_identity_repository import OptionIngredientMatch
from app.repositories.ingredient_repository import IngredientRepository, fingerprint
from app.repositories.oy_catalog_repository import OyCatalogRepository
from app.schemas.ingredient import IngredientCondition, IngredientLookupResult, IngredientReadResult
from app.schemas.option_search import (
    CheckedScope,
    OptionCandidate,
    OptionCheck,
    OptionIngredientResolution,
    OptionPrice,
    OptionSearchRequest,
    OptionSearchResponse,
)
from app.services.ingredient_service import evaluate_ingredient, normalize_ingredient_name

_INGREDIENT_GROUPS = {
    "파라벤",
    "파라벤류",
    "paraben",
    "parabens",
    "실리콘오일",
    "실리콘류",
    "siliconeoil",
    "silicones",
}
_BLOCKING_NAMES = {"unresolved", "ambiguous", "unverified_alias", "unsupported_group", "conflict"}
_FRAGRANCE_INGREDIENT = "향료"


class OptionSearchService:
    def __init__(self, catalog, ingredients, prices, settings=None):
        self.catalog, self.ingredients, self.prices = catalog, ingredients, prices
        self.settings = settings or get_settings()

    async def _price(self, request, product, lookup):
        check = OptionCheck(condition="price", verdict="UNKNOWN", reason="price_unavailable")
        evidence = None
        if request.max_price_krw is None:
            return None, None
        if request.price_basis == "current_offer":
            check.reason = "current_price_unverified"
            return check, None
        now = datetime.now(UTC)
        if request.price_basis == "catalog_reference":
            if product.price_krw > 0:
                evidence = OptionPrice(
                    requested_basis=request.price_basis,
                    observed_basis="catalog_reference",
                    amountKRW=product.price_krw,
                    checked_at=now,
                    source_ref=f"/api/products/{product.id}",
                    source_version=fingerprint([product.id, product.price_krw]),
                )
        else:
            try:
                row = await self.prices.option_price(lookup.option_id, product.id)
            except SQLAlchemyError:
                check.verdict, check.reason = "ERROR", "price_lookup_failed"
                return check, None
            if row:
                snapshot, amount, stamp, source = row
                aware = stamp if stamp and stamp.tzinfo and stamp.utcoffset() is not None else None
                version = fingerprint([lookup.option_id, snapshot, amount, stamp, source])
                review = lookup.option_review
                if (
                    not aware
                    and review
                    and review.price_source_version == version
                    and review.price_observed_at.replace(tzinfo=None) == stamp
                ):
                    aware = review.price_observed_at
                    check.review_ref = lookup.evidence.review_ref
                if amount is not None and amount > 0 and source:
                    evidence = OptionPrice(
                        requested_basis=request.price_basis,
                        observed_basis="collected_snapshot",
                        amountKRW=amount,
                        observed_at=aware,
                        observed_at_raw=stamp if stamp and not aware else None,
                        limitations=["timezone_unknown"] if stamp and not aware else [],
                        checked_at=now,
                        source_ref=source,
                        source_version=version,
                    )
        if evidence is None and product.price_krw > 0:
            evidence = OptionPrice(
                requested_basis=request.price_basis,
                observed_basis="catalog_reference",
                amountKRW=product.price_krw,
                checked_at=now,
                source_ref=f"/api/products/{product.id}",
                source_version=fingerprint([product.id, product.price_krw]),
                limitations=["option_price_unavailable"],
            )
        if evidence:
            check.source_version = evidence.source_version
            check.source_ref = evidence.source_ref
            check.observed_at = evidence.observed_at
            if evidence.observed_basis != request.price_basis:
                check.reason = "option_price_unavailable"
            elif evidence.observed_basis == "collected_snapshot" and (
                (not evidence.observed_at and not evidence.observed_at_raw)
                or (evidence.observed_at is not None and evidence.observed_at > now)
            ):
                check.reason = "price_observation_unverified"
            else:
                check.verdict = (
                    "MATCH" if evidence.amount_krw <= request.max_price_krw else "NOT_MATCH"
                )
                check.reason = "requested_price_basis"
        return check, evidence

    async def _ingredient_names(self, conditions):
        if conditions:
            get_ingredient_alias_approvals()
        matches = []
        operators = {}
        for condition in conditions:
            name = condition.ingredient_name
            group = normalize_ingredient_name(name).replace(" ", "").removesuffix("성분군")
            if group in _INGREDIENT_GROUPS:
                match = OptionIngredientMatch(status="unsupported_group")
            else:
                match = await self.ingredients.resolve_option_name(name)
            matches.append(match)
            if match.identity:
                operators.setdefault(match.identity.mfds_ingredient_id, set()).add(
                    condition.operator
                )
        resolutions = []
        for condition, match in zip(conditions, matches, strict=True):
            identity = match.identity
            conflict = identity and len(operators[identity.mfds_ingredient_id]) > 1
            resolutions.append(
                OptionIngredientResolution(
                    ingredient_name=condition.ingredient_name,
                    operator=condition.operator,
                    status="conflict" if conflict else match.status,
                    canonical_name=identity.name_ko if identity else None,
                    suggestions=list(match.suggestions),
                )
            )
        return matches, resolutions

    @staticmethod
    def _ingredient_check(condition, lookup, identity, *, kind="ingredient"):
        check = OptionCheck(
            condition=kind,
            ingredient_name=condition.ingredient_name,
            operator=condition.operator,
            verdict="UNKNOWN",
            reason="evidence_requires_review",
            source_version=lookup.source_version,
            limitations=list(lookup.issues),
        )
        blocking = set(lookup.issues) - (
            {"source_timezone_unknown"} if lookup.mapping_status == "directly_reviewed" else set()
        )
        evidence = lookup.evidence
        if evidence and not blocking:
            try:
                decision = evaluate_ingredient(
                    condition, IngredientLookupResult(status="ok", evidence=evidence), identity
                )
                check.verdict, check.reason, check.evidence_id = (
                    decision.verdict,
                    decision.reason,
                    decision.evidence_id,
                )
            except (SQLAlchemyError, ValueError):
                check.verdict, check.reason = "ERROR", "ingredient_lookup_failed"
        if evidence:
            check.source_ref = evidence.source_ref
            check.review_ref = evidence.review_ref
            check.observed_at = evidence.collected_at
            check.reviewed_at = evidence.reviewed_at
            check.ingredient_coverage = evidence.ingredient_coverage
            check.normalization_status = evidence.normalization_status
            check.review_status = evidence.review_status
        # shortcut: use named fragrance only to reject, until claim evidence is supported.
        if kind == "fragrance_free" and check.verdict == "MATCH":
            check.verdict, check.reason = "UNKNOWN", "fragrance_free_unverified"
        return check

    async def search(self, request: OptionSearchRequest) -> OptionSearchResponse:
        checked_at = datetime.now(UTC)
        names = [
            normalize_ingredient_name(c.ingredient_name) for c in request.ingredient_conditions
        ]
        if not all(names) or len(set(names)) != len(names):
            raise ApiError(400, "Duplicate or conflicting ingredient conditions", "invalid_request")
        items, products = [], []
        total_products = candidate_options = checked = unidentified = errors = work = 0
        reason = "COMPLETE"
        in_progress = None
        resolutions = []
        settings = self.settings
        try:
            async with asyncio.timeout(settings.option_search_timeout_seconds):
                matches, resolutions = await self._ingredient_names(request.ingredient_conditions)
                if any(r.status in _BLOCKING_NAMES for r in resolutions):
                    return OptionSearchResponse(
                        status="PARTIAL",
                        ingredient_resolutions=resolutions,
                        limitations=["rights_unverified"],
                        effective_request=request,
                        checked_at=checked_at,
                        excluded_count=0,
                        omitted_count=0,
                        checked_scope=CheckedScope(
                            candidate_products=0,
                            candidate_options=0,
                            checked_options=0,
                            unidentified_options=0,
                            exhaustive=False,
                            stopped_reason="INGREDIENT_CONFIRMATION",
                            errors=0,
                        ),
                    )
                fragrance_identity = None
                if request.fragrance_free:
                    fragrance_identity = (
                        await self.ingredients.resolve_option_name(_FRAGRANCE_INGREDIENT)
                    ).identity
                products, total_products = await self.catalog.option_search_candidates(
                    request.query,
                    request.category,
                    request.product_ids,
                    settings.option_search_product_limit,
                    product_type=request.product_type,
                )
                if total_products > len(products):
                    reason = "PRODUCT_LIMIT"
                reviewed_texture_keys = set()
                if (
                    request.texture
                    and request.ingredient_conditions
                    and request.product_ids is None
                    and request.option_scope is None
                ):
                    # Lookup still reports an unavailable mapping as a read error.
                    with suppress(ApiError):
                        reviewed_texture_keys = self.ingredients.prioritized_option_keys(
                            reviewed_texture=request.texture
                        )
                    if reason == "PRODUCT_LIMIT" and reviewed_texture_keys:
                        current_ids = {p.id for p in products}
                        reviewed_ids = sorted(
                            {pid for pid, _ in reviewed_texture_keys} - current_ids
                        )[: settings.option_search_product_limit]
                        if reviewed_ids:
                            reviewed, _ = await self.catalog.option_search_candidates(
                                request.query,
                                request.category,
                                reviewed_ids,
                                settings.option_search_product_limit,
                                product_type=request.product_type,
                            )
                            products = (reviewed + products)[: settings.option_search_product_limit]
                if request.product_ids is not None:
                    order = {pid: i for i, pid in enumerate(request.product_ids)}
                    products.sort(key=lambda p: order.get(p.id, len(order)))
                targets = [(p, shade.id) for p in products for shade in p.shades]
                targets += [(p, None) for p in products if not p.shades]
                # Product metadata narrows candidates; it never proves an option texture.
                if request.texture:
                    targets = [(p, sid) for p, sid in targets if p.texture == request.texture]
                scope = request.option_scope
                if scope is not None:
                    by_id = {p.id: p for p in products}
                    scoped = {(r.product_id, r.shade_id, r.option_id) for r in scope}
                    targets = [
                        (by_id[pid], sid, oid)
                        for pid, sid, oid in sorted(scoped, key=str)
                        if pid in by_id
                        and (sid is None or any(s.id == sid for s in by_id[pid].shades))
                    ]
                else:
                    targets = [(p, sid, None) for p, sid in targets]
                candidate_options = len(targets)
                if scope is not None:
                    missing = len(scoped) - len(targets)
                    candidate_options += missing
                    checked += missing
                    unidentified += missing
                if request.ingredient_conditions and request.product_ids is None and targets:
                    keys = {(product.id, shade_id) for product, shade_id, _ in targets}
                    try:
                        prioritized = self.ingredients.prioritized_option_keys(keys)
                    except ApiError:
                        # The normal lookup reports an unavailable mapping as a read error.
                        prioritized = set()
                    targets.sort(
                        key=lambda target: (
                            (target[0].id, target[1]) not in reviewed_texture_keys,
                            (target[0].id, target[1]) not in prioritized,
                        )
                    )
                for product, shade_id, requested_option in targets:
                    in_progress = None
                    cost = (
                        1
                        + len(request.ingredient_conditions)
                        + int(request.fragrance_free)
                        + int(request.max_price_krw is not None)
                        + int(request.texture is not None)
                    )
                    if work + cost > settings.option_search_work_limit:
                        reason = "WORK_LIMIT"
                        break
                    work += cost
                    raw_identity = None
                    option_name = None
                    try:
                        if requested_option and hasattr(self.prices, "option_identity"):
                            raw_identity = await self.prices.option_identity(
                                requested_option, product.id
                            )
                            if raw_identity is None:
                                checked += 1
                                unidentified += 1
                                continue
                        lookup = await self.ingredients.lookup(product.id, shade_id)
                    except (ApiError, SQLAlchemyError):
                        if raw_identity is None:
                            checked += 1
                            unidentified += 1
                            errors += 1
                            continue
                        lookup = IngredientReadResult(
                            product_id=product.id,
                            shade_id=shade_id,
                            reason="ingredient_lookup_failed",
                        )
                    if raw_identity:
                        option_name = raw_identity[1]
                        if (
                            lookup.option_id != requested_option
                            or not IngredientRepository.verified_option(lookup)
                            or (settings.is_production and lookup.synthetic)
                        ):
                            lookup = IngredientReadResult(
                                product_id=product.id,
                                shade_id=shade_id,
                                option_id=requested_option,
                                source_version=fingerprint(list(raw_identity)),
                                reason="ingredient_evidence_unverified",
                            )
                    elif (
                        not IngredientRepository.verified_option(lookup)
                        or (settings.is_production and lookup.synthetic)
                        or (requested_option is not None and requested_option != lookup.option_id)
                    ):
                        checked += 1
                        unidentified += 1
                        continue
                    checks = [
                        OptionCheck(
                            condition="identity",
                            verdict="MATCH",
                            reason="verified_option",
                            source_version=lookup.source_version,
                        )
                    ]
                    if (
                        request.texture
                        and lookup.option_review
                        and lookup.option_review.texture == request.texture
                    ):
                        review = lookup.option_review
                        evidence = lookup.evidence
                        version = fingerprint(
                            [
                                product.id,
                                shade_id,
                                lookup.option_id,
                                review.texture,
                                review.texture_source_ref,
                                evidence.review_ref,
                                evidence.reviewed_at,
                            ]
                        )
                        checks.append(
                            OptionCheck(
                                condition="texture",
                                verdict="MATCH",
                                reason="official_option_texture_reviewed",
                                texture_code=review.texture,
                                texture_basis="official_reviewed",
                                source_ref=review.texture_source_ref,
                                source_version=version,
                                evidence_id=f"texture:{lookup.option_id}:{version}",
                                review_ref=evidence.review_ref,
                                reviewed_at=evidence.reviewed_at,
                                review_status="verified",
                            )
                        )
                    elif request.texture:
                        texture = OptionCheck(
                            condition="texture",
                            verdict="UNKNOWN",
                            reason="option_texture_unverified",
                            texture_code=product.texture,
                            texture_basis="catalog_metadata",
                            limitations=["product_metadata_only"],
                        )
                        try:
                            row = await self.prices.product_texture(product.id)
                            if row and row[0] == product.texture:
                                code, basis, stamp, source = row
                                texture.texture_basis = (
                                    basis
                                    if basis in {"product_name", "review_survey", "review_ai"}
                                    else "catalog_metadata"
                                )
                                texture.source_ref = source
                                texture.source_version = fingerprint(
                                    [product.id, code, basis, stamp, source]
                                )
                            elif row:
                                texture.limitations.append("texture_source_mismatch")
                        except SQLAlchemyError:
                            texture.verdict, texture.reason = "ERROR", "texture_lookup_failed"
                        checks.append(texture)
                    if request.fragrance_free:
                        checks.append(
                            self._ingredient_check(
                                IngredientCondition(
                                    product_id=product.id,
                                    shade_id=shade_id,
                                    option_id=lookup.option_id,
                                    ingredient_name=_FRAGRANCE_INGREDIENT,
                                    operator="excludes",
                                ),
                                lookup,
                                fragrance_identity,
                                kind="fragrance_free",
                            )
                        )
                    if request.moisturizing:
                        checks.append(
                            OptionCheck(
                                condition="moisturizing",
                                verdict="UNKNOWN",
                                reason="unsupported_claim",
                            )
                        )
                    checks.extend(
                        OptionCheck(
                            condition=f"unsupported:{i}",
                            verdict="UNKNOWN",
                            reason="unsupported_condition",
                        )
                        for i, _ in enumerate(request.unsupported_conditions)
                    )
                    in_progress = (product, shade_id, lookup, checks)
                    for condition, match in zip(
                        request.ingredient_conditions, matches, strict=True
                    ):
                        checks.append(
                            self._ingredient_check(
                                IngredientCondition(
                                    product_id=product.id,
                                    shade_id=shade_id,
                                    option_id=lookup.option_id,
                                    ingredient_name=condition.ingredient_name,
                                    operator=condition.operator,
                                ),
                                lookup,
                                match.identity,
                            )
                        )
                    price_check, price = await self._price(request, product, lookup)
                    if price_check:
                        checks.append(price_check)
                    verdicts = {c.verdict for c in checks}
                    group = (
                        "EXCLUDED"
                        if "NOT_MATCH" in verdicts
                        else "ELIGIBLE"
                        if verdicts == {"MATCH"}
                        else "REFERENCE_ONLY"
                    )
                    items.append(
                        OptionCandidate(
                            product_id=product.id,
                            shade_id=shade_id,
                            option_id=lookup.option_id,
                            option_name=option_name,
                            product_type=request.product_type,
                            source_version=lookup.source_version,
                            group=group,
                            checks=checks,
                            price=price,
                            synthetic=lookup.synthetic,
                            ingredient_entry_count=len(lookup.evidence.ingredients)
                            if lookup.evidence
                            else None,
                            ingredient_identity_count=sum(
                                e.identity is not None for e in lookup.evidence.ingredients
                            )
                            if lookup.evidence
                            else None,
                        )
                    )
                    in_progress = None
                    checked += 1
                    errors += sum(c.verdict == "ERROR" for c in checks)
        except TimeoutError:
            reason = "TIMEOUT"
            # A later timeout cannot erase an already established violation.
            if in_progress is not None:
                product, shade_id, lookup, checks = in_progress
                done = sum(c.condition == "ingredient" for c in checks)
                checks.extend(
                    OptionCheck(
                        condition="ingredient",
                        ingredient_name=c.ingredient_name,
                        operator=c.operator,
                        verdict="ERROR",
                        reason="timeout",
                    )
                    for c in request.ingredient_conditions[done:]
                )
                if request.max_price_krw is not None and not any(
                    c.condition == "price" for c in checks
                ):
                    checks.append(OptionCheck(condition="price", verdict="ERROR", reason="timeout"))
                items.append(
                    OptionCandidate(
                        product_id=product.id,
                        shade_id=shade_id,
                        option_id=lookup.option_id,
                        product_type=request.product_type,
                        source_version=lookup.source_version,
                        group="EXCLUDED"
                        if any(c.verdict == "NOT_MATCH" for c in checks)
                        else "REFERENCE_ONLY",
                        checks=checks,
                        synthetic=lookup.synthetic,
                    )
                )
                checked += 1
                errors += sum(c.verdict == "ERROR" for c in checks)
        except IngredientApprovalError as exc:
            raise ApiError(
                503, "Ingredient approvals unavailable", "ingredient_alias_approvals_invalid"
            ) from exc
        except SQLAlchemyError as exc:
            raise ApiError(503, "Option search unavailable", "option_search_unavailable") from exc
        # Prefer verified matches, preserving product order within each group.
        visible_ids = []
        for group in ("ELIGIBLE", "REFERENCE_ONLY"):
            for item in items:
                if (
                    item.group == group
                    and item.product_id not in visible_ids
                    and len(visible_ids) < 6
                ):
                    visible_ids.append(item.product_id)
        visible = [i for i in items if i.group == "EXCLUDED" or i.product_id in visible_ids]
        exhaustive = reason == "COMPLETE" and checked == candidate_options
        all_failed = bool(items) and all(
            any(c.condition != "identity" for c in i.checks)
            and all(c.verdict == "ERROR" for c in i.checks if c.condition != "identity")
            for i in items
        )
        status = (
            "ERROR"
            if all_failed or (not items and (errors or reason == "TIMEOUT"))
            else (
                "PARTIAL"
                if not exhaustive
                or unidentified
                or errors
                or any(i.group == "REFERENCE_ONLY" for i in items)
                else "SUCCESS"
            )
        )
        return OptionSearchResponse(
            limitations=["rights_unverified"],
            effective_request=request.model_copy(deep=True),
            ingredient_resolutions=resolutions,
            checked_at=checked_at,
            status=status,
            items=visible,
            products=[next(p for p in products if p.id == pid) for pid in visible_ids],
            checked_scope=CheckedScope(
                candidate_products=total_products,
                candidate_options=candidate_options,
                checked_options=checked,
                unidentified_options=unidentified,
                exhaustive=exhaustive,
                stopped_reason=reason,
                errors=errors,
            ),
            excluded_count=sum(i.group == "EXCLUDED" for i in items),
            omitted_count=len(items) - len(visible),
        )


async def get_option_search_service(
    session: AsyncSession = Depends(get_session),
) -> OptionSearchService:
    settings = get_settings()
    # First statement on this request session: all repositories share one read-only snapshot.
    try:
        await session.execute(text("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY"))
    except SQLAlchemyError as exc:
        raise ApiError(
            503, "Option search snapshot unavailable", "option_search_unavailable"
        ) from exc
    return OptionSearchService(
        CatalogRepository(session),
        IngredientRepository(session, pin_mapping=True),
        OyCatalogRepository(session),
        settings,
    )

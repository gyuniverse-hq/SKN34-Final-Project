"""Deterministic initial heuristics; no claims of efficacy or clinical validation."""

from fastapi import Depends

from app.repositories.skincare_repository import SkincareRepository, get_skincare_repository
from app.schemas.skincare import (
    GoalCoverage,
    SkincareMatch,
    SkincareRequest,
    SkincareResponse,
    SkincareSnapshot,
)

REVIEW_PRIOR = 20


def recommend(
    snapshot: SkincareSnapshot | None, req: SkincareRequest, trace_allowed: bool = False
) -> SkincareResponse:
    goals = [req.primary_goal, *req.secondary_goals]
    mappings = [m for m in snapshot.mappings if m.eligible()] if snapshot else []
    options = snapshot.options if snapshot else []
    # Product-level reviews must not be counted repeatedly for multiple options.
    reviews = {
        o.product.id: (o.review_count, o.rating_avg)
        for o in sorted(options, key=lambda o: o.option_id)
        if o.available and o.identity_verified and o.review_count and o.rating_avg is not None
    }
    total = sum(n for n, _ in reviews.values())
    baseline = sum(n * r for n, r in reviews.values()) / total if total else None
    candidates, traces = [], []
    found = set()
    for o in options:
        matches = [
            m
            for m in mappings
            if m.target_concern in goals and set(m.ingredient_codes).issubset(o.ingredient_codes)
        ]
        matched = [g for g in goals if any(m.target_concern == g for m in matches)]
        excluded = (
            "unavailable"
            if not o.available
            else "unverified_identity"
            if not o.identity_verified
            else "no_mapping"
            if not matched
            else None
        )
        n = o.review_count or 0
        rating = (
            baseline
            if o.rating_avg is None or not n
            else (
                (n * o.rating_avg + REVIEW_PRIOR * baseline) / (n + REVIEW_PRIOR)
                if baseline is not None
                else None
            )
        )
        key = (
            -int(req.primary_goal in matched),
            -sum(g in matched for g in req.secondary_goals),
            -int(req.irritation_signal == "caution" and bool(o.label_source) and o.sensitive_label),
            -int(
                req.skin_type != "unknown"
                and bool(o.label_source)
                and req.skin_type in o.skin_types
            ),
            -(rating or 0),
            -n,
            o.product.id,
            o.option_id,
        )
        if not excluded:
            found.update(matched)
            candidates.append(
                (
                    key,
                    SkincareMatch(
                        product=o.product,
                        option_id=o.option_id,
                        option_name=o.option_name,
                        priceKRW=o.price_krw,
                        matched_goals=matched,
                        target_concern=matched[0],
                        reason_code="primary" if req.primary_goal in matched else "secondary",
                    ),
                )
            )
        if trace_allowed:
            traces.append(
                {
                    "optionId": o.option_id,
                    "excluded": excluded,
                    "sortKey": key,
                    "mappingIds": [m.mapping_id for m in matches],
                    "evidenceIds": sorted(
                        {link.evidence_id for m in matches for link in m.evidence}
                    ),
                    "ingredients": sorted({c for m in matches for c in m.ingredient_codes}),
                    "combinationMatches": [
                        m.mapping_id
                        for m in snapshot.mappings
                        if m.mapping_type == "combination"
                        and m.eligible()
                        and o.identity_verified
                        and set(m.ingredient_codes).issubset(o.ingredient_codes)
                    ],
                }
            )
    unique = {}
    for _, match in sorted(candidates, key=lambda item: item[0]):
        unique.setdefault(match.product.id, match)
    return SkincareResponse(
        data_version=snapshot.data_version if snapshot else None,
        coverage=[
            GoalCoverage(
                goal=g,
                status="mapping_unavailable"
                if not any(m.target_concern == g for m in mappings)
                else "ok"
                if g in found
                else "no_matches",
            )
            for g in goals
        ],
        matches=list(unique.values())[: req.limit],
        trace={
            "mappingDecisions": [
                {
                    "mappingId": m.mapping_id,
                    "eligible": m.eligible(),
                    "runtimeEnabled": m.runtime_enabled,
                    "applicabilityScope": m.applicability_scope,
                    "mappingType": m.mapping_type,
                    "evidenceIds": [link.evidence_id for link in m.evidence],
                }
                for m in snapshot.mappings
            ]
            if snapshot
            else [],
            "reviewPrior": REVIEW_PRIOR,
            "reviewBaseline": baseline,
            "options": traces,
            "evidence": snapshot.evidence if snapshot else {},
        }
        if trace_allowed
        else None,
    )


class SkincareService:
    def __init__(self, repository: SkincareRepository):
        self.repository = repository

    async def recommend(self, req: SkincareRequest, trace_allowed=False):
        return recommend(await self.repository.read(), req, trace_allowed)

    async def publish(self, snapshot: SkincareSnapshot):
        await self.repository.publish(snapshot)


def get_skincare_service(repository: SkincareRepository = Depends(get_skincare_repository)):
    return SkincareService(repository)


def skincare_service_for_session(session):
    return SkincareService(SkincareRepository(session))

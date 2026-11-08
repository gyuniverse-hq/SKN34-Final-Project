"""Deterministic initial heuristics; no claims of efficacy or clinical validation."""

import math
from collections import defaultdict

from fastapi import Depends

from app.repositories.skincare_repository import SkincareRepository, get_skincare_repository
from app.schemas.skincare import (
    ConcernReason,
    CosingMapping,
    GoalCoverage,
    HybridMatch,
    HybridRequest,
    HybridResponse,
    IngredientMapping,
    SkincareMatch,
    SkincareRequest,
    SkincareResponse,
    SkincareSnapshot,
)

REVIEW_PRIOR = 20
# Fixed median of 956 local serving products, selected on 2026-11-06.
SURVEY_PRIOR = 207
# Policy-example experiment: 0.05 was the smallest tested coefficient passing all cases.
SURVEY_WEIGHT = 0.05
# Initial policy bounds in rating-point units, not learned relevance probabilities.
PROFILE_WEIGHT = 1.0
COMPLEMENT_WEIGHT = 1.0
# Initial diversification policy; evaluate against the frozen prior strategy.
REDUNDANCY_WEIGHT = 0.5
RARITY_FLOOR = 0.05


def ingredient_weights(snapshot):
    """Catalog discrimination, never a measure of ingredient efficacy."""
    products = set()
    present = defaultdict(set)
    breadth = defaultdict(set)
    for option in snapshot.options:
        if option.available and option.identity_verified:
            products.add(option.product.id)
            for code in set(option.ingredient_codes):
                present[code].add(option.product.id)
    for mapping in snapshot.mappings:
        if mapping.eligible():
            for code in mapping.ingredient_codes:
                breadth[code].add(mapping.target_concern)
    weights = {
        code: -math.log(max(len(ids) / len(products), RARITY_FLOOR)) / -math.log(RARITY_FLOOR)
        for code, ids in present.items()
    }
    return weights, {code: len(goals) for code, goals in breadth.items()}


def ingredient_similarity(left, right, weights):
    union = left | right
    denominator = sum(weights.get(code, 0) for code in sorted(union))
    return (
        sum(weights.get(code, 0) for code in sorted(left & right)) / denominator
        if denominator
        else 0.0
    )


def support_similarity(left, right, weights):
    # Compare both known ingredient composition and the actual recommendation basis.
    evidence_union = left[3] | right[3]
    return max(
        ingredient_similarity(left[1], right[1], weights),
        ingredient_similarity(left[2], right[2], weights),
        len(left[3] & right[3]) / len(evidence_union) if evidence_union else 0.0,
    )


def survey_baselines(options):
    """Product-level response averages; total reviews are the user-confirmed denominator."""
    products = {
        o.product.id: o
        for o in sorted(options, key=lambda o: o.option_id)
        if o.available and o.identity_verified and o.review_count
    }
    totals, counts = {}, {}
    for option in products.values():
        for signal, ratio in option.survey_ratios.items():
            totals[signal] = totals.get(signal, 0) + option.review_count * ratio
            counts[signal] = counts.get(signal, 0) + option.review_count
    return {signal: total / counts[signal] for signal, total in totals.items()}


def survey_adjustment(option, req, baselines):
    signals = []
    if req.skin_type in ("dry", "oily"):
        signals.append((req.skin_type, 1))
    goal_signal = {
        "dryness": "hydrating",
        "sensitivity": "soothing",
        "pigmentation": "brighteningFirming",
        "wrinkles": "brighteningFirming",
    }
    if req.primary_goal in goal_signal and getattr(req, "balance_goal", None) != "primary":
        signals.append((goal_signal[req.primary_goal], 1))
    if req.irritation_signal == "caution":
        signals.extend((("gentle", 1), ("irritating", -1)))
    if not signals:
        return 0.0
    count = option.review_count or 0
    reliability = count / (count + SURVEY_PRIOR)
    # Missing responses are neutral. Divide by requested signals so gaps receive no bonus.
    return sum(
        sign * reliability * (option.survey_ratios[signal] - baselines[signal])
        for signal, sign in signals
        if signal in option.survey_ratios and signal in baselines
    ) / len(signals)


def review_baseline(options):
    # Product-level reviews must not be counted repeatedly for multiple options.
    reviews = {
        o.product.id: (o.review_count, o.rating_avg)
        for o in sorted(options, key=lambda o: o.option_id)
        if o.available and o.identity_verified and o.review_count and o.rating_avg is not None
    }
    total = sum(n for n, _ in reviews.values())
    return sum(n * r for n, r in reviews.values()) / total if total else None


def adjusted_rating(option, baseline):
    n = option.review_count or 0
    if option.rating_avg is None or not n or baseline is None:
        return baseline
    return (n * option.rating_avg + REVIEW_PRIOR * baseline) / (n + REVIEW_PRIOR)


def review_sort_score(option, req, rating_mean, survey_means):
    return (adjusted_rating(option, rating_mean) or 0) + SURVEY_WEIGHT * survey_adjustment(
        option, req, survey_means
    )


def _recommend_unfiltered(
    snapshot: SkincareSnapshot | None, req: SkincareRequest, trace_allowed: bool = False
) -> SkincareResponse:
    goals = [req.primary_goal, *req.secondary_goals]
    mappings = [m for m in snapshot.mappings if m.eligible()] if snapshot else []
    options = snapshot.options if snapshot else []
    baseline = review_baseline(options)
    candidates, traces = [], []
    found = set()
    for o in options:
        matches = [
            m
            for m in mappings
            if m.target_concern in goals
            and set(m.ingredient_codes).issubset(o.ingredient_codes)
            and (
                m.mapping_id in (o.matched_mapping_ids or ())
                or (isinstance(m, IngredientMapping) and o.matched_mapping_ids is None)
            )
            and (
                isinstance(m, IngredientMapping)
                and m.review_fingerprint is None
                or m.allows_option(o.option_id)
            )
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
        rating = adjusted_rating(o, baseline)
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
                    "evidenceIds": sorted({e for m in matches for e in m.evidence_ids}),
                    "ingredients": sorted({c for m in matches for c in m.ingredient_codes}),
                    "combinationMatches": [
                        m.mapping_id
                        for m in snapshot.mappings
                        if m.mapping_type == "combination"
                        and o.identity_verified
                        and m.identity_verified
                        and set(m.ingredient_codes).issubset(o.ingredient_codes)
                        and (o.matched_mapping_ids is None or m.mapping_id in o.matched_mapping_ids)
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
                    "status": m.mapping_status
                    if isinstance(m, IngredientMapping)
                    else m.applicability_scope,
                    "identityVerified": m.identity_verified,
                    **(
                        {"reReviewRequired": m.re_review_required}
                        if isinstance(m, IngredientMapping)
                        else {}
                    ),
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


def candidate_options(snapshot, active):
    """Yield each saleable option and its ingredient matches before and after proof checks."""
    for option in snapshot.options:
        if not option.available or not option.identity_verified:
            continue
        ingredients = set(option.ingredient_codes)
        matches = [
            active[mid]
            for mid in option.matched_mapping_ids or ()
            if mid in active and ingredients.issuperset(active[mid].ingredient_codes)
        ]
        if matches:
            yield option, matches, [m for m in matches if m.allows_option(option.option_id)]


def _review_preview_unfiltered(snapshot):
    from app.schemas.skincare import GOALS

    active = {m.mapping_id: m for m in snapshot.mappings if not m.blockers()}
    options = {g: 0 for g in GOALS}
    products = {g: set() for g in GOALS}
    for option, matched, applied in candidate_options(snapshot, active):
        for goal in {m.target_concern for m in matched}:
            options[goal] += 1
        for mapping in applied:
            products[mapping.target_concern].add(option.product.id)
    return {
        "mappings": {m.mapping_id: {"blocked": m.blockers()} for m in snapshot.mappings},
        "coverage": {
            g: {
                "activeMappings": sum(m.target_concern == g for m in active.values()),
                "matchedOptions": options[g],
                "eligibleProducts": len(products[g]),
            }
            for g in GOALS
        },
    }


def skin_care_goals(req):
    goals = set()
    if req.skin_type == "dry":
        goals.add("dryness")
    elif req.skin_type == "oily":
        goals.add("oiliness")
    if req.irritation_signal == "caution":
        goals.add("sensitivity")
    return goals


def balance_preference(req):
    """Prioritize oil or moisture only when exactly one relevant signal applies."""
    if not req.balance_goal:
        return None
    oil_care = any(c.goal == "oiliness" for c in req.detected_concerns)
    dry_skin = req.skin_type == "dry"
    if oil_care == dry_skin:
        return None
    return "oiliness" if oil_care else "dryness"


def display_goal(goal, req):
    return "balance" if req.balance_goal and goal in ("dryness", "oiliness") else goal


def balanced_overall(ranked, req, support, weights):
    """Soft relevance plus diminishing complement value, without category quotas."""
    remaining = list(ranked)
    intents = {req.primary_goal, *req.secondary_goals}
    intents.update(c.goal for c in req.detected_concerns)
    intents.update(skin_care_goals(req))
    if req.balance_goal:
        intents.update(("dryness", "oiliness"))
    groups = {display_goal(goal, req) for goal in intents}
    counts = dict.fromkeys(groups, 0)
    preferred = balance_preference(req)
    selected = []
    while remaining and len(selected) < 5:

        def key(row):
            matched = row[1] & intents
            strengths = support[row[2].option_id][0]
            group_strengths = {}
            for goal in matched:
                group = display_goal(goal, req)
                group_strengths[group] = max(group_strengths.get(group, 0), strengths[goal])
            fit = sum(group_strengths.values()) / len(groups)
            complement = sum(
                value / (1 + counts[group]) for group, value in group_strengths.items()
            ) / len(groups)
            similarity = max(
                (
                    support_similarity(support[row[2].option_id], support[s[2].option_id], weights)
                    for s in selected
                ),
                default=0.0,
            )
            score = (
                row[3]
                + PROFILE_WEIGHT * fit
                + COMPLEMENT_WEIGHT * complement
                - REDUNDANCY_WEIGHT * similarity
            )
            priority = int(
                req.balance_goal == "primary" and preferred is not None and preferred not in matched
            )
            return priority, -score, row[0]

        best = min(remaining, key=key)
        selected.append(best)
        for goal in counts:
            counts[goal] += int(goal in {display_goal(g, req) for g in best[1]})
        product_id = best[2].product.id
        remaining = [row for row in remaining if row[2].product.id != product_id]
    return selected


def _recommend_hybrid_unfiltered(
    snapshot: SkincareSnapshot | None, req: HybridRequest
) -> HybridResponse:
    primary = {req.primary_goal}
    if req.balance_goal == "primary":
        primary.update(("dryness", "oiliness"))
    sources = {goal: ["primary"] for goal in sorted(primary)}
    for goal in req.secondary_goals:
        sources.setdefault(goal, ["secondary"])
    for concern in req.detected_concerns:
        reasons = sources.setdefault(concern.goal, [])
        for source in concern.sources:
            if source not in reasons:
                reasons.append(source)
    for goal in sorted(skin_care_goals(req)):
        sources.setdefault(goal, []).append("skinProfile")
    active = (
        {
            m.mapping_id: m
            for m in snapshot.mappings
            if m.target_concern in sources and m.runtime_enabled and not m.blockers()
        }
        if snapshot
        else {}
    )
    baseline = review_baseline(snapshot.options) if snapshot else None
    survey_means = survey_baselines(snapshot.options) if snapshot else {}
    weights, breadth = ingredient_weights(snapshot) if snapshot else ({}, {})
    support = {}
    reason_codes = {}
    reason_evidence_sources = {}
    ranked = []
    secondary = set(req.secondary_goals) - primary
    detected = {c.goal for c in req.detected_concerns}
    preferred = balance_preference(req)

    def profile_order(option, review_score):
        return (
            -int(
                req.irritation_signal == "caution"
                and bool(option.label_source)
                and option.sensitive_label
            ),
            -int(
                req.skin_type != "unknown"
                and bool(option.label_source)
                and req.skin_type in option.skin_types
            ),
            -review_score,
            -(option.review_count or 0),
            option.product.id,
            option.option_id,
        )

    for option, _, applied in candidate_options(snapshot, active) if snapshot else ():
        goals = {m.target_concern for m in applied}
        if not goals:
            continue
        strengths = {}
        reason_codes[option.option_id] = defaultdict(set)
        reason_evidence_sources[option.option_id] = defaultdict(set)
        codes, evidence = set(), set()
        for mapping in applied:
            reason_codes[option.option_id][mapping.target_concern].update(mapping.ingredient_codes)
            reason_evidence_sources[option.option_id][mapping.target_concern].add(
                "cosing_function" if isinstance(mapping, CosingMapping) else "research_mapping"
            )
            strength = min(weights.get(c, 0) / breadth.get(c, 1) for c in mapping.ingredient_codes)
            strengths[mapping.target_concern] = max(
                strengths.get(mapping.target_concern, 0), strength
            )
            codes.update(mapping.ingredient_codes)
            evidence.update(mapping.evidence_ids)
        support[option.option_id] = (
            strengths, set(option.ingredient_codes) & set(weights), codes, evidence
        )
        review_score = review_sort_score(option, req, baseline, survey_means)
        key = (
            -int(bool(primary & goals)),
            -len({display_goal(g, req) for g in goals & secondary}),
            -int(preferred is not None and preferred in goals),
            -len({display_goal(g, req) for g in (goals & detected) - secondary - primary}),
            *profile_order(option, review_score),
        )
        ranked.append((key, goals, option, review_score))

    def match_for(goals, option):
        return HybridMatch(
            product=option.product,
            option_id=option.option_id,
            option_name=option.option_name,
            priceKRW=option.price_krw,
            reasons=[
                ConcernReason(
                    goal=g,
                    sources=s,
                    ingredient_codes=sorted(reason_codes[option.option_id][g]),
                    evidence_sources=sorted(reason_evidence_sources[option.option_id][g]),
                )
                for g, s in sources.items()
                if g in goals
            ],
        )

    overall = [
        match_for(goals, option)
        for _, goals, option, _ in balanced_overall(ranked, req, support, weights)
    ]
    def concern_matches(target_goals, review_profile, priority=None):
        def order(row):
            _, goals, option, _ = row
            score = review_sort_score(option, review_profile, baseline, survey_means)
            misses_priority = priority is not None and priority not in goals
            return (misses_priority, *profile_order(option, score))

        eligible = (row for row in ranked if row[1] & target_goals)
        products = {}
        for _, goals, option, _ in sorted(eligible, key=order):
            if option.product.id in products:
                continue
            products[option.product.id] = match_for(goals, option)
            if len(products) == 5:
                break
        return list(products.values())

    groups = {
        goal: concern_matches(
            {goal}, req.model_copy(update={"primary_goal": goal, "balance_goal": None})
        )
        for goal in sources
    }
    balance_matches = None
    if req.balance_goal:
        # The combined list uses shared skin and review signals without a single-goal bonus.
        balance_profile = req.model_copy(update={"balance_goal": "primary"})
        balance_matches = concern_matches({"dryness", "oiliness"}, balance_profile, preferred)
    active_goals = {m.target_concern for m in active.values()}
    return HybridResponse(
        data_version=snapshot.data_version if snapshot else None,
        overall_top5=overall,
        by_concern=groups,
        balance_matches=balance_matches,
        coverage=[
            GoalCoverage(
                goal=g,
                status="ok"
                if items
                else "no_matches"
                if g in active_goals
                else "mapping_unavailable",
            )
            for g, items in groups.items()
        ],
    )


def cosing_only(snapshot: SkincareSnapshot | None) -> SkincareSnapshot | None:
    """Apply the current policy even when reading an older mixed-source snapshot."""
    if snapshot is None:
        return None
    mappings = [m for m in snapshot.mappings if isinstance(m, CosingMapping)]
    ids = {m.mapping_id for m in mappings}
    codes = {code for m in mappings for code in m.ingredient_codes}
    options = [
        o.model_copy(update={
            "ingredient_codes": [c for c in o.ingredient_codes if c in codes],
            "matched_mapping_ids": [m for m in o.matched_mapping_ids or () if m in ids],
        })
        for o in snapshot.options
    ]
    return snapshot.model_copy(update={
        "mappings": mappings,
        "options": options,
        "evidence": {},
        "ingredient_provenance": {
            code: provenance for code, provenance in snapshot.ingredient_provenance.items()
            if code in codes
        },
    })


def recommend(snapshot, req, trace_allowed=False):
    return _recommend_unfiltered(cosing_only(snapshot), req, trace_allowed)


def recommend_hybrid(snapshot, req):
    return _recommend_hybrid_unfiltered(cosing_only(snapshot), req)


def review_preview(snapshot):
    return _review_preview_unfiltered(cosing_only(snapshot))


class SkincareService:
    def __init__(self, repository: SkincareRepository):
        self.repository = repository

    async def recommend(self, req: SkincareRequest, trace_allowed=False):
        return recommend(await self.repository.read(), req, trace_allowed)

    async def recommend_hybrid(self, req: HybridRequest):
        return recommend_hybrid(await self.repository.read(), req)

    async def publish(self, snapshot: SkincareSnapshot):
        await self.repository.publish(snapshot)


def get_skincare_service(repository: SkincareRepository = Depends(get_skincare_repository)):
    return SkincareService(repository)


def skincare_service_for_session(session):
    return SkincareService(SkincareRepository(session))

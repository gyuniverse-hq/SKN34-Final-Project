"""Deterministic initial heuristics; no claims of efficacy or clinical validation."""

import logging
import math
from collections import defaultdict
from datetime import UTC, datetime
from statistics import median

from fastapi import Depends
from sqlalchemy.exc import SQLAlchemyError

from app.repositories.skincare_repository import SkincareRepository, get_skincare_repository
from app.schemas.recommendation_feedback import RecordedSkincareInput
from app.schemas.skincare import (
    GOALS,
    ConcernReason,
    CosingMapping,
    GoalCoverage,
    HybridMatch,
    HybridResponse,
    SkincareProfileRequest,
    SkincareSnapshot,
)
from app.services.rating_score_service import confidence_adjusted_rating
from app.services.recommendation_feedback_service import RecommendationFeedbackService
from app.services.review_suitability_service import (
    EMPIRICAL_SKIN_PRIORS,
    EMPIRICAL_SURVEY_PRIORS,
    GOAL_SURVEY_SIGNALS,
    SUITABILITY_WEIGHT,
    posterior_survey_ratio,
    rating_retention,
)

logger = logging.getLogger(__name__)

RARITY_FLOOR = 0.05
# Mobile-v4 model contract; near-boundary inclusion is an initial recommendation policy.
ANALYSIS_CARE_THRESHOLD = 0.5
ANALYSIS_SUPPORT_MIN = 0.35
ANALYSIS_GOOD_WEIGHT = 0.25
ANALYSIS_OUTLIER_MIN_EXCESS = 0.5
ANALYSIS_OUTLIER_MEDIAN_GAP = 0.20


def ingredient_weights(snapshot):
    """Catalog discrimination, never a measure of ingredient efficacy."""
    products = set()
    present = defaultdict(set)
    for option in snapshot.options:
        if option.available and option.identity_verified:
            products.add(option.product.id)
            for code in set(option.ingredient_codes):
                present[code].add(option.product.id)
    weights = {
        code: -math.log(max(len(ids) / len(products), RARITY_FLOOR)) / -math.log(RARITY_FLOOR)
        for code, ids in present.items()
    }
    return weights


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


def profile_review_score(option, skin_type, focus_goals):
    rating = confidence_adjusted_rating(option.rating_avg, option.review_count)
    skin_prior = EMPIRICAL_SKIN_PRIORS.get(skin_type)
    if skin_prior is not None:
        # Use skin-type responses once the user's type has a matching survey choice.
        suitability = posterior_survey_ratio(
            option.review_count, option.survey_ratios.get(skin_type), skin_prior
        )
    else:
        signals = {GOAL_SURVEY_SIGNALS[g] for g in focus_goals if g in GOAL_SURVEY_SIGNALS}
        ratios = [
            posterior_survey_ratio(
                option.review_count,
                option.survey_ratios.get(signal),
                EMPIRICAL_SURVEY_PRIORS[signal],
            )
            for signal in sorted(signals)
        ]
        suitability = math.prod(ratios) ** (1 / len(ratios)) if ratios else None
    return (rating - 1) / 4 * rating_retention(suitability, SUITABILITY_WEIGHT)


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
    oil_care = any(c.goal == "oiliness" for c in req.detected_concerns)
    dry_skin = req.skin_type == "dry"
    if oil_care == dry_skin:
        return None
    return "oiliness" if oil_care else "dryness"


def display_goal(goal):
    return "balance" if goal in ("dryness", "oiliness") else goal


def analysis_threshold(req: SkincareProfileRequest, goal: str) -> float:
    if goal == "blemish" and req.blemish_threshold is not None:
        return req.blemish_threshold
    return ANALYSIS_CARE_THRESHOLD


def profile_goal_weights(req: SkincareProfileRequest) -> dict[str, float]:
    """Policy priorities, never calibrated severity or diagnosis probabilities."""
    priorities = dict.fromkeys(skin_care_goals(req), 1.0)
    for concern in req.detected_concerns:
        priorities[concern.goal] = 1.0
    scores = req.analysis_scores
    if "blemish" not in scores:
        for goal, score in scores.items():
            if score >= ANALYSIS_SUPPORT_MIN:
                priorities[goal] = max(priorities.get(goal, 0), score / ANALYSIS_CARE_THRESHOLD)
        return priorities

    thresholds = {goal: analysis_threshold(req, goal) for goal in scores}
    excess = {
        goal: max(0.0, (score - thresholds[goal]) / (1 - thresholds[goal]))
        for goal, score in scores.items()
    }
    outlier_cutoff = max(
        ANALYSIS_OUTLIER_MIN_EXCESS, median(excess.values()) + ANALYSIS_OUTLIER_MEDIAN_GAP
    )
    for goal, score in scores.items():
        weight = 1.0 if score >= thresholds[goal] else ANALYSIS_GOOD_WEIGHT
        if excess[goal] >= outlier_cutoff:
            weight += 1.0
        priorities[goal] = max(priorities.get(goal, 0), weight)
    return priorities


def balanced_profile_overall(ranked, support, weights, priorities):
    """Greedy weighted function coverage with diminishing returns per display concern."""
    remaining = [row for row in ranked if row[1] & priorities.keys()]
    covered = dict.fromkeys({display_goal(goal) for goal in priorities}, 0.0)
    selected = []

    def contributions(row):
        fit, coverage = {}, {}
        for goal in sorted(row[1] & priorities.keys()):
            group = display_goal(goal)
            strength = support[row[2].option_id][0][goal]
            fit[group] = max(fit.get(group, 0), priorities[goal] * strength)
            coverage[group] = max(coverage.get(group, 0), strength)
        return fit, coverage

    while remaining and len(selected) < 10:

        def key(row):
            fit, _ = contributions(row)
            marginal = sum(value / (1 + covered[group]) for group, value in fit.items())
            similarity = max(
                (
                    support_similarity(support[row[2].option_id], support[s[2].option_id], weights)
                    for s in selected
                ),
                default=0.0,
            )
            *profile_and_review, review_count_order, product_id, option_id = row[0]
            return (
                -round(marginal, 12),
                -round(sum(fit.values()), 12),
                *profile_and_review,
                similarity,
                review_count_order,
                product_id,
                option_id,
            )

        best = min(remaining, key=key)
        selected.append(best)
        for group, strength in contributions(best)[1].items():
            covered[group] += strength
        remaining = [row for row in remaining if row[2].product.id != best[2].product.id]
    return selected


def _recommend_hybrid_unfiltered(
    snapshot: SkincareSnapshot | None, req: SkincareProfileRequest
) -> HybridResponse:
    sources = {}
    for concern in req.detected_concerns:
        reasons = sources.setdefault(concern.goal, [])
        for source in concern.sources:
            if source not in reasons:
                reasons.append(source)
    for goal in sorted(skin_care_goals(req)):
        sources.setdefault(goal, []).append("skinProfile")
    priorities = profile_goal_weights(req)
    for goal in sorted(priorities):
        if goal not in sources:
            sources[goal] = [
                "analysis"
                if req.analysis_scores[goal] >= analysis_threshold(req, goal)
                else "analysisSupport"
            ]
    intents = set(sources)
    for goal in GOALS:
        sources.setdefault(goal, ["concern"])
    active = (
        {
            m.mapping_id: m
            for m in snapshot.mappings
            if m.target_concern in sources and m.runtime_enabled and not m.blockers()
        }
        if snapshot
        else {}
    )
    weights = ingredient_weights(snapshot) if snapshot else {}
    support = {}
    # Coverage of the configured functions, not ingredient quantity or clinical efficacy.
    concern_functions = defaultdict(set)
    option_functions = {}
    for mapping in active.values():
        concern_functions[mapping.target_concern].update(mapping.function_names)
    reason_codes = {}
    ranked = []
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
        option_functions[option.option_id] = defaultdict(set)
        reason_codes[option.option_id] = defaultdict(set)
        codes, evidence = set(), set()
        for mapping in applied:
            option_functions[option.option_id][mapping.target_concern].update(
                mapping.function_names
            )
            reason_codes[option.option_id][mapping.target_concern].update(mapping.ingredient_codes)
            if mapping.target_concern in intents:
                codes.update(mapping.ingredient_codes)
                evidence.update(mapping.evidence_ids)
        strengths = {
            goal: len(functions) / len(concern_functions[goal])
            for goal, functions in option_functions[option.option_id].items()
        }
        support[option.option_id] = (
            strengths,
            set(option.ingredient_codes) & set(weights),
            codes,
            evidence,
        )
        review_score = profile_review_score(option, req.skin_type, intents)
        key = (
            -int(preferred is not None and preferred in goals),
            -len({display_goal(g) for g in goals & detected}),
            *profile_order(option, review_score),
        )
        ranked.append((key, goals, option))

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
                    evidence_sources=["cosing_function"],
                )
                for g, s in sources.items()
                if g in goals
            ],
        )

    overall_rows = balanced_profile_overall(ranked, support, weights, priorities)
    overall = [match_for(goals & intents, option) for _, goals, option in overall_rows]

    def concern_matches(target_goals, focus_goals, priority=None):
        def order(row):
            _, goals, option = row
            score = profile_review_score(option, req.skin_type, focus_goals)
            misses_priority = priority is not None and priority not in goals
            # Equal weight per goal keeps the merged moisture/oil tab balanced even
            # when those goals have different numbers of configured functions.
            fit = sum(
                len(option_functions[option.option_id][goal]) / len(concern_functions[goal])
                if concern_functions[goal]
                else 0.0
                for goal in sorted(target_goals)
            ) / len(target_goals)
            return (misses_priority, -fit, *profile_order(option, score))

        eligible = (row for row in ranked if row[1] & target_goals)
        products = {}
        for _, goals, option in sorted(eligible, key=order):
            if option.product.id in products:
                continue
            products[option.product.id] = match_for(goals, option)
            if len(products) == 5:
                break
        return list(products.values())

    groups = {goal: concern_matches({goal}, {goal}) for goal in sources}
    balance_matches = concern_matches({"dryness", "oiliness"}, (), preferred)
    active_goals = {m.target_concern for m in active.values()}
    return HybridResponse(
        data_version=snapshot.data_version if snapshot else None,
        overall_top5=overall[:5],
        overall_top10=overall,
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
        o.model_copy(
            update={
                "ingredient_codes": [c for c in o.ingredient_codes if c in codes],
                "matched_mapping_ids": [m for m in o.matched_mapping_ids or () if m in ids],
            }
        )
        for o in snapshot.options
    ]
    return snapshot.model_copy(
        update={
            "mappings": mappings,
            "options": options,
            "evidence": {},
            "ingredient_provenance": {
                code: provenance
                for code, provenance in snapshot.ingredient_provenance.items()
                if code in codes
            },
        }
    )


def recommend_hybrid(snapshot, req):
    return _recommend_hybrid_unfiltered(cosing_only(snapshot), req)


def review_preview(snapshot):
    return _review_preview_unfiltered(cosing_only(snapshot))


class SkincareService:
    def __init__(self, repository: SkincareRepository):
        self.repository = repository

    async def recommend_hybrid(self, req: SkincareProfileRequest):
        return recommend_hybrid(await self.repository.read(), req)

    async def recommend_recorded(
        self, req: RecordedSkincareInput, member_id: str, feedback: RecommendationFeedbackService
    ) -> HybridResponse:
        requested_at = datetime.now(UTC)
        result = await self.recommend_hybrid(req.input)
        try:
            await feedback.record_skincare(result, member_id, req.session_id, requested_at)
        except SQLAlchemyError:
            logger.warning("Rule-based skin recommendation history write failed")
        return result

    async def publish(self, snapshot: SkincareSnapshot):
        await self.repository.publish(snapshot)


def get_skincare_service(repository: SkincareRepository = Depends(get_skincare_repository)):
    return SkincareService(repository)

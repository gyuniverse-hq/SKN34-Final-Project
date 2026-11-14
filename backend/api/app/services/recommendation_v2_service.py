"""Fixed CatBoost seeds, original-table COSING expansion and auditable product ranking."""

import hashlib
import json
import re
from functools import lru_cache
from math import isfinite, prod
from pathlib import Path

from app.schemas.recommendation_comparison import ComparisonCatalog, ComparisonInput
from app.services.rating_score_service import ALPHA, DRAWS, MU, K, conservative_rating

GOAL_ORDER = ("pores", "pigmentation", "wrinkles")
CONCERNS = {"pores": "모공케어", "pigmentation": "톤잡티 케어", "wrinkles": "주름 케어"}
FEATURES = ["age_group", "gender", "skin_type", "primary_concern", "pore", "wrinkle", "tone"]
SCORE_FEATURES = ["pore_score", "wrinkle_score", "pigmentation_score"]
GOAL_SURVEY_SIGNALS = {
    "dryness": "hydrating",
    "sensitivity": "soothing",
    "pigmentation": "brighteningFirming",
    "wrinkles": "brighteningFirming",
}
# Frozen marginal-MLE estimates from 940 distinct products; never refit per request.
EMPIRICAL_SURVEY_PRIORS = {
    "brighteningFirming": {"k": 3.193016787576364, "mu": 0.13761171088373558},
    "hydrating": {"k": 5.10486948620085, "mu": 0.512084654830041},
    "soothing": {"k": 4.46375008983532, "mu": 0.35832233101772876},
}
EMPIRICAL_SKIN_PRIORS = {
    "dry": {"k": 11.17745832716916, "mu": 0.3722970100501606},
    "oily": {"k": 14.225746878031464, "mu": 0.11807707913884172},
    "combination": {"k": 28.880449830918376, "mu": 0.5112663779125135},
}
POLICY = {
    "version": "v2-primary-secondary-11",
    "secondaryThreshold": 0.5,
    "primaryConcernWeight": 0.75,
    "secondaryConcernWeight": 0.25,
    "candidatePolicy": "primary concern candidates only; secondary scores rerank them",
    "topK": 5,
    "expansion": "target concern -> function_concern -> ingredient_function",
    "expansionLimit": None,
    "reviewPolicy": "suitability",
    "suitabilityLambda": 0.2,
    "suitabilityCombination": "geometric mean of available EB posterior ratios",
    "surveyPolicy": "empirical_bayes",
    "surveyPriors": EMPIRICAL_SURVEY_PRIORS,
    "surveyPriorVersion": "eb-940-products-20261111",
    "surveyPriorCatalogDigest": "513d7d58728728d20a73c82c9424ab6196d7e50035f299ddba6814d1bc0e2320",
    "legacySurveyPrior": 207,
    "order": "integrated score -> bounded near-duplicate rerank -> stable IDs",
    "surveyWeight": 0.0,
    "skinSurveyWeight": 0.0,
    "legacySurveyWeight": 0.05,
    "legacySkinSurveyWeight": 0.05,
    "skinSurveyPriors": EMPIRICAL_SKIN_PRIORS,
    "skinSurveyPriorVersion": "skin-eb-940-products-20261112",
    "skinSurveyMapping": {"dry": "dry", "oily": "oily", "combination": "combination"},
    "ratingPolicy": "eb_lower10",
    "ratingPrior": K,
    "ratingPriorMean": MU,
    "ratingPriorAlpha": ALPHA,
    "ratingPriorVersion": "dirichlet-940-products-20261112",
    "ratingLowerQuantile": 0.10,
    "ratingQuantileDraws": DRAWS,
    "ratingQuantileSeed": 20261112,
    "legacyRatingPrior": 20,
    "reviewMixWeight": 0.20,
    "reviewRawRange": [1.0, 5.0],
    "additiveReviewRawRange": [0.90, 5.10],
    "legacyReviewRawRange": [0.95, 5.05],
    "indirectSeedWeight": 0.5,
    "mlWeight": 0.75,
    "concernWeight": 0.20,
    "skinTypeWeight": 0.05,
    "diversityWeight": 0.02,
    "nearDuplicateThreshold": 0.85,
    "purposePolicy": "facial leave-on; explicit non-facial name or incompatible category excluded",
    "allowedSubcategories": ["toner", "essence", "serum", "ampoule", "lotion", "cream"],
    "validatedOptimal": False,
}


def target_goal(body: ComparisonInput) -> str:
    # Explicit tie order, not dict insertion order. These are caution scores, not severity grades.
    scores = body.scores.model_dump()
    return max(GOAL_ORDER, key=lambda goal: scores[goal])


def secondary_goal(body: ComparisonInput, primary: str) -> str | None:
    scores = body.scores.model_dump()
    goal = max((g for g in GOAL_ORDER if g != primary), key=lambda g: scores[g])
    return goal if scores[goal] >= POLICY["secondaryThreshold"] else None


def feature_values(
    body: ComparisonInput, goal: str, features: list[str] | None = None
) -> list[str | float]:
    features = FEATURES if features is None else features
    if features not in (FEATURES, FEATURES + SCORE_FEATURES):
        raise ValueError("invalid_model_features")

    def state(score):
        return "주의" if score >= 0.5 else "양호"

    values: list[str | float] = [
        body.age_group,
        body.gender,
        body.skin_type,
        CONCERNS[goal],
        state(body.scores.pores),
        state(body.scores.wrinkles),
        state(body.scores.pigmentation),
    ]
    if features == FEATURES + SCORE_FEATURES:
        values.extend([body.scores.pores, body.scores.wrinkles, body.scores.pigmentation])
    return values


@lru_cache(maxsize=2)
def load_bundle(path: str):
    from catboost import CatBoostClassifier

    root = Path(path)
    manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
    model_path = root / "model.cbm"
    if (
        manifest["features"] not in (FEATURES, FEATURES + SCORE_FEATURES)
        or (
            manifest["features"] == FEATURES + SCORE_FEATURES
            and manifest.get("numericFeatures") != SCORE_FEATURES
        )
        or len(manifest["labels"]) != 80
        or len({label["db_id"] for label in manifest["labels"]}) != 80
        or manifest["modelSha256"] != hashlib.sha256(model_path.read_bytes()).hexdigest()
    ):
        raise ValueError("invalid_model_bundle")
    model = CatBoostClassifier()
    model.load_model(str(model_path))
    if (
        model.get_cat_feature_indices() != list(range(7))
        or len(model.feature_names_) != len(manifest["features"])
    ):
        raise ValueError("invalid_model_features")
    return model, manifest


def predict_seeds(body: ComparisonInput, goal: str, bundle_path: str):
    model, manifest = load_bundle(bundle_path)
    features = manifest["features"]
    values = feature_values(body, goal, features)
    for feature, value in zip(FEATURES, values[:7], strict=True):
        if value not in manifest["categories"][feature]:
            raise ValueError("unsupported_model_category")
    probabilities = list(model.predict_proba([values], thread_count=2)[0])
    if len(probabilities) != 80 or any(not isfinite(p) or not 0 <= p <= 1 for p in probabilities):
        raise ValueError("invalid_model_predictions")
    order = sorted(range(80), key=lambda i: (-probabilities[i], i))[:5]
    seeds = [
        {
            "id": manifest["labels"][i]["db_id"],
            "name": manifest["labels"][i]["name"],
            "score": float(probabilities[i]),
            "rank": rank + 1,
        }
        for rank, i in enumerate(order)
    ]
    return seeds, {
        "version": manifest["version"],
        "sha256": manifest["modelSha256"],
        "features": dict(zip(features, values, strict=True)),
        "trainingContract": manifest["trainingContract"],
    }


def expand(seeds: list[dict], catalog: ComparisonCatalog, goal: str):
    goal_tags = set(catalog.functions_by_concern.get(goal, []))
    by_id = {i: set(tags) & goal_tags for i, tags in catalog.functions_by_id.items()}
    seed_ids = {s["id"] for s in seeds}
    skipped = [
        {
            "id": seed["id"],
            "reason": "no_ml_shared_concern_tag",
            "ingredientTags": sorted(catalog.functions_by_id.get(seed["id"], [])),
            "concernTags": sorted(goal_tags),
        }
        for seed in seeds
        if not by_id.get(seed["id"])
    ]
    candidates = []
    for ingredient_id, tags in sorted(by_id.items()):
        if not tags or ingredient_id in seed_ids:
            continue
        origins = []
        for seed in seeds:
            seed_tags = by_id.get(seed["id"], set())
            common = seed_tags & tags
            if common:
                origins.append(
                    {
                        "seedId": seed["id"],
                        "functions": sorted(common),
                        "similarity": len(common) / len(seed_tags | tags),
                    }
                )
        candidates.append(
            {
                "id": ingredient_id,
                "name": catalog.names.get(ingredient_id, str(ingredient_id)),
                "score": max(
                    (
                        o["similarity"] * next(s["score"] for s in seeds if s["id"] == o["seedId"])
                        for o in origins
                    ),
                    default=0.0,
                ),
                "concern": goal,
                "concernFunctions": sorted(tags),
                "source": "ml_shared_tag" if origins else "concern_only",
                "origins": origins,
            }
        )
    return sorted(candidates, key=lambda r: (-r["score"], r["id"])), skipped


# Explicit words in a product title are evidence for this local routing rule,
# not a verified usage instruction or an inference from ingredient efficacy.
NON_FACIAL = (
    ("neck", r"목\s*주름|넥\s*(?:크림|세럼|밤)|\bneck\s*(?:cream|serum|balm)\b"),
    ("body", r"바디\s*(?:로션|크림|세럼|미스트)|\bbody\s*(?:lotion|cream|serum)\b"),
    ("hands", r"핸드\s*(?:크림|밤)|\bhand\s*(?:cream|balm)\b"),
    ("feet", r"풋\s*(?:크림|밤)|발\s*전용|\bfoot\s*(?:cream|balm)\b"),
    ("lips", r"립\s*(?:밤|마스크)|\blip\s*(?:balm|mask)\b"),
)


def product_purpose(option):
    if option.subcategory and option.subcategory not in POLICY["allowedSubcategories"]:
        return {
            "status": "excluded",
            "reason": "incompatible_category",
            "source": "catalog.subcategory",
            "evidence": option.subcategory,
        }
    # A title explicitly advertising face use as well is not treated as non-facial only.
    face = re.search(r"얼굴|페이스|페이셜|\bface\b|\bfacial\b", option.product_name, re.I)
    if not face:
        for area, pattern in NON_FACIAL:
            match = re.search(pattern, option.product_name, re.I)
            if match:
                return {
                    "status": "excluded",
                    "reason": "explicit_non_facial_title",
                    "source": "catalog.productName",
                    "area": area,
                    "evidence": match[0],
                }
    return {
        "status": "no_explicit_conflict",
        "source": "catalog.category_and_title",
        "usageVerified": False,
    }


def survey_baselines(options):
    # Exactly V1's product deduplication and review-count weighted reference population.
    products = {
        o.product_id: o for o in sorted(options, key=lambda o: o.option_id) if o.review.review_count
    }
    totals, counts = {}, {}
    for option in products.values():
        for signal, ratio in option.review.survey_ratios.items():
            count = option.review.review_count
            totals[signal] = totals.get(signal, 0) + count * ratio
            counts[signal] = counts.get(signal, 0) + count
    return {signal: total / counts[signal] for signal, total in totals.items()}


def survey_adjustment(review, goal, baselines, *, survey_policy="empirical_bayes"):
    if survey_policy not in ("empirical_bayes", "legacy_207"):
        raise ValueError("invalid_survey_policy")
    # Select only the raw survey answer corresponding to the automatic target concern.
    signals = []
    goal_signal = GOAL_SURVEY_SIGNALS
    if goal in goal_signal:
        signals.append((goal_signal[goal], 1))
    count = review.review_count or 0
    prior = EMPIRICAL_SURVEY_PRIORS.get(goal_signal.get(goal))
    k = (
        (prior["k"] if survey_policy == "empirical_bayes" else POLICY["legacySurveyPrior"])
        if prior
        else None
    )
    reliability = count / (count + k) if k is not None else 0.0
    details = [
        {
            "signal": signal,
            "sign": sign,
            "ratio": review.survey_ratios.get(signal),
            "baseline": EMPIRICAL_SURVEY_PRIORS[signal]["mu"]
            if survey_policy == "empirical_bayes"
            else baselines.get(signal),
        }
        for signal, sign in signals
    ]
    used = [d for d in details if d["ratio"] is not None and d["baseline"] is not None]
    adjustment = (
        sum(d["sign"] * reliability * (d["ratio"] - d["baseline"]) for d in used) / len(signals)
        if signals
        else 0.0
    )
    return adjustment, {
        "status": "available"
        if used and count
        else "missing_review_count"
        if used
        else "missing_signals"
        if signals
        else "unsupported_signal",
        "targetConcern": goal,
        "question": "피부고민" if signals else None,
        "answer": {
            "hydrating": "보습에 좋아요",
            "soothing": "진정에 좋아요",
            "brighteningFirming": "주름/미백에 좋아요",
        }.get(goal_signal.get(goal)),
        "reviewCount": review.review_count,
        "countBasis": "review_count_is_respondents_user_confirmed",
        "surveyPolicy": survey_policy,
        "priorK": k,
        "baselineSource": "empirical_bayes_frozen"
        if survey_policy == "empirical_bayes"
        else "catalog_review_weighted_mean",
        "priorVersion": POLICY["surveyPriorVersion"]
        if survey_policy == "empirical_bayes"
        else "legacy-207",
        "reliability": reliability,
        "signals": details,
        "surveyAdjustment": adjustment,
    }


def skin_type_adjustment(review, skin_type):
    # These are suitability answers, not reviewer demographics. No balanced
    # answer exists; never substitute combination, dryness or a concern answer.
    prior = EMPIRICAL_SKIN_PRIORS.get(skin_type)
    ratio = review.survey_ratios.get(skin_type) if prior else None
    count = review.review_count or 0
    reliability = count / (count + prior["k"]) if prior else 0.0
    adjustment = reliability * (ratio - prior["mu"]) if ratio is not None else 0.0
    return adjustment, {
        "status": "unsupported_skin_type"
        if prior is None
        else "missing_signals"
        if ratio is None
        else "missing_review_count"
        if not count
        else "available",
        "skinType": skin_type,
        "question": "피부타입",
        "answer": {
            "dry": "건성에 좋아요",
            "oily": "지성에 좋아요",
            "combination": "복합성에 좋아요",
        }.get(skin_type),
        "signal": skin_type if prior else None,
        "ratio": ratio,
        "baseline": prior["mu"] if prior else None,
        "priorK": prior["k"] if prior else None,
        "priorVersion": POLICY["skinSurveyPriorVersion"],
        "baselineSource": "empirical_bayes_frozen" if prior else None,
        "reliability": reliability,
        "adjustment": adjustment,
    }


def user_suitability(review, goal, skin_type, *, include_skin=True, secondary_concern=None):
    """Combine marginal suitability evidence; never a joint outcome probability."""
    count = review.review_count or 0
    requested = [("concern", GOAL_SURVEY_SIGNALS.get(goal), EMPIRICAL_SURVEY_PRIORS)]
    concern_weights = {GOAL_SURVEY_SIGNALS.get(goal): 1.0}
    concern_goals = {GOAL_SURVEY_SIGNALS.get(goal): [goal]}
    if secondary_concern:
        primary_signal = GOAL_SURVEY_SIGNALS.get(goal)
        secondary_signal = GOAL_SURVEY_SIGNALS.get(secondary_concern)
        concern_weights[primary_signal] = POLICY["primaryConcernWeight"]
        concern_weights[secondary_signal] = (
            concern_weights.get(secondary_signal, 0) + POLICY["secondaryConcernWeight"]
        )
        concern_goals.setdefault(secondary_signal, []).append(secondary_concern)
        if secondary_signal != primary_signal:
            requested.append(("concern", secondary_signal, EMPIRICAL_SURVEY_PRIORS))
    if include_skin:
        requested.append(("skinType", skin_type, EMPIRICAL_SKIN_PRIORS))
    signals = []
    for source, signal, priors in requested:
        prior = priors.get(signal)
        ratio = review.survey_ratios.get(signal) if prior else None
        available = prior is not None and ratio is not None and count > 0
        signals.append(
            {
                "source": source,
                "signal": signal if prior else None,
                "status": "unsupported_signal"
                if prior is None
                else "missing_signals"
                if ratio is None
                else "missing_review_count"
                if not count
                else "available",
                "ratio": ratio,
                "reviewCount": review.review_count,
                "priorK": prior["k"] if prior else None,
                "baseline": prior["mu"] if prior else None,
                "posteriorRatio": (count * ratio + prior["k"] * prior["mu"]) / (count + prior["k"])
                if available
                else prior["mu"]
                if prior
                else None,
                "posteriorSource": "observed_plus_prior"
                if available
                else "prior_only"
                if prior
                else "unsupported",
            }
        )
        if secondary_concern and source == "concern":
            signals[-1].update({"goals": concern_goals[signal], "weight": concern_weights[signal]})
    values = [s["posteriorRatio"] for s in signals if s["posteriorRatio"] is not None]
    if secondary_concern:
        concerns = [
            s for s in signals if s["source"] == "concern" and s["posteriorRatio"] is not None
        ]
        supported_weight = sum(s["weight"] for s in concerns)
        values = (
            [sum(s["weight"] * s["posteriorRatio"] for s in concerns) / supported_weight]
            if concerns
            else []
        )
        values += [
            s["posteriorRatio"]
            for s in signals
            if s["source"] == "skinType" and s["posteriorRatio"] is not None
        ]
        for signal in concerns:
            signal["effectiveWeight"] = signal["weight"] / supported_weight
    return (prod(values) ** (1 / len(values)) if values else None), signals


def rating_baseline(options):
    products = {
        o.product_id: (o.review.review_count, o.review.rating_avg)
        for o in sorted(options, key=lambda o: o.option_id)
        if o.review.review_count and o.review.rating_avg is not None
    }
    total = sum(n for n, _ in products.values())
    return sum(n * rating for n, rating in products.values()) / total if total else None


def combined_review(
    review,
    goal,
    survey_means,
    rating_mean,
    *,
    survey_policy="empirical_bayes",
    rating_policy="eb_lower10",
    skin_type="unknown",
    skin_review=True,
    review_policy="suitability",
    suitability_lambda=POLICY["suitabilityLambda"],
    secondary_concern=None,
):
    if review_policy not in ("suitability", "additive"):
        raise ValueError("invalid_review_policy")
    if not isfinite(suitability_lambda) or not 0 <= suitability_lambda <= 1:
        raise ValueError("invalid_suitability_lambda")
    if rating_policy not in ("eb_lower10", "legacy_20"):
        raise ValueError("invalid_rating_policy")
    adjustment, evidence = survey_adjustment(
        review, goal, survey_means, survey_policy=survey_policy
    )
    if review_policy == "suitability" and survey_policy != "empirical_bayes":
        raise ValueError("suitability_requires_empirical_surveys")
    # Match V1's empirical prior. An entirely unrated catalog uses an explicitly
    # labelled neutral midpoint, never a fabricated observed product rating.
    prior = rating_mean if rating_mean is not None else 3.0
    count = review.review_count or 0
    rated = bool(count and review.rating_avg is not None and rating_mean is not None)
    adjusted = (
        (
            (count * review.rating_avg + POLICY["legacyRatingPrior"] * prior)
            / (count + POLICY["legacyRatingPrior"])
        )
        if rated
        else prior
    )
    rating_evidence = (
        conservative_rating(review)
        if rating_policy == "eb_lower10"
        else {"ratingPolicy": "legacy_20", "ratingPriorK": POLICY["legacyRatingPrior"]}
    )
    if rating_policy == "eb_lower10":
        adjusted = rating_evidence["adjustedRating"]
        rated = rating_evidence["ratingStatus"] == "reconstructed_distribution"
    survey_bonus = POLICY["legacySurveyWeight"] * adjustment
    skin_adjustment, skin_evidence = skin_type_adjustment(review, skin_type)
    if not skin_review:
        skin_adjustment = 0.0
        skin_evidence = {**skin_evidence, "status": "disabled", "adjustment": 0.0}
    skin_bonus = POLICY["legacySkinSurveyWeight"] * skin_adjustment
    raw_score = adjusted + survey_bonus + skin_bonus
    low, high = POLICY["additiveReviewRawRange" if skin_review else "legacyReviewRawRange"]
    normalized = (raw_score - low) / (high - low)
    suitability_evidence = {}
    if review_policy == "suitability":
        suitability, signals = user_suitability(
            review, goal, skin_type, include_skin=skin_review, secondary_concern=secondary_concern
        )
        retention = (
            1.0
            if suitability is None
            else 1 - suitability_lambda + suitability_lambda * suitability
        )
        base = (adjusted - 1.0) / 4.0
        normalized = base * retention
        # Derived star-equivalent diagnostic only; not an observed product rating.
        raw_score, low, high = 1.0 + 4.0 * normalized, 1.0, 5.0
        survey_bonus = skin_bonus = 0.0
        suitability_evidence = {
            "suitabilityScore": suitability,
            "suitabilitySignals": signals,
            "suitabilityLambda": suitability_lambda,
            "ratingRetention": retention,
            "normalizedRating": base,
            "suitabilityPenalty": base - normalized,
        }
    survey_available = evidence["status"] == "available" or skin_evidence["status"] == "available"
    if secondary_concern:
        survey_available = any(
            s["status"] == "available" for s in suitability_evidence["suitabilitySignals"]
        )
    return {
        **evidence,
        "surveyStatus": evidence["status"],
        "status": "rating_and_survey"
        if rated and survey_available
        else "rating_only"
        if rated
        else "survey_only"
        if survey_available
        else "prior_only",
        "ratingAvg": review.rating_avg,
        "ratingBaseline": rating_mean,
        "ratingPriorValue": prior,
        "ratingPriorSource": "catalog_weighted_mean"
        if rating_mean is not None
        else "neutral_midpoint",
        "ratingStatus": "observed" if rated else "prior_only",
        "adjustedRating": adjusted,
        "ratingReliability": count / (count + POLICY["legacyRatingPrior"]) if rated else 0.0,
        **rating_evidence,
        "surveyBonus": survey_bonus,
        "reviewPolicy": review_policy,
        **suitability_evidence,
        "skinTypeReview": skin_evidence,
        "skinTypeBonus": skin_bonus,
        "reviewRawRange": [low, high],
        "rawCombinedScore": raw_score,
        "normalizedScore": normalized,
    }


def ingredient_evidence(ingredients, seed_scores, expanded_by_id, goal_tags, catalog):
    direct = sorted(ingredients & seed_scores.keys())
    related = sorted(ingredients & expanded_by_id.keys())
    denominator = sum(seed_scores.values()) or 1
    seed_matches = []
    for seed_id, probability in seed_scores.items():
        strength, origin_id = (1.0, seed_id) if seed_id in ingredients else (0.0, None)
        if not strength:
            for ingredient_id in related:
                for origin in expanded_by_id[ingredient_id]["origins"]:
                    value = POLICY["indirectSeedWeight"] * origin["similarity"]
                    if origin["seedId"] == seed_id and value > strength:
                        strength, origin_id = value, ingredient_id
        seed_matches.append(
            {
                "seedId": seed_id,
                "matchedIngredientId": origin_id,
                "strength": strength,
                "contribution": probability * strength,
            }
        )
    ml_score = sum(m["contribution"] for m in seed_matches) / denominator
    tags = set()
    for ingredient_id in direct + related:
        tags.update(set(catalog.functions_by_id.get(ingredient_id, [])) & goal_tags)
    concern_score = len(tags) / len(goal_tags) if goal_tags else 0.0
    return {
        "directIngredientIds": direct,
        "expandedIngredientIds": related,
        "mlScore": ml_score,
        "concernScore": concern_score,
        "matchedConcernFunctions": sorted(tags),
        "seedMatches": seed_matches,
    }


def rank_products(
    seeds: list[dict],
    expanded: list[dict],
    catalog: ComparisonCatalog,
    goal: str,
    *,
    skin_type="unknown",
    review_mix_weight: float = POLICY["reviewMixWeight"],
    diversify: bool = True,
    rating_policy: str = "eb_lower10",
    survey_policy: str = "empirical_bayes",
    skin_review: bool = True,
    review_policy: str = "suitability",
    suitability_lambda: float = POLICY["suitabilityLambda"],
    secondary: dict | None = None,
    audit: dict | None = None,
):
    if secondary and (
        secondary["goal"] not in GOAL_ORDER
        or secondary["goal"] == goal
        or review_policy != "suitability"
    ):
        raise ValueError("invalid_secondary_concern")
    if review_policy not in ("suitability", "additive"):
        raise ValueError("invalid_review_policy")
    if not isfinite(suitability_lambda) or not 0 <= suitability_lambda <= 1:
        raise ValueError("invalid_suitability_lambda")
    if rating_policy not in ("eb_lower10", "legacy_20"):
        raise ValueError("invalid_rating_policy")
    if survey_policy not in ("empirical_bayes", "legacy_207"):
        raise ValueError("invalid_survey_policy")
    if review_policy == "suitability" and survey_policy != "empirical_bayes":
        raise ValueError("suitability_requires_empirical_surveys")
    if not isfinite(review_mix_weight) or not 0 <= review_mix_weight <= 1:
        raise ValueError("invalid_review_mix_weight")
    seed_scores = {s["id"]: s["score"] for s in seeds}
    expanded_by_id = {s["id"]: s for s in expanded}
    goal_tags = set(catalog.functions_by_concern.get(goal, []))
    secondary_scores = (
        {s["id"]: s["score"] for s in secondary["coreIngredients"]} if secondary else {}
    )
    secondary_expanded = {s["id"]: s for s in secondary["expandedIngredients"]} if secondary else {}
    secondary_tags = (
        set(catalog.functions_by_concern.get(secondary["goal"], [])) if secondary else set()
    )
    baselines = survey_baselines(catalog.options)
    rating_mean = rating_baseline(catalog.options)
    rows, excluded = [], []
    compositions = {o.option_id: set(o.ingredient_ids) for o in catalog.options}
    categories = {o.option_id: o.subcategory for o in catalog.options}
    for option in catalog.options:
        ingredients = compositions[option.option_id]
        direct = sorted(ingredients & seed_scores.keys())
        related = sorted(ingredients & expanded_by_id.keys())
        if not direct and not related:
            continue
        purpose = product_purpose(option)
        if purpose["status"] == "excluded":
            excluded.append(
                {
                    "productId": option.product_id,
                    "productName": option.product_name,
                    "optionId": option.option_id,
                    **purpose,
                }
            )
            continue
        primary_evidence = ingredient_evidence(
            ingredients, seed_scores, expanded_by_id, goal_tags, catalog
        )
        ml_score, concern_score = primary_evidence["mlScore"], primary_evidence["concernScore"]
        seed_matches = primary_evidence["seedMatches"]
        tags = primary_evidence["matchedConcernFunctions"]
        verified_type = bool(option.label_source and option.skin_types)
        type_score = float(
            verified_type and skin_type != "unknown" and skin_type in option.skin_types
        )
        relevance = (
            POLICY["mlWeight"] * ml_score
            + POLICY["concernWeight"] * concern_score
            + POLICY["skinTypeWeight"] * type_score
        )
        dual_evidence = {}
        if secondary:
            other = ingredient_evidence(
                ingredients, secondary_scores, secondary_expanded, secondary_tags, catalog
            )
            other_score = (
                POLICY["mlWeight"] * other["mlScore"]
                + POLICY["concernWeight"] * other["concernScore"]
                + POLICY["skinTypeWeight"] * type_score
            )
            dual_evidence = {
                "primaryIngredientScore": relevance,
                "secondaryIngredientScore": other_score,
                "secondaryIngredientEvidence": {"goal": secondary["goal"], **other},
                "goalWeights": {
                    goal: POLICY["primaryConcernWeight"],
                    secondary["goal"]: POLICY["secondaryConcernWeight"],
                },
            }
            relevance = (
                POLICY["primaryConcernWeight"] * relevance
                + POLICY["secondaryConcernWeight"] * other_score
            )
        review = combined_review(
            option.review,
            goal,
            baselines,
            rating_mean,
            survey_policy=survey_policy,
            rating_policy=rating_policy,
            skin_type=skin_type,
            skin_review=skin_review,
            review_policy=review_policy,
            suitability_lambda=suitability_lambda,
            secondary_concern=secondary["goal"] if secondary else None,
        )
        rows.append(
            {
                "productId": option.product_id,
                "productName": option.product_name,
                "optionId": option.option_id,
                "directIngredientIds": direct,
                "expandedIngredientIds": related,
                "candidateSources": (["ml_direct"] if direct else [])
                + (["ml_shared_tag"] if any(expanded_by_id[i]["origins"] for i in related) else [])
                + (
                    ["concern_only"]
                    if any(not expanded_by_id[i]["origins"] for i in related)
                    else []
                ),
                "ingredientScore": relevance,
                **dual_evidence,
                "mlScore": ml_score,
                "concernScore": concern_score,
                "skinTypeScore": type_score,
                "skinTypeEvidence": option.label_source,
                "matchedConcernFunctions": sorted(tags),
                "seedMatches": seed_matches,
                "purpose": purpose,
                "review": review,
                "reviewAdjusted": review["normalizedScore"]
                if review["status"] != "prior_only"
                else None,
            }
        )

    def select(weight, use_diversity):
        remaining = [
            {
                **r,
                "reviewBonus": weight * (r["review"]["normalizedScore"] - r["ingredientScore"]),
                "ingredientContribution": (1 - weight) * r["ingredientScore"],
                "reviewContribution": weight * r["review"]["normalizedScore"],
                "score": (1 - weight) * r["ingredientScore"]
                + weight * r["review"]["normalizedScore"],
            }
            for r in rows
        ]
        selected = []
        while remaining and len(selected) < 5:
            evaluated = []
            for row in remaining:
                similarity = 0.0
                similar_to = None
                if use_diversity and categories[row["optionId"]]:
                    for chosen in selected:
                        if categories[row["optionId"]] != categories[chosen["optionId"]]:
                            continue
                        left, right = (
                            compositions[row["optionId"]],
                            compositions[chosen["optionId"]],
                        )
                        value = len(left & right) / len(left | right) if left | right else 0.0
                        if value >= POLICY["nearDuplicateThreshold"] and value > similarity:
                            similarity, similar_to = value, chosen["productId"]
                penalty = POLICY["diversityWeight"] * similarity
                evaluated.append(
                    {
                        **row,
                        "diversityPenalty": penalty,
                        "similarToProductId": similar_to,
                        "selectionScore": row["score"] - penalty,
                    }
                )
            best = min(
                evaluated, key=lambda r: (-r["selectionScore"], r["productId"], r["optionId"])
            )
            selected.append(best)
            remaining = [r for r in remaining if r["productId"] != best["productId"]]
        # Top five use the sequential diversity rule; lower ranks are score-only diagnostics.
        rest = {}
        for row in sorted(remaining, key=lambda r: (-r["score"], r["productId"], r["optionId"])):
            rest.setdefault(row["productId"], row)
        return selected, list(rest.values())

    before, rest_before = select(0, diversify)
    after, rest_after = select(review_mix_weight, diversify)
    score_only, _ = select(review_mix_weight, False)
    before_rank = {row["productId"]: i + 1 for i, row in enumerate(before + rest_before)}
    unique = after + rest_after
    if audit is not None:
        # Preserve every eligible option before product deduplication, without changing ranking.
        options = {o.option_id: o for o in catalog.options}
        selected = {r["optionId"]: {**r, "rank": i + 1} for i, r in enumerate(after)}
        audit["candidates"] = [
            {
                **r,
                "score": (1 - review_mix_weight) * r["ingredientScore"]
                + review_mix_weight * r["review"]["normalizedScore"],
                **selected.get(r["optionId"], {}),
                "catalogOption": options[r["optionId"]].model_dump(mode="json"),
            }
            for r in rows
        ]
        audit["catalog"] = {
            "version": catalog.version,
            "digest": catalog.digest,
            "sourceManifest": catalog.source_manifest,
            "functionsById": catalog.functions_by_id,
            "functionsByConcern": catalog.functions_by_concern,
        }
    return {
        "matches": [
            {**r, "rank": i + 1, "rankBeforeReview": before_rank[r["productId"]]}
            for i, r in enumerate(after)
        ],
        "reviewMixWeight": review_mix_weight,
        "reviewPolicy": review_policy,
        "suitabilityLambda": suitability_lambda if review_policy == "suitability" else None,
        "surveyWeight": POLICY["legacySurveyWeight"] if review_policy == "additive" else 0.0,
        "skinSurveyWeight": POLICY["legacySkinSurveyWeight"]
        if skin_review and review_policy == "additive"
        else 0.0,
        "skinTypeReviewEnabled": skin_review,
        "ratingPolicy": rating_policy,
        "ratingBaseline": MU if rating_policy == "eb_lower10" else rating_mean,
        "beforeReviewMatches": [{**r, "rank": i + 1} for i, r in enumerate(before)],
        "beforeReview": [r["productId"] for r in before],
        "beforeDiversity": [r["productId"] for r in score_only],
        "directCandidateProducts": sum(bool(r["directIngredientIds"]) for r in unique),
        "expansionOnlyCandidateProducts": sum(not r["directIngredientIds"] for r in unique),
        "candidateProducts": len(unique),
        "candidateOptions": len(rows),
        "excludedProducts": len({r["productId"] for r in excluded}),
        "excludedOptions": excluded,
        "reviewAppliedProducts": sum(r["reviewAdjusted"] is not None for r in unique),
        "skinTypeLabeledProducts": sum(bool(r["skinTypeEvidence"]) for r in unique),
        "shortfall": max(0, 5 - len(after)),
        "surveyPolicy": survey_policy,
        "surveyBaselines": {s: p["mu"] for s, p in EMPIRICAL_SURVEY_PRIORS.items()}
        if survey_policy == "empirical_bayes"
        else baselines,
    }


def recommend_v2(
    body: ComparisonInput,
    goal: str,
    catalog: ComparisonCatalog,
    bundle: str,
    *,
    enable_secondary=True,
    audit: dict | None = None,
    model_name: str | None = None,
):
    if model_name is not None:
        _, manifest = load_bundle(bundle)
        if manifest["version"] != model_name:
            raise ValueError("recommendation_model_name_mismatch")
    seeds, model = predict_seeds(body, goal, bundle)
    related, skipped = expand(seeds, catalog, goal)
    second_goal = secondary_goal(body, goal) if enable_secondary else None
    secondary = None
    if second_goal:
        second_seeds, second_model = predict_seeds(body, second_goal, bundle)
        second_expanded, second_skipped = expand(second_seeds, catalog, second_goal)
        secondary = {
            "goal": second_goal,
            "model": second_model,
            "coreIngredients": second_seeds,
            "expandedIngredients": second_expanded,
            "unexpandedSeeds": second_skipped,
        }
    available_ids = {i for o in catalog.options for i in o.ingredient_ids}
    return {
        "status": "ok",
        "model": model,
        "coreIngredients": seeds,
        "expandedIngredients": related,
        "unexpandedSeeds": skipped,
        "expansionCoverage": {
            "totalIngredients": len(related),
            "ingredientsWithProducts": sum(i["id"] in available_ids for i in related),
        },
        "policy": POLICY,
        "secondaryConcern": second_goal,
        "secondarySelection": {
            "enabled": enable_secondary,
            "threshold": POLICY["secondaryThreshold"],
            "status": "active"
            if second_goal
            else "below_threshold"
            if enable_secondary
            else "disabled",
        },
        "secondaryRecommendation": secondary,
        **rank_products(
            seeds,
            related,
            catalog,
            goal,
            secondary=secondary,
            audit=audit,
            skin_type={
                "건성": "dry",
                "중성": "balanced",
                "지성": "oily",
                "복합성": "combination",
            }.get(body.skin_type, "unknown"),
        ),
    }

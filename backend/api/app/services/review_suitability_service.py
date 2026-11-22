"""Empirical survey priors used in skincare recommendation reranking."""

GOAL_SURVEY_SIGNALS = {
    "dryness": "hydrating",
    "sensitivity": "soothing",
    "pigmentation": "brighteningFirming",
    "wrinkles": "brighteningFirming",
}

# Frozen beta-binomial estimates from 940 distinct products.
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
SUITABILITY_WEIGHT = 0.2


def posterior_survey_ratio(
    review_count: int | None, ratio: float | None, prior: dict[str, float]
) -> float:
    if not review_count or ratio is None:
        return prior["mu"]
    return (review_count * ratio + prior["k"] * prior["mu"]) / (review_count + prior["k"])


def rating_retention(suitability: float | None, weight: float) -> float:
    return 1.0 if suitability is None else 1 - weight + weight * suitability

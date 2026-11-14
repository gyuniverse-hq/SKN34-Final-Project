"""Frozen rating prior; conservative posterior score, never fitted per request."""

from functools import lru_cache
from math import isfinite

ALPHA = (
    0.21316285288685022,
    0.22400253262981365,
    1.1943781896886343,
    3.1089355424361247,
    30.133029611688013,
)
K = sum(ALPHA)
MU = sum(star * a for star, a in enumerate(ALPHA, 1)) / K
QUANTILE = 0.10
DRAWS = 100_000


def reconstruct_counts(review):
    n, raw = review.review_count, review.rating_percentages
    if not n or review.rating_avg is None or raw is None or all(v is None for v in raw):
        return None, review.rating_distribution_status
    p = [0.0 if v is None else v for v in raw]
    if any(not isfinite(v) or not 0 <= v <= 100 for v in p) or not 98 <= sum(p) <= 102:
        return None, "invalid_percentage_total"
    expected = [n * v / sum(p) for v in p]
    counts = [int(v) for v in expected]
    order = sorted(range(5), key=lambda i: (-(expected[i] - counts[i]), i))
    for i in order[: n - sum(counts)]:
        counts[i] += 1
    mean = sum(s * x for s, x in enumerate(counts, 1)) / n
    if abs(mean - review.rating_avg) > 0.100001:
        return None, "distribution_display_mean_mismatch"
    return tuple(counts), "absent_stars_zero_assumption" if None in raw else "all_stars_present"


@lru_cache(maxsize=4096)
def posterior_score(counts):
    # Local RNG + fixed seed: identical evidence produces identical scores across
    # products, requests and processes. Cached by evidence, not product identity.
    import numpy as np

    posterior = np.asarray(ALPHA) + counts
    stars = np.arange(1, 6)
    mean = float(posterior @ stars / posterior.sum())
    rng = np.random.default_rng(20261112)
    values = (rng.dirichlet(posterior, size=DRAWS) * stars).sum(axis=1)
    return mean, float(np.quantile(values, QUANTILE))


def conservative_rating(review):
    counts, status = reconstruct_counts(review)
    mean, lower = posterior_score(counts or (0, 0, 0, 0, 0))
    n = sum(counts) if counts else 0
    return {
        "ratingPolicy": "eb_lower10",
        "ratingPriorK": K,
        "ratingBaseline": MU,
        "ratingPriorValue": MU,
        "ratingPriorSource": "frozen_dirichlet_multinomial_940_products",
        "ratingStatus": "reconstructed_distribution" if counts else "prior_only",
        "ratingDistributionStatus": status,
        "ratingStarCounts": list(counts) if counts else None,
        "ratingPosteriorMean": mean,
        "ratingUncertaintyPenalty": mean - lower,
        "ratingLowerQuantile": QUANTILE,
        "ratingQuantileDraws": DRAWS,
        "adjustedRating": lower,
        "ratingReliability": n / (n + K),
    }

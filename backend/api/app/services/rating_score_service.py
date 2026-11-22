"""Frozen rating prior; conservative posterior score, never fitted per request."""

from math import sqrt
from statistics import NormalDist

ALPHA = (
    0.21316285288685022,
    0.22400253262981365,
    1.1943781896886343,
    3.1089355424361247,
    30.133029611688013,
)
K = sum(ALPHA)
MU = sum(star * a for star, a in enumerate(ALPHA, 1)) / K
PRIOR_RATING_VARIANCE = sum((star - MU) ** 2 * a for star, a in enumerate(ALPHA, 1)) / K
QUANTILE = 0.10
LOWER_QUANTILE_Z = NormalDist().inv_cdf(QUANTILE)


def posterior_rating_mean(rating_avg: float | None, review_count: int | None) -> float:
    """Posterior mean using the published review count and average."""
    if rating_avg is None or not review_count:
        return MU
    return (review_count * rating_avg + K * MU) / (review_count + K)


def confidence_adjusted_rating(rating_avg: float | None, review_count: int | None) -> float:
    """Approximate a lower posterior rating from the published mean and count."""
    count = (review_count or 0) if rating_avg is not None else 0
    mean = posterior_rating_mean(rating_avg, count)
    # Snapshots contain the aggregate mean and count. Use the prior's dispersion
    # as a common estimate and scale the standard error by the posterior count.
    standard_error = sqrt(PRIOR_RATING_VARIANCE / (count + K + 1))
    return max(1.0, mean + LOWER_QUANTILE_Z * standard_error)

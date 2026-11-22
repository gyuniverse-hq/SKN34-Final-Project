import pytest

from app.services.rating_score_service import (
    MU,
    confidence_adjusted_rating,
    posterior_rating_mean,
)


def test_posterior_mean_uses_empirical_rating_prior_with_only_count_and_average():
    assert posterior_rating_mean(4.6, 1000) == pytest.approx(4.60669, abs=0.00001)
    assert posterior_rating_mean(5.0, 2) == pytest.approx(4.80956, abs=0.00001)
    assert posterior_rating_mean(None, 0) == pytest.approx(MU)


def test_confidence_margin_favors_more_evidence_at_the_same_posterior_mean():
    assert posterior_rating_mean(MU, 2) == pytest.approx(posterior_rating_mean(MU, 1000))
    assert 1 < confidence_adjusted_rating(MU, 2) < confidence_adjusted_rating(MU, 1000) < MU
    assert confidence_adjusted_rating(None, 500) == confidence_adjusted_rating(None, None)

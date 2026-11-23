import pytest

from app.repositories.skincare_build_repository import survey_ratios
from app.services.review_suitability_service import EMPIRICAL_SKIN_PRIORS, posterior_survey_ratio


def test_survey_shrinkage_uses_empirical_prior_and_distinguishes_zero_from_missing():
    prior = EMPIRICAL_SKIN_PRIORS["dry"]
    small = posterior_survey_ratio(5, 0.8, prior)
    large = posterior_survey_ratio(100, 0.8, prior)
    assert small == pytest.approx((5 * 0.8 + prior["k"] * prior["mu"]) / (5 + prior["k"]))
    assert prior["mu"] < small < large < 0.8
    assert posterior_survey_ratio(100, 0, prior) < prior["mu"]
    assert posterior_survey_ratio(100, None, prior) == prior["mu"]
    assert posterior_survey_ratio(0, 0.8, prior) == prior["mu"]


def test_partial_duplicate_invalid_question_is_not_used():
    rows = [
        dict(goods_no="p", question_name="피부타입", answer_name=a, percentage=v)
        for a, v in [("건성에 좋아요", 40), ("지성에 좋아요", 10), ("복합성에 좋아요", 50)]
    ]
    assert survey_ratios(rows)["p"]["dry"] == 0.4
    assert survey_ratios(rows[:2]) == {}
    assert survey_ratios(rows + [rows[0]]) == {}
    rows[0]["percentage"] = float("nan")
    assert survey_ratios(rows) == {}

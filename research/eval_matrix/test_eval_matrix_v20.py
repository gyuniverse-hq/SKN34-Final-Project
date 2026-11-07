"""Unit checks for eval_matrix.py (python -m pytest test_eval_matrix.py)."""
import math

import eval_matrix_v20 as em


def test_always_ar_rater_gives_ba_half():
    j = [{"truth": "AR", "answer": "AR"}] * 3 + [{"truth": "REAL", "answer": "AR"}] * 3
    ba, sens, spec = em.balanced_accuracy(j)
    assert ba == 0.5 and sens == 1.0 and spec == 0.0


def test_perfect_rater_ba_one():
    j = [{"truth": "AR", "answer": "AR"}, {"truth": "REAL", "answer": "REAL"}]
    assert em.balanced_accuracy(j)[0] == 1.0


def test_texture_rule_two_of_three_and_ties():
    bare = {"dE": 7, "dL_spread": 3.0, "dL_hi": 5.0, "ssim": 0.7}
    assert em.texture_pass({"ar": {"dE": 3, "dL_spread": 1.0, "dL_hi": 4.0, "ssim": 0.6}, "bare": bare}) == (True, False)
    # ties are not wins
    assert em.texture_pass({"ar": {"dE": 3, "dL_spread": 3.0, "dL_hi": 5.0, "ssim": 0.8}, "bare": bare}) == (False, True)


def test_milestone_never_counts_as_pass():
    crit = {"items": {"position": {"conditions": [
        {"id": "f", "metric": "mean(iou)", "op": ">=", "value": 0.90, "stage": "final"},
        {"id": "m", "metric": "mean(iou)", "op": ">=", "value": 0.80, "stage": "milestone"}]}}}
    r = em.evaluate(crit, {"position": {"mean(iou)": 0.85}})
    assert r["position"]["status"] == "in_progress"
    r = em.evaluate(crit, {"position": {"mean(iou)": 0.75}})
    assert r["position"]["status"] == "fail"


def test_missing_stat_is_not_measured():
    crit = {"items": {"naturalness": {"conditions": [{"id": "x", "metric": "balanced accuracy (pair photos)", "op": "<=", "value": 0.55, "stage": "final"}]}}}
    assert em.evaluate(crit, {})["naturalness"]["status"] == "not_measured"


def test_color_below_floor_is_not_valid():
    crit = {"items": {"color": {"conditions": [{"id": "color_dE_median", "metric": "median(dE)", "op": "<=", "value": 1.5, "stage": "final"}]}}}
    assert em.evaluate(crit, {"color": {"median(dE)": 3.6}}, floor=2.9)["color"]["status"] == "not_valid"
    assert em.evaluate(crit, {"color": {"median(dE)": 3.6}}, floor=1.0)["color"]["status"] == "fail"


def test_dprime_symmetric():
    dp, c = em.d_prime(0.8, 0.8, 100, 100)
    assert math.isclose(c, 0.0, abs_tol=1e-9) and dp > 1.6


def test_empty_survey_dir_is_not_measured(tmp_path):
    key = [{"image_id": "i1", "truth": "AR", "kind": "pair"}]
    assert em.naturalness_stats(key, tmp_path, set()) is None

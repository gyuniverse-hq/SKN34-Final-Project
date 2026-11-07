"""Checks for eval_matrix.py v2.1 (python -m pytest research/eval_matrix/test_eval_matrix.py)."""
import csv
import math

import eval_matrix as em


def test_sign_test_threshold_is_15_of_20():
    p15, need = em.sign_test(15, 20)
    p14, _ = em.sign_test(14, 20)
    assert need == 15 and p15 < 0.05 <= p14


def test_sample_size_for_60_percent():
    assert 190 <= em.n_for_accuracy(0.60) <= 200


def _lapa_rows(iou, gt=1000, pred=1000):
    return [{"name": f"i{k}", "detected": "1", "iou": str(v), "gt_px": str(gt), "pred_px": str(pred),
             "spill": "0.1", "miss": "0.1", "bnd_mean_rel": "0.01"} for k, v in enumerate(iou)]


def test_position_sota_line_and_regression():
    good = em.position(_lapa_rows([0.85] * 30))           # F1 = 2*0.85/1.85 = 0.919
    assert good["conditions"][0]["status"] == "pass"
    bad = em.position(_lapa_rows([0.70] * 30))            # F1 = 0.824
    assert bad["conditions"][0]["status"] == "fail"
    worse = em.position(_lapa_rows([0.70] * 30), prev=_lapa_rows([0.75] * 30))
    assert worse["conditions"][1]["status"] == "fail"
    same = em.position(_lapa_rows([0.75] * 30), prev=_lapa_rows([0.75] * 30))
    assert same["conditions"][1]["status"] == "pass"


def _pairs(n, ar, bare):
    return {f"p{k}": {"ar": dict(ar), "bare": dict(bare)} for k in range(n)}


def test_color_floor_blocks_judgement():
    p = _pairs(20, {"dE": 1.0, "dL_spread": 1, "dL_hi": 1, "ssim": 0.9}, {"dE": 7, "dL_spread": 3, "dL_hi": 5, "ssim": 0.7})
    assert em.color(p, floor=2.9)["conditions"][0]["status"] == "not_valid"
    assert em.color(p, floor=0.5)["conditions"][0]["status"] == "pass"
    assert em.color(p, floor=None)["conditions"][0]["status"] == "not_valid"


def test_texture_all_three_must_be_significant():
    p = _pairs(20, {"dE": 1, "dL_spread": 1, "dL_hi": 1, "ssim": 0.9}, {"dE": 7, "dL_spread": 3, "dL_hi": 5, "ssim": 0.7})
    assert em.texture(p)["status"] == "pass"
    p["p0"]["ar"]["ssim"] = 0.5
    assert em.texture(p)["status"] == "pass"            # 19/20 still significant
    for k in range(6):
        p[f"p{k}"]["ar"]["ssim"] = 0.5                  # 14/20 -> not significant
    assert em.texture(p)["status"] == "fail"


def _survey(tmp_path, answers):
    key = []
    with open(tmp_path / "r.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["rater", "order", "image_id", "answer", "score", "parts", "reasons", "ms"])
        for k, (rater, truth, ans, score) in enumerate(answers):
            key.append({"image_id": f"i{k}", "truth": truth, "kind": "pair"})
            w.writerow([rater, k, f"i{k}", ans, score, "", "", 0])
    return key


def test_naturalness_clear_fail_even_when_small(tmp_path):
    ans = [(f"r{r}", t, t, 5 if t == "REAL" else 1) for r in range(5) for t in ("AR", "REAL") * 3]
    res = em.naturalness(_survey(tmp_path, ans), tmp_path, set(), boot=500)
    assert res["conditions"][0]["status"] == "fail"


PAT = (["AR", "AR", "REAL", "REAL", "AR", "REAL"], ["AR", "AR", "REAL", "REAL", "REAL", "AR"])  # 4/6 and 2/6 correct


def _chance(n_raters):
    return [(f"r{r}", t, PAT[r % 2][k], 3 + (k + r) % 2) for r in range(n_raters) for k, t in enumerate(("AR", "REAL") * 3)]


def test_naturalness_chance_but_small_sample_is_not_valid(tmp_path):
    ans = _chance(5)
    res = em.naturalness(_survey(tmp_path, ans), tmp_path, set(), boot=500)
    assert res["conditions"][0]["status"] == "not_valid"


def test_naturalness_chance_with_enough_judgments_passes(tmp_path):
    ans = _chance(40)
    res = em.naturalness(_survey(tmp_path, ans), tmp_path, set(), boot=500)
    assert res["report_only"]["pair judgments"] == 240
    assert res["conditions"][0]["status"] == "pass"


def test_empty_survey_is_none(tmp_path):
    assert em.naturalness([{"image_id": "i1", "truth": "AR", "kind": "pair"}], tmp_path, set()) is None


def test_cohens_h_small_effect():
    assert math.isclose(em.cohens_h(0.6), 0.2014, abs_tol=1e-3)

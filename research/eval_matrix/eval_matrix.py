"""VISHUE AR evaluation matrix v2.1 — evidence-based pass lines only.

Every pass line comes from a published threshold, a published benchmark on the same dataset, or a statistical
test with a computed sample size (see criteria_v2.1.json). Metrics with no such source are reported only.
Reads result files the existing tools already write; never renders, never touches AR code.

  --lapa / --lapa-prev   baseline_landmarks.csv of this version / the previous version (eval_lapa.py)
  --subset               subset200.json (optional; default = all detected LaPa test images)
  --lip                  hw01_compare.py csv (methods ar + bare)
  --floor                skin_floor.csv (skin_floor.py)
  --key + --survey       blind naturalness test answer key + folder of rater CSVs; --exclude the AR creator

    python research/eval_matrix/eval_matrix.py --criteria research/eval_matrix/criteria_v2.1.json \
        --lapa .../baseline_landmarks.csv --lip research/data/hw01_compare.csv \
        --floor research/eval_matrix/data/skin_floor.csv \
        --key .../_v4_카탈로그색/key.csv --survey <csv folder> --exclude 전진영 전진영5 \
        --out research/eval_matrix/results/result_<date>_<commit>.json
"""
import argparse
import csv
import io
import json
import math
from pathlib import Path
from statistics import NormalDist

import numpy as np

SIGN_N_MIN_WINS = None  # computed from the sign test, never typed in


# ---------------- io ----------------

def read_csv(path):
    text = Path(path).read_text(encoding="utf-8-sig", errors="replace")
    start = text.find('"rater"') if '"rater"' in text else 0
    return list(csv.DictReader(io.StringIO(text[start:])))


def cond(cid, status, measured, line, note=""):
    return {"id": cid, "status": status, "measured": measured, "line": line, "note": note}


def item_status(conds):
    s = [c["status"] for c in conds if c["status"] != "report_only"]
    if not s:
        return "report_only"
    if "fail" in s:
        return "fail"
    if "not_measured" in s:
        return "not_measured"
    if "not_valid" in s:
        return "not_valid"
    return "pass"


# ---------------- statistics ----------------

def binom_greater(k, n):
    """Exact one-sided binomial p: P(X >= k) for X ~ Binomial(n, 0.5)."""
    return sum(math.comb(n, j) for j in range(k, n + 1)) / 2 ** n


def sign_test(wins, n, alpha=0.05):
    """One-sided exact sign test: is 'AR better' more often than chance? Returns p and the minimum wins for p < alpha."""
    p = binom_greater(wins, n) if n else float("nan")
    need = next((k for k in range(n + 1) if binom_greater(k, n) < alpha), None)
    return float(p), need


def wilcoxon_greater(a, b):
    """One-sided Wilcoxon signed-rank p that a > b (normal approximation with tie correction; zeros dropped)."""
    d = np.asarray(a, float) - np.asarray(b, float)
    d = d[d != 0]
    n = len(d)
    if n == 0:
        return 1.0
    order = np.argsort(np.abs(d))
    ranks = np.empty(n)
    absd = np.abs(d)[order]
    i = 0
    while i < n:
        j = i
        while j + 1 < n and absd[j + 1] == absd[i]:
            j += 1
        ranks[order[i:j + 1]] = (i + j) / 2 + 1
        i = j + 1
    w = ranks[d > 0].sum()
    mean = n * (n + 1) / 4
    _, counts = np.unique(absd, return_counts=True)
    var = n * (n + 1) * (2 * n + 1) / 24 - (counts ** 3 - counts).sum() / 48
    z = (w - mean - 0.5) / math.sqrt(var) if var > 0 else 0.0
    return 1 - NormalDist().cdf(z)


def cohens_h(p1, p2=0.5):
    return 2 * math.asin(math.sqrt(p1)) - 2 * math.asin(math.sqrt(p2))


def n_for_accuracy(p_alt=0.60, alpha=0.05, power=0.80):
    """Judgments needed to tell accuracy p_alt from chance (two-sided alpha, given power), Cohen's h approximation."""
    z = NormalDist().inv_cdf
    return math.ceil(((z(1 - alpha / 2) + z(power)) / abs(cohens_h(p_alt))) ** 2)


# ---------------- position ----------------

def position(rows, names=None, prev=None, alpha=0.05, line=0.887):
    r = [x for x in rows if x.get("detected") == "1" and (names is None or x["name"] in names)]
    if not r:
        return None
    iou = np.array([float(x["iou"]) for x in r])
    gt = np.array([float(x["gt_px"]) for x in r])
    pr = np.array([float(x["pred_px"]) for x in r])
    inter = iou * (gt + pr) / (1 + iou)
    f1 = float(2 * inter.sum() / (gt.sum() + pr.sum()))
    conds = [cond("lip_f1_sota", "pass" if f1 >= line else "fail", f1, f">= {line} (SegFace AAAI 2025 best U-lip)",
                  f"dataset IoU {f1 / (2 - f1):.3f}")]
    if prev is not None:
        pv = {x["name"]: float(x["iou"]) for x in prev if x.get("detected") == "1"}
        pairs = [(pv[x["name"]], float(x["iou"])) for x in r if x["name"] in pv]
        a, b = np.array(pairs).T
        p = wilcoxon_greater(a, b)
        conds.append(cond("lip_no_regression", "fail" if p < alpha else "pass", float(p), f"p >= {alpha}",
                          f"{len(pairs)} paired images, mean IoU {a.mean():.3f} -> {b.mean():.3f}"))
    else:
        conds.append(cond("lip_no_regression", "not_measured", None, "needs --lapa-prev"))
    bnd = [float(x["bnd_mean_rel"]) for x in r if x.get("bnd_mean_rel")]
    report = {"n": len(r), "mean per-image IoU": float(iou.mean()), "median per-image IoU": float(np.median(iou)),
              "dataset IoU": f1 / (2 - f1), "images IoU<0.2": int((iou < 0.2).sum()),
              "mean spill": float(np.mean([float(x["spill"]) for x in r])),
              "mean miss": float(np.mean([float(x["miss"]) for x in r])),
              "median boundary error / mouth width": float(np.median(bnd)) if bnd else None}
    return {"status": item_status(conds), "conditions": conds, "report_only": report}


# ---------------- lip pairs ----------------

def lip_pairs(rows):
    by = {}
    for x in rows:
        by.setdefault(x["name"], {})[x["method"]] = {k: float(x[k]) for k in ("dE", "dL_spread", "dL_hi", "ssim")}
    return {n: m for n, m in by.items() if "ar" in m and "bare" in m}


def color(pairs, floor=None, alpha=0.05, line=1.8):
    dE = np.array([m["ar"]["dE"] for m in pairs.values()])
    bare = np.array([m["bare"]["dE"] for m in pairs.values()])
    med = float(np.median(dE))
    if floor is None:
        s = "not_valid"
        note = "no measurement floor given (--floor); cannot tell lighting gap from render error"
    elif floor >= line:
        s, note = "not_valid", f"skin floor {floor:.2f} >= {line}: photo pairs differ more than the line before any makeup"
    else:
        s, note = ("pass" if med <= line else "fail"), f"skin floor {floor:.2f}"
    wins = int((dE < bare).sum())
    p, need = sign_test(wins, len(dE), alpha)
    conds = [cond("color_at", s, med, f"<= {line} (Paravina 2015 AT; Lagouvardo 2018 1.81)", note),
             cond("color_beats_bare", "pass" if p < alpha else "fail", wins, f">= {need}/{len(dE)} (sign test p<{alpha})",
                  f"p = {p:.4f}")]
    return {"status": item_status(conds), "conditions": conds,
            "report_only": {"n": len(dE), "median dE bare": float(np.median(bare)), "share dE<=1.8": float((dE <= line).mean())}}


def texture(pairs, alpha=0.05):
    conds = []
    for cid, k, better in (("tex_spread", "dL_spread", "lower"), ("tex_hi", "dL_hi", "lower"), ("tex_ssim", "ssim", "higher")):
        a = np.array([m["ar"][k] for m in pairs.values()])
        b = np.array([m["bare"][k] for m in pairs.values()])
        wins = int((a < b).sum() if better == "lower" else (a > b).sum())
        p, need = sign_test(wins, len(a), alpha)
        conds.append(cond(cid, "pass" if p < alpha else "fail", wins, f">= {need}/{len(a)} (sign test p<{alpha})", f"p = {p:.4f}"))
    return {"status": item_status(conds), "conditions": conds}


# ---------------- naturalness ----------------

def naturalness(key_rows, survey_dir, exclude, alpha=0.05, boot=10000, seed=0, acc_line=0.60, d_line=0.2):
    key = {r["image_id"]: r for r in key_rows}
    judg, unknown = {}, 0
    for f in sorted(list(Path(survey_dir).glob("*.csv")) + list(Path(survey_dir).glob("*.txt"))):
        for r in read_csv(f):
            if not r.get("image_id") or r["rater"] in exclude:
                continue
            k = key.get(r["image_id"])
            if k is None:
                unknown += 1
                continue
            judg[(r["rater"], r["image_id"])] = {"rater": r["rater"], "truth": k["truth"], "kind": k["kind"],
                                                  "answer": r["answer"], "score": int(r["score"])}
    pair = [j for j in judg.values() if j["kind"] == "pair"]
    if not pair:
        print(f"  ! no survey answers matched the key in {survey_dir} (unknown ids: {unknown})")
        return None
    raters = sorted({j["rater"] for j in pair})
    by = {r: [j for j in pair if j["rater"] == r] for r in raters}

    def ba(js):
        a = [j for j in js if j["truth"] == "AR"]
        e = [j for j in js if j["truth"] == "REAL"]
        if not a or not e:
            return float("nan"), float("nan"), float("nan")
        se = np.mean([j["answer"] == "AR" for j in a])
        sp = np.mean([j["answer"] == "REAL" for j in e])
        return (se + sp) / 2, se, sp

    def dval(js):
        ar = np.array([j["score"] for j in js if j["truth"] == "AR"], float)
        re = np.array([j["score"] for j in js if j["truth"] == "REAL"], float)
        if len(ar) < 2 or len(re) < 2:
            return float("nan")
        sd = math.sqrt(((len(ar) - 1) * ar.var(ddof=1) + (len(re) - 1) * re.var(ddof=1)) / (len(ar) + len(re) - 2))
        return (re.mean() - ar.mean()) / sd if sd > 0 else float("inf")

    rng = np.random.default_rng(seed)
    bs_ba, bs_d = [], []
    for _ in range(boot):
        s = [j for r in rng.choice(raters, len(raters)) for j in by[r]]
        v = ba(s)[0]
        if not math.isnan(v):
            bs_ba.append(v)
        d = dval(s)
        if not math.isnan(d):
            bs_d.append(d)
    b, se, sp = ba(pair)
    need = n_for_accuracy(acc_line, alpha, 0.80)
    lo, hi = np.percentile(bs_ba, [5, 95])
    if lo > acc_line:
        s1, n1 = "fail", "even the lower 90% bound is above the line: clearly distinguishable"
    elif len(pair) < need:
        s1, n1 = "not_valid", f"{len(pair)} pair judgments < {need} needed"
    else:
        s1, n1 = ("pass" if hi < acc_line else "fail"), ""
    d = dval(pair)
    dlo, dhi = np.percentile(bs_d, [5, 95]) if bs_d else (float("nan"), float("nan"))
    if dlo > d_line:
        s2, n2 = "fail", "even the lower 90% bound is above the line"
    elif len(pair) < need:
        s2, n2 = "not_valid", f"{len(pair)} pair judgments < {need} needed"
    else:
        s2, n2 = ("pass" if dhi < d_line else "fail"), ""
    z = NormalDist().inv_cdf
    n_ar = sum(j["truth"] == "AR" for j in pair)
    clip = lambda p, n: min(max(p, 0.5 / n), 1 - 0.5 / n)
    H, F = clip(se, n_ar), clip(1 - sp, len(pair) - n_ar)
    conds = [cond("nat_indistinguishable", s1, float(b), f"90% CI upper < {acc_line} with >= {need} judgments",
                  f"90% CI {lo:.3f}-{hi:.3f}. {n1}"),
             cond("nat_score", s2, float(d), f"Cohen d (real - AR) 90% CI upper < {d_line}", f"90% CI {dlo:.2f}-{dhi:.2f}. {n2}")]
    report = {"raters": len(raters), "pair judgments": len(pair), "needed judgments": need, "unknown ids": unknown,
              "simple accuracy": float(np.mean([j["answer"] == j["truth"] for j in pair])), "balanced accuracy": float(b),
              "sensitivity": float(se), "specificity": float(sp), "d_prime": z(H) - z(F), "criterion_c": -(z(H) + z(F)) / 2,
              "AR-answer rate": float(np.mean([j["answer"] == "AR" for j in pair])),
              "mean score real": float(np.mean([j["score"] for j in pair if j["truth"] == "REAL"])),
              "mean score AR": float(np.mean([j["score"] for j in pair if j["truth"] == "AR"])),
              "per-rater accuracy": {r: float(np.mean([j["answer"] == j["truth"] for j in by[r]])) for r in raters}}
    return {"status": item_status(conds), "conditions": conds, "report_only": report}


# ---------------- main ----------------

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--criteria", required=True)
    ap.add_argument("--lapa"); ap.add_argument("--lapa-prev"); ap.add_argument("--subset")
    ap.add_argument("--lip"); ap.add_argument("--floor")
    ap.add_argument("--key"); ap.add_argument("--survey"); ap.add_argument("--exclude", nargs="*", default=[])
    ap.add_argument("--out", default="eval_result.json")
    a = ap.parse_args()
    crit = json.loads(Path(a.criteria).read_text(encoding="utf-8"))
    res = {}
    nm = lambda item: {"status": "not_measured", "conditions": []}
    names = None
    if a.subset:
        names = {x["name"] if isinstance(x, dict) else x for x in json.loads(Path(a.subset).read_text())}
    res["position"] = position(read_csv(a.lapa), names, read_csv(a.lapa_prev) if a.lapa_prev else None) if a.lapa else nm(0)
    floor = float(np.median([float(r["skin_dE"]) for r in read_csv(a.floor)])) if a.floor else None
    if a.lip:
        pairs = lip_pairs(read_csv(a.lip))
        res["color"], res["texture"] = color(pairs, floor), texture(pairs)
    else:
        res["color"], res["texture"] = nm(0), nm(0)
    nat = naturalness(read_csv(a.key), a.survey, set(a.exclude)) if a.key and a.survey else None
    res["naturalness"] = nat or nm(0)
    order = ["color", "position", "texture", "naturalness"]
    out = {"criteria_version": crit["version"], "inputs": vars(a), "skin_floor": floor, "items": {k: res[k] for k in order}}
    Path(a.out).write_text(json.dumps(out, ensure_ascii=False, indent=2, default=float), encoding="utf-8")
    for k in order:
        r = res[k]
        print(f"{k:12s} {r['status'].upper()}")
        for c in r["conditions"]:
            v = c["measured"]
            vs = "-" if v is None else (f"{v:.3f}" if isinstance(v, float) else str(v))
            print(f"    {c['id']:22s} {vs:>8s}  line {c['line']:50s} {c['status']:12s} {c['note']}")
    print(f"→ {a.out}")


if __name__ == "__main__":
    main()

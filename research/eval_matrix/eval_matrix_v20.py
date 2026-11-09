"""VISHUE AR evaluation matrix v2.0: one command → pass / fail / in_progress / not_measured / not_valid per item.

Reads only result files that the existing tools already write; it never renders, never changes AR code.

  --lapa     baseline_landmarks.csv           (research/lip_reference/eval_lapa.py)
  --subset   subset200.json                   (LaPa 200-image subset; optional)
  --lip      hw01_compare csv                 (research/lip_reference/hw01_compare.py; methods ar + bare)
  --floor    skin_floor csv (optional)        (one column skin_dE: bare vs real skin ring per pair)
  --key      key.csv + --survey DIR           (blind naturalness test; AR creator removed with --exclude)

    python eval_matrix.py --criteria criteria_v2.json --lapa ... --subset ... --lip ... \
        --key key.csv --survey responses/ --exclude 전진영 전진영5 --out result.json

Prints a table and writes the JSON. Thresholds come from the criteria file only (team targets, not paper values).
"""
import argparse
import csv
import io
import json
import math
from pathlib import Path
from statistics import NormalDist

import numpy as np

OPS = {"<=": lambda a, b: a <= b, ">=": lambda a, b: a >= b}


# ---------- generic ----------

def read_csv(path):
    text = Path(path).read_text(encoding="utf-8-sig", errors="replace")
    start = text.find('"rater"') if '"rater"' in text else 0
    return list(csv.DictReader(io.StringIO(text[start:])))


def judge(value, cond):
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return "not_measured"
    return "pass" if OPS[cond["op"]](value, cond["value"]) else "fail"


# ---------- position ----------

def position_stats(rows, names=None):
    r = [x for x in rows if x.get("detected") == "1" and (names is None or x["name"] in names)]
    if not r:
        return None
    f = lambda k: np.array([float(x[k]) for x in r])
    iou, spill, miss, bnd = f("iou"), f("spill"), f("miss"), f("bnd_mean_rel") if "bnd_mean_rel" in r[0] else None
    out = {"n": len(r), "mean(iou)": float(iou.mean()), "median(iou)": float(np.median(iou)),
           "p10(iou)": float(np.percentile(iou, 10)), "share(iou>=0.80)": float((iou >= 0.8).mean()),
           "share(iou>=0.90)": float((iou >= 0.9).mean()), "count(iou<0.2)": int((iou < 0.2).sum()),
           "mean(spill)": float(spill.mean()), "median(spill)": float(np.median(spill)),
           "mean(miss)": float(miss.mean()), "median(miss)": float(np.median(miss))}
    if bnd is not None:
        out.update({"share(bnd_mean_rel <= 0.015)": float((bnd <= 0.015).mean()),
                    "share(bnd_mean_rel <= 0.02)": float((bnd <= 0.02).mean()),
                    "median(bnd_mean_rel)": float(np.median(bnd))})
    return out


# ---------- lip pairs: color + texture ----------

def lip_pairs(rows):
    by = {}
    for x in rows:
        by.setdefault(x["name"], {})[x["method"]] = {k: float(x[k]) for k in ("dE", "dL_spread", "dL_hi", "ssim")}
    return {n: m for n, m in by.items() if "ar" in m and "bare" in m}


def color_stats(pairs):
    dE = np.array([m["ar"]["dE"] for m in pairs.values()])
    bare = np.array([m["bare"]["dE"] for m in pairs.values()])
    return {"n": len(dE), "median(dE)": float(np.median(dE)), "share(dE <= 1.5)": float((dE <= 1.5).mean()),
            "share(dE_ar < dE_bare)": float((dE < bare).mean()), "median(dE_bare)": float(np.median(bare))}


def texture_pass(m):
    a, b = m["ar"], m["bare"]
    wins = [a["dL_spread"] < b["dL_spread"], a["dL_hi"] < b["dL_hi"], a["ssim"] > b["ssim"]]
    return sum(wins) >= 2, wins[2]


def texture_stats(pairs):
    res = [texture_pass(m) for m in pairs.values()]
    return {"n": len(res), "count(pair passes)": sum(p for p, _ in res), "count(ssim_ar > ssim_bare)": sum(s for _, s in res)}


# ---------- naturalness ----------

def balanced_accuracy(judgments):
    ar = [j for j in judgments if j["truth"] == "AR"]
    re = [j for j in judgments if j["truth"] == "REAL"]
    if not ar or not re:
        return float("nan"), float("nan"), float("nan")
    sens = sum(j["answer"] == "AR" for j in ar) / len(ar)
    spec = sum(j["answer"] == "REAL" for j in re) / len(re)
    return (sens + spec) / 2, sens, spec


def d_prime(sens, spec, n_ar, n_re):
    z = NormalDist().inv_cdf
    clip = lambda p, n: min(max(p, 0.5 / n), 1 - 0.5 / n)  # log-linear style correction for 0/1
    h, fa = clip(sens, n_ar), clip(1 - spec, n_re)
    return z(h) - z(fa), -(z(h) + z(fa)) / 2


def naturalness_stats(key_rows, survey_dir, exclude, boot=10000, seed=0):
    key = {r["image_id"]: r for r in key_rows}
    judg, unknown = [], 0
    for f in sorted(list(Path(survey_dir).glob("*.csv")) + list(Path(survey_dir).glob("*.txt"))):
        for r in read_csv(f):
            if not r.get("image_id") or r["rater"] in exclude:
                continue
            k = key.get(r["image_id"])
            if k is None:
                unknown += 1
                continue
            judg.append({"rater": r["rater"], "img": r["image_id"], "truth": k["truth"], "kind": k["kind"],
                         "answer": r["answer"], "score": int(r["score"])})
    judg = list({(j["rater"], j["img"]): j for j in judg}.values())
    if not judg:
        print(f"  ! no survey answers matched the key in {survey_dir} (unknown ids: {unknown}) -> not_measured")
        return None
    pair = [j for j in judg if j["kind"] == "pair"]
    raters = sorted({j["rater"] for j in judg})
    ba, sens, spec = balanced_accuracy(pair)
    n_ar = sum(j["truth"] == "AR" for j in pair)
    n_re = len(pair) - n_ar
    dp, c = d_prime(sens, spec, n_ar, n_re) if pair else (float("nan"), float("nan"))
    rng = np.random.default_rng(seed)
    by = {r: [j for j in pair if j["rater"] == r] for r in raters}
    bs = []
    for _ in range(boot):
        s = [j for r in rng.choice(raters, len(raters)) for j in by[r]]
        v = balanced_accuracy(s)[0]
        if not math.isnan(v):
            bs.append(v)
    ar_scores = [j["score"] for j in pair if j["truth"] == "AR"]
    return {
        "raters": len(raters), "judgments": len(judg), "pair_judgments": len(pair), "unknown_image_ids": unknown,
        "simple accuracy (pair photos)": sum(j["answer"] == j["truth"] for j in pair) / len(pair) if pair else float("nan"),
        "balanced accuracy (pair photos)": ba, "sensitivity": sens, "specificity": spec,
        "95% CI upper of BA, rater-cluster bootstrap": float(np.percentile(bs, 97.5)) if bs else float("nan"),
        "95% CI lower of BA, rater-cluster bootstrap": float(np.percentile(bs, 2.5)) if bs else float("nan"),
        "AR-answer rate (pair)": sum(j["answer"] == "AR" for j in pair) / len(pair) if pair else float("nan"),
        "d_prime": dp, "criterion_c": c,
        "VISHUE score = 6 - mean(survey score of AR pair photos)": 6 - float(np.mean(ar_scores)) if ar_scores else float("nan"),
        "valid raters": len(raters),
        "per_rater_accuracy": {r: sum(j["answer"] == j["truth"] for j in by[r]) / len(by[r]) for r in raters if by[r]},
    }


# ---------- assembly ----------

def evaluate(criteria, stats, floor=None):
    out = {}
    for item, spec in criteria["items"].items():
        s = stats.get(item)
        conds = []
        for c in spec["conditions"]:
            v = None if s is None else s.get(c["metric"])
            st = judge(v, c)
            if item == "color" and floor is not None and c.get("id", "").startswith("color_dE") and floor > 1.5 and st == "fail":
                st = "not_valid"
            conds.append({**c, "measured": v, "status": st})
        finals = [x for x in conds if x["stage"] == "final"]
        if any(x["status"] == "not_measured" for x in finals) and not any(x["status"] == "fail" for x in finals):
            status = "not_measured"
        elif all(x["status"] == "pass" for x in finals):
            status = "pass"
        elif any(x["status"] == "fail" for x in finals):
            ms = [x for x in conds if x["stage"] == "milestone"]
            status = "in_progress" if ms and all(x["status"] == "pass" for x in ms) else "fail"
        else:
            status = "not_valid"
        out[item] = {"status": status, "conditions": conds}
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--criteria", required=True)
    ap.add_argument("--lapa"); ap.add_argument("--subset"); ap.add_argument("--lip"); ap.add_argument("--floor")
    ap.add_argument("--key"); ap.add_argument("--survey"); ap.add_argument("--exclude", nargs="*", default=[])
    ap.add_argument("--out", default="eval_result.json")
    a = ap.parse_args()
    crit = json.loads(Path(a.criteria).read_text(encoding="utf-8"))
    stats, extra = {}, {}
    if a.lapa:
        rows = read_csv(a.lapa)
        names = None
        if a.subset:
            raw = json.loads(Path(a.subset).read_text())
            names = {x["name"] if isinstance(x, dict) else x for x in raw}
        stats["position"] = position_stats(rows, names)
        extra["position_full_set"] = position_stats(rows)
    floor = None
    if a.floor:
        fl = [float(r["skin_dE"]) for r in read_csv(a.floor)]
        floor = float(np.median(fl))
        extra["color_measurement_floor_median_skin_dE"] = floor
    if a.lip:
        pairs = lip_pairs(read_csv(a.lip))
        stats["color"], stats["texture"] = color_stats(pairs), texture_stats(pairs)
    if a.key and a.survey:
        stats["naturalness"] = naturalness_stats(read_csv(a.key), a.survey, set(a.exclude))
    result = {"criteria_version": crit["version"], "inputs": vars(a), "items": evaluate(crit, stats, floor),
              "stats": stats, "extra": extra}
    Path(a.out).write_text(json.dumps(result, ensure_ascii=False, indent=2, default=float), encoding="utf-8")
    for item, r in result["items"].items():
        print(f"{item:12s} {r['status'].upper()}")
        for c in r["conditions"]:
            v = c["measured"]
            vs = "-" if v is None else (f"{v:.3f}" if isinstance(v, float) else str(v))
            print(f"    [{c['stage']:9s}] {c['metric']:55s} {vs:>8s} {c['op']} {c['value']:<6} {c['status']}")
    print(f"→ {a.out}")


if __name__ == "__main__":
    main()

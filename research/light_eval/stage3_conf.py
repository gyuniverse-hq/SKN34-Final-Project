"""stage3_conf.py: how to combine the fit R² and the relative signal |b| / mean into the direction confidence (stage 3).

Input: synthetic runs (synth_light.py with the robust fit on; rows carry r2, rel and the true angle error) and the real-photo
consistency run (base photos: r2 / rel are not stored there, so only the synthetic rows decide).

A confidence is good when it is low where the direction is wrong and does not depend on skin darkness by itself:
  * rank correlation (Spearman) between confidence and angle error, should be negative
  * median confidence per albedo, should not drop for dark skin at the same light
  * mean angle error of the half the confidence trusts most vs the other half

Candidates (each value mapped to 0..1 linearly between the 10th and 90th percentile of the synthetic rows):
  r2 (today), rel, min(r2, rel), product, max(r2, rel), mean.

    python research/light_eval/stage3_conf.py research/light_eval/results/stage3_synth_on.json [more.json] [--out ...]
"""
import argparse
import json
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
R2_RANGE = (0.1, 0.4)    # TUNING.lightConfR2 today


def spearman(a, b):
    ra, rb = np.argsort(np.argsort(a)), np.argsort(np.argsort(b))
    return float(np.corrcoef(ra, rb)[0, 1])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("runs", nargs="+", type=Path)
    ap.add_argument("--out", type=Path, default=HERE / "results/stage3_conf.json")
    a = ap.parse_args()
    rows = [r for p in a.runs for r in json.loads(p.read_text())["rows"] if r.get("r2") is not None]
    err = np.array([r["err"] for r in rows])
    r2 = np.array([r["r2"] for r in rows])
    rel = np.array([r["rel"] for r in rows])
    alb = np.array([r["albedo"] for r in rows])
    lin = lambda v, lo, hi: np.clip((v - lo) / max(hi - lo, 1e-9), 0, 1)
    rel_lo, rel_hi = np.percentile(rel, 10), np.percentile(rel, 90)
    r2_lo, r2_hi = np.percentile(r2, 10), np.percentile(r2, 90)
    c_r2_today = lin(r2, *R2_RANGE)
    c_r2 = lin(r2, r2_lo, r2_hi)
    c_rel = lin(rel, rel_lo, rel_hi)
    cands = {"r2 today (0.1..0.4)": c_r2_today, "r2 (p10..p90)": c_r2, "rel": c_rel, "min": np.minimum(c_r2, c_rel),
             "product": c_r2 * c_rel, "max": np.maximum(c_r2, c_rel), "mean": 0.5 * (c_r2 + c_rel)}
    out = {"runs": [str(p) for p in a.runs], "n": len(rows), "r2_p10_p90": [r2_lo, r2_hi], "rel_p10_p90": [rel_lo, rel_hi],
           "raw": {k: {al: float(np.median(v[alb == al])) for al in ("light", "medium", "dark")} for k, v in (("r2", r2), ("rel", rel))},
           "candidates": {}}
    print(f"{len(rows)} rows.  r2 p10..p90 {r2_lo:.3f}..{r2_hi:.3f}   rel p10..p90 {rel_lo:.3f}..{rel_hi:.3f}")
    print("raw median by albedo:", json.dumps(out["raw"]))
    print(f"{'candidate':22s}{'spearman':>10s}{'light':>8s}{'medium':>8s}{'dark':>8s}{'err top half':>14s}{'err bottom':>12s}")
    for name, c in cands.items():
        order = np.argsort(-c, kind="stable")
        top, bot = order[: len(c) // 2], order[len(c) // 2:]
        m = {"spearman_conf_err": spearman(c, err) if np.ptp(c) > 0 else None,
             "median_by_albedo": {al: float(np.median(c[alb == al])) for al in ("light", "medium", "dark")},
             "err_trusted_half": float(err[top].mean()), "err_other_half": float(err[bot].mean())}
        out["candidates"][name] = m
        s = "  n/a" if m["spearman_conf_err"] is None else f"{m['spearman_conf_err']:+.2f}"
        mb = m["median_by_albedo"]
        print(f"{name:22s}{s:>10s}{mb['light']:8.2f}{mb['medium']:8.2f}{mb['dark']:8.2f}{m['err_trusted_half']:14.1f}{m['err_other_half']:12.1f}")
    a.out.parent.mkdir(parents=True, exist_ok=True)
    a.out.write_text(json.dumps(out, indent=1))
    print("->", a.out)


if __name__ == "__main__":
    main()

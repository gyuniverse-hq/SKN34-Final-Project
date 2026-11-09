"""Color measurement floor: skin around the lips, bare photo vs applied photo (lipstick never touches it).

If this skin already differs by more than the color threshold (ΔE 1.5), the lip ΔE test cannot tell a good
render from a bad one on this photo set: the gap is lighting/exposure between the two shots, not the AR.

    PYTHONPATH=research/lip_reference python research/eval_matrix/skin_floor.py \
        --raw research/data/hw01_raw --out research/eval_matrix/data/skin_floor.csv
"""
import argparse
import csv
from pathlib import Path

import cv2
import numpy as np

import hw01_compare as h


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--raw", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    a = ap.parse_args()
    faces = h.Faces()
    rows = []
    for rp in sorted(a.raw.glob("*_3.jp*g")) + sorted(a.raw.glob("*_1.jp*g")):
        bp = rp.with_name(rp.name[: -len(rp.suffix) - 2] + "_0" + rp.suffix)
        if not bp.exists():
            continue
        real, bare = h.fit(cv2.imread(str(rp))), h.fit(cv2.imread(str(bp)))
        pr, pb = faces.points(real), faces.points(bare)
        if pr is None or pb is None:
            continue
        ring_r = h.skin_ring(pr, real.shape[:2], np.linalg.norm(pr[61] - pr[291])) > 0
        ring_b = h.skin_ring(pb, bare.shape[:2], np.linalg.norm(pb[61] - pb[291])) > 0
        dE = float(h.ciede2000(h.stats(h.to_lab(real), ring_r)["mean"], h.stats(h.to_lab(bare), ring_b)["mean"]))
        rows.append({"name": rp.stem, "skin_dE": dE})
    a.out.parent.mkdir(parents=True, exist_ok=True)
    with open(a.out, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["name", "skin_dE"])
        w.writeheader()
        w.writerows(rows)
    v = np.array([r["skin_dE"] for r in rows])
    print(f"{len(v)} pairs  skin ΔE median {np.median(v):.2f}  (≤1.5: {(v <= 1.5).sum()})  → {a.out}")


if __name__ == "__main__":
    main()

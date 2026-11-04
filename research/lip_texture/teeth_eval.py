"""Teeth check on render.py output: how much of the bare teeth got painted, and whether the lip itself changed.

teeth px  : inside or within 6 px of the image-mode inner lip ring, paler than 0.6 x the lip core's median saturation or
            less red than 0.4 x its median redness, and brighter than 1.2 x its median brightness, in the bare render.
painted   : |render - bare| max channel > 12.
Run: research/ar_evaluation/.venv/Scripts/python.exe research/lip_texture/teeth_eval.py --tag teeth2 --a t0 --b t1
"""

from __future__ import annotations

import argparse
import json

import cv2
import numpy as np

from metrics import DATA, lab_of, lip_core, lum, sparkles, to_lin


def mouth_zone(face: str, shape: tuple[int, int]) -> np.ndarray:
    """Inside the image-mode inner lip ring or within 6 px of it (mirrored like the page)."""
    j = json.loads((DATA / "faces" / f"{face}.json").read_text())
    p = np.array(j["inner"])
    p[:, 0] = shape[1] - 1 - p[:, 0]
    m = np.zeros(shape, np.uint8)
    cv2.polylines(m, [p.astype(np.int32)], True, 1, thickness=12)
    cv2.fillPoly(m, [p.astype(np.int32)], 1)
    return m > 0


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--tag", required=True)
    ap.add_argument("--a", required=True)
    ap.add_argument("--b", required=True)
    args = ap.parse_args()
    d = DATA / "renders" / args.tag
    print(f"{'face':12} {'shade':12} {'teeth':>6} {'paint ' + args.a:>11} {'paint ' + args.b:>11} {'core chg':>9} {'spark ' + args.a:>9} {'spark ' + args.b:>9} {'lip lost':>9}")
    for off in sorted(d.glob("*__off.png")):
        face = off.name.split("__")[0]
        bare_bgr = cv2.imread(str(off))
        bare = to_lin(bare_bgr)
        shape = bare.shape[:2]
        mx, mn = bare.max(-1), bare.min(-1)
        sat = (mx - mn) / np.maximum(mx, 1e-4)
        core = lip_core(face, shape)
        y = lum(bare)
        red = (bare[..., 0] - bare[..., 1]) / np.maximum(bare.sum(-1), 1e-4)
        pale = (sat < 0.6 * np.median(sat[core])) | (red < 0.4 * np.median(red[core]))
        teeth = mouth_zone(face, shape) & pale & (y > 1.2 * np.median(y[core]))
        teeth = cv2.morphologyEx(teeth.astype(np.uint8), cv2.MORPH_OPEN, np.ones((2, 2), np.uint8)) > 0
        # Lip near the inner line: in the zone, not teeth (with a 2 px margin), saturated like lip.
        near_teeth = cv2.dilate(teeth.astype(np.uint8), np.ones((5, 5), np.uint8)) > 0
        lip_near = mouth_zone(face, shape) & ~near_teeth & (sat > 0.8 * np.median(sat[core]))
        lab_b = lab_of(bare)
        spb = sparkles(lab_b, core).sum()
        for shade in sorted({p.name.split("__")[1] for p in d.glob(f"{face}__*__{args.a}.png")}):
            ra = cv2.imread(str(d / f"{face}__{shade}__{args.a}.png")).astype(int)
            rb = cv2.imread(str(d / f"{face}__{shade}__{args.b}.png")).astype(int)
            pa = np.abs(ra - bare_bgr).max(2) > 12
            pb = np.abs(rb - bare_bgr).max(2) > 12
            n = int(teeth.sum())
            share = lambda p: f"{(p & teeth).sum() / max(n, 1):.2f}" if n >= 10 else "-"
            core_chg = np.abs(ra - rb).max(2)[core & ~teeth].mean()
            spa = sparkles(lab_of(to_lin(ra.astype(np.uint8))), core).sum() / max(spb, 1)
            spbb = sparkles(lab_of(to_lin(rb.astype(np.uint8))), core).sum() / max(spb, 1)
            lost = (pa & ~pb & lip_near).sum() / max((pa & lip_near).sum(), 1)
            print(f"{face:12} {shade:12} {n:6d} {share(pa):>11} {share(pb):>11} {core_chg:9.2f} {spa:9.2f} {spbb:9.2f} {lost:9.3f}")


if __name__ == "__main__":
    main()

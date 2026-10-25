"""How strongly, and how far out, does the shader paint? (10-25: "입술 끝까지, 진하게")

On offline renders (render_ar_offline.py) of LaPa phone frames, per lip zone:
  strength  - how far each pixel moved from the bare frame toward the render's own lip core, along the
              bare → painted color direction in Lab (core p90 = 1). < 1 = paler than the middle of the
              lip, i.e. the corner/edge fades the reference photo does not have.
  coverage  - in the lip core: share of the bare-lip → product Lab distance covered (1 = the product
              color itself, ignoring lighting; real photos of an applied matte red sit near 1 in a*/b*)
  C*, L*    - core chroma and lightness of the render, the bare lip and the product

    python research/lip_reference/eval_paint_strength.py <render dir> <product hex> [--raw DIR]
Frames are p{i}_day_00_{product}_3.png, i = order in <raw>/../names.json.
"""
import argparse
import json
from pathlib import Path

import cv2
import numpy as np

from eval_lapa import LIPS_INNER, LIPS_OUTER, ROOT

PHONE = ROOT / "research/data/reference/lapa/phone"
W, H = 720, 960


def lab(img):
    return cv2.cvtColor(img.astype(np.float32) / 255, cv2.COLOR_BGR2LAB)


def hex_lab(hexstr):
    n = int(hexstr.lstrip("#"), 16)
    bgr = np.array([[[n & 255, (n >> 8) & 255, (n >> 16) & 255]]], np.uint8)
    return lab(bgr)[0, 0]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("renders", type=Path)
    ap.add_argument("hex")
    ap.add_argument("--raw", type=Path, default=ROOT / "research/data/mask_probe/raw")
    args = ap.parse_args()
    meta = json.loads((PHONE / "meta.json").read_text())
    names = json.loads((args.raw.parent / "names.json").read_text())
    prod = hex_lab(args.hex)
    zones = {k: [] for k in ("core", "edge 2px", "edge", "inner", "corner")}
    prof, profn = np.zeros(12), np.zeros(12)
    cov, cs = [], {"render": [], "bare": []}
    ls = {"render": [], "bare": []}
    fit_gt = {"iou": [], "spill": [], "miss": []}
    for i, n in enumerate(names, 1):
        files = list(args.renders.glob(f"p{i}_day_00_*_3.png"))
        if not files:
            continue
        m = meta[n]
        P = np.stack([np.array(m["x"]) * W, np.array(m["y"]) * H], 1)
        fl, rl = lab(cv2.imread(str(PHONE / f"{n}.jpg"))), lab(cv2.imread(str(files[0])))
        o = np.zeros((H, W), np.uint8)
        cv2.fillPoly(o, [P[LIPS_OUTER].round().astype(np.int32)], 1)
        inn = np.zeros((H, W), np.uint8)
        cv2.fillPoly(inn, [P[LIPS_INNER].round().astype(np.int32)], 1)
        lm = (o & (1 - inn)).astype(bool)
        mw = np.linalg.norm(P[61] - P[291])
        dout = cv2.distanceTransform(o, cv2.DIST_L2, 3)
        din = cv2.distanceTransform((1 - inn).astype(np.uint8), cv2.DIST_L2, 3)
        yy, xx = np.mgrid[:H, :W]
        dc = np.minimum(np.hypot(xx - P[61, 0], yy - P[61, 1]), np.hypot(xx - P[291, 0], yy - P[291, 1]))
        core = lm & (dout > 0.04 * mw) & (din > 0.04 * mw) & (dc > 0.15 * mw)
        if core.sum() < 30:
            continue
        delta = rl - fl
        direction = np.median(delta[core], 0)
        direction /= max(np.linalg.norm(direction), 1e-3)
        proj = delta @ direction
        s = proj / max(np.percentile(proj[core], 90), 1e-3)
        med = lambda sel: np.median(s[sel]) if sel.any() else np.nan
        zones["core"].append(med(core))
        zones["edge 2px"].append(med(lm & (dout < 2.5) & (dc > 0.15 * mw)))
        zones["edge"].append(med(lm & (dout >= 2.5) & (dout < 0.04 * mw) & (dc > 0.15 * mw)))
        zones["inner"].append(med(lm & (din < 0.04 * mw) & (dc > 0.15 * mw)))
        zones["corner"].append(med(lm & (dc < 0.08 * mw)))
        for b in range(12):
            sel = lm & (dc >= b * 0.02 * mw) & (dc < (b + 1) * 0.02 * mw)
            if sel.any():
                prof[b] += np.median(s[sel])
                profn[b] += 1
        bare_c, rend_c = np.median(fl[core], 0), np.median(rl[core], 0)
        span = prod - bare_c
        cov.append(float((rend_c - bare_c) @ span / max(span @ span, 1e-3)))
        for k, c in (("render", rend_c), ("bare", bare_c)):
            cs[k].append(np.hypot(c[1], c[2]))
            ls[k].append(c[0])
        # Against the lip ground truth: painted = moved at least a quarter of the way the core moved.
        gt = cv2.imread(str(PHONE / f"{n}_gt.png"), cv2.IMREAD_GRAYSCALE) > 127
        painted = s > 0.25
        fit_gt["iou"].append((painted & gt).sum() / max((painted | gt).sum(), 1))
        fit_gt["spill"].append((painted & ~gt).sum() / max(painted.sum(), 1))
        fit_gt["miss"].append((gt & ~painted).sum() / max(gt.sum(), 1))
    print(f"{args.renders.name}: {len(cov)} faces, product {args.hex} L* {prod[0]:.1f} C* {np.hypot(prod[1], prod[2]):.1f}")
    for k, v in zones.items():
        print(f"  strength {k:9s} {np.nanmedian(v):.2f}")
    print("  from corner tip:", " ".join(f"{b * 2}%:{prof[b] / max(profn[b], 1):.2f}" for b in range(0, 12, 2)))
    print(f"  core coverage bare→product {np.median(cov):.2f}   C* render {np.median(cs['render']):.1f} "
          f"(bare {np.median(cs['bare']):.1f})   L* render {np.median(ls['render']):.1f} (bare {np.median(ls['bare']):.1f})")
    print("  vs lip ground truth: " + "  ".join(f"{k} {np.mean(v):.3f}" for k, v in fit_gt.items()))


if __name__ == "__main__":
    main()

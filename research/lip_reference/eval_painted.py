"""Where did the shader actually paint? Offline renders vs LaPa lip ground truth (plan track E).

eval_lapa.py compares outlines; this compares the final rendered pixels, so the shader's own mask
decisions (edge refine, band growth, A2, reflections) are included. A pixel counts as painted when
the render differs from the frame by more than CHANGED (sum of |ΔRGB|, 8-bit).

    python research/lip_reference/eval_painted.py <render dir> [<render dir> ...]

Needs research/data/paint_eval/ from render_ar_offline.py (frames named p{i}_..._3.png, i = order
in names.json) and the phone frames + masks from prep_lapa_phone.py.
"""
import json
import sys
from pathlib import Path

import cv2
import numpy as np

from eval_lapa import ROOT

PHONE = ROOT / "research/data/reference/lapa/phone"
EVAL = ROOT / "research/data/paint_eval"
CHANGED = 24


def reflections(frame, gt):
    """Bright, desaturated peaks on the real lip (the pixels the 10-25 fix is about)."""
    img = frame.astype(np.float32) / 255
    lin = np.where(img <= 0.04045, img / 12.92, ((img + 0.055) / 1.055) ** 2.4)
    L = lin @ np.array([0.0722, 0.7152, 0.2126])
    mx, mn = lin.max(2), lin.min(2)
    sat = (mx - mn) / np.maximum(mx, 1e-4)
    return (L > 1.3 * L[gt].mean()) & (L > 1.15 * cv2.blur(L, (7, 7))) & (sat < 0.45) & gt


def main():
    dirs = [Path(d) for d in sys.argv[1:]] or [EVAL / "before", EVAL / "after"]
    names = json.loads((EVAL / "names.json").read_text())
    for d in dirs:
        iou, spill, miss, hl_paint, hl_n = [], [], [], 0, 0
        for i, n in enumerate(names, 1):
            r = d / f"p{i}_day_00_eval-satin_3.png"
            if not r.exists():
                continue
            frame = cv2.imread(str(PHONE / f"{n}.jpg"))
            gt = cv2.imread(str(PHONE / f"{n}_gt.png"), cv2.IMREAD_GRAYSCALE) > 127
            render = cv2.imread(str(r))
            painted = np.abs(render.astype(int) - frame.astype(int)).sum(2) > CHANGED
            iou.append((painted & gt).sum() / max((painted | gt).sum(), 1))
            spill.append((painted & ~gt).sum() / max(painted.sum(), 1))
            miss.append((gt & ~painted).sum() / max(gt.sum(), 1))
            hl = reflections(frame, gt)
            hl_paint += (hl & painted).sum()
            hl_n += hl.sum()
        print(f"{d.name:8s} n={len(iou)}  IoU {np.mean(iou):.3f} (median {np.median(iou):.3f})  "
              f"spill {np.mean(spill):.3f}  miss {np.mean(miss):.3f}  "
              f"reflection px painted {hl_paint / max(hl_n, 1):.3f} ({hl_n} px)")


if __name__ == "__main__":
    main()

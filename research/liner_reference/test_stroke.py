"""Stroke geometry without photos or the app."""
from types import SimpleNamespace

import numpy as np

from stroke import IRIS_DROP, THICKNESS, stroke_mask


def _lms():
    pts = [SimpleNamespace(x=0.5, y=0.5) for _ in range(478)]
    # Left eye: outer 33 at x=0.2, inner 133 at x=0.4, lids at y=0.4
    xs = np.linspace(0.20, 0.40, 9)
    for i, idx in enumerate([33, 246, 161, 160, 159, 158, 157, 173, 133]):
        pts[idx] = SimpleNamespace(x=float(xs[i]), y=0.40)
    for i, idx in enumerate([33, 7, 163, 144, 145, 153, 154, 155, 133]):
        pts[idx] = SimpleNamespace(x=float(xs[i]), y=0.42)
    pts[468] = SimpleNamespace(x=0.30, y=0.41)
    pts[46] = SimpleNamespace(x=0.28, y=0.32)
    # Right eye
    xs = np.linspace(0.80, 0.60, 9)
    for i, idx in enumerate([263, 466, 388, 387, 386, 385, 384, 398, 362]):
        pts[idx] = SimpleNamespace(x=float(xs[i]), y=0.40)
    for i, idx in enumerate([263, 249, 390, 373, 374, 380, 381, 382, 362]):
        pts[idx] = SimpleNamespace(x=float(xs[i]), y=0.42)
    pts[473] = SimpleNamespace(x=0.70, y=0.41)
    pts[276] = SimpleNamespace(x=0.72, y=0.32)
    return pts


def test_stroke_has_pixels_and_self_iou():
    pred = stroke_mask(_lms(), 400, 300)
    assert pred.sum() > 80
    inter = (pred & pred).sum()
    union = (pred | pred).sum()
    assert inter / union == 1.0
    assert THICKNESS == 0.05
    assert IRIS_DROP == 0.02


def test_closed_eye_keeps_stroke():
    lms = _lms()
    for idx in (246, 161, 160, 159, 158, 157, 173, 466, 388, 387, 386, 385, 384, 398):
        lms[idx] = SimpleNamespace(x=lms[idx].x, y=0.42)
    pred = stroke_mask(lms, 400, 300)
    assert pred.sum() > 40


if __name__ == "__main__":
    test_stroke_has_pixels_and_self_iou()
    test_closed_eye_keeps_stroke()
    print("test_stroke ok")

"""Landmark lash-wing stroke (same numbers as EYELINER_PRESET.lineWing). Research only.

Does not import app code. Indices match components/ar/faceTrackerHtml.ts EYE_LINES.
"""
from __future__ import annotations

import math

import cv2
import numpy as np

# Outer → inner on both eyes (same order as faceTrackerHtml EYE_LINES).
EYE_UPPER = (
    [33, 246, 161, 160, 159, 158, 157, 173, 133],
    [263, 466, 388, 387, 386, 385, 384, 398, 362],
)
EYE_LOWER = (
    [33, 7, 163, 144, 145, 153, 154, 155, 133],
    [263, 249, 390, 373, 374, 380, 381, 382, 362],
)
IRIS = (468, 473)

THICKNESS = 0.05
INNER_SHARE = 0.55
TAPER = 0.55
IRIS_DROP = 0.02
ANGLE_DEG = 24
LENGTH = 0.20
LOWER_THICKNESS = 0.05
LOWER_START = 0.08
LOWER_END = 1.0


def _pts(lms, w, h):
    n = len(lms)
    out = np.zeros((max(n, 478), 2), np.float32)
    for i, l in enumerate(lms):
        out[i] = (l.x * w, l.y * h)
    return out


def _dist(a, b):
    return float(math.hypot(a[0] - b[0], a[1] - b[1]))


def _smooth01(a, b, x):
    if b <= a:
        return 1.0 if x >= b else 0.0
    r = min(1.0, max(0.0, (x - a) / (b - a)))
    return r * r * (3 - 2 * r)


def _band(canvas, curve, n_up, thick_fn, drop_fn=None):
    """Fill a variable-width strip along curve. n_up points toward the brow."""
    top, bot = [], []
    n = len(curve)
    if n < 2:
        return
    for j, q in enumerate(curve):
        t = 1 - j / (n - 1)
        q = np.asarray(q, np.float32)
        if drop_fn is not None:
            q = q + drop_fn(q, t)
        th = thick_fn(t)
        lift = 0.0
        bot.append(q + n_up * lift)
        top.append(q + n_up * (lift + th))
    ring = np.vstack([bot[::-1], top])
    cv2.fillPoly(canvas, [np.round(ring).astype(np.int32)], 1)


def stroke_mask(lms, w, h) -> np.ndarray:
    """Binary mask of the line-wing stroke (upper line + underline + one wing)."""
    pts = _pts(lms, w, h)
    m = np.zeros((h, w), np.uint8)
    for k in (0, 1):
        up = pts[EYE_UPPER[k]]
        low = pts[EYE_LOWER[k]]
        outer, inner = up[0], up[-1]
        eye_w = _dist(outer, inner)
        if eye_w < 4:
            continue
        axis = (outer - inner) / eye_w
        n_up = np.array([-axis[1], axis[0]], np.float32)
        mid = (outer + inner) * 0.5
        brow = pts[46 if k == 0 else 276]
        if np.dot(n_up, brow - mid) < 0:
            n_up = -n_up
        iris = pts[IRIS[k]] if len(pts) > IRIS[k] else mid

        def drop_fn(q, t):
            drop = IRIS_DROP * eye_w * (1 - _smooth01(0.8, 1, t))
            d = iris - q
            dl = float(np.hypot(d[0], d[1])) or 1.0
            return d / dl * drop

        def thick_fn(t):
            return THICKNESS * eye_w * (INNER_SHARE + (1 - INNER_SHARE) * (t**TAPER))

        _band(m, up, n_up, thick_fn, drop_fn)

        ang = math.radians(ANGLE_DEG)
        wdir = axis * math.cos(ang) + n_up * math.sin(ang)
        length = LENGTH * eye_w
        tip = outer + wdir * length
        th0 = thick_fn(1.0)
        wing = np.array(
            [outer + n_up * th0, tip, outer - n_up * 0.15 * th0],
            np.float32,
        )
        cv2.fillPoly(m, [np.round(wing).astype(np.int32)], 1)

        n_low = len(low)
        ltop, lbot = [], []
        span = max(LOWER_END - LOWER_START, 1e-3)
        for j in range(n_low):
            t = 1 - j / max(n_low - 1, 1)
            if t < LOWER_START or t > LOWER_END:
                continue
            u = (t - LOWER_START) / span
            th = LOWER_THICKNESS * eye_w * (0.35 + 0.65 * u) * (1 - _smooth01(0.92, 1, t))
            q = low[j]
            ltop.append(q)
            lbot.append(q - n_up * th)
        ltop.append(outer)
        lbot.append(outer)
        if len(ltop) > 2:
            ring = np.vstack([np.array(lbot[::-1]), np.array(ltop)])
            cv2.fillPoly(m, [np.round(ring).astype(np.int32)], 1)
    return m.astype(bool)

"""Face-shape features from MediaPipe 468 landmarks. The page script (components/ar/faceTrackerHtml.ts,
`faceShapeFeatures`) computes the same numbers; keep the two in step (a Jest test runs the JS on the same input).

All features are ratios or angles, so camera distance does not matter. Coordinates: x*w, y*h, z*w (MediaPipe's z
shares the scale of x). Left chain = image-left jaw, right chain = its mirror.
"""
import math

import numpy as np

LEFT = [132, 58, 172, 136, 150, 149, 176, 148, 152]
RIGHT = [361, 288, 397, 365, 379, 378, 400, 377, 152]
FEATURES = ["faceLong", "cheekWide", "foreheadW", "jawEarW", "chinW", "jawAngle", "jawCurve", "chinAngle"]


def _p(L, i, w, h):
    return np.array([L[i][0] * w, L[i][1] * h, L[i][2] * w], dtype=float)


def _ang(a, b, c):
    """Angle at b between b->a and b->c, degrees."""
    u, v = a - b, c - b
    cs = float(np.dot(u, v) / max(1e-9, np.linalg.norm(u) * np.linalg.norm(v)))
    return math.degrees(math.acos(max(-1.0, min(1.0, cs))))


def pose_ok(L, w, h, yaw=(0.85, 1.18), roll_deg=10.0):
    d = lambda a, b: float(np.linalg.norm(_p(L, a, w, h) - _p(L, b, w, h)))
    side = d(1, 234) / max(1e-6, d(1, 454))
    ear = _p(L, 454, w, h) - _p(L, 234, w, h)
    roll = abs(math.degrees(math.atan2(ear[1], abs(ear[0]))))  # |dx|: independent of a mirrored x axis
    return yaw[0] <= side <= yaw[1] and roll <= roll_deg


def features(L, w, h):
    P = lambda i: _p(L, i, w, h)
    d = lambda a, b: float(np.linalg.norm(P(a) - P(b)))
    width = d(234, 454)
    jaw = d(172, 397)
    angs, curves = [], []
    for chain in (LEFT, RIGHT):
        angs.append(_ang(P(chain[1]), P(chain[2]), P(chain[4])))  # at 172 / 397: ear-side edge vs chin-side edge
        turns = []
        for k in range(1, len(chain) - 1):
            a, b, c = P(chain[k - 1]), P(chain[k]), P(chain[k + 1])
            turns.append(180.0 - _ang(a, b, c))
        curves.append(max(turns) / max(1e-6, sum(turns)))
    return {
        "faceLong": d(10, 152) / width,
        "cheekWide": width / jaw,
        "foreheadW": d(54, 284) / width,
        "jawEarW": d(132, 361) / width,
        "chinW": d(148, 377) / jaw,
        "jawAngle": float(np.mean(angs)),
        "jawCurve": float(np.mean(curves)),
        "chinAngle": _ang(P(148), P(152), P(377)),
    }

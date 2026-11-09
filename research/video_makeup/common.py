"""Shared pieces for measuring how a makeup was drawn in a public YouTube tutorial.

Local research only (AR_SPEC 6-12, 11-08 exception): videos and frames stay under research/data/video_makeup/
(git-ignored). Only measured numbers are meant to leave that folder. The app and the servers never download videos.
"""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass
from pathlib import Path

import cv2
import mediapipe as mp
import numpy as np
from mediapipe.tasks.python import BaseOptions, vision

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "research" / "data" / "video_makeup"
MODEL = ROOT / "research" / "data" / "models" / "face_landmarker.task"
HAND_MODEL = ROOT / "research" / "data" / "models" / "hand_landmarker.task"
STYLE_LOOKS = ROOT / "backend" / "api" / "app" / "catalog_data" / "style_looks.json"

# Side 0 / side 1 follow CHEEKS in components/ar/faceTrackerHtml.ts.
EYES = (
    {"inner": 133, "outer": 33, "upper": [173, 157, 158, 159, 160, 161, 246], "lower": [155, 154, 153, 145, 144, 163, 7],
     "lid_top": 159, "lid_low": 145, "brow": 105},
    {"inner": 362, "outer": 263, "upper": [398, 384, 385, 386, 387, 388, 466], "lower": [382, 381, 380, 374, 373, 390, 249],
     "lid_top": 386, "lid_low": 374, "brow": 334},
)
CHEEKS = (
    {"inner": 50, "outer": 116, "low": 205, "lid": 145, "ala": 129, "mouth": 61, "jaw": 132, "edge": 234, "eye": 0},
    {"inner": 280, "outer": 345, "low": 425, "lid": 374, "ala": 358, "mouth": 291, "jaw": 361, "edge": 454, "eye": 1},
)
FACE_EDGES = (234, 454)
FACE_OVAL = [10, 338, 297, 332, 284, 251, 389, 356, 454, 323, 361, 288, 397, 365, 379, 378, 400, 377,
             152, 148, 176, 149, 150, 136, 172, 58, 132, 93, 234, 127, 162, 21, 54, 103, 67, 109]
LIPS_OUTER = [61, 185, 40, 39, 37, 0, 267, 269, 270, 409, 291, 375, 321, 405, 314, 17, 84, 181, 91, 146]

# AR defaults (faceTrackerHtml.ts TUNING.blushSize · appleScale) and eyeliner chips (lib/linerLooks.ts, the same numbers as
# backend/api/app/schemas/look_recipe.py LINER_LOOKS). Lengths and thicknesses are shares of the eye width.
BLUSH_RADII = (0.17 * 0.8, 0.11 * 0.8)
LINER_CHIPS = {
    "natural": {"thickness": 0.063, "length": 0.0, "angle": 0, "linerLower": False},
    "cat_wing": {"thickness": 0.108, "length": 0.3, "angle": 15, "linerLower": False},
    "puppy": {"thickness": 0.09, "length": 0.12, "angle": -10, "linerLower": False},
    "smoky": {"thickness": 0.144, "length": 0.08, "angle": 0, "linerLower": True},
    "gyaru": {"thickness": 0.144, "length": 0.35, "angle": 12, "linerLower": True},
    "under_point": {"thickness": 0.054, "length": 0.0, "angle": 0, "linerLower": True},
}


def env_value(name: str) -> str | None:
    """A setting from the environment or the repo's .env files (never printed)."""
    if os.environ.get(name):
        return os.environ[name]
    for path in (ROOT / ".env", ROOT / "backend" / "api" / ".env"):
        if not path.exists():
            continue
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.startswith(name + "="):
                value = line.split("=", 1)[1].strip().strip('"').strip("'")
                if value:
                    return value
    return None


def video_dir(video_id: str) -> Path:
    path = DATA / video_id
    path.mkdir(parents=True, exist_ok=True)
    return path


def write_json(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def read_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def landmarker() -> vision.FaceLandmarker:
    opts = vision.FaceLandmarkerOptions(base_options=BaseOptions(model_asset_path=str(MODEL)), num_faces=1)
    return vision.FaceLandmarker.create_from_options(opts)


def detect(lm: vision.FaceLandmarker, rgb: np.ndarray) -> np.ndarray | None:
    res = lm.detect(mp.Image(image_format=mp.ImageFormat.SRGB, data=np.ascontiguousarray(rgb)))
    if not res.face_landmarks:
        return None
    h, w = rgb.shape[:2]
    return np.array([[p.x * w, p.y * h] for p in res.face_landmarks[0][:468]], dtype=np.float32)


def hand_landmarker() -> vision.HandLandmarker:
    opts = vision.HandLandmarkerOptions(base_options=BaseOptions(model_asset_path=str(HAND_MODEL)), num_hands=2)
    return vision.HandLandmarker.create_from_options(opts)


def hand_on_face(hl: vision.HandLandmarker, rgb: np.ndarray, pts: np.ndarray) -> bool:
    """A hand is within a quarter face of the face box: the brush or pencil it holds then usually crosses the face."""
    res = hl.detect(mp.Image(image_format=mp.ImageFormat.SRGB, data=np.ascontiguousarray(rgb)))
    if not res.hand_landmarks:
        return False
    h, w = rgb.shape[:2]
    oval = pts[FACE_OVAL]
    (x0, y0), (x1, y1) = oval.min(0), oval.max(0)
    mx, my = 0.25 * (x1 - x0), 0.25 * (y1 - y0)
    for hand in res.hand_landmarks:
        xy = np.array([[p.x * w, p.y * h] for p in hand])
        inside = (xy[:, 0] > x0 - mx) & (xy[:, 0] < x1 + mx) & (xy[:, 1] > y0 - my) & (xy[:, 1] < y1 + my)
        if inside.any():
            return True
    return False


def lab(rgb: np.ndarray) -> np.ndarray:
    """CIE Lab with L 0..100 (float)."""
    return cv2.cvtColor(rgb.astype(np.float32) / 255.0, cv2.COLOR_RGB2Lab)


def dist(a: np.ndarray, b: np.ndarray) -> float:
    return float(np.linalg.norm(np.asarray(a, dtype=np.float64) - np.asarray(b, dtype=np.float64)))


def face_width(pts: np.ndarray) -> float:
    return dist(pts[FACE_EDGES[0]], pts[FACE_EDGES[1]])


def poly_mask(shape: tuple[int, int], poly: np.ndarray) -> np.ndarray:
    mask = np.zeros(shape, np.uint8)
    cv2.fillPoly(mask, [np.round(poly).astype(np.int32)], 1)
    return mask.astype(bool)


def eye_frame(pts: np.ndarray, k: int) -> tuple[np.ndarray, np.ndarray, float]:
    """Origin at the outer eye corner, x toward the ear along the eye axis, y toward the brow; unit = eye width."""
    e = EYES[k]
    inner, outer = pts[e["inner"]].astype(np.float64), pts[e["outer"]].astype(np.float64)
    x = outer - inner
    width = float(np.linalg.norm(x))
    x /= width
    y = np.array([x[1], -x[0]])
    if np.dot(pts[e["brow"]] - outer, y) < 0:
        y = -y
    return outer, np.stack([x, y]), width


def to_eye(points: np.ndarray, frame: tuple[np.ndarray, np.ndarray, float]) -> np.ndarray:
    origin, axes, width = frame
    return (np.asarray(points, dtype=np.float64) - origin) @ axes.T / width


def from_eye(points: np.ndarray, frame: tuple[np.ndarray, np.ndarray, float]) -> np.ndarray:
    origin, axes, width = frame
    return np.asarray(points, dtype=np.float64) * width @ axes + origin


def tail_poly(pts: np.ndarray, k: int) -> np.ndarray:
    """Where a wing goes: just past the outer eye corner, from the corner line up toward the brow tail."""
    return from_eye(np.array([[0.0, -0.05], [0.4, -0.05], [0.4, 0.32], [0.0, 0.32]]), eye_frame(pts, k))


def cheek_poly(pts: np.ndarray, k: int) -> np.ndarray:
    """The cheek below the lower lid, between the nose wing, the mouth corner and the face edge."""
    c = CHEEKS[k]
    e = EYES[c["eye"]]
    fw = face_width(pts)
    _, axes, _ = eye_frame(pts, c["eye"])
    down = -axes[1]
    p = pts.astype(np.float64)
    # The top follows the lower lid closely (the AR clips blush at the lower lid), so an under-eye blush is not cut.
    return np.array([
        p[e["outer"]] + down * 0.04 * fw,
        p[c["lid"]] + down * 0.025 * fw,
        p[e["inner"]] + down * 0.05 * fw,
        p[c["ala"]] + (p[c["edge"]] - p[c["ala"]]) * 0.08,
        p[c["mouth"]] + (p[c["edge"]] - p[c["mouth"]]) * 0.15,
        p[c["jaw"]] + (p[c["ala"]] - p[c["jaw"]]) * 0.12,
        p[c["edge"]] + (p[c["ala"]] - p[c["edge"]]) * 0.1,
    ])


def chin_mask(shape: tuple[int, int], pts: np.ndarray) -> np.ndarray:
    """Skin under the lower lip: the exposure reference (rarely made up, never covered by bangs)."""
    ctr = (pts[17] + pts[152]) / 2
    rx = 0.35 * dist(pts[61], pts[291])
    ry = 0.3 * dist(pts[17], pts[152])
    mask = np.zeros(shape, np.uint8)
    cv2.ellipse(mask, (int(ctr[0]), int(ctr[1])), (max(int(rx), 2), max(int(ry), 2)), 0, 0, 360, 1, -1)
    return mask.astype(bool)


@dataclass(frozen=True)
class Quality:
    ok: bool
    face_frac: float
    yaw: float
    eye_open: float
    sharp: float
    score: float


def quality(pts: np.ndarray, rgb: np.ndarray) -> Quality:
    """Frontal, open-eyed, whole face in the frame and sharp enough to read an eyeliner tail."""
    h, w = rgb.shape[:2]
    fw = face_width(pts)
    yaw = (dist(pts[1], pts[234]) - dist(pts[1], pts[454])) / max(fw, 1e-6)
    eye_open = min(dist(pts[EYES[k]["lid_top"]], pts[EYES[k]["lid_low"]]) / dist(pts[EYES[k]["outer"]], pts[EYES[k]["inner"]])
                   for k in (0, 1))
    oval = pts[FACE_OVAL]
    (x0, y0), (x1, y1) = oval.min(0), oval.max(0)
    inside = x0 >= 0 and y0 >= 0 and x1 < w and y1 < h
    sharp = 0.0
    if inside:
        crop = cv2.cvtColor(rgb[int(y0):int(y1), int(x0):int(x1)], cv2.COLOR_RGB2GRAY)
        if crop.size:
            crop = cv2.resize(crop, (256, max(int(256 * crop.shape[0] / crop.shape[1]), 1)))
            sharp = float(cv2.Laplacian(crop, cv2.CV_32F).var())
    ok = bool(inside and fw / w >= 0.22 and abs(yaw) <= 0.12 and eye_open >= 0.18)
    score = (min(sharp / 150.0, 1.5) * (1 - 0.5 * min(abs(yaw) / 0.12, 1)) * min(fw / w / 0.4, 1.0)) if ok else 0.0
    return Quality(ok, round(fw / w, 3), round(yaw, 3), round(eye_open, 3), round(sharp, 1), round(score, 3))


def quality_dict(q: Quality) -> dict:
    return asdict(q)

"""Find exploratory blush-change centroids in one aligned pre/post video pair.

These are colour-change candidates, not verified makeup outlines or product
placement parameters. The threshold and face-relative coordinates are recorded
so they can be reviewed and challenged rather than used as ground truth.
"""

from __future__ import annotations

import json
from pathlib import Path

import cv2
import numpy as np
from mediapipe.tasks.python import BaseOptions, vision

from analyze_blush import points, read_rgb

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "research/data/karina_look/blush_baseline"
REDNESS_THRESHOLD = 1.5  # exploratory CIELAB a* difference; not a validated segmentation cutoff


def main() -> None:
    before, ar, video = [read_rgb(OUT / name) for name in ("off.png", "blush.png", "target_warped.png")]
    mask = cv2.imread(str(OUT / "cheek_mask.png"), cv2.IMREAD_GRAYSCALE) > 0
    lab = [cv2.cvtColor(rgb.astype(np.float32) / 255, cv2.COLOR_RGB2Lab) for rgb in (before, ar, video)]
    opts = vision.FaceLandmarkerOptions(
        base_options=BaseOptions(model_asset_path=str(ROOT / "research/data/models/face_landmarker.task")),
        num_faces=1,
    )
    with vision.FaceLandmarker.create_from_options(opts) as detector:
        pts = points(detector, before)
    eye_center = (pts[33] + pts[263]) / 2
    face_width = float(np.linalg.norm(pts[234] - pts[454]))
    if face_width <= 0:
        raise RuntimeError("Invalid face width")
    y, x = np.indices(mask.shape)
    # BGR for OpenCV output: green = current app, magenta = video candidate.
    annotated = cv2.cvtColor(before.copy(), cv2.COLOR_RGB2BGR)
    out = {
        "kind": "exploratory_color_change_centroids_not_validated_placement",
        "coordinate_system": "offset from midpoint of outer eye corners, divided by face width; mirrored screen",
        "redness_delta_a_threshold": REDNESS_THRESHOLD,
        "limitations": ["one_frame_pair", "video_color_correction_residual", "video_edit_and_warp", "arbitrary_threshold"],
        "centroids": {},
    }
    for label, after, color in (("ar", lab[1], (0, 220, 0)), ("video", lab[2], (255, 0, 255))):
        delta = after[:, :, 1] - lab[0][:, :, 1]
        out["centroids"][label] = {}
        for side, side_mask in (("screen_left", x < eye_center[0]), ("screen_right", x >= eye_center[0])):
            region = mask & side_mask
            weight = np.where(region, np.maximum(delta - REDNESS_THRESHOLD, 0), 0)
            total = float(weight.sum())
            if total <= 0:
                raise RuntimeError(f"No colour-change signal for {label} {side}")
            cx, cy = float((weight * x).sum() / total), float((weight * y).sum() / total)
            out["centroids"][label][side] = {
                "x_face_widths_from_eye_center": (cx - float(eye_center[0])) / face_width,
                "y_face_widths_from_eye_center": (cy - float(eye_center[1])) / face_width,
                "qualifying_pixels": int((weight > 0).sum()),
            }
            cv2.drawMarker(annotated, (round(cx), round(cy)), color, cv2.MARKER_CROSS, 15, 2)
    (OUT / "blush_location_candidates.json").write_text(json.dumps(out, indent=2), encoding="utf-8")
    cv2.imwrite(str(OUT / "blush_location_candidates.png"), annotated)
    print(json.dumps(out, indent=2))


if __name__ == "__main__":
    main()

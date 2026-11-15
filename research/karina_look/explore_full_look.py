"""Visualize the entire actual app look against a landmark-aligned video frame.

The frames differ in pose, framing and lighting; this is an uncalibrated visual
aid, not a measured makeup mask or a claim that the app matches the video.
"""

from __future__ import annotations

import json
from pathlib import Path

import cv2
import numpy as np
from mediapipe.tasks.python import BaseOptions, vision
from PIL import Image, ImageDraw

from analyze_blush import points, read_rgb, warp_mesh

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "research/data/karina_look"
OUT = DATA / "all_baseline"


def main() -> None:
    before = read_rgb(OUT / "off.png")
    applied = read_rgb(OUT / "all.png")
    target = read_rgb(DATA / "whole_after/0000.png")  # 250 s, near complete; minor touch-ups follow
    target = cv2.flip(cv2.resize(target, (before.shape[1], before.shape[0]), interpolation=cv2.INTER_AREA), 1)
    opts = vision.FaceLandmarkerOptions(
        base_options=BaseOptions(model_asset_path=str(ROOT / "research/data/models/face_landmarker.task")),
        num_faces=1,
    )
    with vision.FaceLandmarker.create_from_options(opts) as detector:
        before_points = points(detector, before)
        target_points = points(detector, target)
    warped, covered = warp_mesh(target.astype(np.float32) / 255.0, target_points, before_points, before.shape[:2])
    aligned = before.copy()
    aligned[covered] = np.clip(warped[covered] * 255, 0, 255).astype(np.uint8)
    overlay = before.copy()
    overlay[covered] = np.round(before[covered] * 0.5 + aligned[covered] * 0.5).astype(np.uint8)
    for filename, rgb in (("video_aligned_unscaled_color.png", aligned), ("before_video_overlay.png", overlay)):
        cv2.imwrite(str(OUT / filename), cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR))

    width = 500
    height = round(before.shape[0] * width / before.shape[1])
    sheet = Image.new("RGB", (width * 4, height + 34), "white")
    draw = ImageDraw.Draw(sheet)
    panels = (("before_9.25s", before), ("current_app_all", applied),
              ("video_250s_aligned", aligned), ("before_video_overlay", overlay))
    for i, (label, rgb) in enumerate(panels):
        img = Image.fromarray(rgb).resize((width, height), Image.Resampling.LANCZOS)
        sheet.paste(img, (width * i, 0))
        draw.text((width * i + 5, height + 8), label, fill="black")
    sheet.save(OUT / "whole_look_exploration.png")
    h, w = before.shape[:2]
    payload = {
        "before_s": 9.25, "video_s": 250, "coordinate_space": "mirrored_image_fraction_of_frame; points may be outside frame",
        "note": "These are face landmarks, not automatically validated makeup boundaries.",
        "before_landmarks": (before_points / [w, h]).tolist(),
        "video_landmarks": (target_points / [w, h]).tolist(),
        "color_calibrated": False,
        "limits": ["before_chin_occluded", "target_angled", "additional_video_touchups_follow", "background_calibration_failed"],
    }
    (OUT / "face_landmarks_exploratory.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(f"Wrote uncalibrated whole-look alignment and face landmarks to {OUT}")


if __name__ == "__main__":
    main()

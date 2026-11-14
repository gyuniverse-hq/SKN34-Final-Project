"""Descriptive lip measurements for an imperfect, uncalibrated video comparison.

The target is still being painted and cushion has been applied in between.
These numbers are not an isolated product test or evidence of improvement.
"""

from __future__ import annotations

import csv
import importlib.util
import sys
from dataclasses import asdict
from pathlib import Path

import cv2
import numpy as np
from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "research" / "data" / "karina_look"
COMPARISON = ROOT / "research" / "vto_benchmark" / "compare_lips.py"


def main() -> None:
    spec = importlib.util.spec_from_file_location("karina_compare_lips", COMPARISON)
    if spec is None or spec.loader is None:
        raise RuntimeError("Missing the existing lip comparison tool")
    compare = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = compare
    spec.loader.exec_module(compare)
    out = DATA / "lip_baseline"
    paths = [out / "off.png", out / "lip.png", DATA / "lip_target" / "0004.png"]
    images = [compare.read_rgb(path) for path in paths]
    # Match the render dimensions and mirror the original target like the WebView.
    target = cv2.resize(images[2], (images[0].shape[1], images[0].shape[0]), interpolation=cv2.INTER_AREA)
    images[2] = np.ascontiguousarray(target[:, ::-1])
    labels = ["before_161s", "ar_current_161s", "video_in_progress_191_5s"]
    with compare.load_landmarker(ROOT / "research/data/models/face_landmarker.task") as detector:
        source_points = compare.detect(detector, images[0])
        target_points = compare.detect(detector, images[2])
    if source_points is None or target_points is None:
        raise RuntimeError("Face landmarks missing; no comparison produced")
    rows = []
    for label, path, rgb, points in zip(
        labels, paths, images, [source_points, source_points, target_points], strict=True
    ):
        result, _ = compare.measure(rgb, points, "exploratory", label, path.name)
        rows.append(asdict(result))
    with (out / "descriptive_metrics.csv").open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)

    # Images remain solely in the Git-ignored research data directory.
    thumb_width = 480
    thumb_height = round(images[0].shape[0] * thumb_width / images[0].shape[1])
    sheet = Image.new("RGB", (thumb_width * 3, thumb_height + 32), "white")
    draw = ImageDraw.Draw(sheet)
    for i, (label, rgb) in enumerate(zip(labels, images, strict=True)):
        img = Image.fromarray(rgb).resize((thumb_width, thumb_height), Image.Resampling.LANCZOS)
        sheet.paste(img, (thumb_width * i, 0))
        draw.text((thumb_width * i + 5, thumb_height + 6), label, fill="black")
    sheet.save(out / "exploratory_comparison.png")
    print(f"Wrote descriptive measurements and image to {out}")
    for row in rows:
        print(row["source"], "L_spread", row["L_spread"], "texture", row["texture"],
              "hl_area_pct", row["hl_area_pct"], "upper_lower_L", row["upper_lower_L"])


if __name__ == "__main__":
    main()

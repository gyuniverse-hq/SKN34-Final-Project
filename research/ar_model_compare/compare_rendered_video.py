"""Compose same-frame research renderer outputs into an offline comparison MP4."""
import argparse
import json
from pathlib import Path

import cv2
import numpy as np


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--left", required=True, type=Path)
    p.add_argument("--right", required=True, type=Path)
    p.add_argument("--output", required=True, type=Path)
    p.add_argument("--fps", type=float, default=5)
    args = p.parse_args()
    if args.fps <= 0:
        p.error("fps must be positive")
    left = json.loads((args.left / "render_metadata.json").read_text(encoding="utf8"))
    right = json.loads((args.right / "render_metadata.json").read_text(encoding="utf8"))
    for key in ("video_sha256", "colour", "texture", "intensity"):
        if left[key] != right[key]:
            raise ValueError(f"Inconsistent rendering condition: {key}")
    lrows, rrows = left["frames"], right["frames"]
    if not lrows or [r["frame"] for r in lrows] != [r["frame"] for r in rrows]:
        raise ValueError("Frame lists do not match")
    first = cv2.imread(str(args.left / lrows[0]["image"]))
    if first is None:
        raise ValueError("Could not read first rendered frame")
    h, w = first.shape[:2]
    header = 52
    args.output.parent.mkdir(parents=True, exist_ok=True)
    writer = cv2.VideoWriter(str(args.output), cv2.VideoWriter_fourcc(*"mp4v"), args.fps, (w * 2, h + header))
    if not writer.isOpened():
        raise RuntimeError("Could not create output video")
    try:
        for a, b in zip(lrows, rrows):
            aimg = cv2.imread(str(args.left / a["image"]))
            bimg = cv2.imread(str(args.right / b["image"]))
            if aimg is None or bimg is None or aimg.shape != first.shape or bimg.shape != first.shape:
                raise ValueError(f"Invalid rendered frame {a['frame']}")
            result = np.full((h + header, w * 2, 3), (31, 27, 23), np.uint8)
            result[header:, :w] = aimg
            result[header:, w:] = bimg
            cv2.putText(result, left["model"], (16, 33), cv2.FONT_HERSHEY_SIMPLEX, .75, (255, 255, 255), 2, cv2.LINE_AA)
            cv2.putText(result, right["model"], (w + 16, 33), cv2.FONT_HERSHEY_SIMPLEX, .75, (255, 255, 255), 2, cv2.LINE_AA)
            writer.write(result)
    finally:
        writer.release()
    print(args.output)


if __name__ == "__main__":
    main()

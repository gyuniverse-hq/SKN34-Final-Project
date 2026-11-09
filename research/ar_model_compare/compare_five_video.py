"""Render a six-panel comparison from matching offline app-shader frames."""
import argparse
import hashlib
import json
from pathlib import Path

import cv2
import numpy as np


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--renders", required=True, type=Path)
    p.add_argument("--source", required=True, type=Path)
    p.add_argument("--output", required=True, type=Path)
    args = p.parse_args()
    names = ["mediapipe", "segformer", "farl-lapa", "bisenet", "sam2"]
    manifests = [json.loads((args.renders / n / "render_metadata.json").read_text(encoding="utf8")) for n in names]
    source_hash = hashlib.sha256(args.source.read_bytes()).hexdigest()
    conditions = ("video_sha256", "colour", "texture", "intensity")
    first = manifests[0]
    if source_hash != first["video_sha256"] or any(any(m[k] != first[k] for k in conditions) for m in manifests):
        raise ValueError("Video or render conditions differ")
    frame_ids = [r["frame"] for r in first["frames"]]
    if not frame_ids or any([r["frame"] for r in m["frames"]] != frame_ids for m in manifests):
        raise ValueError("Frame indices differ")
    if len(frame_ids) > 1 and any(b - a != 30 for a, b in zip(frame_ids, frame_ids[1:])):
        raise ValueError("Expected one frame per second from this 30fps video")
    cap = cv2.VideoCapture(str(args.source))
    if not cap.isOpened():
        raise ValueError("Cannot decode video")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    width, height, header = 360, 640, 36
    writer = cv2.VideoWriter(str(args.output), cv2.VideoWriter_fourcc(*"mp4v"), 1, (width * 3, (height + header) * 2))
    if not writer.isOpened():
        raise RuntimeError("Cannot create output video")
    try:
        for i, frame_id in enumerate(frame_ids):
            panels = []
            for name, manifest in zip(names, manifests):
                image = cv2.imread(str(args.renders / name / manifest["frames"][i]["image"]))
                if image is None:
                    raise ValueError(f"Missing render for {name} frame {frame_id}")
                panels.append(cv2.resize(image, (width, height), interpolation=cv2.INTER_AREA))
            cap.set(cv2.CAP_PROP_POS_FRAMES, frame_id)
            ok, original = cap.read()
            if not ok:
                raise ValueError(f"Cannot decode original frame {frame_id}")
            panels.append(cv2.resize(cv2.flip(original, 1), (width, height), interpolation=cv2.INTER_AREA))
            canvas = np.full(((height + header) * 2, width * 3, 3), (30, 27, 24), np.uint8)
            for n, (label, image) in enumerate(zip(names + ["original"], panels)):
                x, y = (n % 3) * width, (n // 3) * (height + header)
                canvas[y + header:y + header + height, x:x + width] = image
                cv2.putText(canvas, label, (x + 12, y + 25), cv2.FONT_HERSHEY_SIMPLEX, .65, (255, 255, 255), 1, cv2.LINE_AA)
            writer.write(canvas)
    finally:
        cap.release()
        writer.release()
    print(args.output)


if __name__ == "__main__":
    main()

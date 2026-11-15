"""Score captured frames for the bare/final look comparison and draw a contact sheet.

File names: <videoId>_<seconds>_<kind>.png, kind = bare | final | left | right | open.
"""

from __future__ import annotations

import argparse
import json
import math
import re
from pathlib import Path

import cv2
import mediapipe as mp
import numpy as np
from mediapipe.tasks.python import BaseOptions, vision

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "research" / "data" / "look6"
MODELS = ROOT / "research" / "data" / "models"
NAME = re.compile(r"^(?P<video>[A-Za-z0-9_-]{11})_(?P<sec>\d+(?:\.\d+)?)_(?P<kind>bare|final|left|right|open)$", re.I)
KINDS = ("bare", "final", "left", "right", "open")
FRONTAL_YAW, FRONTAL_PITCH = 8.0, 12.0
ANGLED_YAW = (15.0, 35.0)
BLINK_MAX = 0.5
LIP_GAP_CLOSED = 0.02
MIN_FACE_PX = 300


def pose(matrix: np.ndarray) -> tuple[float, float, float]:
    r = matrix[:3, :3]
    yaw = math.degrees(math.atan2(r[0, 2], r[2, 2]))
    pitch = math.degrees(math.asin(max(-1.0, min(1.0, -r[1, 2]))))
    roll = math.degrees(math.atan2(r[1, 0], r[1, 1]))
    return yaw, pitch, roll


def measure(face_lm, hand_lm, path: Path) -> dict:
    bgr = cv2.imread(str(path))
    if bgr is None:
        return {"error": "unreadable"}
    h, w = bgr.shape[:2]
    image = mp.Image(image_format=mp.ImageFormat.SRGB, data=cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB))
    face = face_lm.detect(image)
    if not face.face_landmarks:
        return {"error": "no face", "width": w, "height": h}
    pts = np.array([[p.x * w, p.y * h] for p in face.face_landmarks[0]])
    x0, y0 = pts.min(axis=0)
    x1, y1 = pts.max(axis=0)
    blend = {c.category_name: c.score for c in face.face_blendshapes[0]}
    yaw, pitch, roll = pose(np.array(face.facial_transformation_matrixes[0]))
    # Nose tip between the two face edges: 0.5 when frontal, a landmark-only check on the matrix yaw.
    nose_ratio = (pts[1, 0] - pts[234, 0]) / max(1e-6, pts[454, 0] - pts[234, 0])
    face_height = np.linalg.norm(pts[10] - pts[152])
    lip_gap = np.linalg.norm(pts[13] - pts[14]) / max(1e-6, face_height)
    pad_x, pad_y = 0.1 * (x1 - x0), 0.1 * (y1 - y0)
    box = (x0 - pad_x, y0 - pad_y, x1 + pad_x, y1 + pad_y)
    hands = hand_lm.detect(image)
    hand_points = sum(
        1 for hand in hands.hand_landmarks for p in hand
        if box[0] <= p.x * w <= box[2] and box[1] <= p.y * h <= box[3]
    )
    crop = cv2.cvtColor(bgr[max(0, int(y0)):int(y1), max(0, int(x0)):int(x1)], cv2.COLOR_BGR2GRAY)
    crop = cv2.resize(crop, (256, max(1, round(256 * crop.shape[0] / max(1, crop.shape[1])))))
    return {
        "width": w, "height": h,
        "facePx": round(float(x1 - x0), 1), "faceRatio": round(float((x1 - x0) / w), 3),
        "eyeDistPx": round(float(np.linalg.norm(pts[33] - pts[263])), 1),
        "yaw": round(yaw, 1), "pitch": round(pitch, 1), "roll": round(roll, 1), "noseRatio": round(float(nose_ratio), 3),
        "blink": round(max(blend.get("eyeBlinkLeft", 0), blend.get("eyeBlinkRight", 0)), 3),
        "jawOpen": round(blend.get("jawOpen", 0), 3), "lipGap": round(float(lip_gap), 4),
        "handPointsOnFace": hand_points,
        "sharpness": round(float(cv2.Laplacian(crop, cv2.CV_64F).var()), 1),
        "box": [round(float(v), 1) for v in (x0, y0, x1, y1)],
    }


def verdict(kind: str | None, m: dict) -> list[str]:
    if "error" in m:
        return [m["error"]]
    problems = []
    if m["handPointsOnFace"]:
        problems.append("hand on face")
    if m["facePx"] < MIN_FACE_PX:
        problems.append("small face")
    if m["blink"] >= BLINK_MAX:
        problems.append("eyes closed")
    if kind in ("bare", "final", None):
        if abs(m["yaw"]) > FRONTAL_YAW or abs(m["pitch"]) > FRONTAL_PITCH:
            problems.append("not frontal")
        if m["lipGap"] >= LIP_GAP_CLOSED:
            problems.append("mouth open")
    elif kind in ("left", "right"):
        if not ANGLED_YAW[0] <= abs(m["yaw"]) <= ANGLED_YAW[1]:
            problems.append(f"yaw {m['yaw']} outside {ANGLED_YAW[0]:.0f}-{ANGLED_YAW[1]:.0f}")
    elif kind == "open" and m["lipGap"] < LIP_GAP_CLOSED:
        problems.append("mouth closed")
    return problems


def sheet(rows: list[dict], folder: Path, out: Path) -> None:
    tiles = []
    for row in rows:
        bgr = cv2.imread(str(folder / row["file"]))
        m = row["metrics"]
        if bgr is None or "box" not in m:
            tile = np.full((400, 320, 3), 40, np.uint8)
        else:
            x0, y0, x1, y1 = m["box"]
            pad = 0.25 * (x1 - x0)
            crop = bgr[max(0, int(y0 - pad)):int(y1 + pad), max(0, int(x0 - pad)):int(x1 + pad)]
            tile = cv2.resize(crop, (320, 400))
        ok = not row["problems"]
        cv2.rectangle(tile, (0, 0), (319, 399), (0, 200, 0) if ok else (0, 0, 230), 6)
        label = [row["file"][:30], f"yaw {m.get('yaw')} pitch {m.get('pitch')}",
                 f"face {m.get('facePx')}px sharp {m.get('sharpness')}", "OK" if ok else ", ".join(row["problems"])[:34]]
        for i, text in enumerate(label):
            cv2.putText(tile, text, (8, 24 + 22 * i), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 0, 0), 3)
            cv2.putText(tile, text, (8, 24 + 22 * i), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1)
        tiles.append(tile)
    if not tiles:
        return
    cols = 6
    while len(tiles) % cols:
        tiles.append(np.full((400, 320, 3), 255, np.uint8))
    grid = np.vstack([np.hstack(tiles[i:i + cols]) for i in range(0, len(tiles), cols)])
    cv2.imwrite(str(out), grid, [cv2.IMWRITE_JPEG_QUALITY, 85])


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--folder", type=Path, default=DATA / "manual")
    args = parser.parse_args()
    folder = args.folder.resolve()
    if not folder.is_relative_to((ROOT / "research" / "data").resolve()):
        parser.error("folder must stay inside the ignored research data directory")
    files = sorted(p for p in folder.iterdir() if p.suffix.lower() in (".png", ".jpg", ".jpeg"))
    face_opts = vision.FaceLandmarkerOptions(
        base_options=BaseOptions(model_asset_path=str(MODELS / "face_landmarker.task")), num_faces=1,
        output_face_blendshapes=True, output_facial_transformation_matrixes=True)
    hand_opts = vision.HandLandmarkerOptions(
        base_options=BaseOptions(model_asset_path=str(MODELS / "hand_landmarker.task")), num_hands=2)
    rows = []
    with vision.FaceLandmarker.create_from_options(face_opts) as face_lm, \
            vision.HandLandmarker.create_from_options(hand_opts) as hand_lm:
        for path in files:
            match = NAME.match(path.stem)
            kind = match["kind"].lower() if match else None
            metrics = measure(face_lm, hand_lm, path)
            rows.append({"file": path.name, "video": match["video"] if match else None,
                         "sec": float(match["sec"]) if match else None, "kind": kind,
                         "metrics": metrics, "problems": verdict(kind, metrics)})

    videos = {}
    for row in rows:
        if row["video"]:
            videos.setdefault(row["video"], []).append(row)
    summary = {}
    for video, items in sorted(videos.items()):
        good = {k: [r for r in items if r["kind"] == k and not r["problems"]] for k in KINDS}
        bare, final = good["bare"], good["final"]
        scale = None
        if bare and final:
            scale = round(max(f["metrics"]["eyeDistPx"] for f in final) / max(b["metrics"]["eyeDistPx"] for b in bare), 2)
        summary[video] = {k: len(v) for k, v in good.items()} | {
            "pairReady": bool(bare and final), "finalToBareScale": scale,
            "validationReady": bool(bare and final and (good["left"] or good["right"])),
        }

    (folder / "scores.json").write_text(json.dumps({"frames": rows, "videos": summary}, indent=2, ensure_ascii=False),
                                        encoding="utf-8")
    sheet(rows, folder, folder / "sheet.jpg")
    for row in rows:
        print(f"{row['file']:<40} {'OK' if not row['problems'] else '; '.join(row['problems'])}")
    for video, info in summary.items():
        print(video, info)


if __name__ == "__main__":
    main()

"""Extract face-shape features for every image of the Roboflow dataset (folder format).

    python research/face_shape/extract_features.py <face_landmarker.task> [dataset_dir]

Writes features.csv next to the images (git-ignored). Images with no face or a non-frontal pose are skipped
and counted, because the app only measures on frontal frames (same gate: yaw 0.85-1.18, roll <= 10 deg).
"""
import csv
import sys
from collections import Counter
from pathlib import Path

import mediapipe as mp
from mediapipe.tasks.python import BaseOptions, vision

sys.path.insert(0, str(Path(__file__).parent))
from features import FEATURES, features, pose_ok  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
DEFAULT = ROOT / "research/data/reference/face_shape/ashish-workspace__face-shape-classification-yoqx4-lfvhe__v1"


def main() -> None:
    model = sys.argv[1]
    data = Path(sys.argv[2]) if len(sys.argv) > 2 else DEFAULT
    lm = vision.FaceLandmarker.create_from_options(
        vision.FaceLandmarkerOptions(base_options=BaseOptions(model_asset_path=model), num_faces=1))
    rows, skipped = [], Counter()
    for split in ("train", "valid", "test"):
        for cls_dir in sorted((data / split).iterdir()):
            for f in sorted(cls_dir.iterdir()):
                img = mp.Image.create_from_file(str(f))
                res = lm.detect(img)
                if not res.face_landmarks:
                    skipped[(split, cls_dir.name, "noface")] += 1
                    continue
                L = [(p.x, p.y, p.z) for p in res.face_landmarks[0][:468]]
                w, h = img.width, img.height
                if not pose_ok(L, w, h):
                    skipped[(split, cls_dir.name, "pose")] += 1
                    continue
                feat = features(L, w, h)
                rows.append([split, cls_dir.name, f.name] + [feat[k] for k in FEATURES])
    out = data / "features.csv"
    with out.open("w", newline="", encoding="utf-8") as fh:
        wr = csv.writer(fh)
        wr.writerow(["split", "cls", "file"] + FEATURES)
        wr.writerows(rows)
    print("kept", len(rows), "skipped", sum(skipped.values()))
    for k, v in sorted(skipped.items()):
        print("  skipped", k, v)
    print("kept per class", dict(Counter(r[1] for r in rows)))


if __name__ == "__main__":
    main()

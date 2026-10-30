"""Count original device ROI labels using the smartphone experiment's subject splits."""

import collections
import hashlib
import json
import math
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parents[3]
DATA = ROOT / "ml/data/028.한국인 피부상태 측정 데이터/3.개방데이터/1.데이터"
MANIFEST = ROOT / "ml/runs/batch-diversity-ablation-20261027/device-supplement-fixed-20261027/baseline-manifest.json"
OUTPUT = Path(__file__).with_suffix(".json")
TASKS = {
    "pore": (6, {"pore": [5, 6]}),
    "pigmentation": (6, {"forehead_pigmentation": [1], "cheek_pigmentation": [5, 6]}),
    "wrinkle": (7, {"forehead_wrinkle": [1], "glabellus_wrinkle": [2], "perocular_wrinkle": [3, 4]}),
}
DEVICES = {"01": "1. 디지털카메라", "02": "2. 스마트패드", "03": "3. 스마트폰"}


def valid_bbox(bbox, width, height):
    if not isinstance(bbox, list) or len(bbox) != 4:
        return False
    if any(type(v) not in (int, float) or not math.isfinite(v) for v in bbox):
        return False
    x1, y1, x2, y2 = map(int, bbox)
    return 0 <= x1 < x2 <= width and 0 <= y1 < y2 <= height and int(max(x2 - x1, y2 - y1) / 2) >= 1


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False, allow_nan=False).encode()).hexdigest()


def main():
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    subjects = {}
    reference = {}
    for record in manifest["records"]:
        subject, split = record["subject"], record["split"]
        if subject in subjects and subjects[subject] != split:
            raise ValueError(f"Subject has multiple splits: {subject}")
        subjects[subject] = split
        reference[record["id"]] = (record["truth"], split)
    result = {}
    for device, folder in DEVICES.items():
        counts = {task: {split: [0] * spec[0] for split in ("train", "valid", "test")} for task, spec in TASKS.items()}
        seen, excluded, photos, checked_subjects = {}, collections.Counter(), 0, set()
        for partition, imageset, labelset in (("Training", "TS", "TL"), ("Validation", "VS", "VL")):
            label_root = DATA / partition / "02.라벨링데이터" / labelset / folder
            image_root = DATA / partition / "01.원천데이터" / imageset / folder
            for subject_dir in sorted(p for p in label_root.iterdir() if p.is_dir()):
                grouped = collections.defaultdict(list)
                for path in subject_dir.glob("*.json"):
                    parts = path.stem.split("_")
                    if len(parts) != 4 or parts[1] != device or int(parts[3]) not in range(1, 7):
                        continue
                    label = json.loads(path.read_text(encoding="utf-8"))
                    meta = label["images"]
                    if meta["device"] != int(device) - 1 or meta["facepart"] != int(parts[3]):
                        raise ValueError(f"Device/facepart mismatch: {path}")
                    grouped[(parts[0], label["info"]["filename"])].append(label)
                for (subject, filename), labels in grouped.items():
                    if subject not in subjects:
                        raise ValueError(f"No smartphone subject split: {subject}")
                    checked_subjects.add(subject)
                    image_path = image_root / subject / filename
                    with Image.open(image_path) as image:
                        width, height = image.size
                        if image.getexif().get(274, 1) in (5, 6, 7, 8):
                            width, height = height, width
                    photos += 1
                    for label in labels:
                        meta = label["images"]
                        if (width, height) != (meta["width"], meta["height"]):
                            raise ValueError(f"Image dimensions mismatch: {image_path}")
                        part = meta["facepart"]
                        candidates = []
                        for task, (classes, areas) in TASKS.items():
                            for area, faceparts in areas.items():
                                if part not in faceparts:
                                    continue
                                values = [v for k, v in label["annotations"].items() if area in k]
                                if len(values) != 1:
                                    raise ValueError(f"Ambiguous label: {subject} {filename} {area}")
                                truth = values[0]
                                if truth is None:
                                    excluded[f"{task}:missing_label"] += 1
                                    continue
                                if type(truth) is not int or not 0 <= truth < classes:
                                    raise ValueError(f"Invalid grade: {subject} {filename} {area}")
                                candidates.append((task, truth))
                        if not candidates:
                            continue
                        if not valid_bbox(meta["bbox"], width, height):
                            excluded["invalid_roi"] += len(candidates)
                            continue
                        for task, truth in candidates:
                            record_id = f'{digest([[subject, filename], part])}:{task}'
                            if record_id in seen:
                                raise ValueError(f"Duplicate record: {record_id}")
                            split = subjects[subject]
                            seen[record_id] = (truth, split)
                            counts[task][split][truth] += 1
        if device == "03" and seen != reference:
            raise ValueError(f"Smartphone records differ from reference: {len(set(seen) ^ set(reference))} ID differences")
        result[device] = {"counts": counts, "photos": photos, "subjects": len(checked_subjects), "excluded": dict(excluded)}
        print(json.dumps({"device": device, "photos": photos, "subjects": len(checked_subjects), "counts": counts, "excluded": dict(excluded)}, ensure_ascii=False), flush=True)
    OUTPUT.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()

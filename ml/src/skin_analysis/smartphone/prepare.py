"""Read original ZIPs, cache selected ROIs, and split subjects before training."""

import argparse
import collections
import hashlib
import json
import zipfile
from pathlib import Path

import cv2
import numpy as np
from server.nia.imaging import crop_bounds
from sklearn.model_selection import StratifiedGroupKFold

from .common import (
    DEFAULT_CONFIG,
    PREPROCESSING,
    TASKS,
    assert_disjoint,
    digest,
    file_hash,
    load_config,
    write_json,
)


def assign_splits(records, settings):
    if (
        settings["folds"] < 3
        or settings["valid_fold"] == settings["test_fold"]
        or not 0 <= settings["valid_fold"] < settings["folds"]
        or not 0 <= settings["test_fold"] < settings["folds"]
    ):
        raise ValueError("Distinct validation/test folds are required")
    labels = [f"{r['task']}:{r['truth']}" for r in records]
    groups = [r["group"] for r in records]
    splitter = StratifiedGroupKFold(
        n_splits=settings["folds"],
        shuffle=True,
        random_state=settings["seed"],
    )
    assigned = {}
    for fold, (_, indices) in enumerate(splitter.split(np.zeros(len(records)), labels, groups)):
        split = (
            "test"
            if fold == settings["test_fold"]
            else "valid"
            if fold == settings["valid_fold"]
            else "train"
        )
        for index in indices:
            assigned[records[index]["group"]] = split
    result = [{**r, "split": assigned[r["group"]]} for r in records]
    assert_disjoint(result)
    for task, spec in TASKS.items():
        for split in ("train", "valid", "test"):
            values = {r["truth"] for r in result if r["task"] == task and r["split"] == split}
            if values != set(range(spec["classes"])):
                raise ValueError(f"Missing grade in {task}/{split}; review split before training")
    return result


def prepare(config):
    settings = config["data"]
    print("Preparing smartphone data; original ZIPs remain read-only", flush=True)
    root, output = Path(settings["root"]), Path(settings["output"])
    output.mkdir(parents=True, exist_ok=False)
    cache = output / "crops"
    cache.mkdir()
    archives = {
        p.name: p
        for p in root.glob("*/*/*/*/*.zip")
        if p.name in {"TS.zip", "VS.zip", "TL.zip", "VL.zip"}
    }
    if set(archives) != {"TS.zip", "VS.zip", "TL.zip", "VL.zip"}:
        raise ValueError("Original TS/VS/TL/VL archives are required")
    annotations = collections.defaultdict(list)
    excluded = collections.Counter()
    sources = []
    for name in ("TL.zip", "VL.zip"):
        print(f"Reading smartphone labels: {name}", flush=True)
        sources.append({"archive": name, "sha256": file_hash(archives[name])})
        with zipfile.ZipFile(archives[name]) as bundle:
            for member in sorted(bundle.namelist()):
                parts = Path(member).stem.split("_")
                if len(parts) != 4 or parts[1] != "03" or int(parts[3]) not in range(1, 7):
                    continue
                label = json.loads(bundle.read(member))
                images = label["images"]
                if images["device"] != 2 or images["facepart"] != int(parts[3]):
                    raise ValueError("Source smartphone device/facepart metadata mismatch")
                annotations[(parts[0], label["info"]["filename"])].append(label)
    records, photo_hashes = [], {}
    parents = {subject: subject for subject, _ in annotations}

    def find(subject):
        while parents[subject] != subject:
            parents[subject] = parents[parents[subject]]
            subject = parents[subject]
        return subject

    # Both byte-identical and decoded-pixel-identical photos link subject groups.
    duplicate_owners = {}
    for name in ("TS.zip", "VS.zip"):
        archive = archives[name]
        sources.append(
            {
                "archive": name,
                "bytes": archive.stat().st_size,
                "integrity": "SHA-256 of every selected image and decoded pixel array in records",
            }
        )
        with zipfile.ZipFile(archive) as bundle:
            print(f"Preparing smartphone crops: {name}", flush=True)
            for member in sorted(bundle.namelist()):
                parts = Path(member).stem.split("_")
                if len(parts) != 3 or parts[1] != "03":
                    continue
                key = parts[0], Path(member).name
                if key not in annotations:
                    continue
                if key in photo_hashes:
                    raise ValueError("Duplicate photo key across source archives")
                raw = bundle.read(member)
                image = cv2.imdecode(np.frombuffer(raw, dtype=np.uint8), cv2.IMREAD_COLOR)
                if image is None:
                    raise ValueError("Original smartphone image failed decoding")
                image_hash = hashlib.sha256(raw).hexdigest()
                pixel_hash = hashlib.sha256(image.tobytes()).hexdigest()
                photo_hashes[key] = image_hash
                for kind, hashed in (("bytes", image_hash), ("pixels", pixel_hash)):
                    prior = duplicate_owners.setdefault((kind, hashed), parts[0])
                    parents[find(parts[0])] = find(prior)
                for label in annotations[key]:
                    meta = label["images"]
                    if [image.shape[1], image.shape[0]] != [meta["width"], meta["height"]]:
                        raise ValueError("Original image dimensions differ from annotation")
                    part = meta["facepart"]
                    candidates = []
                    for task, spec in TASKS.items():
                        for area, faceparts in spec["areas"].items():
                            if part not in faceparts:
                                continue
                            values = [v for k, v in label["annotations"].items() if area in k]
                            if len(values) != 1:
                                raise ValueError("Ambiguous task/ROI label")
                            value = values[0]
                            if value is None:
                                excluded[f"{task}:missing_label"] += 1
                                continue
                            if type(value) is not int or not 0 <= value < spec["classes"]:
                                raise ValueError("Grade does not match declared classifier head")
                            candidates.append((task, area, value))
                    if not candidates:
                        continue
                    try:
                        bounds = crop_bounds(meta["bbox"], image.shape[1], image.shape[0], part)
                    except (ValueError, TypeError):
                        excluded["invalid_roi"] += len(candidates)
                        continue
                    x1, y1, x2, y2 = bounds
                    crop = cv2.resize(
                        image[y1:y2, x1:x2], (256, 256), interpolation=cv2.INTER_LINEAR
                    )
                    ok, encoded = cv2.imencode(".jpg", crop)
                    if not ok:
                        raise ValueError("ROI JPEG encoding failed")
                    roi_id = digest([key, part])
                    relative = f"crops/{roi_id}.jpg"
                    (output / relative).write_bytes(encoded.tobytes())
                    for task, area, truth in candidates:
                        records.append(
                            dict(
                                id=f"{roi_id}:{task}",
                                subject=parts[0],
                                device=3,
                                task=task,
                                area=area,
                                facepart=part,
                                truth=truth,
                                path=relative,
                                crop_sha256=hashlib.sha256(encoded).hexdigest(),
                                image_sha256=image_hash,
                                pixel_sha256=pixel_hash,
                            )
                        )
                if len(photo_hashes) % 200 == 0:
                    print(
                        json.dumps(
                            {"prepared_photos": len(photo_hashes), "labelled_rois": len(records)}
                        ),
                        flush=True,
                    )
    missing = len(set(annotations) - set(photo_hashes))
    if missing:
        raise ValueError(f"Missing original smartphone photos: {missing}")
    if len({r["id"] for r in records}) != len(records):
        raise ValueError("Repeated labelled ROI")
    records = assign_splits([{**r, "group": find(r["subject"])} for r in records], settings)
    summary = {
        task: {
            split: {
                "n": len(
                    selected := [r for r in records if r["task"] == task and r["split"] == split]
                ),
                "subjects": len({r["subject"] for r in selected}),
                "grade_support": [
                    sum(r["truth"] == grade for r in selected) for grade in range(spec["classes"])
                ],
            }
            for split in ("train", "valid", "test")
        }
        for task, spec in TASKS.items()
    }
    manifest = dict(
        schema="nia-smartphone-data-v1",
        preprocessing=PREPROCESSING,
        root=str(output.resolve()),
        settings=settings,
        sources=sources,
        split_method="StratifiedGroupKFold(task:grade), subject+exact-photo groups",
        source_photo_count=len(photo_hashes),
        excluded=dict(excluded),
        summary=summary,
        records=records,
    )
    manifest["fingerprint"] = digest(manifest)
    write_json(output / "manifest.json", manifest)
    write_json(
        output / "summary.json",
        {
            k: manifest[k]
            for k in (
                "schema",
                "fingerprint",
                "summary",
                "excluded",
                "source_photo_count",
                "split_method",
            )
        },
    )
    print(json.dumps(manifest["summary"]), flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    args = parser.parse_args()
    cv2.setNumThreads(1)
    prepare(load_config(args.config))


if __name__ == "__main__":
    main()

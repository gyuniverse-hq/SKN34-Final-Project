"""Official split/AI-Hub annotation adapter. Reject unknown or ambiguous labels."""

import csv
import json
import math
import re
from pathlib import Path

from .catalog import TASKS
from .engine import sha256

DESCRIPTOR = re.compile(r"Sub_(\d+)_Equ_([123])_Angle_(\d+)_Area_(\d+)(?:\.(?:jpg|png))?$")
DEVICES = {"1": "DSLR", "2": "tablet", "3": "smartphone"}


def inside(root, relative):
    path = (root / relative).resolve(strict=True)
    if not path.is_relative_to(root.resolve()):
        raise ValueError("Path escapes dataset directory")
    return path


def read_split(path):
    data = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(data, dict) or any(not isinstance(v, list) for v in data.values()):
        raise ValueError("Official split must be {analysis_area: [Sub_..._Area_...]} JSON")
    for entries in data.values():
        for entry in entries:
            if not isinstance(entry, str) or not DESCRIPTOR.fullmatch(entry):
                raise ValueError("Unknown official split descriptor; explicit adapter required")
        if len(entries) != len(set(entries)):
            raise ValueError("Repeated sample in official split")
    return data


def people(split):
    return {DESCRIPTOR.fullmatch(entry)[1] for entries in split.values() for entry in entries}


def annotation_selection(root, directory, model, areas):
    """Select original labelled ROIs without pretending that they form an official test split."""
    folder = inside(root, directory)
    if not folder.is_dir() or not folder.is_relative_to((root / "label").resolve()):
        raise ValueError("Original annotations must be inside dataset/label/")
    selected = {area: [] for area in areas}
    mode = TASKS[model["task"]][0]
    for file in sorted(folder.rglob("*.json")):
        file = inside(root, file.relative_to(root))
        match = re.fullmatch(r"(\d+)_([123])_(\d+)_(\d+)\.json", file.name)
        if not match:
            raise ValueError(f"Unknown original annotation filename: {file.name}")
        subject, equipment, angle, part = match.groups()
        annotation = json.loads(file.read_text(encoding="utf-8-sig"))
        for area in areas:
            if area not in model["areas"]:
                raise ValueError("Area unavailable in checkpoint")
            parts = model["areas"][area]
            if not isinstance(parts, list):
                parts = [parts]
            if int(part) in parts and any(area in key for key in annotation.get("annotations" if mode == "class" else "equipment", {})):
                selected[area].append(f"Sub_{subject}_Equ_{equipment}_Angle_{angle}_Area_{part}")
    if any(len(entries) != len(set(entries)) for entries in selected.values()):
        raise ValueError("Duplicate original annotation descriptor")
    return selected


def prepare_dataset(request, model, allowed_roots, metadata_evidence=None):
    root = Path(request["dataset_root"]).resolve(strict=True)
    if not any(root.is_relative_to(Path(r).resolve()) for r in allowed_roots):
        raise ValueError("Dataset root is outside the server-configured dataset_roots")
    areas = request.get("areas") or list(model["areas"])
    if not isinstance(areas, list) or len(set(areas)) != len(areas):
        raise ValueError("areas must be a unique list")
    if request.get("test_split") and request.get("labels_directory"):
        raise ValueError("Choose a test split OR original annotation directory")
    if request.get("test_split"):
        test_path = inside(root, request["test_split"])
        test = read_split(test_path)
        hashes = {"test_split": sha256(test_path)}
        selection_source = "official_split"
    elif request.get("labels_directory"):
        test = annotation_selection(root, request["labels_directory"], model, areas)
        hashes = {}
        selection_source = "original_annotations_without_official_test_split"
    else:
        raise ValueError("Connect an official split or original annotation directory")
    audit = {"status": "unverified", "overlap_person_ids": [], "comparisons": {}}
    test_people = people(test)
    comparison_sets = {}
    for name in ("train", "val"):
        path = request.get(f"{name}_split")
        if path:
            file = inside(root, path)
            comparison_sets[name] = people(read_split(file))
            hashes[f"{name}_split"] = sha256(file)
    if comparison_sets:
        overlaps = set()
        for name, ids in comparison_sets.items():
            common = test_people & ids
            audit["comparisons"][f"{name}_test"] = len(common)
            overlaps.update(common)
        audit["overlap_person_ids"] = sorted(overlaps)
        audit["status"] = "overlap" if overlaps else (
            "no_overlap" if len(comparison_sets) == 2 else "unverified")
    audit["independent_global_validation"] = False
    metadata = {}
    if request.get("metadata_csv"):
        if not metadata_evidence:
            raise ValueError("Server metadata_evidence is required for demographic breakdowns")
        file = inside(root, request["metadata_csv"])
        hashes["metadata_csv"] = sha256(file)
        with file.open(encoding="utf-8-sig", newline="") as handle:
            for row in csv.DictReader(handle):
                key = row["sample_id"]
                if key in metadata:
                    raise ValueError("Duplicate metadata sample_id")
                metadata[key] = {k: row[k] for k in ("age_group", "skin_tone", "population") if row.get(k)}
    mode, classes, _, _ = TASKS[model["task"]]
    records = []
    annotation_hash = []
    for area in areas:
        if area not in model["areas"] or area not in test:
            raise ValueError(f"Area unavailable in checkpoint or split: {area}")
        for entry in test[area]:
            subject, equipment, angle, part = DESCRIPTOR.fullmatch(entry).groups()
            device = DEVICES[equipment]
            if request.get("device") and request["device"] != device:
                continue
            relative = f"{equipment}/{subject}/{subject}_{equipment}_{angle}_{part}"
            label_path = inside(root, f"label/{relative}.json")
            label = json.loads(label_path.read_text(encoding="utf-8-sig"))
            annotation_hash.append([str(label_path.relative_to(root)), sha256(label_path)])
            expected_parts = model["areas"][area]
            if not isinstance(expected_parts, list):
                expected_parts = [expected_parts]
            if label["images"]["facepart"] != int(part) or int(part) not in expected_parts:
                raise ValueError(f"Annotation ROI differs from verified checkpoint ROI: {entry}")
            values = [v for k, v in label["annotations" if mode == "class" else "equipment"].items() if area in k]
            if len(values) != 1:
                raise ValueError(f"Missing or ambiguous label: {entry}, {area}")
            value = values[0]
            if type(value) not in (int, float) or not math.isfinite(value):
                raise ValueError(f"Invalid original label: {entry}")
            if mode == "class" and (int(value) != value or not 0 <= value < classes):
                raise ValueError(f"Grade does not match checkpoint output head: {entry}")
            if mode == "class":
                value = int(value)
            crop = root / f"cropped_img/{relative}.jpg"
            precropped = crop.is_file()
            image_path = inside(root, f"cropped_img/{relative}.jpg" if precropped else
                                f"img/{equipment}/{subject}/{label['info']['filename']}")
            if not precropped and label["images"].get("bbox") is None:
                raise ValueError(f"Missing ROI; sample cannot be silently skipped: {entry}")
            records.append(dict(id=entry, area=area, device=device, truth=value,
                                path=image_path, bbox=label["images"].get("bbox"),
                                precropped=precropped, **metadata.get(entry, {})))
    if not records:
        raise ValueError("No labelled samples match the selected settings")
    return records, dict(root=str(root), files=hashes, annotations=annotation_hash,
                         selection_source=selection_source,
                         metadata_evidence=metadata_evidence, leakage=audit)

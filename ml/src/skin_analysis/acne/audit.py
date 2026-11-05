"""Inspect ZIPs one image at a time; retain original files and detailed annotations."""

import argparse
import hashlib
import io
import re
import zipfile
from collections import Counter, defaultdict
from pathlib import Path, PurePosixPath

import imagehash
import numpy as np
from PIL import Image, ImageOps

from .common import CLASSES, digest, file_hash, load_config, write_json


class UnionFind:
    def __init__(self, count):
        self.parent = list(range(count))

    def find(self, index):
        while self.parent[index] != index:
            self.parent[index] = self.parent[self.parent[index]]
            index = self.parent[index]
        return index

    def join(self, a, b):
        a, b = self.find(a), self.find(b)
        self.parent[max(a, b)] = min(a, b)


def members(archive, suffix):
    result = {}
    for info in archive.infolist():
        if info.is_dir():
            continue
        name = PurePosixPath(info.filename.lstrip("/"))
        if ".." in name.parts or name.suffix.lower() != suffix or name.stem in result:
            raise ValueError(f"Unexpected or ambiguous ZIP member: {info.filename}")
        result[name.stem] = info.filename
    return result


def read_annotation(raw, stem, disease, view):
    import json

    annotations = json.loads(raw)["annotations"]
    if len(annotations) != 1:
        raise ValueError("Expected exactly one image annotation")
    annotation = annotations[0]
    photo = annotation["photograph"]
    if (annotation["identifier"] != stem or PurePosixPath(photo["file_path"]).stem != stem
            or annotation["diagnosis_info"]["diagnosis_name"] != disease
            or PurePosixPath(photo["file_path"]).parts[:2] != (disease, view)):
        raise ValueError("JSON/image/class/view mapping mismatch")
    return annotation


def group_records(records, distance):
    """Source-prefix semantics are UNVERIFIED; also group all perceptually close images."""
    union = UnionFind(len(records))
    owners = {}
    exact = defaultdict(list)
    near_pairs = []
    for i, row in enumerate(records):
        candidate = re.sub(r"_P\d+_L\d+$", "", row["identifier"])
        row["candidate_source_prefix"] = candidate
        for kind, value in (("candidate", candidate), ("pixel", row["pixel_sha256"]),
                            ("bytes", row["sha256"])):
            key = (kind, value)
            if key in owners:
                union.join(i, owners[key])
            owners.setdefault(key, i)
        exact[row["pixel_sha256"]].append(i)
    hashes = [int(row["phash"], 16) for row in records]
    for i, value in enumerate(hashes):
        for j in range(i):
            delta = (value ^ hashes[j]).bit_count()
            if delta <= distance:
                union.join(i, j)
                near_pairs.append({"a": records[j]["id"], "b": records[i]["id"],
                                   "distance": delta})
    conflicts = {union.find(i) for group in exact.values()
                 if len({records[i]["label"] for i in group}) > 1 for i in group}
    audit_groups = {union.find(i) for i, r in enumerate(records)
                    if r["original_split"] == "Validation"}
    duplicates = []
    seen = set()
    for i, row in enumerate(records):
        root = union.find(i)
        row["group_id"] = f"group-{root:06d}"
        row["split"] = "pending"
        if root in conflicts:
            row.update(split="quarantine", exclusion_reason="conflicting_exact_image_labels")
        elif row["original_split"] == "Validation":
            row["split"] = "official_audit"
        elif root in audit_groups:
            row.update(split="quarantine", exclusion_reason="group_overlaps_official_audit")
        # Keep one same-label copy per content/split; never delete the original.
        content = (row["pixel_sha256"], row["split"])
        if row["split"] != "quarantine" and content in seen:
            row.update(split="quarantine", exclusion_reason="duplicate_content")
        seen.add(content)
    for group in exact.values():
        if len(group) > 1:
            duplicates.append([records[i]["id"] for i in group])
    return {"exact_duplicate_groups": duplicates, "near_pairs": near_pairs,
            "group_identity_status": "candidate_prefix_and_similarity_not_verified_person_id"}


def split_groups(records, seed, minimum):
    """Choose whole groups using label/age/gender/prefix metadata only, never model scores."""
    eligible = [r for r in records if r["split"] == "pending"]
    group_ids = sorted({r["group_id"] for r in eligible})
    if len(group_ids) < 20:
        raise ValueError("Too few groups after quarantine")
    categories = sorted({f"{r['label']}:{key}:{r[key]}" for r in eligible
                         for key in ("age_range", "gender", "series")})
    indices = {value: i + 3 for i, value in enumerate(categories)}
    vectors = np.zeros((len(group_ids), len(categories) + 3))
    lookup = {value: i for i, value in enumerate(group_ids)}
    for row in eligible:
        vector = vectors[lookup[row["group_id"]]]
        vector[0] += 1
        vector[1 + row["label"]] += 1
        for key in ("age_range", "gender", "series"):
            vector[indices[f"{row['label']}:{key}:{row[key]}"]] += 1
    ratios = np.array([.7, .15, .15])
    targets = ratios[:, None] * vectors.sum(axis=0)
    rng = np.random.default_rng(seed)
    best = None
    for _ in range(1024):
        order = rng.permutation(len(group_ids))
        cuts = [int(.7 * len(order)), int(.85 * len(order))]
        chunks = np.split(order, cuts)
        actual = np.stack([vectors[chunk].sum(axis=0) for chunk in chunks])
        if (actual[:, 1:3] < minimum).any():
            continue
        weights = np.ones(vectors.shape[1])
        weights[:3] = 10
        score = float((((actual - targets) ** 2 / np.maximum(targets, 1)) * weights).sum())
        if best is None or score < best[0]:
            best = (score, chunks)
    if best is None:
        raise ValueError("Unable to meet both-class support minima in whole-group splits")
    assignment = {group_ids[i]: split for split, chunk in
                  zip(("train", "valid", "test"), best[1], strict=True) for i in chunk}
    for row in eligible:
        row["split"] = assignment[row["group_id"]]
    return {"algorithm": "metadata-balanced-whole-groups-v1", "seed": seed,
            "candidates": 1024, "target_ratios": ratios.tolist(), "objective": best[0]}


def audit(config):
    settings = config["data"]
    root, output = Path(settings["root"]), Path(settings["output"])
    if (output / "manifest.json").exists():
        raise FileExistsError("Audit is immutable; select a new data.output to rerun")
    records, archives, inventory = [], [], []
    for path in sorted(root.rglob("*.zip")):
        with zipfile.ZipFile(path) as source:
            inventory.append({"path": str(path.relative_to(root)), "files":
                              sum(not i.is_dir() for i in source.infolist())})
    for original_split, image_prefix, label_prefix in (
            ("Training", "TS", "TL"), ("Validation", "VS", "VL")):
        for disease, label in CLASSES.items():
            image_paths = list(root.rglob(f"{image_prefix}_{disease}_정면.zip"))
            label_paths = list(root.rglob(f"{label_prefix}_{disease}_정면.zip"))
            if len(image_paths) != 1 or len(label_paths) != 1:
                raise ValueError("Exactly one frontal image/label archive per split/class required")
            image_path, label_path = image_paths[0], label_paths[0]
            for path in (image_path, label_path):
                archives.append({"path": str(path.relative_to(root)), "sha256": file_hash(path)})
            with zipfile.ZipFile(image_path) as images, zipfile.ZipFile(label_path) as labels:
                image_members, label_members = members(images, ".png"), members(labels, ".json")
                if image_members.keys() != label_members.keys():
                    raise ValueError("Image/annotation member sets differ")
                for stem in sorted(image_members):
                    a = read_annotation(labels.read(label_members[stem]), stem, disease, "정면")
                    raw = images.read(image_members[stem])  # ZIP CRC checked by ZipFile.read.
                    with Image.open(io.BytesIO(raw)) as image:
                        if image.format != "PNG" or image.size != (
                                a["photograph"]["width"], a["photograph"]["height"]):
                            raise ValueError("Image dimensions/format differ from JSON")
                        image.load()
                        rgb = ImageOps.exif_transpose(image).convert("RGB")
                        pixel_hash = hashlib.sha256(
                            str(rgb.size).encode() + rgb.tobytes()).hexdigest()
                        phash = str(imagehash.phash(rgb))
                    metadata = a["generated_parameters"]
                    relative = str(image_path.relative_to(root))
                    records.append({
                        "id": relative + "#" + image_members[stem], "identifier": stem,
                        "archive": relative, "member": image_members[stem],
                        "annotation_archive": str(label_path.relative_to(root)),
                        "annotation_member": label_members[stem], "annotation": a,
                        "original_split": original_split, "label": label,
                        "age_range": metadata.get("age_range", "N/A"),
                        "gender": metadata.get("gender", "N/A"),
                        "series": stem.split("_")[0], "sha256": hashlib.sha256(raw).hexdigest(),
                        "pixel_sha256": pixel_hash, "phash": phash,
                    })
            print(f"Audited {original_split}/{disease}: {len(image_members)} images", flush=True)
    grouping = group_records(records, settings["phash_distance"])
    splitting = split_groups(records, settings["seed"], settings["min_eval_per_class"])
    distributions = {}
    for split in ("train", "valid", "test", "official_audit", "quarantine"):
        rows = [r for r in records if r["split"] == split]
        distributions[split] = {
            "images": len(rows), "classes": dict(Counter(str(r["label"]) for r in rows)),
            "groups": len({r["group_id"] for r in rows}),
            "label_age": dict(Counter(f"{r['label']}:{r['age_range']}" for r in rows)),
            "label_series": dict(Counter(f"{r['label']}:{r['series']}" for r in rows)),
        }
    report = {"inventory": inventory, "distributions": distributions, "grouping": grouping,
              "splitting": splitting, "warnings": [
                  "Synthetic-only research; no real smartphone generalization established",
                  "No verified person/source identity: similarity groups are a leakage mitigation",
                  "Official validation has age/series shift; not used for model selection",
                  "Mask paths retained; actual segmentation files are absent from local archives",
                  "Commercial service/export/redistribution rights remain unconfirmed",
              ]}
    manifest = {
        "schema": "acne-manifest-v1", "root": str(root.resolve()), "training_ready": True,
        "classes": CLASSES, "archives": archives, "records": records,
        "grouping": {"phash_distance": settings["phash_distance"],
                     "person_independence_verified": False},
        "splitting": splitting, "limitations": report["warnings"],
    }
    manifest["fingerprint"] = digest(manifest)
    write_json(output / "report.json", report)
    write_json(output / "manifest.json", manifest)
    print(distributions, flush=True)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", default=None)
    args = parser.parse_args()
    audit(load_config(args.config) if args.config else load_config())


if __name__ == "__main__":
    main()

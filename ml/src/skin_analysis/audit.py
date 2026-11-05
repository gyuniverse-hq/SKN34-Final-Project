"""Audit Roboflow multiclass CSV exports without inventing negative labels."""

import argparse
import csv
import hashlib
import random
from collections import Counter, defaultdict
from copy import deepcopy
from pathlib import Path

import imagehash
import numpy as np
from PIL import Image, ImageOps

from .config import (
    DEFAULT_CONFIG,
    PUBLIC_CLASSES,
    SPLITS,
    class_key,
    digest,
    load_config,
    positive_support_minima,
    read_json,
    write_json,
)
from .preparation import quarantine_records, resplit_records


class DataContractError(ValueError):
    """The dataset does not satisfy the image/label contract."""


def safe_image_path(root: Path, relative: str) -> Path:
    path = (root / relative).resolve()
    if not path.is_relative_to(root.resolve()) or not path.is_file():
        raise DataContractError(f"Missing or unsafe image path: {relative}")
    return path


def load_table(path: Path) -> list[dict]:
    if not path.is_file():
        return []
    with path.open(encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        if not reader.fieldnames or len(set(reader.fieldnames)) != len(reader.fieldnames):
            raise DataContractError(f"Invalid CSV header: {path}")
        rows = list(reader)
    if any(None in row for row in rows):
        raise DataContractError(f"CSV contains extra fields: {path}")
    return rows


def parse_label(value: str | None, location: str) -> int | None:
    if value is None or value.strip().casefold() in {"", "unknown", "null", "nan", "na", "?"}:
        return None
    try:
        number = float(value)
    except ValueError as exc:
        raise DataContractError(f"Non-binary label at {location}") from exc
    if number not in (0.0, 1.0):
        raise DataContractError(f"Non-binary label at {location}: {value}")
    return int(number)


def load_export(root: Path) -> tuple[list[str], list[dict], str]:
    classes = None
    records = []
    csv_hashes = {}
    for split in SPLITS:
        candidates = [root / split / name for name in ("_classes.csv", "classes.csv")]
        found = [path for path in candidates if path.is_file()]
        if len(found) != 1:
            raise DataContractError(f"Expected one _classes.csv or classes.csv in {root / split}")
        csv_path = found[0]
        csv_hashes[split] = hashlib.sha256(csv_path.read_bytes()).hexdigest()
        with csv_path.open(encoding="utf-8-sig", newline="") as handle:
            reader = csv.reader(handle)
            headers = next(reader, [])
        if not headers or headers[0].strip().casefold() != "filename":
            raise DataContractError(f"Expected filename as first CSV column: {csv_path}")
        split_classes = [name.strip() for name in headers[1:]]
        keys = [class_key(name) for name in split_classes]
        if not keys or any(not key for key in keys) or len(set(keys)) != len(keys):
            raise DataContractError(f"Empty or ambiguous class names: {csv_path}")
        if classes is None:
            classes = split_classes
        elif classes != split_classes:
            raise DataContractError(f"Class names/order differ between splits: {csv_path}")
        rows = load_table(csv_path)
        if not rows:
            raise DataContractError(f"Empty split: {split}")
        seen = set()
        for row in rows:
            filename = (row[headers[0]] or "").strip()
            if not filename or filename in seen:
                raise DataContractError(f"Empty or repeated filename in {split}: {filename}")
            seen.add(filename)
            path = safe_image_path(root / split, filename)
            relative = path.relative_to(root.resolve()).as_posix()
            try:
                with Image.open(path) as source:
                    image = ImageOps.exif_transpose(source).convert("RGB")
                    pixel_bytes = str(image.size).encode() + image.tobytes()
                    pixel_hash = hashlib.sha256(pixel_bytes).hexdigest()
                    perceptual_hash = str(imagehash.phash(image))
                    size = list(image.size)
            except (OSError, ValueError) as exc:
                raise DataContractError(f"Unreadable image: {relative}") from exc
            labels = [parse_label(row[name], f"{relative}:{name}") for name in headers[1:]]
            records.append(
                {
                    "path": relative,
                    "split": split,
                    "original_split": split,
                    "labels": labels,
                    "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                    "pixel_sha256": pixel_hash,
                    "phash": perceptual_hash,
                    "size": size,
                    "image_type": "unknown",
                    "labels_reviewed": False,
                }
            )
    return classes, records, digest(csv_hashes)


def apply_metadata(records: list[dict], metadata: list[dict]) -> list[str]:
    by_path = {record["path"]: record for record in records}
    seen = set()
    for row in metadata:
        path = row.get("path", "")
        if path not in by_path or path in seen:
            raise DataContractError(f"Unknown/repeated metadata path: {path}")
        seen.add(path)
        record = by_path[path]
        for field in ("person_id", "session_id", "source_id", "notes"):
            record[field] = (row.get(field) or "").strip()
        image_type = row.get("image_type") or "unknown"
        if image_type not in {"full_face", "partial_face", "skin_closeup", "non_face", "unknown"}:
            raise DataContractError(f"Invalid image_type for {path}")
        record["image_type"] = image_type
        reviewed = (row.get("labels_reviewed") or "").casefold()
        if reviewed not in {"", "true", "false"}:
            raise DataContractError(f"Invalid labels_reviewed for {path}")
        record["labels_reviewed"] = reviewed == "true" and bool(record["notes"])
    return [record["path"] for record in records if not record.get("person_id")]


def group_and_deduplicate(records: list[dict], reviews: list[dict], distance: int) -> tuple:
    parent = {record["path"]: record["path"] for record in records}
    duplicate_parent = dict(parent)

    def find(key, table=parent):
        while table[key] != key:
            table[key] = table[table[key]]
            key = table[key]
        return key

    def union(a, b, table=parent):
        a, b = find(a, table), find(b, table)
        table[max(a, b)] = min(a, b)

    buckets = {}
    for record in records:
        for field in ("sha256", "pixel_sha256", "person_id", "session_id", "source_id"):
            value = record.get(field)
            if value:
                key = (field, value)
                if key in buckets:
                    union(record["path"], buckets[key])
                    if field in ("sha256", "pixel_sha256"):
                        union(record["path"], buckets[key], duplicate_parent)
                buckets[key] = record["path"]
    issues = []
    decisions = {}
    for row in reviews:
        a, b = row.get("path_a"), row.get("path_b")
        key = tuple(sorted((a or "", b or "")))
        if a not in parent or b not in parent or a == b or key in decisions:
            raise DataContractError(f"Invalid/repeated duplicate review: {key}")
        decision = row.get("decision")
        if decision not in {"duplicate", "distinct"} or not row.get("notes"):
            raise DataContractError(f"Review needs decision and notes: {key}")
        decisions[key] = decision
        if decision == "duplicate":
            union(a, b)
            union(a, b, duplicate_parent)
    # Confirmed perceptual duplicates must not inflate support either. Person/session grouping
    # alone does not delete distinct photos of the same person.
    reviewed_groups = defaultdict(list)
    for record in records:
        reviewed_groups[find(record["path"], duplicate_parent)].append(record)
    kept, duplicates = [], []
    for group in reviewed_groups.values():
        ordered = sorted(group, key=lambda r: r["path"])
        kept.append(ordered[0])
        if len(group) > 1:
            duplicates.append([r["path"] for r in ordered])
            if len({tuple(r["labels"]) for r in ordered}) > 1:
                issues.append(f"Conflicting labels on confirmed duplicates: {duplicates[-1]}")
    near_candidates = []
    hashes = [(record, int(record["phash"], 16)) for record in kept]
    for index, (a, ha) in enumerate(hashes):
        for b, hb in hashes[index + 1 :]:
            if find(a["path"], duplicate_parent) == find(b["path"], duplicate_parent):
                continue
            hamming = (ha ^ hb).bit_count()
            if hamming <= distance:
                key = tuple(sorted((a["path"], b["path"])))
                if key not in decisions:
                    near_candidates.append(
                        {"path_a": key[0], "path_b": key[1], "distance": hamming}
                    )
    original_group_splits = defaultdict(set)
    for record in records:
        record["group_id"] = find(record["path"])
        original_group_splits[record["group_id"]].add(record["split"])
    leakage = {
        group: sorted(splits) for group, splits in original_group_splits.items() if len(splits) > 1
    }
    return sorted(kept, key=lambda r: r["path"]), duplicates, near_candidates, leakage, issues


def distribution(records: list[dict], classes: list[str], normal_index: int | None) -> dict:
    result = {}
    for split in SPLITS:
        subset = [record for record in records if record["split"] == split]
        counts = []
        for index, name in enumerate(classes):
            column = [record["labels"][index] for record in subset]
            counts.append(
                {
                    "class": name,
                    "positive": column.count(1),
                    "negative": column.count(0),
                    "unknown": column.count(None),
                    "positive_ratio": column.count(1) / len(subset) if subset else None,
                }
            )
        cardinality = Counter(sum(value == 1 for value in record["labels"]) for record in subset)
        compound = sum(
            sum(value == 1 for index, value in enumerate(record["labels"]) if index != normal_index)
            >= 2
            for record in subset
        )
        normal_only = sum(
            normal_index is not None
            and record["labels"][normal_index] == 1
            and sum(value == 1 for value in record["labels"]) == 1
            for record in subset
        )
        normal_conflicts = [
            record["path"]
            for record in subset
            if normal_index is not None
            and record["labels"][normal_index] == 1
            and sum(value == 1 for value in record["labels"]) > 1
        ]
        binary = np.array([[int(value == 1) for value in record["labels"]] for record in subset])
        cooccurrence = (binary.T @ binary).tolist() if subset else []
        result[split] = {
            "images": len(subset),
            "groups": len({r["group_id"] for r in subset}),
            "classes": counts,
            "positive_cardinality": dict(sorted(cardinality.items())),
            "compound_images": compound,
            "normal_only": normal_only,
            "normal_conflicts": normal_conflicts,
            "cooccurrence": cooccurrence,
            "image_types": dict(Counter(record["image_type"] for record in subset)),
        }
    return result


def review_samples(
    records: list[dict], classes: list[str], normal_index: int | None, seed: int
) -> dict:
    rng = random.Random(seed)
    samples = {}
    for index, name in enumerate(classes):
        for value, suffix in ((1, "positive"), (0, "negative")):
            candidates = sorted(
                record["path"] for record in records if record["labels"][index] == value
            )
            samples[f"{name}:{suffix}"] = {
                "required": 20,
                "available": len(candidates),
                "paths": rng.sample(candidates, min(20, len(candidates))),
            }
    for name, candidates in {
        "compound": [
            r["path"]
            for r in records
            if sum(value == 1 for i, value in enumerate(r["labels"]) if i != normal_index) >= 2
        ],
        "normal": [
            r["path"]
            for r in records
            if normal_index is not None and r["labels"][normal_index] == 1
        ],
    }.items():
        samples[name] = {
            "required": 30,
            "available": len(candidates),
            "paths": rng.sample(sorted(candidates), min(30, len(candidates))),
        }
    return samples


def audit_dataset(config: dict) -> tuple[dict, dict | None]:
    data, settings = config["data"], config["audit"]
    report = {
        "schema_version": 1,
        "status": "blocked",
        "issues": [],
        "warnings": [],
        "public_classes_unverified": list(PUBLIC_CLASSES),
    }
    try:
        root = Path(data["root"])
        classes, all_records, csv_hash = load_export(root)
        listed = {record["path"] for record in all_records}
        extensions = set(Image.registered_extensions())
        orphan_images = sorted(
            path.relative_to(root).as_posix()
            for split in SPLITS
            for path in (root / split).rglob("*")
            if path.is_file()
            and path.suffix.casefold() in extensions
            and path.relative_to(root).as_posix() not in listed
        )
        metadata = load_table(Path(data["metadata"]))
        reviews = load_table(Path(data["duplicate_reviews"]))
        missing_person = apply_metadata(all_records, metadata)
        records, duplicates, source_near, leakage, _duplicate_issues = group_and_deduplicate(
            all_records, reviews, settings["phash_distance"]
        )
        raw_records = deepcopy(all_records)
        records, quarantined, conflicts, near = quarantine_records(
            records, all_records, duplicates, source_near, settings
        )
        issues = [f"Conflicting labels on confirmed duplicates: {paths}" for paths in conflicts]
        if orphan_images:
            issues.append("Images absent from CSV annotations require explicit review")
        evidence_path = Path(data["evidence"])
        evidence = read_json(evidence_path) if evidence_path.is_file() else {}
        normal = next(
            (i for i, name in enumerate(classes) if class_key(name) == "normal skin"), None
        )
        split_details = None
        if settings["resplit"]:
            try:
                split_details = resplit_records(
                    records,
                    settings["seed"],
                    settings=settings,
                    classes=classes,
                    normal_index=normal,
                )
            except ValueError as exc:
                issues.append(f"Resplit failed: {exc}")
        elif any(record["group_id"] in leakage for record in records):
            issues.append("Groups cross original splits; review and enable audit.resplit")
        prepared_groups = defaultdict(set)
        for record in records:
            prepared_groups[record["group_id"]].add(record["split"])
        prepared_leakage = {
            group: sorted(splits) for group, splits in prepared_groups.items() if len(splits) > 1
        }
        if prepared_leakage:
            issues.append("Prepared groups still cross split boundaries")
        stats = distribution(records, classes, normal)
        positive_minima = {
            name: positive_support_minima(
                settings, sum(record["labels"][i] == 1 for record in records)
            )
            for i, name in enumerate(classes)
        }
        samples = review_samples(records, classes, normal, settings["seed"])
        report.update(
            {
                "classes": classes,
                "unannotated_image_paths": orphan_images,
                "raw_images": len(all_records),
                "retained_images": len(records),
                "raw_distribution": distribution(raw_records, classes, normal),
                "distribution": stats,
                "positive_support_policy": settings.get("positive_support_policy", "fixed"),
                "positive_minima": positive_minima,
                "confirmed_duplicate_groups": duplicates,
                "near_duplicate_candidates": near,
                "source_near_duplicate_candidates": source_near,
                "original_split_leakage": leakage,
                "post_preparation_group_leakage": prepared_leakage,
                "quarantined_source_images": quarantined,
                "unresolved_label_conflicts": conflicts,
                "split_details": split_details,
                "review_samples": samples,
                "evidence": evidence,
                "resplit": split_details is not None,
                "resplit_requested": settings["resplit"],
                "public_class_set_matches": {class_key(c) for c in classes}
                == {class_key(c) for c in PUBLIC_CLASSES},
            }
        )
        if missing_person:
            report["warnings"].append(
                f"No person ID for {len(missing_person)} source images; identity leakage unverified"
            )
        if quarantined:
            report["warnings"].append(
                f"Quarantined {len(quarantined)} source images; files and labels unchanged. "
                "unreviewed similarity is not proof of duplication and may exclude valid examples"
            )
        report["warnings"].append("Skin-tone/global generalization requires independent evidence")
        if evidence.get("confirmed_classes") != classes:
            issues.append("Evidence must confirm every exported class in its exact order")
        for field in (
            "dataset_url",
            "rights_evidence",
            "exhaustive_negatives_evidence",
            "normal_definition_evidence",
            "full_face_evaluation_evidence",
            "label_review_evidence",
            "image_sources",
        ):
            if not isinstance(evidence.get(field), str) or not evidence[field].strip():
                issues.append(f"Missing documented evidence: {field}")
        if evidence.get("dataset_version") != 1:
            issues.append("Expected dataset_version=1")
        if evidence.get("license") != "CC-BY-4.0" or not evidence.get("license_url"):
            issues.append("Dataset license and attribution URL must be recorded")
        if normal is not None and not isinstance(evidence.get("normal_exclusive"), bool):
            issues.append("normal_exclusive must be explicitly true or false")
        if near:
            issues.append(f"Review {len(near)} unresolved perceptual duplicate candidates")
        required_paths = {path for sample in samples.values() for path in sample["paths"]}
        unreviewed = [
            r["path"] for r in records if r["path"] in required_paths and not r["labels_reviewed"]
        ]
        if unreviewed:
            issues.append(f"Label review and notes missing for {len(unreviewed)} sampled images")
        for split, info in stats.items():
            if split != "train" and info["groups"] < 2:
                issues.append(f"{split}: at least two independent evaluation groups are required")
            if info["compound_images"] < settings[f"min_compound_{split}"]:
                issues.append(f"{split}: insufficient genuine compound images")
            if info["normal_conflicts"] and evidence.get("normal_exclusive") is True:
                issues.append(f"{split}: Normal Skin conflicts with the documented definition")
            if (
                split != "train"
                and info["image_types"].get("full_face", 0) < settings["min_full_face_eval"]
            ):
                issues.append(f"{split}: insufficient verified full-face evaluation images")
            for counts in info["classes"]:
                if counts["unknown"]:
                    issues.append(
                        f"{split}:{counts['class']}: unknown labels cannot become negatives"
                    )
                min_pos = positive_minima[counts["class"]][split]
                min_neg = 1 if split == "train" else settings["min_eval_negative"]
                if split != "train" and counts["positive"] < settings["min_eval_positive"]:
                    report["warnings"].append(
                        f"{split}:{counts['class']}: only {counts['positive']} positive images; "
                        "below the initial fixed support recommendation, evaluation is limited"
                    )
                if counts["positive"] < min_pos or counts["negative"] < min_neg:
                    issues.append(
                        f"{split}:{counts['class']}: insufficient positive/negative support"
                    )
        zero_unreviewed = [
            r["path"]
            for r in records
            if all(v == 0 for v in r["labels"]) and not r["labels_reviewed"]
        ]
        if zero_unreviewed:
            issues.append("All-zero annotations require explicit image review; not inferred normal")
        manifest = {
            "schema_version": 1,
            "root": str(root.resolve()),
            "classes": classes,
            "records": records,
            "source_csv_hash": csv_hash,
            "source_images_hash": digest([(r["path"], r["sha256"]) for r in all_records]),
            "evidence": evidence,
            "metadata": metadata,
            "duplicate_reviews": reviews,
            "audit_settings": settings,
            "quarantined_source_images": quarantined,
            "split_details": split_details,
        }
        # Output location is incidental; all data, evidence, reviews and audit policies are bound.
        fingerprint_data = {
            **manifest,
            "audit_settings": {key: value for key, value in settings.items() if key != "output"},
        }
        fingerprint_data.pop("root")
        manifest["fingerprint"] = digest(fingerprint_data)
        report["manifest_fingerprint"] = manifest["fingerprint"]
        report["issues"] = issues
        report["status"] = "approved" if not issues else "blocked"
        return report, manifest
    except (DataContractError, OSError, ValueError, TypeError, KeyError) as exc:
        report["issues"].append(str(exc))
        return report, None


def write_audit_summary(report: dict, manifest: dict | None, output: Path) -> None:
    """Regenerate human-readable tables with the same assignments as manifest.json."""
    classes = report.get("classes", [])
    with (output / "prepared-manifest.csv").open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.writer(handle)
        writer.writerow(["path", "original_split", "split", "group_id", *classes])
        for record in (manifest or {}).get("records", []):
            writer.writerow(
                [
                    record["path"],
                    record["original_split"],
                    record["split"],
                    record["group_id"],
                    *record["labels"],
                ]
            )
    with (output / "quarantine.csv").open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.writer(handle)
        writer.writerow(["path", "original_split", "group_id", "reasons", *classes])
        for record in report.get("quarantined_source_images", []):
            writer.writerow(
                [
                    record["path"],
                    record["original_split"],
                    record["group_id"],
                    ";".join(record["reasons"]),
                    *record["labels"],
                ]
            )
    lines = [
        "# 데이터 정리 및 재분할 결과",
        "",
        f"감사 상태: **{report['status']}**. 분할 완료와 본학습 승인은 별도입니다.",
        "",
        "원본 이미지·CSV는 보존하며 실제 학습 분할은 manifest의 split 열을 사용합니다.",
        "valid는 모델 선택·임계값 조정용 검증셋, test는 최종 평가용 테스트셋입니다.",
        "",
        f"원본 {report.get('raw_images', 0):,}장 → 준비 {report.get('retained_images', 0):,}장. "
        f"검수 대기 격리 {len(report.get('quarantined_source_images', [])):,}장.",
        f"양성 표본 정책: `{report.get('positive_support_policy', 'unknown')}`.",
        "",
        "| 분할 | 원본 이미지 | 준비 이미지 | 준비 비율 | 복합 사례 | 독립 그룹 |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    stats = report.get("distribution", {})
    for split, info in stats.items():
        original = report["raw_distribution"][split]["images"]
        ratio = info["images"] / max(report["retained_images"], 1)
        lines.append(
            f"| {split} | {original} | {info['images']} | {ratio:.1%} | "
            f"{info['compound_images']} | {info['groups']} |"
        )
    if stats:
        lines.extend(
            [
                "",
                "| 클래스 | Train 양성 | Valid 양성 | Test 양성 | 전체 양성 |",
                "|---|---:|---:|---:|---:|",
            ]
        )
        for i, name in enumerate(classes):
            counts = [stats[split]["classes"][i]["positive"] for split in SPLITS]
            lines.append(f"| {name} | " + " | ".join(map(str, [*counts, sum(counts)])) + " |")
    lines.extend(["", "## 경고 및 평가 한계", ""])
    lines.extend(f"- {warning}" for warning in report.get("warnings", []))
    lines.extend(["", "## 남은 감사 차단 사유", ""])
    lines.extend(f"- {issue}" for issue in report["issues"])
    lines.extend(
        ["", "모델 학습·성능 측정 결과가 아닙니다. 테스트 결과를 본 뒤 재분할하지 않습니다.", ""]
    )
    (output / "summary.md").write_text("\n".join(lines), encoding="utf-8")


def run_audit(config: dict) -> tuple[dict, dict | None]:
    report, manifest = audit_dataset(config)
    output = Path(config["audit"]["output"])
    write_json(output / "report.json", report)
    write_json(output / "manifest.json", manifest or {"status": "blocked"})
    write_audit_summary(report, manifest, output)
    return report, manifest


def require_approved(config: dict) -> tuple[dict, dict]:
    # Recompute from files rather than trusting an editable approval flag or stale manifest.
    report, manifest = run_audit(config)
    if report["status"] != "approved" or manifest is None:
        raise DataContractError("Training blocked by data audit: " + "; ".join(report["issues"]))
    return report, manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", default=str(DEFAULT_CONFIG))
    args = parser.parse_args()
    config = load_config(args.config)
    report, _ = run_audit(config)
    print(f"Audit {report['status']}: {Path(config['audit']['output']) / 'report.json'}")
    for issue in report["issues"]:
        print(f"- {issue}")
    raise SystemExit(0 if report["status"] == "approved" else 2)


if __name__ == "__main__":
    main()

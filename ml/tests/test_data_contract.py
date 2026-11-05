import csv
import shutil
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

from skin_analysis.audit import (
    DataContractError,
    audit_dataset,
    load_export,
    parse_label,
    require_approved,
    run_audit,
    safe_image_path,
)
from skin_analysis.config import read_json, write_json
from skin_analysis.dataset import SkinDataset


def rewrite_row(config, split, row_index, values):
    path = Path(config["data"]["root"]) / split / "_classes.csv"
    with path.open(newline="", encoding="utf-8") as handle:
        rows = list(csv.reader(handle))
    rows[row_index] = values
    with path.open("w", newline="", encoding="utf-8") as handle:
        csv.writer(handle).writerows(rows)


def test_complete_export_preserves_compound_classes(synthetic_export):
    report, manifest = audit_dataset(synthetic_export)
    assert report["status"] == "approved", report["issues"]
    assert manifest["classes"] == ["Acne", "Pores", "Normal Skin"]
    assert report["distribution"]["train"]["compound_images"] == 2
    assert report["distribution"]["train"]["classes"][0]["positive"] == 4
    dataset = SkinDataset(manifest, "train")
    image, target, index = dataset[0]
    assert image.shape == (3, 224, 224) and index == 0
    assert target.tolist() == [1, 1, 0]


def test_unknown_labels_are_not_negatives(synthetic_export):
    rewrite_row(synthetic_export, "train", 1, ["image-0.png", "", 1, 0])
    report, manifest = audit_dataset(synthetic_export)
    assert report["status"] == "blocked"
    record = next(r for r in manifest["records"] if r["path"] == "train/image-0.png")
    assert record["labels"][0] is None
    assert report["distribution"]["train"]["classes"][0]["unknown"] == 1
    with pytest.raises(DataContractError):
        SkinDataset(manifest, "train")


@pytest.mark.parametrize("value", ["2", "-1", "0.5", "inf", "bad"])
def test_nonbinary_labels_rejected(value):
    with pytest.raises(DataContractError):
        parse_label(value, "fixture")


def test_reordered_columns_rejected(synthetic_export):
    rewrite_row(synthetic_export, "valid", 0, ["filename", "Pores", "Acne", "Normal Skin"])
    with pytest.raises(DataContractError, match="Class names/order"):
        load_export(Path(synthetic_export["data"]["root"]))


def test_missing_and_unsafe_images_rejected(synthetic_export, tmp_path):
    root = Path(synthetic_export["data"]["root"])
    with pytest.raises(DataContractError):
        safe_image_path(root, "../evidence.json")
    (root / "train/image-0.png").unlink()
    report, manifest = audit_dataset(synthetic_export)
    assert report["status"] == "blocked" and manifest is None


def test_identical_image_leakage_deduplicates_and_blocks(synthetic_export):
    root = Path(synthetic_export["data"]["root"])
    shutil.copyfile(root / "train/image-0.png", root / "valid/image-0.png")
    report, _ = audit_dataset(synthetic_export)
    assert report["status"] == "blocked"
    assert report["retained_images"] == 23
    assert report["original_split_leakage"]


def test_conflicting_duplicate_labels_never_merged(synthetic_export):
    root = Path(synthetic_export["data"]["root"])
    shutil.copyfile(root / "train/image-0.png", root / "valid/image-1.png")
    report, _ = audit_dataset(synthetic_export)
    assert report["status"] == "blocked"
    assert any("Conflicting labels" in issue for issue in report["issues"])


def test_normal_conflict_blocks(synthetic_export):
    rewrite_row(synthetic_export, "train", 1, ["image-0.png", 1, 1, 1])
    report, _ = audit_dataset(synthetic_export)
    assert any("Normal Skin conflicts" in issue for issue in report["issues"])


def test_actual_single_label_data_does_not_pass(synthetic_export):
    for split in ("train", "valid", "test"):
        rewrite_row(synthetic_export, split, 1, ["image-0.png", 1, 0, 0])
        rewrite_row(synthetic_export, split, 5, ["image-4.png", 0, 1, 0])
    report, _ = audit_dataset(synthetic_export)
    assert report["status"] == "blocked"
    assert report["distribution"]["train"]["compound_images"] == 0


def test_approval_is_recomputed_not_trusted(synthetic_export):
    report, manifest = require_approved(synthetic_export)
    fingerprint = manifest["fingerprint"]
    evidence_path = Path(synthetic_export["data"]["evidence"])
    evidence = read_json(evidence_path)
    evidence["exhaustive_negatives_evidence"] = ""
    write_json(evidence_path, evidence)
    with pytest.raises(DataContractError, match="exhaustive_negatives"):
        require_approved(synthetic_export)
    assert fingerprint != audit_dataset(synthetic_export)[1]["fingerprint"]


def test_missing_export_writes_blocked_report(synthetic_export):
    synthetic_export["data"]["root"] += "-missing"
    report, manifest = run_audit(synthetic_export)
    assert report["status"] == "blocked" and manifest is None
    assert read_json(Path(synthetic_export["audit"]["output"]) / "report.json")["issues"]


def test_group_resplit_is_disjoint_and_deterministic(synthetic_export):
    root = Path(synthetic_export["data"]["root"])
    shutil.copyfile(root / "train/image-0.png", root / "valid/image-0.png")
    synthetic_export["audit"]["resplit"] = True
    _, first = audit_dataset(synthetic_export)
    _, second = audit_dataset(synthetic_export)
    assert first["fingerprint"] == second["fingerprint"]
    groups = {}
    for record in first["records"]:
        groups.setdefault(record["group_id"], set()).add(record["split"])
    assert all(len(splits) == 1 for splits in groups.values())


def test_unannotated_images_cannot_silently_disappear(synthetic_export):
    root = Path(synthetic_export["data"]["root"])
    shutil.copyfile(root / "train/image-0.png", root / "train/orphan.png")
    report, _ = audit_dataset(synthetic_export)
    assert report["status"] == "blocked"
    assert report["unannotated_image_paths"] == ["train/orphan.png"]


def test_perceptual_candidates_require_review_then_deduplicate(synthetic_export):
    root = Path(synthetic_export["data"]["root"])
    with Image.open(root / "train/image-0.png") as image:
        pixels = np.array(image)
    pixels[0, 0, 0] = (int(pixels[0, 0, 0]) + 1) % 256
    Image.fromarray(pixels).save(root / "valid/image-0.png")
    report, _ = audit_dataset(synthetic_export)
    assert report["status"] == "blocked"
    assert any(
        candidate["path_a"] == "train/image-0.png" and candidate["path_b"] == "valid/image-0.png"
        for candidate in report["near_duplicate_candidates"]
    )
    reviews = Path(synthetic_export["data"]["duplicate_reviews"])
    with reviews.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(["path_a", "path_b", "decision", "notes"])
        writer.writerow(["train/image-0.png", "valid/image-0.png", "duplicate", "Synthetic copy"])
    reviewed, _ = audit_dataset(synthetic_export)
    assert reviewed["retained_images"] == 23
    assert reviewed["original_split_leakage"]


def test_identity_metadata_groups_distinct_photos(synthetic_export):
    metadata_path = Path(synthetic_export["data"]["metadata"])
    with metadata_path.open(encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        fields, rows = reader.fieldnames, list(reader)
    rows[0]["person_id"] = "same-person"
    rows[8]["person_id"] = "same-person"
    with metadata_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)
    report, _ = audit_dataset(synthetic_export)
    assert report["status"] == "blocked" and report["retained_images"] == 24
    assert report["original_split_leakage"]

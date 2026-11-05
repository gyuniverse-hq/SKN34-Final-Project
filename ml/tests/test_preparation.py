import csv
import hashlib
import shutil
from collections import defaultdict
from copy import deepcopy
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

from skin_analysis.audit import audit_dataset, run_audit
from skin_analysis.config import positive_support_minima
from skin_analysis.preparation import quarantine_records, resplit_records


def test_conflicting_duplicates_quarantine_every_variant_without_relabeling(synthetic_export):
    root = Path(synthetic_export["data"]["root"])
    shutil.copyfile(root / "train/image-0.png", root / "valid/image-1.png")
    before = hashlib.sha256((root / "valid/_classes.csv").read_bytes()).hexdigest()
    synthetic_export["audit"]["quarantine_conflicts"] = True
    report, manifest = audit_dataset(synthetic_export)
    assert report["status"] == "approved", report["issues"]
    excluded = {record["path"]: record for record in report["quarantined_source_images"]}
    assert set(excluded) == {"train/image-0.png", "valid/image-1.png"}
    assert excluded["train/image-0.png"]["labels"] == [1, 1, 0]
    assert excluded["valid/image-1.png"]["labels"] == [1, 0, 0]
    assert not any(record["path"] in excluded for record in manifest["records"])
    assert report["retained_images"] == 22
    assert before == hashlib.sha256((root / "valid/_classes.csv").read_bytes()).hexdigest()
    assert (root / "train/image-0.png").is_file() and (root / "valid/image-1.png").is_file()


def test_unreviewed_similarity_is_quarantined_not_declared_duplicate(synthetic_export):
    root = Path(synthetic_export["data"]["root"])
    with Image.open(root / "train/image-0.png") as image:
        pixels = np.array(image)
    pixels[0, 0, 0] = (int(pixels[0, 0, 0]) + 1) % 256
    Image.fromarray(pixels).save(root / "valid/image-0.png")
    synthetic_export["audit"]["quarantine_unreviewed_similarities"] = True
    report, manifest = audit_dataset(synthetic_export)
    assert report["status"] == "approved", report["issues"]
    assert report["source_near_duplicate_candidates"]
    assert report["near_duplicate_candidates"] == []
    assert report["confirmed_duplicate_groups"] == []
    assert len(report["quarantined_source_images"]) == 2
    assert len(manifest["records"]) == 22


def test_quarantine_expands_to_entire_existing_group():
    records = [
        {
            "path": name,
            "group_id": group,
            "original_split": "train",
            "labels": [1, 0],
            "sha256": name,
        }
        for name, group in (
            ("a", "person-a"),
            ("b", "person-a"),
            ("c", "person-c"),
            ("d", "person-d"),
        )
    ]
    kept, quarantined, _, near = quarantine_records(
        records,
        records,
        [],
        [{"path_a": "a", "path_b": "c", "distance": 2}],
        {"quarantine_unreviewed_similarities": True},
    )
    assert [record["path"] for record in kept] == ["d"]
    assert {record["path"] for record in quarantined} == {"a", "b", "c"}
    assert not near


def support_fixture():
    records = [
        {
            "path": str(i),
            "group_id": f"person-{i // 2}" if i >= 20 else f"image-{i}",
            "split": "train",
            "labels": [int(i % 2 == 0), int(i < 8)],
        }
        for i in range(100)
    ]
    settings = {
        "min_eval_positive": 3,
        "min_eval_negative": 3,
        "min_compound_train": 1,
        "min_compound_valid": 1,
        "min_compound_test": 1,
    }
    return records, settings


def test_split_enforces_rare_support_and_keeps_groups_deterministically():
    records, settings = support_fixture()
    again = deepcopy(records)
    result = resplit_records(records, 42, settings=settings, classes=["common", "rare"])
    resplit_records(again, 42, settings=settings, classes=["common", "rare"])
    assert records == again
    assert result["size_tolerance"] == 1
    groups = defaultdict(set)
    for record in records:
        groups[record["group_id"]].add(record["split"])
    assert all(len(splits) == 1 for splits in groups.values())
    for split in ("train", "valid", "test"):
        labels = np.array([record["labels"] for record in records if record["split"] == split])
        minimum = 1 if split == "train" else 3
        assert (labels.sum(axis=0) >= minimum).all()
        assert ((1 - labels).sum(axis=0) >= minimum).all()
    assert sum(record["labels"][1] for record in records if record["split"] == "test") >= 3


def test_impossible_support_does_not_relax_thresholds_or_split_groups():
    records, settings = support_fixture()
    for record in records:
        if int(record["path"]) >= 6:
            record["labels"][1] = 0
    before = deepcopy(records)
    with pytest.raises(ValueError, match="Cannot split rare"):
        resplit_records(records, 42, settings=settings, classes=["common", "rare"])
    assert records == before


def test_quarantine_cannot_fabricate_missing_annotation_evidence(synthetic_export):
    from skin_analysis.config import read_json, write_json

    evidence_path = Path(synthetic_export["data"]["evidence"])
    evidence = read_json(evidence_path)
    evidence["exhaustive_negatives_evidence"] = ""
    write_json(evidence_path, evidence)
    synthetic_export["audit"].update(
        quarantine_conflicts=True, quarantine_unreviewed_similarities=True, resplit=True
    )
    report, manifest = audit_dataset(synthetic_export)
    assert manifest is not None and report["split_details"]
    assert report["status"] == "blocked"
    assert any("exhaustive_negatives_evidence" in issue for issue in report["issues"])


def test_unknown_labels_cannot_count_as_negatives_during_resplit():
    records, settings = support_fixture()
    records[0]["labels"][0] = None
    with pytest.raises(ValueError, match="incomplete"):
        resplit_records(records, 42, settings=settings, classes=["common", "rare"])


def test_proportional_policy_restores_rare_training_support_and_is_deterministic():
    records, settings = support_fixture()
    for i, record in enumerate(records):
        record["group_id"] = f"image-{i}"
        record["labels"][1] = int(i < 46)
    settings.update(positive_support_policy="proportional", min_eval_positive=20)
    again = deepcopy(records)
    result = resplit_records(records, 42, settings=settings, classes=["common", "rare"])
    resplit_records(again, 42, settings=settings, classes=["common", "rare"])
    assert records == again
    assert result["target_images"] == {"train": 70, "valid": 20, "test": 10}
    assert [sum(r["split"] == split for r in records) for split in ("train", "valid", "test")] == [
        70,
        20,
        10,
    ]
    assert [
        sum(r["labels"][1] for r in records if r["split"] == split)
        for split in ("train", "valid", "test")
    ] == [32, 9, 5]
    assert result["positive_minima"]["rare"] == {"train": 1, "valid": 9, "test": 4}


def test_audit_uses_explicit_proportional_policy_without_hiding_small_support(synthetic_export):
    synthetic_export["audit"].update(min_eval_positive=20, positive_support_policy="fixed")
    report, _ = audit_dataset(synthetic_export)
    assert any("insufficient positive/negative support" in issue for issue in report["issues"])
    synthetic_export["audit"].update(positive_support_policy="proportional", resplit=True)
    report, _ = audit_dataset(synthetic_export)
    assert report["status"] == "approved", report["issues"]
    assert any("evaluation is limited" in warning for warning in report["warnings"])


def test_invalid_support_policy_and_impossible_tiny_class_are_rejected():
    with pytest.raises(ValueError, match="Unknown positive_support_policy"):
        positive_support_minima({"positive_support_policy": "typo"}, 46)
    records, settings = support_fixture()
    settings["positive_support_policy"] = "proportional"
    for i, record in enumerate(records):
        record["labels"][1] = int(i < 2)
    before = deepcopy(records)
    with pytest.raises(ValueError, match="Cannot split rare"):
        resplit_records(records, 42, settings=settings, classes=["common", "rare"])
    assert records == before


def test_exported_split_table_and_summary_follow_current_manifest(synthetic_export):
    synthetic_export["audit"].update(positive_support_policy="proportional", resplit=True)
    report, manifest = run_audit(synthetic_export)
    output = Path(synthetic_export["audit"]["output"])
    with (output / "prepared-manifest.csv").open(encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    assert len(rows) == len(manifest["records"])
    expected = {record["path"]: record for record in manifest["records"]}
    for row in rows:
        record = expected[row["path"]]
        assert row["split"] == record["split"]
        assert row["original_split"] == record["original_split"]
        assert [int(row[name]) for name in manifest["classes"]] == record["labels"]
    summary = (output / "summary.md").read_text(encoding="utf-8")
    assert "proportional" in summary
    for split, info in report["distribution"].items():
        assert f"| {split} | 8 | {info['images']} |" in summary

"""Synthetic fixtures only. Never download data or pretrained weights in tests."""

import csv
import os

os.environ["CUDA_VISIBLE_DEVICES"] = ""

import numpy as np
import pytest
import torch
from PIL import Image

from skin_analysis.config import load_config, write_json

torch.set_num_threads(2)


@pytest.fixture
def synthetic_export(tmp_path):
    config = load_config()
    root = tmp_path / "dataset"
    classes = ["Acne", "Pores", "Normal Skin"]
    patterns = [
        [1, 1, 0],
        [1, 0, 0],
        [0, 1, 0],
        [0, 0, 1],
        [1, 1, 0],
        [0, 0, 1],
        [1, 0, 0],
        [0, 1, 0],
    ]
    rng = np.random.default_rng(123)
    metadata = []
    for split in ("train", "valid", "test"):
        (root / split).mkdir(parents=True)
        with (root / split / "_classes.csv").open("w", newline="", encoding="utf-8") as handle:
            writer = csv.writer(handle)
            writer.writerow(["filename", *classes])
            for index, labels in enumerate(patterns):
                name = f"image-{index}.png"
                pixels = rng.integers(0, 256, (32, 32, 3), dtype=np.uint8)
                Image.fromarray(pixels).save(root / split / name)
                writer.writerow([name, *labels])
                path = f"{split}/{name}"
                metadata.append(
                    {
                        "path": path,
                        "person_id": path,
                        "image_type": "full_face",
                        "labels_reviewed": "true",
                        "notes": "Synthetic test fixture",
                    }
                )
    metadata_path = tmp_path / "metadata.csv"
    with metadata_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(metadata[0]))
        writer.writeheader()
        writer.writerows(metadata)
    evidence = {
        "dataset_url": "synthetic-fixture-only",
        "dataset_version": 1,
        "confirmed_classes": classes,
        "license": "CC-BY-4.0",
        "license_url": "synthetic-only",
        "rights_evidence": "Synthetic test fixture, no actual faces",
        "exhaustive_negatives_evidence": "Programmatically generated complete labels",
        "normal_definition_evidence": "Normal excludes the two synthetic conditions",
        "normal_exclusive": True,
        "full_face_evaluation_evidence": "Synthetic only",
        "label_review_evidence": "Synthetic only",
        "image_sources": "NumPy generated",
    }
    evidence_path = tmp_path / "evidence.json"
    write_json(evidence_path, evidence)
    config["data"].update(
        root=str(root),
        metadata=str(metadata_path),
        evidence=str(evidence_path),
        duplicate_reviews=str(tmp_path / "reviews.csv"),
    )
    config["audit"].update(
        resplit=False,
        quarantine_conflicts=False,
        quarantine_unreviewed_similarities=False,
        output=str(tmp_path / "audit"),
        min_compound_train=1,
        min_compound_valid=1,
        min_compound_test=1,
        min_eval_positive=1,
        positive_support_policy="fixed",
        min_eval_negative=1,
        min_full_face_eval=1,
    )
    config["train"].update(
        output=str(tmp_path / "run"), num_workers=0, freeze_epochs=1, finetune_epochs=2, amp=False
    )
    config["evaluation"]["bootstrap_iterations"] = 30
    return config

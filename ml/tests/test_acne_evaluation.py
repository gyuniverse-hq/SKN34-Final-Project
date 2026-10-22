from pathlib import Path
from unittest.mock import patch

import numpy as np
import pytest
import torch

from skin_analysis.acne.common import (
    ARCHITECTURE,
    PREPROCESSING,
    digest,
    file_hash,
    load_config,
    load_manifest,
    write_json,
)
from skin_analysis.acne.evaluate import evaluate


def test_manifest_blocks_changed_archives_and_group_leakage(tmp_path):
    root = tmp_path / "raw"
    root.mkdir()
    archive = root / "a.zip"
    archive.write_bytes(b"immutable fixture")
    output = tmp_path / "audit"
    config = {"data": {"root": str(root), "output": str(output)}}
    manifest = {"schema": "acne-manifest-v1", "root": str(root), "training_ready": True,
                "archives": [{"path": "a.zip", "sha256": file_hash(archive)}],
                "records": [{"split": "train", "group_id": "a", "pixel_sha256": "a"},
                            {"split": "test", "group_id": "b", "pixel_sha256": "b"}]}

    def publish():
        manifest.pop("fingerprint", None)
        manifest["fingerprint"] = digest(manifest)
        write_json(output / "manifest.json", manifest)

    publish()
    assert load_manifest(config)["training_ready"]
    archive.write_bytes(b"changed after audit")
    with pytest.raises(ValueError, match="Source archive changed"):
        load_manifest(config)
    manifest["records"][1]["group_id"] = "a"
    publish()
    with pytest.raises(ValueError, match="Data leakage"):
        load_manifest(config, verify_archives=False)
    manifest["training_ready"] = False
    publish()
    with pytest.raises(ValueError, match="unresolved errors"):
        load_manifest(config, verify_archives=False)


class EvaluationDataset:
    def __init__(self, manifest, split):
        self.records = [r for r in manifest["records"] if r["split"] == split]

    def close(self):
        pass


def test_test_scores_never_choose_the_model_and_final_report_is_frozen(tmp_path):
    config = load_config()
    config["train"].update(output=str(tmp_path), freeze_epochs=1, finetune_epochs=1)
    config["evaluation"]["bootstrap_iterations"] = 10
    rows = [{"id": f"{split}-{i}", "split": split, "label": i % 2,
             "group_id": f"{split}-{i}", "age_range": "19-29", "gender": "N/A",
             "series": "fixture", "annotation": {"bbox": {}}}
            for split in ("train", "valid", "test", "official_audit") for i in range(4)]
    manifest = {"fingerprint": "fixture", "records": rows, "limitations": ["synthetic fixture"]}
    for source in ("imagenet", "nia"):
        write_json(tmp_path / f"{source}-seed-42/complete.json",
                   {"epochs": 2, "manifest_fingerprint": "fixture"})

    def bundle(path):
        source = "imagenet" if "imagenet" in str(path) else "nia"
        model = torch.nn.Linear(1, 1)
        model.source = source
        return model, {
            "architecture": ARCHITECTURE, "preprocessing": PREPROCESSING,
            "class_mapping": {"normal": 0, "acne": 1}, "score_type": "sigmoid_uncalibrated",
            "initialization": {}, "manifest_fingerprint": "fixture",
            "train_config": config["train"], "source": source, "environment": {},
            "validation_status": "synthetic_only_person_independence_unverified",
            "limitations": ["fixture"], "epoch": 0,
            "best_key": [.95 if source == "imagenet" else .8, -.1],
        }

    def predictions(model, dataset, *args, **kwargs):
        split = dataset.records[0]["split"]
        if split == "test" and model.source == "imagenet":
            scores = [.9, .1, .9, .1]  # Worse test, better validation: still must select A.
        else:
            scores = [.1, .9, .1, .9]
        return np.array([r["label"] for r in dataset.records]), np.array(scores)[:, None], None

    with patch("skin_analysis.acne.evaluate.load_manifest", return_value=manifest), patch(
            "skin_analysis.acne.evaluate.select_cuda", return_value=torch.device("cpu")), patch(
            "skin_analysis.acne.evaluate.load_bundle", side_effect=bundle), patch(
            "skin_analysis.acne.evaluate.AcneDataset", EvaluationDataset), patch(
            "skin_analysis.acne.evaluate.make_loader", side_effect=lambda d, *a: d), patch(
            "skin_analysis.acne.evaluate.predict_loader", side_effect=predictions), patch(
            "skin_analysis.acne.evaluate.latency", return_value={"fixture": True}), patch(
            "torch.cuda.synchronize"), patch("torch.cuda.empty_cache"):
        report = evaluate(config)
        assert report["experiments"]["nia"]["metrics"]["test"]["fixed_05"]["accuracy"] == 1
        assert report["selected_for_local_research"] == "imagenet"
        assert not report["deployment_ready"]
        assert Path(report["experiments"]["imagenet"]["checkpoint"]).is_file()
        with pytest.raises(FileExistsError, match="Final test evaluation already exists"):
            evaluate(config)

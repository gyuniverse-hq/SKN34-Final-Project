import io
import zipfile

import numpy as np
import pytest
import torch
from PIL import Image
from torch import nn

from skin_analysis.acne.audit import group_records, members, split_groups
from skin_analysis.acne.common import ARCHITECTURE, PREPROCESSING
from skin_analysis.acne.data import AcneDataset, prepare_image
from skin_analysis.acne.metrics import binary_metrics, choose_threshold, paired_bootstrap
from skin_analysis.acne.model import AcneModel, load_bundle


def record(index, **overrides):
    return {"id": str(index), "identifier": f"H0_{index}_P0_L0", "label": index % 2,
            "original_split": "Training", "sha256": f"sha-{index}",
            "pixel_sha256": f"pixel-{index}", "phash": f"{index:016x}",
            "age_range": "19-29", "gender": "N/A", "series": "H0", **overrides}


def test_duplicate_and_near_groups_cannot_cross_official_boundary():
    rows = [record(0), record(1, original_split="Validation", label=0,
                              pixel_sha256="pixel-0", sha256="sha-0"), record(99)]
    group_records(rows, 0)
    assert rows[0]["split"] == "quarantine"
    assert rows[1]["split"] == "official_audit"
    assert rows[0]["group_id"] == rows[1]["group_id"]


def test_conflicting_identical_pixels_quarantine_entire_group():
    rows = [record(0), record(1, pixel_sha256="pixel-0")]
    group_records(rows, 0)
    assert all(r["split"] == "quarantine" for r in rows)


def test_split_whole_groups_is_reproducible_and_has_both_classes():
    rows = [record(i, group_id=f"group-{i//2}", split="pending") for i in range(160)]
    other = [dict(r) for r in rows]
    split_groups(rows, 42, 10)
    split_groups(other, 42, 10)
    assert rows == other
    for split in ("train", "valid", "test"):
        selected = [r for r in rows if r["split"] == split]
        assert {r["label"] for r in selected} == {0, 1}
    assignments = {}
    for r in rows:
        assert assignments.setdefault(r["group_id"], r["split"]) == r["split"]


def test_macro_f1_really_includes_normal_and_acne_and_threshold_uses_validation():
    metrics = binary_metrics([0, 0, 1, 1], [.1, .1, .1, .1])
    assert metrics["macro_f1"] == pytest.approx(1 / 3)
    assert metrics["confusion_matrix"] == [[2, 0], [2, 0]]
    assert choose_threshold([0, 0, 1, 1], [.1, .2, .3, .4]) <= .3
    result = paired_bootstrap([0, 0, 1, 1], [.1, .2, .3, .4], [.1, .2, .8, .9],
                              ["a", "b", "c", "d"], 30, 42)
    assert result["difference_ci95"][0] >= 0


def test_zip_traversal_and_duplicate_stems_rejected(tmp_path):
    path = tmp_path / "bad.zip"
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("../bad.png", b"bad")
    with zipfile.ZipFile(path) as archive, pytest.raises(ValueError):
        members(archive, ".png")


def test_zip_dataset_matches_inference_preprocessing(tmp_path):
    raw = io.BytesIO()
    Image.fromarray(np.random.default_rng(42).integers(0, 256, (60, 40, 3),
                                                    dtype=np.uint8)).save(raw, format="PNG")
    path = tmp_path / "images.zip"
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("/face.png", raw.getvalue())
    manifest = {"root": str(tmp_path), "records": [{"archive": "images.zip",
                "member": "/face.png", "label": 1, "split": "valid"}]}
    dataset = AcneDataset(manifest, "valid")
    actual, target, _ = dataset[0]
    torch.testing.assert_close(actual, prepare_image(raw.getvalue()), atol=0, rtol=0)
    assert target.tolist() == [1.]
    dataset.close()


def test_backbone_freeze_layer4_and_strict_bundle_roundtrip(tmp_path):
    model = AcneModel()
    model.set_stage(True)
    model.train()
    assert not any(p.requires_grad for p in model.backbone.parameters())
    assert not model.backbone.bn1.training
    model.set_stage(False)
    assert model.backbone.layer4[0].conv1.weight.requires_grad
    assert not model.backbone.layer3[0].conv1.weight.requires_grad
    x = torch.randn(2, 3, 32, 32)
    loss = nn.BCEWithLogitsLoss()(model(x), torch.tensor([[0.], [1.]]))
    loss.backward()
    assert model.head.weight.grad is not None
    assert model.backbone.layer4[0].conv1.weight.grad is not None
    assert model.backbone.layer3[0].conv1.weight.grad is None
    path = tmp_path / "binary.pt"
    torch.save({"architecture": ARCHITECTURE, "preprocessing": PREPROCESSING,
                "class_mapping": {"normal": 0, "acne": 1}, "score_type": "sigmoid_uncalibrated",
                "threshold": .5, "model_state": model.state_dict()}, path)
    loaded, _ = load_bundle(path)
    with torch.inference_mode():
        torch.testing.assert_close(loaded(x), model.eval()(x))

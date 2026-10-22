"""Leakage, ordinal heads, frozen BN and inference preprocessing contracts."""

import copy

import numpy as np
import pytest
import torch
from PIL import Image
from server.nia.imaging import prepare

from skin_analysis.smartphone.common import TASKS, assert_disjoint
from skin_analysis.smartphone.data import GradeDataset
from skin_analysis.smartphone.prepare import assign_splits
from skin_analysis.smartphone.train import GradeModel, class_weights


def record(subject, grade=0, split="train", task="pore"):
    return dict(
        subject=str(subject),
        group=str(subject),
        device=3,
        split=split,
        image_sha256=f"image-{subject}",
        pixel_sha256=f"pixels-{subject}",
        task=task,
        truth=grade,
        path="crop.jpg",
    )


@pytest.mark.parametrize("field", ["subject", "group", "image_sha256", "pixel_sha256"])
def test_rejects_cross_split_person_and_photo_leakage(field):
    first, second = record(1), record(2, split="test")
    second[field] = first[field]
    with pytest.raises(ValueError, match="Cross-split leakage"):
        assert_disjoint([first, second])


def test_split_is_reproducible_and_keeps_all_views_of_each_person_together():
    records = [
        record(subject, grade, task=task)
        for subject in range(140)
        for task, spec in TASKS.items()
        for grade in range(spec["classes"])
        for _ in range(2)
    ]
    settings = dict(seed=42, folds=7, valid_fold=1, test_fold=0)
    result = assign_splits(copy.deepcopy(records), settings)
    assert result == assign_splits(copy.deepcopy(records), settings)
    assert_disjoint(result)
    assert {r["split"] for r in result} == {"train", "valid", "test"}


def test_class_weights_use_training_distribution_and_reject_missing_grades():
    weights = class_weights([0] * 100 + [1] * 4, 2, 4.0)
    assert weights[1] > weights[0]
    assert weights.max() <= 4.0
    with pytest.raises(ValueError):
        class_weights([0, 0], 2, 4.0)


@pytest.mark.parametrize("classes", [6, 7])
def test_head_stage_keeps_pretrained_batch_norm_statistics_frozen(classes):
    model = GradeModel(classes)
    model.set_stage(True)
    model.train()
    assert model.network.fc.training
    assert not model.network.bn1.training
    assert not model.network.conv1.weight.requires_grad
    assert model.network.fc.weight.requires_grad
    model.set_stage(False)
    model.train()
    assert model.network.bn1.training
    assert model.network.conv1.weight.requires_grad
    assert model.network.fc.out_features == classes


def test_dataset_matches_inference_normalization_and_integer_labels(tmp_path):
    pixels = np.random.default_rng(42).integers(0, 256, (256, 256, 3), dtype=np.uint8)
    Image.fromarray(pixels).save(tmp_path / "crop.jpg")
    item = {**record(1, 4), "path": "crop.jpg"}
    data = GradeDataset(dict(root=str(tmp_path), records=[item]), "pore", "train")
    image, target, index = data[0]
    with Image.open(tmp_path / "crop.jpg") as source:
        expected = torch.from_numpy(np.array(source.convert("RGB"))).permute(2, 0, 1) / 255
    expected = (expected - torch.tensor([0.485, 0.456, 0.406])[:, None, None]) / torch.tensor(
        [0.229, 0.224, 0.225]
    )[:, None, None]
    torch.testing.assert_close(image, expected)
    inference, _ = prepare(
        (tmp_path / "crop.jpg").read_bytes(), precropped=True, include_preview=False
    )
    torch.testing.assert_close(image, inference[0], rtol=0, atol=0)
    assert target.dtype == torch.long and target.item() == 4 and index == 0

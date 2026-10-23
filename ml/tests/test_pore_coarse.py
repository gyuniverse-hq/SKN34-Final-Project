"""Derived labels, natural-frequency WCE and explicit three-output contracts."""

import copy

import numpy as np
import pytest
import torch

from skin_analysis.smartphone.common import (
    PORE_COARSE_MAPPING,
    PREPROCESSING,
    classification_contract,
)
from skin_analysis.smartphone.data import GradeDataset
from skin_analysis.smartphone.pore_coarse import load_model
from skin_analysis.smartphone.train import GradeModel, criterion_for


def test_cached_dataset_derives_targets_and_wce_counts_without_rewriting_source(tmp_path):
    np.save(tmp_path / "pixels.npy", np.zeros((6, 256, 256, 3), dtype=np.uint8))
    records = [dict(task="pore", split="train", truth=g, cache_index=g) for g in range(6)]
    original = copy.deepcopy(records)
    manifest = dict(root=str(tmp_path), pixel_cache=dict(path="pixels.npy"), records=records)
    raw = GradeDataset(manifest, "pore", "train")
    data = GradeDataset(manifest, "pore", "train", target_mapping=PORE_COARSE_MAPPING)
    targets = [int(data[i][1]) for i in range(6)]
    assert targets == [0, 0, 1, 1, 2, 2]
    assert [int(raw[i][1]) for i in range(6)] == list(range(6))
    assert records == original
    criterion, specification = criterion_for(targets, 3, dict(class_weight_cap=4), "cpu")
    assert specification["counts"] == [2, 2, 2]
    assert specification["kind"] == "weighted_cross_entropy"
    torch.testing.assert_close(criterion.weight, torch.ones(3))


@pytest.mark.parametrize(
    "settings,task",
    [
        (dict(classes=3), "pore"),
        (dict(classes=3, target_mapping=[0, 1, 2, 0, 1, 2]), "pore"),
        (dict(classes=3, target_mapping=PORE_COARSE_MAPPING), "wrinkle"),
        (dict(classes=6, target_mapping=PORE_COARSE_MAPPING), "pore"),
    ],
)
def test_rejects_implicit_or_incompatible_grade_changes(settings, task):
    with pytest.raises(ValueError):
        classification_contract(settings, task)


def test_original_task_contracts_remain_six_and_seven_classes():
    assert classification_contract({}, "pore") == (6, None, "pore")
    assert classification_contract({}, "pigmentation") == (6, None, "pigmentation")
    assert classification_contract({}, "wrinkle") == (7, None, "wrinkle")
    assert classification_contract(dict(classes=3, target_mapping=PORE_COARSE_MAPPING), "pore") == (
        3,
        PORE_COARSE_MAPPING,
        "pore_coarse",
    )


def test_strict_coarse_loader_accepts_real_head_and_rejects_wrong_mapping_or_shape():
    state = GradeModel(3).network.state_dict()
    checkpoint = dict(
        schema="nia-smartphone-training-v1",
        architecture="resnet50",
        task="pore_coarse",
        grades=[0, 1, 2],
        original_grades=list(range(6)),
        original_to_target=PORE_COARSE_MAPPING,
        preprocessing=PREPROCESSING,
        training_device="smartphone",
        resolution=256,
        decoding="softmax_argmax",
        model_state=state,
    )
    model = load_model(checkpoint)
    assert model.network.fc.out_features == 3
    assert not model.training and not any(p.requires_grad for p in model.parameters())
    with pytest.raises(ValueError, match="contract"):
        load_model(checkpoint | dict(original_to_target=list(range(6))))
    malformed = dict(state)
    malformed["fc.weight"] = torch.zeros(6, 2048)
    with pytest.raises(RuntimeError, match="size mismatch"):
        load_model(checkpoint | dict(model_state=malformed))

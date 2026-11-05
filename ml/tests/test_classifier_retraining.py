"""Sampling leakage, target semantics and actual frozen-feature optimizer behavior."""

import copy

import numpy as np
import pytest
import torch
from torch import nn
from torch.utils.data import DataLoader, TensorDataset

from skin_analysis.smartphone import classifier_retraining as crt
from skin_analysis.smartphone.sam import train_epoch
from skin_analysis.smartphone.train import GradeModel


def records():
    return [
        dict(split="train", task="pore", truth=g, subject=f"{g}-{p}")
        for g in range(6)
        for p in range(2)
        for _ in range(1 if p == 0 else 9)
    ]


@pytest.mark.parametrize("classes", [3, 6])
def test_balancing_is_deterministic_has_original_step_budget_and_preserves_labels(classes):
    original = records()
    before = copy.deepcopy(original)
    rng = torch.Generator().manual_seed(42)
    state = rng.get_state()
    sampler = crt.BalancedSubjectSampler(original, classes, rng)
    first = list(sampler)
    rng.set_state(state)
    assert list(sampler) == first
    assert len(first) == len(original) == len(sampler)
    targets = [crt.label_mapping(classes)[original[i]["truth"]] for i in first]
    counts = np.bincount(targets, minlength=classes)
    assert counts.max() - counts.min() <= 1
    assert original == before
    assert list(sampler) != first  # Subsequent epochs consume new random draws.


def test_sampling_balances_people_rather_than_number_of_photos():
    data = records()
    sampler = crt.BalancedSubjectSampler(data, 6, torch.Generator().manual_seed(12))
    seen = [data[i]["subject"].endswith("-0") for _ in range(100) for i in sampler]
    assert 0.47 < np.mean(seen) < 0.53  # Natural ROI sampling would be 0.1.


@pytest.mark.parametrize("split", ["valid", "test"])
def test_sampler_refuses_held_out_records(split):
    data = records()
    data[0]["split"] = split
    with pytest.raises(ValueError, match="training"):
        crt.BalancedSubjectSampler(data, 6, torch.Generator())


def test_sampler_requires_every_target():
    with pytest.raises(ValueError, match="Every target"):
        crt.BalancedSubjectSampler(records()[:10], 6, torch.Generator())


def test_coarse_target_is_derived_and_probability_pairs_are_aggregated_before_argmax():
    base = TensorDataset(torch.zeros(6, 2), torch.arange(6), torch.arange(6))
    dataset = crt.TargetDataset(base, 3)
    assert [int(dataset[i][1]) for i in range(6)] == [0, 0, 1, 1, 2, 2]
    assert torch.equal(base.tensors[1], torch.arange(6))
    p = [[0.2, 0.2, 0.35, 0.05, 0.1, 0.1]]
    np.testing.assert_allclose(crt.coarse_probabilities(p), [[0.4, 0.4, 0.2]])
    assert crt.coarse_probabilities(p).argmax(1)[0] == 0
    assert np.argmax(p) // 2 == 1  # Mapping the fine argmax is a different rule.
    with pytest.raises(ValueError, match="normalized"):
        crt.coarse_probabilities([[1] * 6])


def test_three_class_high_recall_does_not_pool_middle_class():
    metrics = crt.metrics_for([0, 1, 2], [0, 1, 1], 3)
    assert metrics["high_grade_pooled_recall"] == 0


def test_sam_updates_only_new_head_and_preserves_bn_buffers_exactly(monkeypatch):
    class TinyNetwork(nn.Module):
        def __init__(self):
            super().__init__()
            self.features = nn.Sequential(nn.Linear(2, 2048), nn.BatchNorm1d(2048))
            self.fc = nn.Linear(2048, 6)

        def forward(self, images):
            return self.fc(self.features(images))

    # Keep the real GradeModel's stage/train behavior, replacing only its network.
    monkeypatch.setattr("skin_analysis.smartphone.train.build_network", lambda *args: TinyNetwork())
    source = copy.deepcopy(GradeModel(6).network.state_dict())
    model = crt.initialize_classifier(source, 3, 42)
    assert not model.network.features[1].training
    initial_head = model.network.fc.weight.detach().clone()
    loader = DataLoader(
        TensorDataset(torch.randn(6, 2), torch.arange(6) % 3, torch.arange(6)),
        batch_size=2,
    )
    optimizer = torch.optim.AdamW(model.network.fc.parameters(), lr=0.01)
    train_epoch(
        model,
        loader,
        optimizer,
        nn.CrossEntropyLoss(),
        torch.device("cpu"),
        torch.amp.GradScaler("cpu", enabled=False),
        2,
        False,
        rho=0.05,
    )
    assert crt.frozen_backbone_matches(model.network.state_dict(), source)
    assert not torch.equal(initial_head, model.network.fc.weight)
    assert all(p.grad is None for p in model.network.features.parameters())
    assert not model.network.features[1].training


def test_loader_rejects_fine_coarse_contract_mixup_before_loading_weights():
    checkpoint = dict(
        schema=crt.SCHEMA,
        architecture="resnet50",
        task="pore_coarse",
        grades=[0, 1, 2],
        original_to_target=[0, 0, 1, 1, 2, 2],
        preprocessing=crt.PREPROCESSING,
        decoding="softmax_argmax",
        initialization=dict(sha256=crt.BASELINE_SHA),
    )
    with pytest.raises(ValueError, match="contract"):
        crt.load_candidate(checkpoint, 6)


def test_six_gate_rejects_accuracy_tradeoff_and_zero_grade_five_recall():
    baseline = crt.metrics_for(list(range(6)) * 2, [0, 1, 2, 2, 2, 2] * 2, 6)
    zero_five = crt.metrics_for(list(range(6)) * 2, [0, 1, 2, 3, 4, 4] * 2, 6)
    assert not crt.passes_six_gate(baseline, zero_five)
    perfect = crt.metrics_for(list(range(6)), list(range(6)), 6)
    assert crt.passes_six_gate(baseline, perfect)

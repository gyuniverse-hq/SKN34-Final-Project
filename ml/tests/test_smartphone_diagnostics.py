"""Train-only subject sampling and observational metric collection contracts."""

import random

import numpy as np
import pytest
import torch
from torch.utils.data import DataLoader, TensorDataset

from skin_analysis.smartphone.diagnostics import choose_balanced_people, tiny_passed
from skin_analysis.smartphone.train import evaluate_training


def test_balanced_selection_is_reproducible_subject_distinct_and_train_only():
    records = [
        dict(subject=f"{grade}-{person}", truth=grade, split="train")
        for grade in range(6)
        for person in range(10)
        for _ in range(2)
    ]
    indices = choose_balanced_people(records, 6, 8, 42)
    assert indices == choose_balanced_people(records, 6, 8, 42)
    assert len(indices) == len({records[i]["subject"] for i in indices}) == 48
    assert [sum(records[i]["truth"] == g for i in indices) for g in range(6)] == [8] * 6
    records[0]["split"] = "valid"
    with pytest.raises(ValueError, match="training records only"):
        choose_balanced_people(records, 6, 8, 42)


def test_tiny_selection_refuses_to_duplicate_people_when_grade_is_sparse():
    records = [dict(subject="same", truth=g, split="train") for g in range(6)]
    with pytest.raises(ValueError, match="distinct"):
        choose_balanced_people(records, 6, 1, 42)


def test_memorization_pass_requires_both_accuracy_and_macro_f1():
    assert tiny_passed(dict(accuracy=1, macro_f1=1))
    assert not tiny_passed(dict(accuracy=1, macro_f1=0.5))
    assert not tiny_passed(dict(accuracy=0.5, macro_f1=1))


def test_train_evaluation_preserves_rng_weights_bn_and_uses_unweighted_ce(monkeypatch):
    monkeypatch.setattr(torch.cuda, "is_available", lambda: False)
    torch.set_num_threads(4)

    class Model(torch.nn.Module):
        def __init__(self):
            super().__init__()
            self.bn = torch.nn.BatchNorm1d(2)

        def forward(self, x):
            random.random()
            np.random.random()
            torch.rand(1)
            return self.bn(x)

    model = Model().train()
    images, targets = torch.tensor([[3.0, 0.0], [0.0, 3.0]]), torch.tensor([0, 1])
    data = TensorDataset(images, targets, torch.arange(2))
    generator = torch.Generator().manual_seed(42)
    # Deliberately use the training generator; even its state must be restored.
    loader = DataLoader(data, batch_size=2, generator=generator)
    torch_before, loader_before = torch.get_rng_state().clone(), generator.get_state().clone()
    python_before, numpy_before = random.getstate(), np.random.get_state()
    weights = {k: v.clone() for k, v in model.state_dict().items()}
    result = evaluate_training(model, loader, "cpu", 2, generator)
    assert result["train_eval_accuracy"] == result["train_eval_macro_f1"] == 1
    assert result["train_eval_loss"] == pytest.approx(
        torch.nn.functional.cross_entropy(images / (1 + model.bn.eps) ** 0.5, targets).item()
    )
    assert torch.equal(torch.get_rng_state(), torch_before)
    assert torch.equal(generator.get_state(), loader_before)
    assert random.getstate() == python_before
    assert np.array_equal(np.random.get_state()[1], numpy_before[1])
    assert np.random.get_state()[2:] == numpy_before[2:]
    assert all(torch.equal(v, weights[k]) for k, v in model.state_dict().items())


def test_train_evaluation_restores_rng_even_if_inference_fails(monkeypatch):
    monkeypatch.setattr(torch.cuda, "is_available", lambda: False)

    class Broken(torch.nn.Module):
        def forward(self, x):
            torch.rand(3)
            raise RuntimeError("diagnostic failure")

    generator = torch.Generator().manual_seed(42)
    before = torch.get_rng_state().clone()
    with pytest.raises(RuntimeError, match="diagnostic failure"):
        evaluate_training(
            Broken(), [(torch.zeros(1, 2), torch.tensor([0]), None)], "cpu", 2, generator
        )
    assert torch.equal(torch.get_rng_state(), before)

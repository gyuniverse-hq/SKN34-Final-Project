"""Focal mathematics, numerical stability and controlled experiment contracts."""

import pytest
import torch
from torch.nn import functional as F

from skin_analysis.smartphone.focal_compare import qualifies, require_matched_conditions
from skin_analysis.smartphone.losses import ClassBalancedFocalLoss, effective_number_weights
from skin_analysis.smartphone.train import criterion_for


def test_effective_number_weights_match_formula():
    counts = torch.tensor([48, 224, 2486], dtype=torch.float64)
    expected = (1 - 0.999) / (1 - 0.999**counts)
    expected /= expected.mean()
    torch.testing.assert_close(effective_number_weights(counts, 0.999), expected.float())
    torch.testing.assert_close(effective_number_weights(counts, 0), torch.ones(3))


@pytest.mark.parametrize(
    "counts,beta",
    [([0, 2], 0.9), ([1.5, 2], 0.9), ([1, 2], 1), ([1, 2], -0.1), ([1, float("nan")], 0.9)],
)
def test_invalid_effective_number_settings_rejected(counts, beta):
    with pytest.raises(ValueError):
        effective_number_weights(counts, beta)


def test_gamma_zero_matches_weighted_cross_entropy_and_gradients():
    logits = torch.tensor([[1.0, 2.0, -1.0], [0.3, -0.5, 0.2]], requires_grad=True)
    targets = torch.tensor([0, 2])
    criterion = ClassBalancedFocalLoss([10, 20, 100], beta=0.999, gamma=0)
    actual = criterion(logits, targets)
    expected = F.cross_entropy(logits, targets, weight=criterion.weight)
    torch.testing.assert_close(actual, expected)
    (first,) = torch.autograd.grad(actual, logits, retain_graph=True)
    (second,) = torch.autograd.grad(expected, logits)
    torch.testing.assert_close(first, second)


def test_focal_modulation_matches_manual_true_class_probability():
    logits = torch.tensor([[2.0, 0.0], [0.0, 1.0]])
    targets = torch.tensor([0, 1])
    criterion = ClassBalancedFocalLoss([10, 100], beta=0.99, gamma=2)
    ce = F.cross_entropy(logits, targets, reduction="none")
    pt = logits.softmax(1)[torch.arange(2), targets]
    alpha = criterion.weight[targets]
    expected = (alpha * (1 - pt).square() * ce).sum() / alpha.sum()
    torch.testing.assert_close(criterion(logits, targets), expected)


def test_fp16_extreme_logits_have_finite_loss_and_gradients():
    logits = torch.tensor(
        [[1000.0, -1000.0], [-1000.0, 1000.0]], dtype=torch.float16, requires_grad=True
    )
    loss = ClassBalancedFocalLoss([1, 1000])(logits, torch.tensor([0, 0]))
    loss.backward()
    assert loss.dtype == torch.float32
    assert torch.isfinite(loss) and torch.isfinite(logits.grad).all()


def test_easy_correct_examples_receive_less_focal_loss():
    criterion = ClassBalancedFocalLoss([10, 10])
    target = torch.tensor([0])
    assert criterion(torch.tensor([[5.0, 0.0]]), target) < criterion(torch.zeros(1, 2), target)


def test_default_criterion_preserves_existing_weighted_ce():
    labels = [0] * 20 + [1] * 3
    criterion, specification = criterion_for(labels, 2, {"class_weight_cap": 4}, "cpu")
    assert isinstance(criterion, torch.nn.CrossEntropyLoss)
    assert specification["kind"] == "weighted_cross_entropy"


def test_cb_focal_does_not_use_legacy_cap_or_sqrt_weights():
    criterion, specification = criterion_for(
        [0] * 100 + [1] * 2,
        2,
        dict(loss="class_balanced_focal", cb_beta=0.999, focal_gamma=2),
        "cpu",
    )
    torch.testing.assert_close(criterion.weight, effective_number_weights([100, 2], 0.999))
    assert specification["legacy_sqrt_class_weights_used"] is False


@pytest.mark.parametrize("gamma", [-1, float("nan"), float("inf")])
def test_invalid_gamma_rejected(gamma):
    with pytest.raises(ValueError):
        ClassBalancedFocalLoss([10, 10], gamma=gamma)


def test_comparison_rejects_non_loss_budget_or_data_changes():
    baseline = dict(
        train_config=dict(output="old", seed=42, finetune_epochs=18),
        manifest_fingerprint="same",
        initialization=dict(nia_weights_used=False),
        preprocessing="same-crop",
    )
    config = dict(
        train=dict(
            output="new",
            seed=42,
            finetune_epochs=18,
            loss="class_balanced_focal",
            cb_beta=0.999,
            focal_gamma=2,
        )
    )
    manifest = dict(fingerprint="same", preprocessing="same-crop")
    require_matched_conditions(config, manifest, baseline)
    config["train"]["finetune_epochs"] = 30
    with pytest.raises(ValueError, match="non-loss"):
        require_matched_conditions(config, manifest, baseline)
    config["train"]["finetune_epochs"] = 18
    manifest["fingerprint"] = "changed"
    with pytest.raises(ValueError):
        require_matched_conditions(config, manifest, baseline)


def test_expansion_requires_exact_accuracy_macro_f1_and_high_grade_improvement():
    def metrics(accuracy, f1, high_correct):
        return dict(
            accuracy=accuracy,
            macro_f1=f1,
            per_grade=[dict(grade=i, support=10) for i in range(3)],
            confusion=[
                [5, 5, 0],
                [5, high_correct, 5 - high_correct],
                [10 - high_correct, 0, high_correct],
            ],
        )

    baseline = metrics(0.55, 0.30, 1)
    assert qualifies(baseline, metrics(0.56, 0.35, 2))
    assert not qualifies(baseline, metrics(0.54, 0.35, 2))
    assert not qualifies(baseline, metrics(0.56, 0.29, 2))
    assert not qualifies(baseline, metrics(0.56, 0.35, 1))

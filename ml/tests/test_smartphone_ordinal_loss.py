"""Independent ordinal-loss mathematics and unchanged inference contract."""

import pytest
import torch

from skin_analysis.smartphone.experiment_checks import (
    require_ordinal_loss_only as require_loss_only,
)
from skin_analysis.smartphone.ordinal_loss import WeightedOrdinalCdfLoss
from skin_analysis.smartphone.train import criterion_for


def test_weighted_cdf_matches_independent_nested_boundary_sum_and_gradients():
    logits = torch.tensor([[0.1, -0.2, 0.4], [0.2, 0.5, -0.6]], requires_grad=True)
    y = torch.tensor([0, 2])
    weights = torch.tensor([2.0, 1.0, 3.0])
    p = logits.softmax(1)
    numerator = sum(
        weights[y[i]]
        * sum((sum(p[i, j] for j in range(k + 1)) - float(y[i] <= k)) ** 2 for k in range(2))
        for i in range(2)
    )
    expected = numerator / weights[y].sum()
    actual = WeightedOrdinalCdfLoss(weights)(logits, y)
    torch.testing.assert_close(actual, expected)
    torch.testing.assert_close(
        torch.autograd.grad(actual, logits, retain_graph=True)[0],
        torch.autograd.grad(expected, logits)[0],
    )


def test_confident_errors_pay_one_unit_per_crossed_grade_boundary():
    loss = WeightedOrdinalCdfLoss(torch.ones(6))
    for predicted in range(6):
        z = torch.full((1, 6), -100.0)
        z[0, predicted] = 100.0
        assert loss(z, torch.tensor([1])).item() == pytest.approx(abs(predicted - 1))


def test_weight_scaling_does_not_change_reduction_and_binary_matches_squared_error():
    z = torch.tensor([[0.2, 0.7], [0.8, -0.3]])
    y = torch.tensor([0, 1])
    w = torch.tensor([2.0, 3.0])
    expected = (w[y] * (z.softmax(1)[:, 0] - (y == 0).float()).square()).sum() / w[y].sum()
    torch.testing.assert_close(WeightedOrdinalCdfLoss(w)(z, y), expected)
    torch.testing.assert_close(WeightedOrdinalCdfLoss(10 * w)(z, y), expected)


def test_fp16_inputs_have_float32_finite_loss_and_finite_nonzero_gradients():
    z = torch.tensor([[2.0, 0.0, -1.0], [-1.0, 1.0, 3.0]], dtype=torch.float16, requires_grad=True)
    loss = WeightedOrdinalCdfLoss([1.0, 2.0, 3.0])(z, torch.tensor([0, 1]))
    loss.backward()
    assert loss.dtype == torch.float32 and torch.isfinite(loss)
    assert torch.isfinite(z.grad).all() and z.grad.abs().sum() > 0


@pytest.mark.parametrize(
    "weights", [[1.0], [1.0, 0.0], [1.0, -1.0], [1.0, float("nan")], [[1.0, 2.0]]]
)
def test_invalid_class_weights_rejected(weights):
    with pytest.raises(ValueError, match="positive class weights"):
        WeightedOrdinalCdfLoss(weights)


@pytest.mark.parametrize(
    "targets",
    [
        torch.tensor([-1]),
        torch.tensor([3]),
        torch.tensor([1.0]),
        torch.tensor([], dtype=torch.long),
    ],
)
def test_invalid_targets_rejected(targets):
    with pytest.raises(ValueError, match="integer grades"):
        WeightedOrdinalCdfLoss(torch.ones(3))(torch.zeros(len(targets), 3), targets)


def test_loss_factory_retains_ce_class_weights_and_uses_six_softmax_logits():
    labels = [grade for grade, count in enumerate([100, 30, 20, 10, 5, 2]) for _ in range(count)]
    settings = dict(class_weight_cap=4.0)
    ce, _ = criterion_for(labels, 6, settings, "cpu")
    ordinal, spec = criterion_for(labels, 6, settings | dict(loss="weighted_ordinal_cdf"), "cpu")
    torch.testing.assert_close(ordinal.weight, ce.weight, rtol=0, atol=0)
    assert ordinal.weight.shape == (6,)
    assert spec["cross_entropy_component"] is False
    assert spec["decoding"] == "softmax_argmax_unchanged"


def test_loss_comparison_rejects_other_changes_including_sam_radius_and_budget():
    baseline = dict(
        output="old",
        optimizer="sam_adamw",
        sam_rho=0.05,
        batch_size=16,
        finetune_epochs=18,
        record_train_metrics=True,
    )
    candidate = baseline | dict(output="new", loss="weighted_ordinal_cdf")
    require_loss_only(candidate, baseline)
    for change in (
        dict(sam_rho=0.1),
        dict(optimizer="adamw"),
        dict(batch_size=32),
        dict(finetune_epochs=40),
        dict(loss="coral"),
    ):
        with pytest.raises(ValueError, match="Only weighted CE"):
            require_loss_only(candidate | change, baseline)

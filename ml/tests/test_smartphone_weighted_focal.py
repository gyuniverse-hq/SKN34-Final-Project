"""WFL preserves WCE alpha, uses unweighted p_t, and differentiates focal modulation."""

import pytest
import torch
from torch.nn import functional as F

from skin_analysis.smartphone.experiment_checks import (
    require_weighted_focal_only as require_loss_only,
)
from skin_analysis.smartphone.losses import (
    ClassBalancedFocalLoss,
    WeightedFocalLoss,
    effective_number_weights,
)
from skin_analysis.smartphone.train import criterion_for


def test_gamma_zero_exactly_recovers_wce_value_and_gradient():
    z = torch.tensor([[1.0, 2.0, -1.0], [0.3, -0.5, 0.2]], requires_grad=True)
    y = torch.tensor([0, 2])
    w = torch.tensor([2.9, 0.6, 4.0])
    actual = WeightedFocalLoss(w, gamma=0)(z, y)
    expected = F.cross_entropy(z, y, weight=w)
    torch.testing.assert_close(actual, expected)
    torch.testing.assert_close(
        torch.autograd.grad(actual, z, retain_graph=True)[0], torch.autograd.grad(expected, z)[0]
    )


def test_nonzero_gamma_matches_direct_softmax_formula_and_full_gradient():
    z = torch.tensor([[2.0, 0.0, 1.0], [-1.0, 0.5, 2.0]], requires_grad=True)
    y = torch.tensor([0, 1])
    w = torch.tensor([3.0, 0.6, 4.0])
    p = z.softmax(1)[torch.arange(2), y]
    expected = (-w[y] * (1 - p).pow(2) * p.log()).sum() / w[y].sum()
    actual = WeightedFocalLoss(w, gamma=2)(z, y)
    torch.testing.assert_close(actual, expected)
    torch.testing.assert_close(
        torch.autograd.grad(actual, z, retain_graph=True)[0], torch.autograd.grad(expected, z)[0]
    )
    # Applying exp(-weighted CE) would make p_t depend on alpha and is incorrect.
    wrong_p = torch.exp(-F.cross_entropy(z, y, weight=w, reduction="none"))
    assert not torch.allclose(p, wrong_p)


def test_loss_factory_uses_identical_six_grade_weights_to_wce_and_no_cb_weights():
    labels = [g for g, n in enumerate([114, 721, 2486, 519, 224, 48]) for _ in range(n)]
    settings = dict(class_weight_cap=4.0)
    ce, _ = criterion_for(labels, 6, settings, "cpu")
    focal, spec = criterion_for(
        labels, 6, settings | dict(loss="weighted_focal", focal_gamma=2.0), "cpu"
    )
    torch.testing.assert_close(focal.weight, ce.weight, rtol=0, atol=0)
    assert spec["gamma"] == 2 and spec["effective_number_weights_used"] is False
    assert not torch.allclose(focal.weight, effective_number_weights(spec["counts"], 0.999))


def test_legacy_cb_focal_retains_value_gradient_and_effective_number_weights():
    z = torch.tensor([[2.0, 0.0, 1.0], [-1.0, 0.5, 2.0]], requires_grad=True)
    y = torch.tensor([0, 1])
    weights = effective_number_weights([10, 40, 100], 0.999)
    ce = F.cross_entropy(z, y, reduction="none")
    expected = (weights[y] * (-torch.expm1(-ce)).square() * ce).sum() / weights[y].sum()
    actual = ClassBalancedFocalLoss([10, 40, 100], beta=0.999, gamma=2)(z, y)
    torch.testing.assert_close(actual, expected, rtol=0, atol=0)
    torch.testing.assert_close(
        torch.autograd.grad(actual, z, retain_graph=True)[0],
        torch.autograd.grad(expected, z)[0],
        rtol=0,
        atol=0,
    )


def test_easy_examples_downweighted_and_weight_rescaling_preserves_loss():
    loss = WeightedFocalLoss([1.0, 2.0])
    assert loss(torch.tensor([[5.0, 0.0]]), torch.tensor([0])) < loss(
        torch.zeros(1, 2), torch.tensor([0])
    )
    z = torch.tensor([[2.0, 0.0], [0.0, 1.0]])
    y = torch.tensor([0, 1])
    torch.testing.assert_close(loss(z, y), WeightedFocalLoss([10.0, 20.0])(z, y))


def test_fp16_extremes_produce_float32_finite_loss_and_gradients():
    z = torch.tensor(
        [[1000.0, -1000.0], [-1000.0, 1000.0]], dtype=torch.float16, requires_grad=True
    )
    loss = WeightedFocalLoss([1.0, 4.0])(z, torch.tensor([0, 0]))
    loss.backward()
    assert loss.dtype == torch.float32 and torch.isfinite(loss) and torch.isfinite(z.grad).all()


@pytest.mark.parametrize(
    "weights", [[1.0], [1.0, 0.0], [1.0, -1.0], [1.0, float("nan")], [[1.0, 2.0]]]
)
def test_invalid_weights_rejected(weights):
    with pytest.raises(ValueError, match="weights"):
        WeightedFocalLoss(weights)


@pytest.mark.parametrize("gamma", [-1.0, float("nan"), float("inf")])
def test_invalid_gamma_rejected(gamma):
    with pytest.raises(ValueError, match="gamma"):
        WeightedFocalLoss([1.0, 2.0], gamma)


def test_wfl_experiment_rejects_other_treatments_and_gamma_search():
    baseline = dict(output="old", optimizer="sam_adamw", sam_rho=0.05, batch_size=16)
    candidate = baseline | dict(output="new", loss="weighted_focal", focal_gamma=2.0)
    require_loss_only(candidate, baseline)
    for change in (
        dict(focal_gamma=1.0),
        dict(sam_rho=0.1),
        dict(batch_size=32),
        dict(loss="class_balanced_focal"),
        dict(optimizer="adamw"),
    ):
        with pytest.raises(ValueError, match="Only WCE"):
            require_loss_only(candidate | change, baseline)

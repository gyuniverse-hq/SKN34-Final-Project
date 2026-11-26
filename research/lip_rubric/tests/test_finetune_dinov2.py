"""Weighted regression helpers for finetune_dinov2 (no hub download)."""
import sys
from pathlib import Path

import torch

HERE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HERE))
from finetune_dinov2 import PASS_LINE, score_weights, weighted_mse  # noqa: E402


def test_score_weights_boost_tails_and_pass_band():
    y = torch.tensor([0.5, 1.5, 3.0, 4.2, 4.8])
    w = score_weights(y)
    assert float(w[0]) == 2.5
    assert float(w[1]) == 1.5
    assert float(w[2]) == 1.0
    assert float(w[3]) == 3.0
    assert float(w[4]) == 3.5
    assert PASS_LINE == 4.68


def test_weighted_mse_puts_more_pull_on_heavy_samples():
    pred = torch.tensor([0.0, 0.0], requires_grad=True)
    target = torch.tensor([1.0, 1.0])
    light = weighted_mse(pred, target, torch.tensor([1.0, 1.0]))
    heavy = weighted_mse(pred, target, torch.tensor([1.0, 10.0]))
    assert float(light.detach()) == float(heavy.detach())
    pred2 = torch.tensor([0.0, 0.5], requires_grad=True)
    w = torch.tensor([1.0, 10.0])
    loss = weighted_mse(pred2, torch.tensor([0.0, 0.0]), w)
    loss.backward()
    # heavier sample dominates gradient on second logit
    assert abs(float(pred2.grad[1])) > abs(float(pred2.grad[0]))

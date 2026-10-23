"""Exclusive-grade softmax focal loss with explicit or effective-number weights."""

import math

import torch
from torch import nn
from torch.nn import functional as F


def effective_number_weights(counts, beta):
    counts = torch.as_tensor(counts, dtype=torch.float64)
    if (
        counts.ndim != 1
        or counts.numel() < 2
        or not torch.isfinite(counts).all()
        or (counts <= 0).any()
        or (counts != counts.floor()).any()
        or not math.isfinite(beta)
        or not 0 <= beta < 1
    ):
        raise ValueError("Positive integer class counts and 0 <= beta < 1 are required")
    if beta == 0:
        weights = torch.ones_like(counts)
    else:
        # expm1 avoids cancellation when beta is close to 1.
        effective = -torch.expm1(counts * math.log(beta))
        weights = (1 - beta) / effective
    return (weights / weights.mean()).float()


class WeightedFocalLoss(nn.Module):
    """sum(alpha_y * (1-p_y)^gamma * CE) / sum(alpha_y).

    Mutually exclusive multiclass softmax variant; no per-class sigmoid losses.
    gamma=0 exactly recovers weighted CE with the same class weights.
    """

    def __init__(self, weight, gamma=2.0):
        super().__init__()
        if not math.isfinite(gamma) or gamma < 0:
            raise ValueError("Focal gamma must be finite and nonnegative")
        weight = torch.as_tensor(weight, dtype=torch.float32).detach().clone()
        if (
            weight.ndim != 1
            or weight.numel() < 2
            or not torch.isfinite(weight).all()
            or (weight <= 0).any()
        ):
            raise ValueError("Focal class weights must be finite and positive")
        self.register_buffer("weight", weight)
        self.gamma = float(gamma)

    def forward(self, logits, targets):
        if (
            logits.ndim != 2
            or targets.ndim != 1
            or not targets.numel()
            or logits.shape != (len(targets), len(self.weight))
        ):
            raise ValueError("Expected nonempty [N,C] logits and [N] class targets")
        # Compute probabilities/loss in float32 even inside the fp16 training autocast.
        ce = F.cross_entropy(logits.float(), targets, reduction="none")
        modulation = (-torch.expm1(-ce)).pow(self.gamma)
        alpha = self.weight[targets]
        return (alpha * modulation * ce).sum() / alpha.sum()


class ClassBalancedFocalLoss(WeightedFocalLoss):
    """Legacy CB Focal keeps the same effective-number weights and calculation."""

    def __init__(self, counts, beta=0.999, gamma=2.0):
        super().__init__(effective_number_weights(counts, beta), gamma=gamma)

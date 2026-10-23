"""Exclusive-grade softmax focal loss with effective-number class balancing."""

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


class ClassBalancedFocalLoss(nn.Module):
    """sum(alpha_y * (1-p_y)^gamma * CE) / sum(alpha_y).

    This softmax, mutually exclusive multiclass variant is not the paper author's
    sigmoid one-vs-all implementation. gamma=0 exactly recovers weighted CE.
    """

    def __init__(self, counts, beta=0.999, gamma=2.0):
        super().__init__()
        if not math.isfinite(gamma) or gamma < 0:
            raise ValueError("Focal gamma must be finite and nonnegative")
        self.register_buffer("weight", effective_number_weights(counts, beta))
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

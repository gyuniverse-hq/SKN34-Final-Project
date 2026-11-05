"""Shared-score CORAL head, cumulative loss and explicit ordinal decoding.

Reference: Cao et al., https://arxiv.org/abs/1901.07884 and the authors'
coral-pytorch documentation. Implementation uses PyTorch's stable BCE primitive.
"""

from pathlib import Path

import torch
from torch import nn
from torch.nn import functional as F
from torchvision.models import resnet50

from .common import PREPROCESSING, TASKS, file_hash

ARCHITECTURE = "resnet50_coral"
DECODING = "count_sigmoid_strictly_above_0.5"


class CoralHead(nn.Module):
    def __init__(self, features, classes):
        super().__init__()
        if type(classes) is not int or classes < 2:
            raise ValueError("CORAL needs at least two ordered classes")
        self.score = nn.Linear(features, 1, bias=False)
        self.bias = nn.Parameter(torch.linspace(1.0, 1.0 / (classes - 1), classes - 1))

    def forward(self, features):
        return self.score(features) + self.bias


def ordinal_levels(targets, classes):
    if (
        targets.ndim != 1
        or not targets.numel()
        or targets.dtype != torch.long
        or (targets < 0).any()
        or (targets >= classes).any()
    ):
        raise ValueError("Expected nonempty integer grades in [0, classes)")
    return (targets[:, None] > torch.arange(classes - 1, device=targets.device)).float()


class CoralLoss(nn.Module):
    """Unweighted sum over K-1 binary thresholds, mean over examples."""

    def forward(self, logits, targets):
        if logits.ndim != 2 or logits.shape[0] != len(targets) or logits.shape[1] < 1:
            raise ValueError("Expected [N,K-1] cumulative logits and [N] targets")
        levels = ordinal_levels(targets, logits.shape[1] + 1)
        return (
            F.binary_cross_entropy_with_logits(logits.float(), levels, reduction="none")
            .sum(1)
            .mean()
        )


class WeightedCoralLoss(nn.Module):
    """Class-weighted CORAL threshold BCE with target-class normalization."""

    def __init__(self, weight):
        super().__init__()
        weight = torch.as_tensor(weight, dtype=torch.float32).detach().clone()
        if (
            weight.ndim != 1
            or weight.numel() < 2
            or not torch.isfinite(weight).all()
            or (weight <= 0).any()
        ):
            raise ValueError("Weighted CORAL requires finite positive class weights")
        self.register_buffer("weight", weight)

    def forward(self, logits, targets):
        if logits.ndim != 2 or logits.shape[0] != len(targets) or logits.shape[1] < 1:
            raise ValueError("Expected [N,K-1] cumulative logits and [N] targets")
        levels = ordinal_levels(targets, logits.shape[1] + 1)
        per_example = (
            F.binary_cross_entropy_with_logits(logits.float(), levels, reduction="none")
            .sum(1)
        )
        target_weight = self.weight[targets]
        return (per_example * target_weight).sum() / target_weight.sum()


def decode_coral(logits):
    if logits.ndim != 2 or logits.shape[1] < 1 or not torch.isfinite(logits).all():
        raise ValueError("Expected finite cumulative threshold logits")
    if (logits[:, 1:] > logits[:, :-1] + 1e-6).any():
        raise ValueError("CORAL thresholds are not rank consistent")
    # These are P(y > k), not softmax class probabilities. Never use argmax.
    return (logits > 0).sum(1), logits.float().sigmoid()


def load_coral_checkpoint(path, expected_sha256):
    """Safe CPU load for this architecture; never pass it to the CE engine."""
    path = Path(path)
    if file_hash(path) != expected_sha256:
        raise ValueError("CORAL checkpoint hash mismatch")
    checkpoint = torch.load(path, map_location="cpu", weights_only=True)
    task = checkpoint.get("task")
    if (
        checkpoint.get("architecture") != ARCHITECTURE
        or task not in TASKS
        or checkpoint.get("resolution") != 256
        or checkpoint.get("preprocessing") != PREPROCESSING
        or checkpoint.get("decoding") != DECODING
        or checkpoint.get("grades") != list(range(TASKS[task]["classes"]))
    ):
        raise ValueError("Incompatible CORAL inference contract")
    state = checkpoint["model_state"]
    if any(not isinstance(v, torch.Tensor) or not torch.isfinite(v).all() for v in state.values()):
        raise ValueError("Non-finite CORAL state")
    model = resnet50(weights=None)
    model.fc = CoralHead(2048, TASKS[task]["classes"])
    model.load_state_dict(state, strict=True)
    if (model.fc.bias[1:] > model.fc.bias[:-1]).any():
        raise ValueError("CORAL head bias ordering is invalid")
    return model.eval().requires_grad_(False), checkpoint

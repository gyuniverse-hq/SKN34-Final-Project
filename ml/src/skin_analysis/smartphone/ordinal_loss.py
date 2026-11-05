"""Weighted squared cumulative-distribution distance for ordered softmax bins.

This is the unnormalized ranked probability score: sum across K-1 boundaries.
It preserves the K-class softmax head and uses unit cost per adjacent boundary,
not measured physical distances or a continuous severity target.
"""

import torch
from torch import nn


class WeightedOrdinalCdfLoss(nn.Module):
    def __init__(self, weight):
        super().__init__()
        weight = torch.as_tensor(weight, dtype=torch.float32).detach().clone()
        if (
            weight.ndim != 1
            or weight.numel() < 2
            or not torch.isfinite(weight).all()
            or (weight <= 0).any()
        ):
            raise ValueError("Ordinal CDF loss requires finite positive class weights")
        self.register_buffer("weight", weight)

    def forward(self, logits, targets):
        if (
            logits.ndim != 2
            or targets.ndim != 1
            or not targets.numel()
            or logits.shape != (len(targets), len(self.weight))
            or targets.dtype != torch.long
            or (targets < 0).any()
            or (targets >= len(self.weight)).any()
        ):
            raise ValueError("Expected nonempty [N,K] logits and integer grades in [0,K)")
        # The final CDF component is identically one; exclude it. FP32 prevents
        # low-precision cumsum/squaring from changing the objective under AMP.
        cumulative = logits.float().softmax(1).cumsum(1)[:, :-1]
        target_cdf = (
            targets[:, None] <= torch.arange(len(self.weight) - 1, device=targets.device)
        ).float()
        per_example = (cumulative - target_cdf).square().sum(1)
        alpha = self.weight[targets]
        return (alpha * per_example).sum() / alpha.sum()

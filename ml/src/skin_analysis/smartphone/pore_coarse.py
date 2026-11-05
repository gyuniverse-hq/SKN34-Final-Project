"""Explicit inference contract for a naturally sampled, three-output pore model."""

import torch

from .common import PORE_COARSE_MAPPING, PREPROCESSING
from .train import GradeModel


def load_model(checkpoint):
    if (
        checkpoint.get("schema") != "nia-smartphone-training-v1"
        or checkpoint.get("architecture") != "resnet50"
        or checkpoint.get("task") != "pore_coarse"
        or checkpoint.get("grades") != [0, 1, 2]
        or checkpoint.get("original_grades") != list(range(6))
        or checkpoint.get("original_to_target") != PORE_COARSE_MAPPING
        or checkpoint.get("preprocessing") != PREPROCESSING
        or checkpoint.get("training_device") != "smartphone"
        or checkpoint.get("resolution") != 256
        or checkpoint.get("decoding") != "softmax_argmax"
    ):
        raise ValueError("Incompatible three-class pore inference contract")
    state = checkpoint["model_state"]
    if not all(isinstance(v, torch.Tensor) and torch.isfinite(v).all() for v in state.values()):
        raise ValueError("Invalid coarse checkpoint tensors")
    model = GradeModel(3)
    model.network.load_state_dict(state, strict=True)
    return model.eval().requires_grad_(False)

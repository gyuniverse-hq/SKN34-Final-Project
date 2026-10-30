"""Check the added backbones keep their regression heads and optimizer groups intact."""

import pytest
import torch

from skin_analysis.smartphone.backbones import head_for
from skin_analysis.smartphone.train import GradeModel, optimizer_for


@pytest.mark.parametrize("backbone", ["efficientnet_b3", "mobilenet_v3_large"])
def test_regression_head_and_full_finetuning_parameter_groups(backbone):
    model = GradeModel(1, pretrained=False, backbone=backbone)
    settings = {
        "head_lr": 0.001, "finetune_head_lr": 0.0001, "backbone_lr": 0.00001,
        "weight_decay": 0.0001, "finetune_epochs": 98,
    }
    frozen_optimizer, _ = optimizer_for(model, settings, frozen=True)
    head = {id(p) for p in head_for(model.network).parameters()}
    assert {id(p) for p in model.parameters() if p.requires_grad} == head
    assert {id(p) for g in frozen_optimizer.param_groups for p in g["params"]} == head
    model.eval()
    with torch.inference_mode():
        assert model(torch.zeros(1, 3, 64, 64)).shape == (1, 1)
    optimizer, _ = optimizer_for(model, settings, frozen=False)
    groups = [{id(p) for p in group["params"]} for group in optimizer.param_groups]
    assert groups[0] == head
    assert not groups[0].intersection(groups[1])
    assert groups[0].union(groups[1]) == {id(p) for p in model.parameters() if p.requires_grad}
    with pytest.raises(ValueError, match="ResNet-only"):
        GradeModel(1, backbone=backbone, finetune_scope="layer4")

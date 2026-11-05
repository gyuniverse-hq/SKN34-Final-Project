"""Independently composed torchvision ResNet-50 and multilabel logits head."""

import torch
from torch import nn
from torchvision.models import ResNet50_Weights, resnet50

ARCHITECTURE = "resnet50-mlp512-dropout03-logits-v1"
WEIGHTS = "IMAGENET1K_V2"


class SkinAnalysisModel(nn.Module):
    def __init__(self, num_classes: int, *, pretrained: bool = True):
        super().__init__()
        if num_classes < 1:
            raise ValueError("At least one class is required")
        self.backbone = resnet50(weights=ResNet50_Weights.IMAGENET1K_V2 if pretrained else None)
        features = self.backbone.fc.in_features
        self.backbone.fc = nn.Identity()
        self.head = nn.Sequential(
            nn.Linear(features, 512), nn.ReLU(), nn.Dropout(0.3), nn.Linear(512, num_classes)
        )
        self._backbone_frozen = False

    def forward(self, images: torch.Tensor) -> torch.Tensor:
        return self.head(self.backbone(images))

    def set_stage(self, frozen: bool) -> None:
        self._backbone_frozen = frozen
        self.backbone.requires_grad_(not frozen)
        self.train(self.training)

    def train(self, mode: bool = True):
        super().train(mode)
        if self._backbone_frozen:
            self.backbone.eval()
        # Keep running statistics fixed even after unfreezing, including singleton batches.
        for module in self.backbone.modules():
            if isinstance(module, nn.modules.batchnorm._BatchNorm):
                module.eval()
        return self

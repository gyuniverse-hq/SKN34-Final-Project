"""Explicit ImageNet initialization and classifier access for research backbones."""

from torch import nn
from torchvision.models import (
    EfficientNet_B0_Weights,
    EfficientNet_B3_Weights,
    MobileNet_V3_Large_Weights,
    ResNet18_Weights,
    ResNet50_Weights,
    efficientnet_b0,
    efficientnet_b3,
    mobilenet_v3_large,
    resnet18,
    resnet50,
)

BACKBONES = {
    "resnet50": (resnet50, ResNet50_Weights.IMAGENET1K_V2),
    "resnet18": (resnet18, ResNet18_Weights.IMAGENET1K_V1),
    "efficientnet_b0": (efficientnet_b0, EfficientNet_B0_Weights.IMAGENET1K_V1),
    "efficientnet_b3": (efficientnet_b3, EfficientNet_B3_Weights.IMAGENET1K_V1),
    "mobilenet_v3_large": (mobilenet_v3_large, MobileNet_V3_Large_Weights.IMAGENET1K_V2),
}


def build_network(name, classes, pretrained=False, ordinal=False):
    from .coral import CoralHead

    if name not in BACKBONES or (ordinal and name != "resnet50"):
        raise ValueError("Unsupported backbone/head combination")
    builder, weights = BACKBONES[name]
    network = builder(weights=weights if pretrained else None)
    if hasattr(network, "classifier"):
        width = network.classifier[-1].in_features
        network.classifier[-1] = nn.Linear(width, classes)
    else:
        width = network.fc.in_features
        network.fc = CoralHead(width, classes) if ordinal else nn.Linear(width, classes)
    return network


def head_for(network):
    return network.fc if hasattr(network, "fc") else network.classifier

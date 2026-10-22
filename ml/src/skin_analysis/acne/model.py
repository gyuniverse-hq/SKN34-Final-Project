"""Identical linear binary heads; strict NIA loading before head replacement."""

import torch
from torch import nn
from torchvision.models import ResNet50_Weights, resnet50

from .common import ARCHITECTURE, PREPROCESSING, file_hash, read_json


class AcneModel(nn.Module):
    def __init__(self, backbone=None, head_seed=42):
        super().__init__()
        self.backbone = backbone if backbone is not None else resnet50(weights=None)
        self.backbone.fc = nn.Identity()
        with torch.random.fork_rng(devices=[]):
            torch.manual_seed(head_seed)
            self.head = nn.Linear(2048, 1)
        self.set_stage(True)

    def forward(self, images):
        return self.head(self.backbone(images))

    def set_stage(self, frozen):
        self.backbone.requires_grad_(False)
        if not frozen:
            self.backbone.layer4.requires_grad_(True)
        self.head.requires_grad_(True)
        self.train(self.training)

    def train(self, mode=True):
        super().train(mode)
        # eval also prevents accidental running-stat changes in frozen layers.
        self.backbone.eval()
        return self


def initialize(source, config):
    if source == "imagenet":
        backbone = resnet50(weights=ResNet50_Weights.IMAGENET1K_V2)
        cached = torch.hub.get_dir() + "/checkpoints/resnet50-11ad3fa6.pth"
        provenance = {"source": source, "weights": "IMAGENET1K_V2",
                      "sha256": file_hash(cached)}
    elif source == "nia":
        setup = config["initialization"]
        matches = [r for r in read_json(setup["nia_config"])["models"]
                   if r["task"] == setup["nia_task"]]
        if len(matches) != 1:
            raise ValueError("Exactly one evidenced NIA initialization required")
        record = matches[0]
        sha = file_hash(record["checkpoint"])
        if sha != record["sha256"]:
            raise ValueError("NIA initialization hash mismatch")
        checkpoint = torch.load(record["checkpoint"], weights_only=True, map_location="cpu")
        state = checkpoint["model_state"]
        if any(not torch.isfinite(value).all() for value in state.values()):
            raise ValueError("Non-finite NIA initialization")
        backbone = resnet50(weights=None, num_classes=state["fc.weight"].shape[0])
        backbone.load_state_dict(state, strict=True)
        provenance = {"source": source, "task": record["task"], "sha256": sha,
                      "original_sha256": record.get("original_sha256"),
                      "evidence": record["source"], "discarded_keys": ["fc.weight", "fc.bias"]}
    else:
        raise ValueError("Initialization must be imagenet or nia")
    return AcneModel(backbone, config["train"]["seed"]), provenance


def load_bundle(path):
    bundle = torch.load(path, weights_only=True, map_location="cpu")
    if (bundle.get("architecture") != ARCHITECTURE
            or bundle.get("preprocessing") != PREPROCESSING
            or bundle.get("class_mapping") != {"normal": 0, "acne": 1}
            or bundle.get("score_type") != "sigmoid_uncalibrated"
            or not 0 < bundle.get("threshold", 0) < 1):
        raise ValueError("Incompatible acne checkpoint contract")
    model = AcneModel()
    model.load_state_dict(bundle["model_state"], strict=True)
    if any(not torch.isfinite(v).all() for v in model.state_dict().values()):
        raise ValueError("Non-finite acne checkpoint")
    return model.eval().requires_grad_(False), bundle

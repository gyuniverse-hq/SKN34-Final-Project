"""Offline synthetic ResNet/CUDA smoke check; never trains on facial data."""

import argparse
import tempfile
import time
from pathlib import Path

import torch
from torch import nn
from torch.utils.data import DataLoader, TensorDataset

from .config import DEFAULT_CONFIG, load_config, write_json
from .model import ARCHITECTURE, SkinAnalysisModel
from .runtime import (
    cpu_tree,
    environment_metadata,
    load_checkpoint,
    model_from_checkpoint,
    save_checkpoint,
    seed_all,
    select_cuda,
)
from .train import train_epoch
from .transforms import PREPROCESSING


def run_smoke(config: dict, cuda: bool = False) -> dict:
    device = select_cuda(config["train"]["device_uuid"]) if cuda else torch.device("cpu")
    seed_all(42)
    torch.set_num_threads(2)
    started = time.perf_counter()
    model = SkinAnalysisModel(3, pretrained=False).to(device)
    images = torch.randn(2, 3, 224, 224)
    labels = torch.tensor([[1.0, 1.0, 0.0], [0.0, 0.0, 1.0]])
    loader = DataLoader(TensorDataset(images, labels, torch.arange(2)), batch_size=2)
    scaler = torch.amp.GradScaler("cuda", enabled=cuda)
    losses = []
    if cuda:
        torch.cuda.reset_peak_memory_stats(device)
    for frozen in (True, False):
        model.set_stage(frozen)
        optimizer = torch.optim.AdamW(
            filter(lambda p: p.requires_grad, model.parameters()), lr=1e-5
        )
        losses.append(
            train_epoch(model, loader, optimizer, nn.BCEWithLogitsLoss(), device, scaler, 32, cuda)
        )
    model.eval()
    with torch.inference_mode():
        expected = model(images.to(device)).sigmoid().cpu()
    checkpoint = {
        "schema_version": 1,
        "kind": "smoke",
        "architecture": ARCHITECTURE,
        "classes": ["synthetic-a", "synthetic-b", "synthetic-normal"],
        "preprocessing": PREPROCESSING,
        "score_type": "sigmoid_uncalibrated",
        "model_state": cpu_tree(model.state_dict()),
    }
    with tempfile.TemporaryDirectory(prefix="skin-smoke-") as temporary:
        path = Path(temporary) / "smoke.pt"
        save_checkpoint(path, checkpoint)
        restored = model_from_checkpoint(load_checkpoint(path), device)
        with torch.inference_mode():
            actual = restored(images.to(device)).sigmoid().cpu()
        torch.testing.assert_close(actual, expected, atol=1e-6, rtol=0)
    result = {
        "status": "passed",
        "synthetic_only": True,
        "pretrained": False,
        "batch_size": 2,
        "input_size": [224, 224],
        "stage_bce": losses,
        "seconds": time.perf_counter() - started,
        "environment": environment_metadata(),
        "amp": cuda,
        "reload_max_absolute_error": float((actual - expected).abs().max()),
        "peak_allocated_bytes": torch.cuda.max_memory_allocated(device) if cuda else None,
    }
    write_json(Path(config["audit"]["output"]).parent / "smoke.json", result)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", default=str(DEFAULT_CONFIG))
    parser.add_argument("--cuda", action="store_true")
    args = parser.parse_args()
    print(run_smoke(load_config(args.config), args.cuda))


if __name__ == "__main__":
    main()

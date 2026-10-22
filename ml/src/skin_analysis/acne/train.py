"""Matched-budget binary A/B training; never reads internal test/audit predictions."""

import argparse
import importlib.metadata
import time
from pathlib import Path

import torch
from torch import nn

from ..dataset import make_loader
from ..runtime import capture_rng, cpu_tree, restore_rng, save_checkpoint, seed_all, select_cuda
from ..train import predict_loader, train_epoch
from .common import (
    ARCHITECTURE,
    PREPROCESSING,
    digest,
    file_hash,
    load_config,
    load_manifest,
    write_json,
)
from .data import AcneDataset
from .metrics import binary_metrics
from .model import AcneModel, initialize


def source_fingerprint():
    folder = Path(__file__).parent
    paths = [folder / f"{name}.py" for name in ("train", "data", "model", "common", "metrics")]
    paths += [folder.parent / f"{name}.py" for name in ("train", "dataset", "runtime")]
    return digest({str(p.relative_to(folder.parent)): file_hash(p) for p in paths})


def optimizer_for(model, settings, frozen):
    model.set_stage(frozen)
    groups = [{"params": model.head.parameters(), "lr": settings["head_lr"]
               if frozen else settings["finetune_head_lr"]}]
    if not frozen:
        groups.append({"params": model.backbone.layer4.parameters(), "lr": settings["backbone_lr"]})
    optimizer = torch.optim.AdamW(groups, weight_decay=settings["weight_decay"])
    scheduler = None if frozen else torch.optim.lr_scheduler.CosineAnnealingLR(
        optimizer, T_max=settings["finetune_epochs"], eta_min=1e-7)
    return optimizer, scheduler


def train(config, source, resume=None):
    settings = config["train"]
    if (settings["effective_batch"] % settings["batch_size"] or settings["freeze_epochs"] < 1
            or settings["finetune_epochs"] < 1 or settings["num_workers"] < 0):
        raise ValueError("Invalid batch/stage/worker configuration")
    manifest = load_manifest(config)
    output = Path(settings["output"]) / f"{source}-seed-{settings['seed']}"
    if not resume and any((output / p).exists() for p in ("best.pt", "last.pt")):
        raise FileExistsError("Existing experiment; choose --resume or a new output")
    device = select_cuda(settings["device_uuid"])
    torch.set_num_threads(4)
    seed_all(settings["seed"])
    environment = {"source_hash": source_fingerprint(), "packages":
                   {p: importlib.metadata.version(p) for p in
                    ("torch", "torchvision", "numpy", "pillow", "scikit-learn")},
                   "gpu": torch.cuda.get_device_name(device), "cuda_runtime": torch.version.cuda}
    checkpoint = torch.load(resume, weights_only=True, map_location="cpu") if resume else None
    if checkpoint:
        if (checkpoint.get("architecture") != ARCHITECTURE
                or checkpoint["manifest_fingerprint"] != manifest["fingerprint"]
                or checkpoint["train_config"] != settings or checkpoint["source"] != source
                or checkpoint["environment"] != environment or not (output / "best.pt").exists()):
            raise ValueError("Resume requires matching data, config, environment and best.pt")
        model, provenance = AcneModel(), checkpoint["initialization"]
        model.load_state_dict(checkpoint["model_state"], strict=True)
    else:
        model, provenance = initialize(source, config)
    model = model.to(device)
    # Isolate augmentation/shuffle RNG from differing initialization constructors.
    seed_all(settings["seed"])
    generator = torch.Generator().manual_seed(settings["seed"])
    train_data, valid_data = AcneDataset(manifest, "train", True), AcneDataset(manifest, "valid")
    train_loader = make_loader(train_data, settings["batch_size"], settings["num_workers"],
                               settings["seed"], shuffle=True, generator=generator)
    valid_loader = make_loader(valid_data, settings["batch_size"], settings["num_workers"],
                               settings["seed"])
    criterion = nn.BCEWithLogitsLoss()  # No double compensation for balanced binary labels.
    scaler = torch.amp.GradScaler("cuda", enabled=settings["amp"])
    start = checkpoint["epoch"] + 1 if checkpoint else 0
    history = checkpoint["history"] if checkpoint else []
    best_key = tuple(checkpoint["best_key"]) if checkpoint else (-1., -float("inf"))
    frozen = start < settings["freeze_epochs"]
    optimizer, scheduler = optimizer_for(model, settings, frozen)
    if checkpoint:
        if checkpoint["stage"] == ("head" if frozen else "layer4"):
            optimizer.load_state_dict(checkpoint["optimizer_state"])
            if scheduler:
                scheduler.load_state_dict(checkpoint["scheduler_state"])
        scaler.load_state_dict(checkpoint["scaler_state"])
        restore_rng(checkpoint["rng_state"], generator)
    total = settings["freeze_epochs"] + settings["finetune_epochs"]
    try:
        for epoch in range(start, total):
            now_frozen = epoch < settings["freeze_epochs"]
            if now_frozen != frozen:
                frozen = now_frozen
                optimizer, scheduler = optimizer_for(model, settings, frozen)
            torch.cuda.reset_peak_memory_stats(device)
            started = time.perf_counter()
            loss = train_epoch(model, train_loader, optimizer, criterion, device, scaler,
                               settings["effective_batch"], settings["amp"])
            targets, scores, valid_loss = predict_loader(model, valid_loader, device,
                                                         criterion, amp=False)
            metrics = binary_metrics(targets, scores)
            key = (metrics["macro_f1"], -valid_loss)
            improved = key > best_key
            if improved:
                best_key = key
            if scheduler:
                scheduler.step()
            torch.cuda.synchronize(device)
            row = {"epoch": epoch + 1, "stage": "head" if frozen else "layer4",
                   "train_bce": loss, "valid_bce": valid_loss, "validation": metrics,
                   "seconds": time.perf_counter() - started,
                   "peak_allocated_bytes": torch.cuda.max_memory_allocated(device),
                   "amp_overflow_retries": model._amp_overflow_retries}
            history.append(row)
            saved = {
                "architecture": ARCHITECTURE, "preprocessing": PREPROCESSING,
                "class_mapping": {"normal": 0, "acne": 1}, "score_type": "sigmoid_uncalibrated",
                "threshold": .5, "source": source, "initialization": provenance,
                "manifest_fingerprint": manifest["fingerprint"], "train_config": settings,
                "environment": environment, "epoch": epoch, "stage": row["stage"],
                "model_state": cpu_tree(model.state_dict()),
                "optimizer_state": cpu_tree(optimizer.state_dict()),
                "scheduler_state": scheduler.state_dict() if scheduler else None,
                "scaler_state": scaler.state_dict(), "rng_state": capture_rng(generator),
                "best_key": list(best_key), "history": history,
                "validation_status": "synthetic_only_person_independence_unverified",
                "limitations": manifest["limitations"],
            }
            if improved:
                save_checkpoint(output / "best.pt", saved)
            save_checkpoint(output / "last.pt", saved)
            write_json(output / "history.json", history)
            print(f"{source} {epoch + 1}/{total} {row['stage']} "
                  f"train={loss:.4f} valid={valid_loss:.4f} "
                  f"macroF1={metrics['macro_f1']:.4f} sec={row['seconds']:.1f}", flush=True)
    finally:
        train_data.close()
        valid_data.close()
    write_json(output / "complete.json", {"epochs": len(history), "best_key": list(best_key),
                                          "manifest_fingerprint": manifest["fingerprint"]})
    return output


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", default=None)
    parser.add_argument("--source", choices=["imagenet", "nia"], required=True)
    parser.add_argument("--resume")
    args = parser.parse_args()
    config = load_config(args.config) if args.config else load_config()
    print(train(config, args.source, args.resume))


if __name__ == "__main__":
    main()

"""Two-stage training. A fresh, approved dataset audit is mandatory."""

import argparse
import math
import time
from pathlib import Path

import numpy as np
import torch
from torch import nn

from .audit import DataContractError, require_approved
from .config import DEFAULT_CONFIG, load_config, write_json
from .dataset import SkinDataset, make_loader
from .metrics import classification_metrics
from .model import ARCHITECTURE, WEIGHTS, SkinAnalysisModel
from .runtime import (
    capture_rng,
    cpu_tree,
    environment_metadata,
    load_checkpoint,
    restore_rng,
    save_checkpoint,
    seed_all,
    select_cuda,
)
from .transforms import PREPROCESSING


def positive_weights(labels, cap: float = 20.0) -> torch.Tensor:
    labels = np.asarray(labels)
    if labels.ndim != 2 or not np.isin(labels, [0, 1]).all() or not np.isfinite(cap) or cap <= 0:
        raise ValueError("Complete binary training labels and a positive weight cap are required")
    positive = labels.sum(axis=0)
    negative = len(labels) - positive
    if (positive == 0).any() or (negative == 0).any():
        raise ValueError("Every training class needs both positive and negative examples")
    return torch.tensor(np.minimum(negative / positive, cap), dtype=torch.float32)


def train_epoch(
    model, loader, optimizer, criterion, device, scaler, effective_batch: int, amp: bool
) -> float:
    model.train()
    optimizer.zero_grad(set_to_none=True)
    micro_batch = getattr(loader, "micro_batch_size", loader.batch_size)
    if not len(loader.dataset) or micro_batch is None or effective_batch % micro_batch:
        raise ValueError("Nonempty dataset and a micro batch dividing the effective batch required")
    model._amp_overflow_retries = 0
    seen, group_seen, weighted_loss = 0, 0, 0.0
    group_target = min(effective_batch, len(loader.dataset))
    window = []

    def optimize_window(batches, samples):
        # Match SAM recovery: failed forwards must not persist BN/RNG updates.
        before_bn = [
            (b, b.detach().clone())
            for m in model.modules()
            if isinstance(m, nn.modules.batchnorm._BatchNorm)
            for b in m.buffers(recurse=False)
        ]
        before_cpu = torch.get_rng_state()
        before_cuda = torch.cuda.get_rng_state(device) if device.type == "cuda" else None

        def rewind():
            with torch.no_grad():
                for buffer, value in before_bn:
                    buffer.copy_(value)
            torch.set_rng_state(before_cpu)
            if before_cuda is not None:
                torch.cuda.set_rng_state(before_cuda, device)

        # FP16 overflows are recoverable. Replay the same accumulation window at a smaller
        # scale, without dropping its labels or applying a partial optimizer update.
        for attempt in range(17):
            optimizer.zero_grad(set_to_none=True)
            window_loss = 0.0
            for cpu_images, cpu_targets in batches:
                images = cpu_images.to(device, non_blocking=True)
                targets = cpu_targets.to(device, non_blocking=True)
                with torch.amp.autocast(device.type, dtype=torch.float16, enabled=amp):
                    loss = criterion(model(images), targets)
                if not torch.isfinite(loss):
                    raise RuntimeError("Non-finite training loss")
                scaler.scale(loss * (len(images) / samples)).backward()
                window_loss += float(loss.detach()) * len(images)
            scaler.unscale_(optimizer)
            norm = nn.utils.clip_grad_norm_(model.parameters(), 1.0)
            if torch.isfinite(norm):
                scaler.step(optimizer)
                scaler.update()
                optimizer.zero_grad(set_to_none=True)
                return window_loss
            if not scaler.is_enabled() or attempt == 16:
                rewind()
                optimizer.zero_grad(set_to_none=True)
                raise RuntimeError("Non-finite training gradients after AMP scale recovery")
            rewind()
            scaler.update(new_scale=scaler.get_scale() * 0.5)
            model._amp_overflow_retries += 1
        raise RuntimeError("Unreachable accumulation state")

    for images, targets, _ in loader:
        batch = len(images)
        window.append((images, targets))
        seen += batch
        group_seen += batch
        if group_seen == group_target:
            weighted_loss += optimize_window(window, group_target)
            window = []
            group_seen = 0
            group_target = min(effective_batch, len(loader.dataset) - seen)
    return weighted_loss / seen


@torch.inference_mode()
def predict_loader(model, loader, device, criterion=None, amp: bool = False):
    model.eval()
    targets_list, scores_list, index_list = [], [], []
    total_loss = 0.0
    for images, targets, indices in loader:
        images, targets = (
            images.to(device, non_blocking=True),
            targets.to(device, non_blocking=True),
        )
        with torch.amp.autocast(device.type, dtype=torch.float16, enabled=amp):
            logits = model(images)
            if criterion is not None:
                total_loss += float(criterion(logits, targets)) * len(images)
        targets_list.append(targets.cpu().numpy())
        scores_list.append(logits.float().sigmoid().cpu().numpy())
        index_list.extend(indices.tolist())
    order = np.argsort(index_list)
    return (
        np.concatenate(targets_list)[order],
        np.concatenate(scores_list)[order],
        total_loss / len(loader.dataset) if criterion is not None else None,
    )


def make_optimizer(model: SkinAnalysisModel, settings: dict, frozen: bool):
    model.set_stage(frozen)
    if frozen:
        groups = [{"params": model.head.parameters(), "lr": settings["head_lr"]}]
    else:
        groups = [
            {"params": model.backbone.parameters(), "lr": settings["backbone_lr"]},
            {"params": model.head.parameters(), "lr": settings["finetune_head_lr"]},
        ]
    optimizer = torch.optim.AdamW(groups, weight_decay=settings["weight_decay"])
    scheduler = (
        None
        if frozen
        else torch.optim.lr_scheduler.CosineAnnealingLR(
            optimizer, T_max=settings["finetune_epochs"], eta_min=settings["eta_min"]
        )
    )
    return optimizer, scheduler


def train(config: dict, resume: str | None = None) -> dict:
    settings = config["train"]
    if (
        settings["batch_size"] != 32
        or settings["freeze_epochs"] < 1
        or settings["finetune_epochs"] < 1
        or settings["patience"] < 1
        or settings["num_workers"] < 0
    ):
        raise ValueError("Use effective batch 32, positive stage epochs/patience and >=0 workers")
    if not 0 < settings["min_delta"] < 1:
        raise ValueError("min_delta must be in (0,1)")
    report, manifest = require_approved(config)
    output = Path(settings["output"])
    if resume is None and any((output / name).exists() for name in ("best.pt", "last.pt")):
        raise FileExistsError("Run already exists; use --resume or a new train.output")
    checkpoint = load_checkpoint(resume) if resume else None
    if checkpoint and (
        checkpoint["manifest_fingerprint"] != manifest["fingerprint"]
        or checkpoint["classes"] != manifest["classes"]
        or checkpoint["train_config"] != settings
    ):
        raise ValueError("Resume dataset, classes or training configuration changed")
    if checkpoint and not (output / "best.pt").is_file():
        raise ValueError("Resume requires the matching best.pt in train.output")
    device = select_cuda(settings["device_uuid"])
    seed_all(settings["seed"])
    generator = torch.Generator().manual_seed(settings["seed"])
    train_data = SkinDataset(manifest, "train", training=True)
    valid_data = SkinDataset(manifest, "valid")
    weights = positive_weights(
        [r["labels"] for r in train_data.records], settings["pos_weight_cap"]
    )
    criterion = nn.BCEWithLogitsLoss(pos_weight=weights.to(device))
    model = SkinAnalysisModel(len(manifest["classes"]), pretrained=checkpoint is None).to(device)
    scaler = torch.amp.GradScaler("cuda", enabled=settings["amp"])
    start = checkpoint["epoch"] + 1 if checkpoint else 0
    total_epochs = settings["freeze_epochs"] + settings["finetune_epochs"]
    frozen = start < settings["freeze_epochs"]
    optimizer, scheduler = make_optimizer(model, settings, frozen)
    best_ap, best_loss = -1.0, math.inf
    early_best, stale = -1.0, 0
    history = []
    micro_batch = settings["batch_size"]
    if checkpoint:
        model.load_state_dict(checkpoint["model_state"])
        same_stage = checkpoint["stage"] == ("freeze" if frozen else "finetune")
        if same_stage:
            optimizer.load_state_dict(checkpoint["optimizer_state"])
            if scheduler:
                scheduler.load_state_dict(checkpoint["scheduler_state"])
        scaler.load_state_dict(checkpoint["scaler_state"])
        best_ap, best_loss = checkpoint["best_ap"], checkpoint["best_loss"]
        early_best, stale = (
            (checkpoint["early_best"], checkpoint["stale"]) if same_stage else (best_ap, 0)
        )
        history, micro_batch = checkpoint["history"], checkpoint["micro_batch"]
        restore_rng(checkpoint["rng_state"], generator)
        if stale >= settings["patience"]:
            return {"status": "early_stopped", "epochs": start, "best_ap": best_ap}
    environment = environment_metadata()
    if checkpoint and (
        checkpoint["environment"]["packages"] != environment["packages"]
        or checkpoint["environment"]["source_hash"] != environment["source_hash"]
    ):
        raise ValueError("Resume requires the same locked packages and training source files")
    for epoch in range(start, total_epochs):
        now_frozen = epoch < settings["freeze_epochs"]
        if now_frozen != frozen:
            frozen = now_frozen
            optimizer, scheduler = make_optimizer(model, settings, frozen)
            early_best, stale = best_ap, 0
        started = time.perf_counter()
        snapshot = {
            "model": cpu_tree(model.state_dict()),
            "optimizer": cpu_tree(optimizer.state_dict()),
            "scaler": scaler.state_dict(),
            "rng": capture_rng(generator),
        }
        torch.cuda.reset_peak_memory_stats(device)
        while True:
            loader = make_loader(
                train_data,
                micro_batch,
                settings["num_workers"],
                settings["seed"],
                shuffle=True,
                generator=generator,
            )
            valid_loader = make_loader(
                valid_data, micro_batch, settings["num_workers"], settings["seed"]
            )
            try:
                training_loss = train_epoch(
                    model,
                    loader,
                    optimizer,
                    criterion,
                    device,
                    scaler,
                    settings["batch_size"],
                    settings["amp"],
                )
                targets, scores, validation_loss = predict_loader(
                    model, valid_loader, device, criterion, settings["amp"]
                )
                break
            except torch.cuda.OutOfMemoryError:
                optimizer.zero_grad(set_to_none=True)
                if micro_batch <= 8:
                    raise
                model.load_state_dict(snapshot["model"])
                optimizer.load_state_dict(snapshot["optimizer"])
                scaler.load_state_dict(snapshot["scaler"])
                restore_rng(snapshot["rng"], generator)
                micro_batch //= 2
                torch.cuda.empty_cache()
                print(f"CUDA OOM: retrying the entire epoch with micro batch {micro_batch}")
        metrics = classification_metrics(targets, scores, manifest["classes"])
        ap = metrics["macro_ap"]
        if ap is None or metrics["macro_ap_evaluable_classes"] != len(manifest["classes"]):
            raise RuntimeError("All validation classes must have evaluable AP")
        improved = ap > best_ap or (ap == best_ap and validation_loss < best_loss)
        if improved:
            best_ap, best_loss = ap, validation_loss
        if not frozen:
            if ap >= early_best + settings["min_delta"]:
                early_best, stale = ap, 0
            else:
                stale += 1
        if scheduler:
            scheduler.step()
        torch.cuda.synchronize(device)
        row = {
            "epoch": epoch + 1,
            "stage": "freeze" if frozen else "finetune",
            "train_bce": training_loss,
            "valid_bce": validation_loss,
            "valid_macro_ap": ap,
            "valid_macro_f1_at_05": metrics["macro_f1"],
            "valid_micro_f1_at_05": metrics["micro_f1"],
            "micro_batch": micro_batch,
            "amp_overflow_retries": model._amp_overflow_retries,
            "seconds": time.perf_counter() - started,
            "peak_allocated_bytes": torch.cuda.max_memory_allocated(device),
            "peak_reserved_bytes": torch.cuda.max_memory_reserved(device),
        }
        history.append(row)
        saved = {
            "schema_version": 1,
            "kind": "training",
            "architecture": ARCHITECTURE,
            "weights": WEIGHTS,
            "score_type": "sigmoid_uncalibrated",
            "classes": manifest["classes"],
            "preprocessing": PREPROCESSING,
            "manifest_fingerprint": manifest["fingerprint"],
            "evidence": manifest["evidence"],
            "split_manifest": [
                {k: r[k] for k in ("path", "split", "group_id")} for r in manifest["records"]
            ],
            "train_config": settings,
            "environment": environment,
            "epoch": epoch,
            "stage": row["stage"],
            "model_state": cpu_tree(model.state_dict()),
            "optimizer_state": cpu_tree(optimizer.state_dict()),
            "scheduler_state": scheduler.state_dict() if scheduler else None,
            "scaler_state": scaler.state_dict(),
            "rng_state": capture_rng(generator),
            "best_ap": best_ap,
            "best_loss": best_loss,
            "early_best": early_best,
            "stale": stale,
            "micro_batch": micro_batch,
            "history": history,
            "pos_weight": weights.tolist(),
            "thresholds": None,
        }
        if improved:
            save_checkpoint(output / "best.pt", saved)
        save_checkpoint(output / "last.pt", saved)
        write_json(output / "history.json", history)
        write_json(output / "data_audit.json", report)
        print(f"Epoch {epoch + 1}: train BCE {training_loss:.4f}, valid macro AP {ap:.4f}")
        if not frozen and stale >= settings["patience"]:
            break
    return {
        "status": "complete",
        "epochs": len(history),
        "best_ap": best_ap,
        "best_checkpoint": str(output / "best.pt"),
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", default=str(DEFAULT_CONFIG))
    parser.add_argument("--resume")
    args = parser.parse_args()
    try:
        print(train(load_config(args.config), args.resume))
    except (DataContractError, ValueError, OSError) as exc:
        parser.exit(2, f"Training refused: {exc}\n")


if __name__ == "__main__":
    main()

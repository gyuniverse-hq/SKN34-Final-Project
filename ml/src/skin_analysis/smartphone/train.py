"""Train only three ImageNet-initialized, independent smartphone classifiers."""

import argparse
import importlib.metadata
import json
import time
from pathlib import Path

import numpy as np
import torch
from server.nia.metrics import classification
from torch import nn
from torch.utils.data import DataLoader
from torchvision.models import ResNet50_Weights, resnet50

from ..dataset import seed_worker
from ..runtime import capture_rng, cpu_tree, restore_rng, save_checkpoint, seed_all, select_cuda
from ..train import train_epoch
from .common import (
    DEFAULT_CONFIG,
    PREPROCESSING,
    TASKS,
    classification_contract,
    digest,
    file_hash,
    load_config,
    load_manifest,
    write_json,
)
from .coral import ARCHITECTURE as CORAL_ARCHITECTURE
from .coral import DECODING, CoralHead, CoralLoss, decode_coral
from .data import GradeDataset
from .losses import ClassBalancedFocalLoss, WeightedFocalLoss
from .ordinal_loss import WeightedOrdinalCdfLoss
from .sam import optimization_spec
from .sam import train_epoch as sam_train_epoch


class GradeModel(nn.Module):
    def __init__(
        self,
        classes,
        pretrained=False,
        ordinal=False,
        freeze_bn_stats=False,
        finetune_scope="all",
    ):
        super().__init__()
        if finetune_scope not in ("all", "layer4"):
            raise ValueError("Finetune scope must be all or layer4")
        self.freeze_bn_stats = freeze_bn_stats
        self.finetune_scope = finetune_scope
        self.network = resnet50(weights=ResNet50_Weights.IMAGENET1K_V2 if pretrained else None)
        self.network.fc = CoralHead(2048, classes) if ordinal else nn.Linear(2048, classes)
        self.frozen = False

    def set_stage(self, frozen):
        self.frozen = frozen
        self.network.requires_grad_(not frozen and self.finetune_scope == "all")
        if not frozen and self.finetune_scope == "layer4":
            self.network.layer4.requires_grad_(True)
        self.network.fc.requires_grad_(True)

    def train(self, mode=True):
        super().train(mode)
        if mode and self.frozen:
            self.network.eval()
            self.network.fc.train()
        elif mode and self.freeze_bn_stats:
            # Freeze running mean/variance/count only; affine weights stay trainable.
            for module in self.network.modules():
                if isinstance(module, nn.BatchNorm2d):
                    module.eval()
        return self

    def forward(self, images):
        return self.network(images)


def class_weights(labels, classes, cap):
    counts = np.bincount(labels, minlength=classes)
    if len(counts) != classes or (counts == 0).any() or not np.isfinite(cap) or cap < 1:
        raise ValueError("Every training grade and a finite weight cap >= 1 are required")
    weights = np.sqrt(len(labels) / counts)
    weights /= np.dot(weights, counts / len(labels))
    return torch.tensor(np.minimum(weights, cap), dtype=torch.float32)


def criterion_for(labels, classes, settings, device):
    kind = settings.get("loss", "weighted_cross_entropy")
    counts = np.bincount(labels, minlength=classes).tolist()
    if kind == "weighted_cross_entropy":
        weight = class_weights(labels, classes, settings["class_weight_cap"])
        criterion = nn.CrossEntropyLoss(weight=weight.to(device))
        specification = dict(
            kind=kind,
            counts=counts,
            weights=weight.tolist(),
            reduction="sum_weighted_ce / sum_target_weights",
        )
    elif kind == "weighted_focal":
        weight = class_weights(labels, classes, settings["class_weight_cap"])
        criterion = WeightedFocalLoss(weight, gamma=settings["focal_gamma"]).to(device)
        specification = dict(
            kind=kind,
            counts=counts,
            weights=weight.tolist(),
            gamma=settings["focal_gamma"],
            formulation="exclusive_multiclass_softmax",
            reduction="sum_alpha_modulated_ce / sum_target_alpha",
            pt_source="unweighted_cross_entropy",
            weighting="same_capped_inverse_sqrt_frequency_as_wce",
            effective_number_weights_used=False,
        )
    elif kind == "weighted_ordinal_cdf":
        weight = class_weights(labels, classes, settings["class_weight_cap"])
        criterion = WeightedOrdinalCdfLoss(weight).to(device)
        specification = dict(
            kind=kind,
            counts=counts,
            weights=weight.tolist(),
            formulation="sum_squared_cdf_distance_over_K_minus_1_boundaries",
            reduction="sum_alpha_cdf_distance / sum_target_alpha",
            boundary_weights="uniform_unit_cost_not_physical_distances",
            cross_entropy_component=False,
            decoding="softmax_argmax_unchanged",
        )
    elif kind == "class_balanced_focal":
        criterion = ClassBalancedFocalLoss(
            counts, beta=settings["cb_beta"], gamma=settings["focal_gamma"]
        ).to(device)
        specification = dict(
            kind=kind,
            counts=counts,
            weights=criterion.weight.cpu().tolist(),
            beta=settings["cb_beta"],
            gamma=settings["focal_gamma"],
            formulation="exclusive_multiclass_softmax",
            reduction="sum_alpha_modulated_ce / sum_target_alpha",
            legacy_sqrt_class_weights_used=False,
        )
    elif kind == "coral":
        criterion = CoralLoss().to(device)
        specification = dict(
            kind=kind,
            counts=counts,
            formulation="shared_score_cumulative_binary_thresholds",
            reduction="mean_examples_sum_threshold_bce",
            legacy_sqrt_class_weights_used=False,
            threshold_weights="uniform",
        )
    else:
        raise ValueError("Unknown smartphone training loss")
    return criterion, specification


def make_loader(data, settings, generator=None, training=False):
    return DataLoader(
        data,
        batch_size=settings["batch_size"],
        shuffle=training,
        num_workers=settings["num_workers"],
        pin_memory=True,
        persistent_workers=settings["num_workers"] > 0,
        worker_init_fn=seed_worker,
        generator=generator,
    )


@torch.inference_mode()
def predict(model, loader, device, ordinal=False):
    model.eval()
    truth, predicted, probabilities = [], [], []
    total_loss = 0.0
    for images, targets, _ in loader:
        images, targets = images.to(device, non_blocking=True), targets.to(device)
        logits = model(images).float()
        if ordinal:
            total_loss += float(CoralLoss()(logits, targets)) * len(targets)
            labels, scores = decode_coral(logits)
        else:
            total_loss += float(nn.functional.cross_entropy(logits, targets, reduction="sum"))
            labels, scores = logits.argmax(1), logits.softmax(1)
        truth.extend(targets.cpu().tolist())
        predicted.extend(labels.cpu().tolist())
        probabilities.extend(scores.cpu().tolist())
    return truth, predicted, probabilities, total_loss / len(truth)


def evaluate_training(model, loader, device, classes, generator, ordinal=False):
    # Diagnostic evaluation must not alter subsequent training RNG or BN buffers.
    state = capture_rng(generator)
    try:
        truth, predicted, _, loss = predict(model, loader, device, ordinal=ordinal)
        metrics = classification(truth, predicted, classes)
        return dict(
            train_eval_loss=loss,
            **{
                f"train_eval_{k}": metrics[k] for k in ("accuracy", "macro_f1", "mae", "within_one")
            },
        )
    finally:
        restore_rng(state, generator)


def optimizer_for(model, settings, frozen):
    model.set_stage(frozen)
    groups = [
        {
            "params": model.network.fc.parameters(),
            "lr": settings["head_lr"] if frozen else settings["finetune_head_lr"],
        }
    ]
    if not frozen:
        groups.append(
            {
                "params": [
                    p
                    for n, p in model.network.named_parameters()
                    if not n.startswith("fc.") and p.requires_grad
                ],
                "lr": settings["backbone_lr"],
            }
        )
    optimizer = torch.optim.AdamW(groups, weight_decay=settings["weight_decay"])
    scheduler = (
        None
        if frozen
        else torch.optim.lr_scheduler.CosineAnnealingLR(
            optimizer, T_max=settings["finetune_epochs"], eta_min=1e-7
        )
    )
    return optimizer, scheduler


def verify_crops(manifest):
    # Validate all audited bytes before any epoch, not just before data preparation.
    root = Path(manifest["root"])
    if "pixel_cache" in manifest:
        cache = manifest["pixel_cache"]
        path = (root / cache["path"]).resolve(strict=True)
        if not path.is_relative_to(root) or file_hash(path) != cache["sha256"]:
            raise ValueError("Audited pixel cache has changed")
        return
    checked = {}
    for record in manifest["records"]:
        path = (root / record["path"]).resolve(strict=True)
        if not path.is_relative_to(root):
            raise ValueError("Crop path escapes the audited root")
        if path not in checked:
            checked[path] = file_hash(path)
        if checked[path] != record["crop_sha256"]:
            raise ValueError("Audited crop bytes have changed")


def require_coral_gate(config, manifest, task):
    if config["train"].get("loss") != "coral" or task == "pore":
        return
    path = Path(config["train"]["output"]) / "pore-comparison.json"
    if task == "all" or not path.is_file():
        raise ValueError("Train pore first and record its validation comparison before expansion")
    result = json.loads(path.read_text(encoding="utf-8"))
    # Use the recorded policy and metrics together, not just a manually changed flag.
    from .focal_compare import qualifies

    if (
        result.get("schema") != "nia-coral-validation-v1"
        or result.get("data_fingerprint") != manifest["fingerprint"]
        or result.get("selection_policy") != config["comparison"]["policy"]
        or result.get("test_set_evaluated") is not False
        or result.get("qualifies_for_expansion") is not True
        or not qualifies(result["results"]["ce"]["metrics"], result["results"]["coral"]["metrics"])
    ):
        raise ValueError("Pore validation must pass the predefined CORAL expansion policy")


def train_task(config, manifest, task, device, resume=None):
    require_coral_gate(config, manifest, task)
    settings = config["train"]
    classes, mapping, exported_task = classification_contract(settings, task)
    optimizer_spec = optimization_spec(settings)
    ordinal = settings.get("loss") == "coral"
    output = Path(settings["output"]) / task
    if not resume and output.exists():
        raise FileExistsError("Experiment already exists; choose explicit resume or a new output")
    output.mkdir(parents=True, exist_ok=True)
    seed_all(settings["seed"])
    environment = {
        "packages": {
            p: importlib.metadata.version(p)
            for p in ("torch", "torchvision", "numpy", "pillow", "scikit-learn")
        },
        "source_hash": digest(
            {p.name: file_hash(p) for p in sorted(Path(__file__).parent.glob("*.py"))}
        ),
        "gpu": torch.cuda.get_device_name(device),
        "cuda": torch.version.cuda,
    }
    checkpoint = torch.load(resume, map_location="cpu", weights_only=True) if resume else None
    if checkpoint and (
        checkpoint["manifest_fingerprint"] != manifest["fingerprint"]
        or checkpoint["train_config"] != settings
        or checkpoint["task"] != exported_task
        or checkpoint["environment"] != environment
        or not (output / "best.pt").is_file()
    ):
        raise ValueError("Resume requires identical source, data, config, environment and best.pt")
    model = GradeModel(
        classes,
        pretrained=not bool(checkpoint),
        ordinal=ordinal,
        freeze_bn_stats=settings.get("freeze_bn_stats", False),
        finetune_scope=settings.get("finetune_scope", "all"),
    ).to(device)
    if checkpoint:
        model.network.load_state_dict(checkpoint["model_state"], strict=True)
    initial_weights = (
        Path(torch.hub.get_dir()) / "checkpoints" / Path(ResNet50_Weights.IMAGENET1K_V2.url).name
    )
    initialization = (
        checkpoint["initialization"]
        if checkpoint
        else dict(
            source="torchvision/ResNet50_Weights.IMAGENET1K_V2",
            sha256=file_hash(initial_weights),
            nia_weights_used=False,
        )
    )
    seed_all(settings["seed"])
    generator = torch.Generator().manual_seed(settings["seed"])
    training = GradeDataset(manifest, task, "train", training=True, target_mapping=mapping)
    validation = GradeDataset(manifest, task, "valid", target_mapping=mapping)
    train_loader = make_loader(training, settings, generator, training=True)
    valid_loader = make_loader(validation, settings)
    train_eval_loader = (
        make_loader(
            GradeDataset(manifest, task, "train", training=False, target_mapping=mapping),
            settings,
            torch.Generator().manual_seed(settings["seed"] + 1),
        )
        if settings.get("record_train_metrics", False)
        else None
    )
    criterion, loss_spec = criterion_for(
        [training.target(r) for r in training.records], classes, settings, device
    )
    scaler = torch.amp.GradScaler("cuda", enabled=settings["amp"])
    start = checkpoint["epoch"] + 1 if checkpoint else 0
    history = checkpoint["history"] if checkpoint else []
    best_key = tuple(checkpoint["best_key"]) if checkpoint else (-1.0, -float("inf"))
    stale = checkpoint["stale"] if checkpoint else 0
    frozen = start < settings["freeze_epochs"]
    optimizer, scheduler = optimizer_for(model, settings, frozen)
    if checkpoint:
        expected_stage = (
            "head"
            if frozen
            else ("layer4" if model.finetune_scope == "layer4" else "full_backbone")
        )
        if checkpoint["stage"] == expected_stage:
            optimizer.load_state_dict(checkpoint["optimizer_state"])
            if scheduler:
                scheduler.load_state_dict(checkpoint["scheduler_state"])
        scaler.load_state_dict(checkpoint["scaler_state"])
        restore_rng(checkpoint["rng_state"], generator)
    total = settings["freeze_epochs"] + settings["finetune_epochs"]
    for epoch in range(start, total):
        started = time.perf_counter()
        now_frozen = epoch < settings["freeze_epochs"]
        if frozen != now_frozen:
            frozen = now_frozen
            stale = 0
            optimizer, scheduler = optimizer_for(model, settings, frozen)
        epoch_runner = sam_train_epoch if optimizer_spec["kind"] == "sam_adamw" else train_epoch
        loss = epoch_runner(
            model,
            train_loader,
            optimizer,
            criterion,
            device,
            scaler,
            settings["effective_batch"],
            settings["amp"],
            **({"rho": settings["sam_rho"]} if optimizer_spec["kind"] == "sam_adamw" else {}),
        )
        truth, predicted, _, valid_loss = predict(model, valid_loader, device, ordinal=ordinal)
        metrics = classification(truth, predicted, classes)
        key = metrics["macro_f1"], -valid_loss
        improved = key > best_key
        stale = 0 if improved else stale + 1
        if improved:
            best_key = key
        if scheduler:
            scheduler.step()
        row = dict(
            task=task,
            epoch=epoch + 1,
            stage="head"
            if frozen
            else ("layer4" if model.finetune_scope == "layer4" else "full_backbone"),
            train_loss=loss,
            valid_loss=valid_loss,
            valid_accuracy=metrics["accuracy"],
            valid_macro_f1=metrics["macro_f1"],
            valid_within_one=metrics["within_one"],
            seconds=time.perf_counter() - started,
            selected=improved,
            amp_overflow_retries=model._amp_overflow_retries,
            trainable_parameters=sum(p.numel() for p in model.parameters() if p.requires_grad),
        )
        if train_eval_loader is not None:
            row.update(
                evaluate_training(model, train_eval_loader, device, classes, generator, ordinal)
            )
        if optimizer_spec["kind"] == "sam_adamw":
            row.update(sam_steps=model._sam_steps, sam_perturbed_loss=model._sam_perturbed_loss)
        history.append(row)
        saved = dict(
            schema="nia-smartphone-training-v1",
            architecture=CORAL_ARCHITECTURE if ordinal else "resnet50",
            decoding=DECODING if ordinal else "softmax_argmax",
            task=exported_task,
            training_device="smartphone",
            resolution=256,
            grades=list(range(classes)),
            preprocessing=PREPROCESSING,
            model_state=cpu_tree(model.network.state_dict()),
            manifest_fingerprint=manifest["fingerprint"],
            train_config=settings,
            initialization=initialization,
            environment=environment,
            epoch=epoch,
            stage=row["stage"],
            history=history,
            best_key=list(best_key),
            stale=stale,
            optimizer_state=cpu_tree(optimizer.state_dict()),
            scheduler_state=scheduler.state_dict() if scheduler else None,
            scaler_state=scaler.state_dict(),
            rng_state=capture_rng(generator),
            selection="validation macro-F1; unweighted validation "
            + ("threshold BCE tie-break" if ordinal else "CE tie-break"),
            loss_spec=loss_spec,
            optimization_spec=optimizer_spec,
            finetune_policy=dict(
                scope=model.finetune_scope,
                freeze_bn_stats=model.freeze_bn_stats,
                bn_running_stats_during_finetune=(
                    "fixed" if model.freeze_bn_stats else "update_all_layers"
                ),
                note="scope controls parameters only; BN statistics are a separate factor",
            ),
        )
        if mapping is not None:
            saved.update(original_to_target=mapping, original_grades=list(range(6)))
        save_checkpoint(output / "last.pt", saved)
        if improved:
            save_checkpoint(output / "best.pt", saved)
        write_json(output / "history.json", history)
        print(json.dumps(row), flush=True)
        if not frozen and stale >= settings["patience"]:
            break
    best = torch.load(output / "best.pt", map_location="cpu", weights_only=True)
    exported = {
        k: best[k]
        for k in (
            "schema",
            "architecture",
            "decoding",
            "task",
            "training_device",
            "resolution",
            "grades",
            "preprocessing",
            "model_state",
            "manifest_fingerprint",
            "initialization",
            "environment",
            "epoch",
            "selection",
            "loss_spec",
            "finetune_policy",
        )
    }
    exported["optimization_spec"] = best.get(
        "optimization_spec", optimization_spec(best["train_config"])
    )
    exported["kind"] = "inference"
    if mapping is not None:
        exported.update(original_to_target=mapping, original_grades=list(range(6)))
    save_checkpoint(output / "inference.bin", exported)
    write_json(
        output / "summary.json",
        dict(
            task=task,
            best_epoch=best["epoch"] + 1,
            epochs_run=len(history),
            best_key=best["best_key"],
            sha256=file_hash(output / "inference.bin"),
        ),
    )
    del train_loader, valid_loader, train_eval_loader, optimizer, model, best, exported, saved
    torch.cuda.empty_cache()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--task", choices=[*TASKS, "all"], default="all")
    parser.add_argument("--resume", type=Path)
    args = parser.parse_args()
    config = load_config(args.config)
    settings = config["train"]
    if (
        settings["freeze_epochs"] < 1
        or settings["finetune_epochs"] < 1
        or settings["patience"] < 1
        or settings["num_workers"] < 0
        or settings["effective_batch"] % settings["batch_size"]
    ):
        raise ValueError("Invalid training budget, loader or batch settings")
    if args.resume and args.task == "all":
        raise ValueError("Resume one explicitly selected task at a time")
    for task in TASKS if args.task == "all" else [args.task]:
        classification_contract(settings, task)
    manifest = load_manifest(config)
    require_coral_gate(config, manifest, args.task)
    verify_crops(manifest)
    device = select_cuda(settings["device_uuid"])
    torch.set_num_threads(4)
    for task in TASKS if args.task == "all" else [args.task]:
        train_task(config, manifest, task, device, args.resume)


if __name__ == "__main__":
    main()

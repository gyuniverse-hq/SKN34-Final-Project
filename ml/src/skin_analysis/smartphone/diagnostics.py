"""Training-only memorization check and matched train/validation diagnostics."""

import argparse
import importlib.metadata
import json
import random
from pathlib import Path

import torch
from torch import nn
from torch.utils.data import DataLoader, TensorDataset
from torchvision.models import resnet50

from ..config import PROJECT_ROOT
from ..runtime import cpu_tree, save_checkpoint, seed_all, select_cuda
from ..train import train_epoch
from .common import file_hash, load_config, load_manifest, write_json
from .coral import load_coral_checkpoint
from .data import GradeDataset
from .focal_compare import verified_metrics
from .train import GradeModel, make_loader, predict, verify_crops

DEFAULT_CONFIG = PROJECT_ROOT / "configs/nia_smartphone_diagnostics.toml"


def choose_balanced_people(records, classes, per_grade, seed):
    if not records or any(r["split"] != "train" for r in records):
        raise ValueError("Memorization selection must use training records only")
    if type(per_grade) is not int or per_grade < 1:
        raise ValueError("Positive samples per grade required")
    rng = random.Random(seed)
    groups = {g: [i for i, r in enumerate(records) if r["truth"] == g] for g in range(classes)}
    order = sorted(groups, key=lambda g: len({records[i]["subject"] for i in groups[g]}))
    chosen, people = [], set()
    for grade in order:
        candidates = groups[grade].copy()
        rng.shuffle(candidates)
        selected = []
        for index in candidates:
            person = records[index]["subject"]
            if person not in people:
                selected.append(index)
                people.add(person)
            if len(selected) == per_grade:
                break
        if len(selected) != per_grade:
            raise ValueError("Not enough distinct training people for balanced selection")
        chosen.extend(selected)
    return sorted(chosen)


def tiny_passed(metrics):
    return metrics["accuracy"] >= 0.99 and metrics["macro_f1"] >= 0.99


def root_for(config):
    return PROJECT_ROOT / config["diagnostics"]["output"]


def tiny(config):
    manifest = load_manifest(config)
    verify_crops(manifest)
    root = root_for(config) / "tiny-ce"
    if root.exists():
        raise FileExistsError("Tiny diagnostic already exists; preserve the recorded run")
    data = GradeDataset(manifest, "pore", "train", training=False)
    spec = config["diagnostics"]
    indices = choose_balanced_people(
        data.records, 6, spec["samples_per_grade"], config["train"]["seed"]
    )
    root.mkdir(parents=True)
    write_json(root / "selected-records.json", [data.records[i] for i in indices])
    device = select_cuda(config["train"]["device_uuid"])
    torch.set_num_threads(4)
    seed_all(config["train"]["seed"])
    model = GradeModel(6, pretrained=True).to(device)
    model.set_stage(False)
    images = torch.stack([data[i][0] for i in indices])
    targets = torch.tensor([data.records[i]["truth"] for i in indices])
    dataset = TensorDataset(images, targets, torch.arange(len(indices)))
    generator = torch.Generator().manual_seed(config["train"]["seed"])
    loader = DataLoader(dataset, batch_size=16, shuffle=True, generator=generator, pin_memory=True)
    evaluation = DataLoader(
        dataset, batch_size=16, generator=torch.Generator().manual_seed(43), pin_memory=True
    )
    optimizer = torch.optim.AdamW(
        [
            dict(params=model.network.fc.parameters(), lr=spec["tiny_head_lr"]),
            dict(
                params=[p for n, p in model.network.named_parameters() if not n.startswith("fc.")],
                lr=spec["tiny_backbone_lr"],
            ),
        ],
        weight_decay=0,
    )
    scaler = torch.amp.GradScaler("cuda", enabled=False)
    history, streak = [], 0
    for epoch in range(spec["tiny_max_epochs"] + 1):
        if epoch:
            train_epoch(model, loader, optimizer, nn.CrossEntropyLoss(), device, scaler, 16, False)
        if epoch not in (0, 1, spec["tiny_max_epochs"]) and epoch % spec["tiny_eval_every"]:
            continue
        truth, predicted, _, loss = predict(model, evaluation, device)
        metrics = verified_metrics(truth, predicted, 6)
        row = dict(
            epoch=epoch, optimizer_steps=epoch * len(loader), unweighted_ce=loss, metrics=metrics
        )
        history.append(row)
        write_json(root / "history.json", history)
        print(
            json.dumps(
                dict(
                    phase="tiny",
                    epoch=epoch,
                    accuracy=metrics["accuracy"],
                    macro_f1=metrics["macro_f1"],
                    ce=loss,
                )
            ),
            flush=True,
        )
        streak = streak + 1 if tiny_passed(metrics) else 0
        if streak >= spec["tiny_success_checks"]:
            break
    save_checkpoint(
        root / "diagnostic-only.pt",
        dict(
            purpose="training_only_sanity_check_not_deployment",
            model_state=cpu_tree(model.network.state_dict()),
            epoch=epoch,
            data_fingerprint=manifest["fingerprint"],
        ),
    )
    result = dict(
        schema="nia-tiny-overfit-v1",
        task="pore",
        seed=config["train"]["seed"],
        records=len(indices),
        subjects=len(indices),
        split="train",
        augmentation=False,
        initial_weights="torchvision/ImageNet1K_V2",
        nia_weights_used=False,
        amp=False,
        weight_decay=0,
        batch_size=16,
        head_lr=spec["tiny_head_lr"],
        backbone_lr=spec["tiny_backbone_lr"],
        max_epochs=spec["tiny_max_epochs"],
        required_success_checks=spec["tiny_success_checks"],
        passed=streak >= spec["tiny_success_checks"],
        test_set_evaluated=False,
        history=history,
    )
    write_json(root / "result.json", result)


def checkpoint_gaps(config):
    manifest = load_manifest(config)
    verify_crops(manifest)
    root = root_for(config)
    destination = root / "checkpoint-gaps.json"
    if destination.exists():
        raise FileExistsError("Checkpoint diagnostics already recorded")
    device = select_cuda(config["train"]["device_uuid"])
    torch.set_num_threads(4)
    data = {
        split: GradeDataset(manifest, "pore", split, training=False) for split in ("train", "valid")
    }
    loaders = {split: make_loader(dataset, config["train"]) for split, dataset in data.items()}
    paths = {
        "ce_batch32": PROJECT_ROOT / "runs/nia-smartphone-seed-42/pore/inference.bin",
        "ce_batch16": PROJECT_ROOT / "runs/nia-smartphone-ce-batch16-seed-42/pore/inference.bin",
        "cb_focal": PROJECT_ROOT / "runs/nia-smartphone-cb-focal-seed-42/pore/inference.bin",
        "coral": PROJECT_ROOT / "runs/nia-smartphone-coral-seed-42/pore/inference.bin",
        "diagnostic_ce_batch16": Path(config["train"]["output"]) / "pore/inference.bin",
    }
    results = {}
    for name, path in paths.items():
        summary = json.loads((path.parent / "summary.json").read_text(encoding="utf-8"))
        if file_hash(path) != summary["sha256"]:
            raise ValueError("Checkpoint changed after training")
        ordinal = name == "coral"
        if ordinal:
            model, checkpoint = load_coral_checkpoint(path, summary["sha256"])
        else:
            checkpoint = torch.load(path, map_location="cpu", weights_only=True)
            model = resnet50(weights=None, num_classes=6)
            model.load_state_dict(checkpoint["model_state"], strict=True)
        if (
            checkpoint["manifest_fingerprint"] != manifest["fingerprint"]
            or checkpoint["task"] != "pore"
        ):
            raise ValueError("Checkpoint diagnostic data mismatch")
        model = model.to(device).eval()
        results[name] = dict(epoch=checkpoint["epoch"] + 1, sha256=summary["sha256"], splits={})
        for split, loader in loaders.items():
            truth, predicted, probabilities, loss = predict(model, loader, device, ordinal=ordinal)
            results[name]["splits"][split] = dict(
                metrics=verified_metrics(truth, predicted, 6),
                loss=loss,
                loss_type="threshold_bce" if ordinal else "unweighted_ce",
            )
            write_json(
                root / f"{name}-{split}-predictions.json",
                dict(
                    ids=[r["id"] for r in data[split].records],
                    truth=truth,
                    predicted=predicted,
                    probabilities=probabilities,
                    probability_semantics="P(y>k)" if ordinal else "P(y=k)",
                ),
            )
            print(
                json.dumps(
                    dict(
                        phase="gaps",
                        model=name,
                        split=split,
                        metrics=results[name]["splits"][split]["metrics"],
                    )
                ),
                flush=True,
            )
        del model, checkpoint
        torch.cuda.empty_cache()
    write_json(
        destination,
        dict(
            schema="nia-train-valid-gaps-v1",
            data_fingerprint=manifest["fingerprint"],
            augmentation=False,
            model_mode="eval",
            test_set_evaluated=False,
            packages={p: importlib.metadata.version(p) for p in ("torch", "torchvision", "numpy")},
            results=results,
        ),
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--phase", choices=("tiny", "gaps"), required=True)
    args = parser.parse_args()
    config = load_config(args.config)
    (tiny if args.phase == "tiny" else checkpoint_gaps)(config)


if __name__ == "__main__":
    main()

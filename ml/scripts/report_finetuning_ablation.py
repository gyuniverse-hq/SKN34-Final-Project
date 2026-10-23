"""Evaluate/publish independent BN-statistics and layer4-parameter experiments.

Run from repo root: uv run --project ml python -m ml.scripts.report_finetuning_ablation
"""

import argparse
import json
import math
from pathlib import Path

import torch
from torchvision.models import ResNet50_Weights, resnet50

from skin_analysis.config import PROJECT_ROOT
from skin_analysis.runtime import select_cuda
from skin_analysis.smartphone.common import file_hash, load_config, load_manifest, write_json
from skin_analysis.smartphone.data import GradeDataset
from skin_analysis.smartphone.focal_compare import verified_metrics
from skin_analysis.smartphone.train import make_loader, predict, verify_crops

ROOT = PROJECT_ROOT / "runs/nia-smartphone-finetuning-seed-42"
REPORT = PROJECT_ROOT.parent / "reports/skin-analysis/finetuning-ablation.md"
CONFIGS = {
    "bn_stats_frozen": PROJECT_ROOT / "configs/nia_smartphone_bn_frozen.toml",
    "layer4_only": PROJECT_ROOT / "configs/nia_smartphone_layer4.toml",
}
BASELINE = PROJECT_ROOT / "runs/nia-smartphone-ce-batch16-seed-42/pore"


def require_one_factor(settings, baseline, variant):
    def normalize(value):
        return dict(
            freeze_bn_stats=False,
            finetune_scope="all",
            **{
                k: v
                for k, v in value.items()
                if k not in ("output", "record_train_metrics", "freeze_bn_stats", "finetune_scope")
            },
        ) | {k: value[k] for k in ("freeze_bn_stats", "finetune_scope") if k in value}

    expected = normalize(baseline)
    if variant == "bn_stats_frozen":
        expected["freeze_bn_stats"] = True
    elif variant == "layer4_only":
        expected["finetune_scope"] = "layer4"
    else:
        raise ValueError("Unknown ablation variant")
    if normalize(settings) != expected or settings.get("record_train_metrics") is not True:
        raise ValueError(
            "Ablation requires exactly one predefined treatment; other settings unchanged"
        )


def preflight():
    baseline = torch.load(BASELINE / "best.pt", map_location="cpu", weights_only=True)
    base_config = load_config(PROJECT_ROOT / "configs/nia_smartphone_ce_batch16.toml")
    for variant, path in CONFIGS.items():
        config = load_config(path)
        require_one_factor(config["train"], baseline["train_config"], variant)
        manifest = load_manifest(config)
        if (
            config["data"] != base_config["data"]
            or baseline["manifest_fingerprint"] != manifest["fingerprint"]
            or baseline["initialization"].get("nia_weights_used") is not False
        ):
            raise ValueError("Ablation data or baseline mismatch")
    return baseline


def verify_training_policy(path, initial, variant):
    last = torch.load(path.parent / "last.pt", map_location="cpu", weights_only=True)
    state = last["model_state"]
    buffers = [
        k for k in state if k.endswith(("running_mean", "running_var", "num_batches_tracked"))
    ]
    if variant == "bn_stats_frozen":
        assert all(torch.equal(state[k], initial[k]) for k in buffers)
        result = dict(all_bn_buffers_unchanged=True, buffers_checked=len(buffers))
    else:
        prefix = [k for k in state if not k.startswith(("layer4.", "fc.")) and k not in buffers]
        assert all(torch.equal(state[k], initial[k]) for k in prefix)
        prefix_bn_updated = any(
            not torch.equal(state[k], initial[k]) for k in buffers if not k.startswith("layer4.")
        )
        assert prefix_bn_updated
        result = dict(
            frozen_prefix_parameters_unchanged=True,
            tensors_checked=len(prefix),
            prefix_bn_stats_updated=True,
        )
    del last
    return dict(checkpoint="last.pt", **result)


def evaluate():
    if (ROOT / "comparison.json").exists():
        raise FileExistsError("Ablation evaluation already recorded")
    baseline = preflight()
    config = load_config(CONFIGS["bn_stats_frozen"])
    manifest = load_manifest(config)
    verify_crops(manifest)
    device = select_cuda(config["train"]["device_uuid"])
    torch.set_num_threads(4)
    initial_path = (
        Path(torch.hub.get_dir()) / "checkpoints" / Path(ResNet50_Weights.IMAGENET1K_V2.url).name
    )
    assert file_hash(initial_path) == baseline["initialization"]["sha256"]
    initial = torch.load(initial_path, map_location="cpu", weights_only=True)
    data = {s: GradeDataset(manifest, "pore", s, training=False) for s in ("train", "valid")}
    loaders = {s: make_loader(d, config["train"]) for s, d in data.items()}
    paths = {"ce_batch16": BASELINE / "inference.bin"} | {
        name: Path(load_config(path)["train"]["output"]) / "pore/inference.bin"
        for name, path in CONFIGS.items()
    }
    results = {}
    for variant, path in paths.items():
        summary = json.loads((path.parent / "summary.json").read_text(encoding="utf-8"))
        assert file_hash(path) == summary["sha256"]
        checkpoint = torch.load(path, map_location="cpu", weights_only=True)
        assert all(torch.isfinite(value).all() for value in checkpoint["model_state"].values())
        assert checkpoint["architecture"] == "resnet50" and checkpoint["task"] == "pore"
        assert checkpoint["manifest_fingerprint"] == manifest["fingerprint"]
        assert checkpoint["initialization"] == baseline["initialization"]
        assert checkpoint["environment"]["packages"] == baseline["environment"]["packages"]
        verification = {}
        if variant in CONFIGS:
            best = torch.load(path.parent / "best.pt", map_location="cpu", weights_only=True)
            expected = load_config(CONFIGS[variant])["train"]
            assert best["train_config"] == expected
            assert checkpoint["epoch"] == best["epoch"]
            assert checkpoint["finetune_policy"] == best["finetune_policy"]
            verification = verify_training_policy(path, initial, variant)
            del best
        network = resnet50(weights=None, num_classes=6)
        network.load_state_dict(checkpoint["model_state"], strict=True)
        network = network.to(device).eval()
        result = dict(
            epoch=checkpoint["epoch"] + 1,
            epochs_run=summary["epochs_run"],
            sha256=summary["sha256"],
            policy_verification=verification,
            splits={},
        )
        for split, loader in loaders.items():
            truth, predicted, probabilities, ce = predict(network, loader, device)
            assert math.isfinite(ce)
            result["splits"][split] = dict(
                unweighted_ce=ce, metrics=verified_metrics(truth, predicted, 6)
            )
            write_json(
                ROOT / f"{variant}-{split}-predictions.json",
                dict(
                    ids=[r["id"] for r in data[split].records],
                    truth=truth,
                    predicted=predicted,
                    probabilities=probabilities,
                ),
            )
            m = result["splits"][split]["metrics"]
            print(
                json.dumps(
                    dict(
                        variant=variant,
                        split=split,
                        accuracy=m["accuracy"],
                        macro_f1=m["macro_f1"],
                        high_recall=m["high_grade_pooled_recall"],
                    )
                ),
                flush=True,
            )
        results[variant] = result
        del network, checkpoint
        torch.cuda.empty_cache()
    before = json.loads((ROOT / "preservation-before.json").read_text(encoding="utf-8"))
    assert before == {p: file_hash(p) for p in before}
    write_json(
        ROOT / "comparison.json",
        dict(
            schema="nia-finetuning-ablation-v1",
            task="pore",
            data_fingerprint=manifest["fingerprint"],
            test_set_evaluated=False,
            condition_check="passed",
            preservation=dict(files=len(before), passed=True),
            results=results,
        ),
    )


def publish():
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    result = json.loads((ROOT / "comparison.json").read_text(encoding="utf-8"))
    history = {
        "ce_batch16": json.loads(
            (
                PROJECT_ROOT
                / "runs/nia-smartphone-diagnostics-seed-42/full-ce-batch16/pore/history.json"
            ).read_text(encoding="utf-8")
        )
    }
    for name, path in CONFIGS.items():
        history[name] = json.loads(
            (Path(load_config(path)["train"]["output"]) / "pore/history.json").read_text(
                encoding="utf-8"
            )
        )
    write_json(REPORT.with_suffix(".metrics.json"), dict(**result, histories=history))
    fig, axes = plt.subplots(2, 3, figsize=(15, 8), constrained_layout=True)
    for column, (name, rows) in enumerate(history.items()):
        for ax, train_key, valid_key, title in (
            (axes[0, column], "train_eval_macro_f1", "valid_macro_f1", "Macro F1"),
            (axes[1, column], "train_eval_loss", "valid_loss", "Unweighted CE"),
        ):
            epochs = [r["epoch"] for r in rows]
            ax.plot(epochs, [r[train_key] for r in rows], label="Train, no augmentation")
            ax.plot(epochs, [r[valid_key] for r in rows], label="Validation")
            ax.axvline(result["results"][name]["epoch"], ls=":", c="grey", label="Selected epoch")
            ax.set(title=f"{name}: {title}", xlabel="Epoch", ylabel=title)
            if title == "Macro F1":
                ax.set_ylim(0, 1)
            ax.grid(alpha=0.25)
            ax.legend(fontsize=8)
    figure = REPORT.parent / "figures/finetuning-ablation.png"
    fig.savefig(figure, dpi=150)
    plt.close(fig)
    prefix = REPORT.read_text(encoding="utf-8").split("\n## 실제 비교 결과")[0]
    lines = [
        "",
        "## 실제 비교 결과",
        "",
        "동일 검증 인물 138명/816 ROI. 학습 지표도 증강 없는 eval mode에서 측정했습니다.",
        "",
        "| 모델 | epoch / 실행 | 검증 Acc | macro P | macro R | macro F1 | "
        "MAE | ±1등급 | 고등급 Recall |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for name, row in result["results"].items():
        m = row["splits"]["valid"]["metrics"]
        lines.append(
            f"| {name} | {row['epoch']} / {row['epochs_run']} | {m['accuracy']:.2%} | "
            f"{m['macro_precision']:.2%} | {m['macro_recall']:.2%} | {m['macro_f1']:.2%} | "
            f"{m['mae']:.4f} | {m['within_one']:.2%} | {m['high_grade_pooled_recall']:.2%} |"
        )
    lines += ["", "| 모델 | 학습 F1 | 검증 F1 | 차이(%p) |", "|---|---:|---:|---:|"]
    for name, row in result["results"].items():
        t = row["splits"]["train"]["metrics"]["macro_f1"]
        v = row["splits"]["valid"]["metrics"]["macro_f1"]
        lines.append(f"| {name} | {t:.2%} | {v:.2%} | {(t - v) * 100:.2f} |")
    lines += [
        "",
        "| 모델 | 등급 | 실제 ROI | 예측 ROI | Precision | Recall | F1 |",
        "|---|---:|---:|---:|---:|---:|---:|",
    ]
    for name, row in result["results"].items():
        for g in row["splits"]["valid"]["metrics"]["per_grade"]:
            lines.append(
                f"| {name} | {g['grade']} | {g['support']} | {g['predicted']} | "
                f"{g['precision']:.2%} | {g['recall']:.2%} | {g['f1']:.2%} |"
            )
    lines += ["", "![학습 검증 곡선](figures/finetuning-ablation.png)", "", "가중치 SHA-256:", ""]
    for name, row in result["results"].items():
        lines.append(f"- {name}: `{row['sha256']}`")
    REPORT.write_text(prefix + "\n".join(lines) + "\n", encoding="utf-8")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--phase", choices=("preflight", "evaluate", "publish"), required=True)
    args = parser.parse_args()
    {"preflight": preflight, "evaluate": evaluate, "publish": publish}[args.phase]()


if __name__ == "__main__":
    main()

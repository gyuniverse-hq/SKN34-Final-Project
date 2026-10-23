"""Compare weighted ordinal CDF+SAM with preserved CE+SAM and CE references.

Run from repository root with python -m ml.scripts.report_ordinal_loss.
"""

import argparse
import json
import math
from pathlib import Path

import torch
from server.nia.engine import Engine
from torchvision.models import ResNet50_Weights, resnet50

from skin_analysis.config import PROJECT_ROOT
from skin_analysis.runtime import select_cuda
from skin_analysis.smartphone.common import file_hash, load_config, load_manifest, write_json
from skin_analysis.smartphone.data import GradeDataset
from skin_analysis.smartphone.focal_compare import verified_metrics
from skin_analysis.smartphone.sam import optimization_spec
from skin_analysis.smartphone.train import criterion_for, make_loader, predict, verify_crops

CONFIG = PROJECT_ROOT / "configs/nia_smartphone_ordinal_cdf_sam.toml"
ROOT = PROJECT_ROOT / "runs/nia-smartphone-ordinal-cdf-sam-seed-42"
REPORT = PROJECT_ROOT.parent / "reports/skin-analysis/ordinal-cdf-experiment.md"
PATHS = {
    "ce_adamw_reference": PROJECT_ROOT / "runs/nia-smartphone-ce-batch16-seed-42/pore",
    "ce_sam_baseline": PROJECT_ROOT / "runs/nia-smartphone-sam-seed-42/pore",
    "ordinal_cdf_sam": ROOT / "pore",
}


def require_loss_only(candidate, baseline):
    excluded = {"output", "loss"}
    if (
        {k: v for k, v in candidate.items() if k not in excluded}
        != {k: v for k, v in baseline.items() if k not in excluded}
        or baseline.get("loss", "weighted_cross_entropy") != "weighted_cross_entropy"
        or candidate.get("loss") != "weighted_ordinal_cdf"
        or candidate.get("optimizer") != "sam_adamw"
    ):
        raise ValueError("Only weighted CE -> weighted ordinal CDF may change")


def preflight():
    baseline = torch.load(
        PATHS["ce_sam_baseline"] / "best.pt", map_location="cpu", weights_only=True
    )
    config = load_config(CONFIG)
    original = load_config(PROJECT_ROOT / "configs/nia_smartphone_sam.toml")
    require_loss_only(config["train"], baseline["train_config"])
    manifest = load_manifest(config)
    assert config["data"] == original["data"]
    assert manifest["fingerprint"] == baseline["manifest_fingerprint"]
    assert manifest["preprocessing"] == baseline["preprocessing"]
    assert baseline["initialization"]["nia_weights_used"] is False
    assert baseline["optimization_spec"] == optimization_spec(config["train"])
    return baseline, config, manifest


def snapshot():
    preflight()
    output = ROOT / "preservation-before.json"
    previous = PROJECT_ROOT / "runs/nia-smartphone-sam-seed-42/preservation-before.json"
    before = json.loads((output if output.exists() else previous).read_text(encoding="utf-8"))
    assert before == {p: file_hash(p) for p in before}
    baseline = PATHS["ce_sam_baseline"] / "inference.bin"
    expected = json.loads((baseline.parent / "summary.json").read_text(encoding="utf-8"))["sha256"]
    assert file_hash(baseline) == expected
    before[str(baseline.relative_to(PROJECT_ROOT.parent))] = expected
    if not output.exists():
        write_json(output, before)
    print(json.dumps(dict(preflight="passed", preserved_files=len(before))), flush=True)


def evaluate():
    if (ROOT / "comparison.json").exists():
        raise FileExistsError("Comparison already recorded")
    baseline, config, manifest = preflight()
    before = json.loads((ROOT / "preservation-before.json").read_text(encoding="utf-8"))
    assert before == {p: file_hash(p) for p in before}
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
    _, expected_loss_spec = criterion_for(
        [r["truth"] for r in data["train"].records], 6, config["train"], "cpu"
    )
    results = {}
    for name, path in PATHS.items():
        summary = json.loads((path / "summary.json").read_text(encoding="utf-8"))
        assert file_hash(path / "inference.bin") == summary["sha256"]
        checkpoint = torch.load(path / "inference.bin", map_location="cpu", weights_only=True)
        assert checkpoint["architecture"] == "resnet50" and checkpoint["task"] == "pore"
        assert checkpoint["decoding"] == "softmax_argmax"
        assert checkpoint["manifest_fingerprint"] == manifest["fingerprint"]
        assert checkpoint["initialization"] == baseline["initialization"]
        assert checkpoint["environment"]["packages"] == baseline["environment"]["packages"]
        assert all(torch.isfinite(v).all() for v in checkpoint["model_state"].values())
        verification = {}
        if name == "ordinal_cdf_sam":
            best = torch.load(path / "best.pt", map_location="cpu", weights_only=True)
            last = torch.load(path / "last.pt", map_location="cpu", weights_only=True)
            assert best["train_config"] == config["train"]
            assert checkpoint["epoch"] == best["epoch"]
            assert checkpoint["loss_spec"] == best["loss_spec"] == expected_loss_spec
            assert checkpoint["loss_spec"]["weights"] == baseline["loss_spec"]["weights"]
            assert checkpoint["optimization_spec"] == baseline["optimization_spec"]
            assert all(
                torch.equal(v, best["model_state"][k]) for k, v in checkpoint["model_state"].items()
            )
            updates = sum(r["sam_steps"] for r in last["history"] if r["stage"] != "head")
            bn_counts = [k for k in initial if k.endswith("num_batches_tracked")]
            assert all(int(last["model_state"][k] - initial[k]) == updates for k in bn_counts)
            assert all(int(s["step"]) == updates for s in last["optimizer_state"]["state"].values())
            assert all(
                r["sam_steps"] == math.ceil(len(data["train"]) / 16) for r in last["history"]
            )
            verification = dict(
                bn_layers_checked=len(bn_counts),
                bn_updates_per_layer=updates,
                updates_per_epoch=257,
                export_matches_selected_weights=True,
                same_class_weights=True,
                same_sam_implementation=True,
                amp_overflow_retries=sum(r["amp_overflow_retries"] for r in last["history"]),
            )
            del best, last
        network = resnet50(weights=None, num_classes=6)
        network.load_state_dict(checkpoint["model_state"], strict=True)
        network = network.to(device).eval()
        row = dict(
            epoch=checkpoint["epoch"] + 1,
            epochs_run=summary["epochs_run"],
            sha256=summary["sha256"],
            loss_spec=checkpoint["loss_spec"],
            verification=verification,
            splits={},
        )
        for split, loader in loaders.items():
            truth, predicted, probabilities, ce = predict(network, loader, device)
            assert math.isfinite(ce)
            metrics = verified_metrics(truth, predicted, 6)
            row["splits"][split] = dict(unweighted_ce=ce, metrics=metrics)
            write_json(
                ROOT / f"{name}-{split}-predictions.json",
                dict(
                    ids=[r["id"] for r in data[split].records],
                    truth=truth,
                    predicted=predicted,
                    probabilities=probabilities,
                ),
            )
            print(
                json.dumps(
                    dict(
                        model=name,
                        split=split,
                        accuracy=metrics["accuracy"],
                        macro_f1=metrics["macro_f1"],
                        high_recall=metrics["high_grade_pooled_recall"],
                    )
                ),
                flush=True,
            )
        results[name] = row
        del network, checkpoint
        torch.cuda.empty_cache()
    service = json.loads((PROJECT_ROOT.parent / "server/nia/config.local.json").read_text("utf-8"))
    model_config = next(c for c in service["models"] if c["task"] == "class/pore").copy()
    model_config.update(
        id="pore-ordinal-cdf-comparison",
        checkpoint=str(ROOT / "pore/inference.bin"),
        sha256=results["ordinal_cdf_sam"]["sha256"],
        source="Local ordinal CDF comparison; not activated",
    )
    engine = Engine(model_config)
    engine.device = torch.device("cpu")
    engine.load()
    with torch.inference_mode():
        output = engine.model(torch.zeros(1, 3, 256, 256))
    assert output.shape == (1, 6) and torch.isfinite(output).all()
    assert before == {p: file_hash(p) for p in before}
    write_json(
        ROOT / "comparison.json",
        dict(
            schema="nia-ordinal-cdf-comparison-v1",
            task="pore",
            test_set_evaluated=False,
            data_fingerprint=manifest["fingerprint"],
            primary_baseline="ce_sam_baseline",
            preservation=dict(files=len(before), passed=True),
            strict_service_loader_passed=True,
            results=results,
        ),
    )


def publish():
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    result = json.loads((ROOT / "comparison.json").read_text(encoding="utf-8"))
    histories = {
        n: json.loads((p / "history.json").read_text(encoding="utf-8"))
        for n, p in PATHS.items()
        if n != "ce_adamw_reference"
    }
    wall = json.loads((ROOT / "wall-time.json").read_text(encoding="utf-8"))
    assert wall["exit_code"] == 0
    write_json(
        REPORT.with_suffix(".metrics.json"),
        dict(**result, histories=histories, training_wall_seconds=wall["seconds"]),
    )
    fig, axes = plt.subplots(
        2, 2, figsize=(11, 8), constrained_layout=True, sharex=True, sharey="row"
    )
    for column, (name, rows) in enumerate(histories.items()):
        for ax, train, valid, title in (
            (axes[0, column], "train_eval_macro_f1", "valid_macro_f1", "Macro F1"),
            (axes[1, column], "train_eval_loss", "valid_loss", "Unweighted CE (common diagnostic)"),
        ):
            ax.plot([r["epoch"] for r in rows], [r[train] for r in rows], label="Train (eval)")
            ax.plot([r["epoch"] for r in rows], [r[valid] for r in rows], label="Validation")
            ax.axvline(result["results"][name]["epoch"], ls=":", c="grey", label="Selected")
            ax.set(title=f"{name}: {title}", xlabel="Epoch", ylabel=title)
            if title == "Macro F1":
                ax.set_ylim(0, 1)
            ax.grid(alpha=0.25)
            ax.legend(fontsize=8)
    fig.savefig(REPORT.parent / "figures/ordinal-cdf-experiment.png", dpi=150)
    plt.close(fig)
    prefix = REPORT.read_text(encoding="utf-8").split("\n## 실제 비교 결과")[0]
    lines = [
        "",
        "## 실제 비교 결과",
        "",
        "동일 검증 138명/816 ROI, 증강 없는 FP32 평가입니다.",
        "",
        "| 모델 | epoch / 실행 | Acc | macro P | macro R | macro F1 | "
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
    lines += [
        "",
        "![학습·검증 곡선](figures/ordinal-cdf-experiment.png)",
        "",
        "가중치 SHA-256:",
        "",
    ]
    lines += [f"- {name}: `{row['sha256']}`" for name, row in result["results"].items()]
    REPORT.write_text(prefix + "\n".join(lines) + "\n", encoding="utf-8")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--phase", choices=("preflight", "evaluate", "publish"), required=True)
    args = parser.parse_args()
    {"preflight": snapshot, "evaluate": evaluate, "publish": publish}[args.phase]()


if __name__ == "__main__":
    main()

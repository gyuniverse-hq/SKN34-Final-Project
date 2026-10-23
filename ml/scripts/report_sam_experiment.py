"""Preflight, local train/validation evaluation and aggregate SAM report.

Run from repo root: uv run --project ml python -m ml.scripts.report_sam_experiment
"""

import argparse
import json
import math
import statistics
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
from skin_analysis.smartphone.train import make_loader, predict, verify_crops

CONFIG = PROJECT_ROOT / "configs/nia_smartphone_sam.toml"
ROOT = PROJECT_ROOT / "runs/nia-smartphone-sam-seed-42"
BASELINE = PROJECT_ROOT / "runs/nia-smartphone-ce-batch16-seed-42/pore"
REPORT = PROJECT_ROOT.parent / "reports/skin-analysis/sam-experiment.md"


def require_matched_settings(candidate, baseline):
    excluded = {"output", "record_train_metrics", "optimizer", "sam_rho"}
    if (
        {k: v for k, v in candidate.items() if k not in excluded}
        != {k: v for k, v in baseline.items() if k not in excluded}
        or baseline.get("optimizer", "adamw") != "adamw"
        or candidate.get("optimizer") != "sam_adamw"
        or candidate.get("sam_rho") != 0.05
        or candidate.get("record_train_metrics") is not True
    ):
        raise ValueError("SAM must be the only treatment; keep baseline training settings")
    return optimization_spec(candidate)


def preflight():
    baseline = torch.load(BASELINE / "best.pt", map_location="cpu", weights_only=True)
    config = load_config(CONFIG)
    original = load_config(PROJECT_ROOT / "configs/nia_smartphone_ce_batch16.toml")
    require_matched_settings(config["train"], baseline["train_config"])
    manifest = load_manifest(config)
    assert config["data"] == original["data"]
    assert manifest["fingerprint"] == baseline["manifest_fingerprint"]
    assert manifest["preprocessing"] == baseline["preprocessing"]
    assert baseline["initialization"]["nia_weights_used"] is False
    summary = json.loads((BASELINE / "summary.json").read_text(encoding="utf-8"))
    assert file_hash(BASELINE / "inference.bin") == summary["sha256"]
    return baseline, config, manifest


def snapshot():
    preflight()
    path = ROOT / "preservation-before.json"
    if path.exists():
        before = json.loads(path.read_text(encoding="utf-8"))
        assert before == {p: file_hash(p) for p in before}
        return
    # Preserve service configuration and all previous comparison candidates too.
    previous = PROJECT_ROOT / "runs/nia-smartphone-finetuning-seed-42/preservation-before.json"
    before = json.loads(previous.read_text(encoding="utf-8"))
    assert before == {p: file_hash(p) for p in before}
    for variant in ("bn-stats-frozen", "layer4-only"):
        p = PROJECT_ROOT / f"runs/nia-smartphone-finetuning-seed-42/{variant}/pore/inference.bin"
        before[str(p.relative_to(PROJECT_ROOT.parent))] = file_hash(p)
    write_json(path, before)
    print(json.dumps(dict(preflight="passed", preserved_files=len(before))), flush=True)


def evaluate():
    if (ROOT / "comparison.json").exists():
        raise FileExistsError("SAM evaluation already recorded")
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
    results = {}
    for name, path in {"ce_batch16": BASELINE, "sam_adamw": ROOT / "pore"}.items():
        summary = json.loads((path / "summary.json").read_text(encoding="utf-8"))
        assert file_hash(path / "inference.bin") == summary["sha256"]
        checkpoint = torch.load(path / "inference.bin", map_location="cpu", weights_only=True)
        assert all(torch.isfinite(v).all() for v in checkpoint["model_state"].values())
        assert checkpoint["architecture"] == "resnet50" and checkpoint["task"] == "pore"
        assert checkpoint["manifest_fingerprint"] == manifest["fingerprint"]
        assert checkpoint["initialization"] == baseline["initialization"]
        assert checkpoint["environment"]["packages"] == baseline["environment"]["packages"]
        verification = {}
        history = json.loads((path / "history.json").read_text(encoding="utf-8"))
        selected_bn_updates = sorted(
            {
                int(v - initial[k])
                for k, v in checkpoint["model_state"].items()
                if k.endswith("num_batches_tracked")
            }
        )
        if name == "ce_batch16":
            selected_rows = history[: checkpoint["epoch"] + 1]
            normal = sum(
                math.ceil(len(data["train"]) / 16) for r in selected_rows if r["stage"] != "head"
            )
            retries = sum(r["amp_overflow_retries"] for r in selected_rows if r["stage"] != "head")
            assert selected_bn_updates == [normal + retries]
            verification = dict(
                selected_bn_updates_per_layer=selected_bn_updates[0],
                selected_normal_bn_updates=normal,
                selected_extra_bn_updates_from_legacy_amp_retries=retries,
            )
        if name == "sam_adamw":
            best = torch.load(path / "best.pt", map_location="cpu", weights_only=True)
            last = torch.load(path / "last.pt", map_location="cpu", weights_only=True)
            assert best["train_config"] == config["train"]
            assert best["optimization_spec"] == optimization_spec(config["train"])
            assert checkpoint["optimization_spec"] == best["optimization_spec"]
            assert checkpoint["epoch"] == best["epoch"]
            assert all(
                torch.equal(v, best["model_state"][k]) for k, v in checkpoint["model_state"].items()
            )
            rows = last["history"]
            expected = sum(r["sam_steps"] for r in rows if r["stage"] != "head")
            counts = [k for k in initial if k.endswith("num_batches_tracked")]
            assert all(int(last["model_state"][k] - initial[k]) == expected for k in counts)
            assert all(r["sam_steps"] == math.ceil(len(data["train"]) / 16) for r in rows)
            assert all(
                int(state["step"]) == expected
                for state in last["optimizer_state"]["state"].values()
            )
            verification = dict(
                bn_layers_checked=len(counts),
                bn_updates_per_layer=expected,
                persistent_bn_updates_once=True,
                adamw_steps_per_epoch=rows[0]["sam_steps"],
                amp_overflow_retries=sum(r["amp_overflow_retries"] for r in rows),
                export_matches_selected_weights=True,
                selected_bn_updates_per_layer=selected_bn_updates[0],
            )
            assert selected_bn_updates == [
                sum(r["sam_steps"] for r in rows[: checkpoint["epoch"] + 1] if r["stage"] != "head")
            ]
            del best, last
        network = resnet50(weights=None, num_classes=6)
        network.load_state_dict(checkpoint["model_state"], strict=True)
        network = network.to(device).eval()
        row = dict(
            epoch=checkpoint["epoch"] + 1,
            epochs_run=summary["epochs_run"],
            sha256=summary["sha256"],
            verification=verification,
            timing=dict(
                recorded_epoch_seconds=sum(r["seconds"] for r in history),
                median_finetune_epoch_seconds=statistics.median(
                    r["seconds"] for r in history if r["stage"] != "head"
                ),
                excludes="train-eval and checkpoint IO; epoch sum includes loader startup",
            ),
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
    assert before == {p: file_hash(p) for p in before}
    service_config = json.loads(
        (PROJECT_ROOT.parent / "server/nia/config.local.json").read_text(encoding="utf-8")
    )
    model_config = next(c for c in service_config["models"] if c["task"] == "class/pore").copy()
    model_config.update(
        id="pore-sam-comparison",
        checkpoint=str(ROOT / "pore/inference.bin"),
        sha256=results["sam_adamw"]["sha256"],
        source="Local SAM comparison; not activated",
    )
    engine = Engine(model_config)
    engine.device = torch.device("cpu")
    metadata = engine.load()
    with torch.inference_mode():
        output = engine.model(torch.zeros(1, 3, 256, 256))
    assert output.shape == (1, 6) and torch.isfinite(output).all()
    loader_verification = dict(
        strict_service_loader_passed=True,
        dummy_shape=list(output.shape),
        device=metadata["device"],
        service_config_modified=False,
    )
    write_json(
        ROOT / "comparison.json",
        dict(
            schema="nia-sam-comparison-v1",
            task="pore",
            data_fingerprint=manifest["fingerprint"],
            test_set_evaluated=False,
            condition_check="passed",
            optimization_spec=optimization_spec(config["train"]),
            loader_verification=loader_verification,
            preservation=dict(files=len(before), passed=True),
            results=results,
        ),
    )


def publish():
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    result = json.loads((ROOT / "comparison.json").read_text(encoding="utf-8"))
    histories = {
        "ce_batch16": json.loads(
            (
                PROJECT_ROOT / "runs/nia-smartphone-diagnostics-seed-42/"
                "full-ce-batch16/pore/history.json"
            ).read_text(encoding="utf-8")
        ),
        "sam_adamw": json.loads((ROOT / "pore/history.json").read_text(encoding="utf-8")),
    }
    wall_time = json.loads((ROOT / "wall-time.json").read_text(encoding="utf-8"))
    assert wall_time["exit_code"] == 0
    write_json(
        REPORT.with_suffix(".metrics.json"),
        dict(**result, histories=histories, sam_training_wall_seconds=wall_time["seconds"]),
    )
    fig, axes = plt.subplots(
        2, 2, figsize=(11, 8), constrained_layout=True, sharex=True, sharey="row"
    )
    for column, (name, rows) in enumerate(histories.items()):
        for ax, train, valid, title in (
            (axes[0, column], "train_eval_macro_f1", "valid_macro_f1", "Macro F1"),
            (axes[1, column], "train_eval_loss", "valid_loss", "Unweighted CE"),
        ):
            ax.plot([r["epoch"] for r in rows], [r[train] for r in rows], label="Train (eval)")
            ax.plot([r["epoch"] for r in rows], [r[valid] for r in rows], label="Validation")
            ax.axvline(result["results"][name]["epoch"], ls=":", c="grey", label="Selected")
            ax.set(title=f"{name}: {title}", xlabel="Epoch", ylabel=title)
            if title == "Macro F1":
                ax.set_ylim(0, 1)
            ax.grid(alpha=0.25)
            ax.legend(fontsize=8)
    fig.savefig(REPORT.parent / "figures/sam-experiment.png", dpi=150)
    plt.close(fig)
    prefix = REPORT.read_text(encoding="utf-8").split("\n## 실제 비교 결과")[0]
    lines = [
        "",
        "## 실제 비교 결과",
        "",
        "동일 인물 분리의 검증 138명/816 ROI 결과입니다.",
        "",
        "| 모델 | epoch / 실행 | Acc | macro P | macro R | macro F1 | "
        "MAE | ±1등급 | 고등급 Recall |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for name, row in result["results"].items():
        m = row["splits"]["valid"]["metrics"]
        lines.append(
            f"| {name} | {row['epoch']} / {row['epochs_run']} | {m['accuracy']:.2%} | "
            f"{m['macro_precision']:.2%} | {m['macro_recall']:.2%} | "
            f"{m['macro_f1']:.2%} | {m['mae']:.4f} | {m['within_one']:.2%} | "
            f"{m['high_grade_pooled_recall']:.2%} |"
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
    lines += ["", "![학습과 검증 곡선](figures/sam-experiment.png)", "", "가중치 SHA-256:", ""]
    lines += [f"- {name}: `{row['sha256']}`" for name, row in result["results"].items()]
    REPORT.write_text(prefix + "\n".join(lines) + "\n", encoding="utf-8")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--phase", choices=("preflight", "evaluate", "publish"), required=True)
    args = parser.parse_args()
    {"preflight": snapshot, "evaluate": evaluate, "publish": publish}[args.phase]()


if __name__ == "__main__":
    main()

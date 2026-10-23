"""Train/evaluate the three-class WCE+SAM fallback without activating services."""

import argparse
import json
import time

import torch

from skin_analysis.config import PROJECT_ROOT
from skin_analysis.runtime import select_cuda
from skin_analysis.smartphone.classifier_retraining import SIX_ROOT, metrics_for
from skin_analysis.smartphone.common import (
    PORE_COARSE_MAPPING,
    classification_contract,
    file_hash,
    load_config,
    load_manifest,
    write_json,
)
from skin_analysis.smartphone.data import GradeDataset
from skin_analysis.smartphone.pore_coarse import load_model
from skin_analysis.smartphone.train import (
    criterion_for,
    make_loader,
    predict,
    train_task,
    verify_crops,
)

CONFIG = PROJECT_ROOT / "configs/nia_smartphone_pore_coarse_sam.toml"
ROOT = PROJECT_ROOT / "runs/nia-smartphone-pore-coarse-sam-seed-42"
HEAD_ROOT = PROJECT_ROOT / "runs/nia-smartphone-pore-coarse-seed-42"
REPORT = PROJECT_ROOT.parent / "reports/skin-analysis/pore-coarse-experiment.md"


def preflight():
    config = load_config(CONFIG)
    previous = load_config(PROJECT_ROOT / "configs/nia_smartphone_sam.toml")
    excluded = {"output", "classes", "target_mapping"}
    if {k: v for k, v in config["train"].items() if k not in excluded} != {
        k: v for k, v in previous["train"].items() if k not in excluded
    } or config["data"] != previous["data"]:
        raise ValueError("Only output path and explicit six-to-three target contract may change")
    classification_contract(config["train"], "pore")
    manifest = load_manifest(config)
    for root in (SIX_ROOT, HEAD_ROOT):
        result = json.loads((root / "comparison.json").read_text(encoding="utf-8"))
        if (
            result["passes_gate"] is not False
            or result["test_set_evaluated"] is not False
            or result["manifest_fingerprint"] != manifest["fingerprint"]
            or file_hash(root / "pore/inference.bin") != result["candidate_sha256"]
        ):
            raise ValueError("Prior classifier-only comparison must be preserved and unsuccessful")
    path = ROOT / "preservation-before.json"
    before = json.loads(
        (path if path.exists() else HEAD_ROOT / "preservation-before.json").read_text("utf-8")
    )
    if not path.exists():
        weight = HEAD_ROOT / "pore/inference.bin"
        before[str(weight.relative_to(PROJECT_ROOT.parent))] = file_hash(weight)
    if before != {p: file_hash(PROJECT_ROOT.parent / p) for p in before}:
        raise ValueError("A preserved model/config changed")
    if not path.exists():
        write_json(path, before)
    return config, manifest, len(before)


def train():
    config, manifest, _ = preflight()
    verify_crops(manifest)
    device = select_cuda(config["train"]["device_uuid"])
    torch.set_num_threads(4)
    started = time.perf_counter()
    train_task(config, manifest, "pore", device)
    write_json(ROOT / "wall-time.json", dict(seconds=time.perf_counter() - started, exit_code=0))
    preflight()


def evaluate():
    config, manifest, preserved = preflight()
    if (ROOT / "comparison.json").exists():
        raise FileExistsError("Comparison already recorded")
    verify_crops(manifest)
    checkpoint = torch.load(ROOT / "pore/inference.bin", map_location="cpu", weights_only=True)
    baseline = torch.load(
        PROJECT_ROOT / "runs/nia-smartphone-sam-seed-42/pore/best.pt",
        map_location="cpu",
        weights_only=True,
    )
    best = torch.load(ROOT / "pore/best.pt", map_location="cpu", weights_only=True)
    if (
        best["train_config"] != config["train"]
        or checkpoint["initialization"] != baseline["initialization"]
        or checkpoint["manifest_fingerprint"] != manifest["fingerprint"]
        or checkpoint["environment"]["packages"] != baseline["environment"]["packages"]
    ):
        raise ValueError("Coarse candidate initialization/data/settings differ")
    summary = json.loads((ROOT / "pore/summary.json").read_text("utf-8"))
    if file_hash(ROOT / "pore/inference.bin") != summary["sha256"]:
        raise ValueError("Candidate hash mismatch")
    training = GradeDataset(manifest, "pore", "train", target_mapping=PORE_COARSE_MAPPING)
    _, expected_loss = criterion_for(
        [training.target(r) for r in training.records], 3, config["train"], "cpu"
    )
    if checkpoint["loss_spec"] != expected_loss:
        raise ValueError("WCE must use mapped training counts only")
    model = load_model(checkpoint)
    torch.set_num_threads(4)
    with torch.inference_mode():
        logits = model(torch.zeros(1, 3, 256, 256))
    if logits.shape != (1, 3) or not torch.isfinite(logits).all():
        raise ValueError("Three-output inference failed")
    device = select_cuda(config["train"]["device_uuid"])
    model.to(device)
    head = json.loads((HEAD_ROOT / "comparison.json").read_text("utf-8"))
    results = {
        "six_probability_pooling": head["results"]["baseline"],
        "six_argmax_mapping": {},
        "three_frozen_balanced": head["results"]["candidate"],
        "three_wce_sam": {},
    }
    for split in ("train", "valid"):
        data = GradeDataset(manifest, "pore", split, target_mapping=PORE_COARSE_MAPPING)
        raw = json.loads((SIX_ROOT / f"baseline-{split}-predictions.json").read_text("utf-8"))
        expected_truth = [data.target(r) for r in data.records]
        if [v // 2 for v in raw["truth"]] != expected_truth or raw["subjects"] != [
            r["subject"] for r in data.records
        ]:
            raise ValueError("Saved reference ordering differs from current audited dataset")
        results["six_argmax_mapping"][split] = metrics_for(
            expected_truth,
            [v // 2 for v in raw["predicted"]],
            3,
        )
        truth, predicted, probabilities, ce = predict(
            model, make_loader(data, config["train"]), device
        )
        if truth != expected_truth:
            raise ValueError("Mapped prediction targets differ")
        metrics = metrics_for(truth, predicted, 3)
        results["three_wce_sam"][split] = dict(**metrics, unweighted_ce=ce)
        write_json(
            ROOT / f"{split}-predictions.json",
            dict(
                original_truth=[r["truth"] for r in data.records],
                truth=truth,
                predicted=predicted,
                probabilities=probabilities,
                subjects=[r["subject"] for r in data.records],
            ),
        )
    candidate = results["three_wce_sam"]["valid"]
    references = [results[n]["valid"] for n in ("six_probability_pooling", "six_argmax_mapping")]
    passed = (
        candidate["accuracy"] >= max(r["accuracy"] for r in references)
        and candidate["macro_f1"] > max(r["macro_f1"] for r in references)
        and candidate["high_grade_pooled_recall"]
        > max(r["high_grade_pooled_recall"] for r in references)
    )
    write_json(
        ROOT / "comparison.json",
        dict(
            schema="nia-pore-coarse-sam-comparison-v1",
            original_to_target=PORE_COARSE_MAPPING,
            manifest_fingerprint=manifest["fingerprint"],
            test_set_evaluated=False,
            summary=summary,
            results=results,
            passes_gate=passed,
            candidate_sha256=summary["sha256"],
            strict_three_output_loader_passed=True,
            loss_spec=expected_loss,
            preservation=dict(files=preserved, passed=True),
            training_environment=checkpoint["environment"],
            initialization=checkpoint["initialization"],
            gate="accuracy >= both six-class decoders; macro-F1 and high recall > both decoders",
        ),
    )
    preflight()
    print(json.dumps(dict(passes_gate=passed, metrics=candidate)), flush=True)


def publish():
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    result = json.loads((ROOT / "comparison.json").read_text("utf-8"))
    history = json.loads((ROOT / "pore/history.json").read_text("utf-8"))
    wall = json.loads((ROOT / "wall-time.json").read_text("utf-8"))
    write_json(REPORT.with_suffix(".metrics.json"), dict(**result, history=history, wall=wall))
    prefix = REPORT.read_text("utf-8").split("\n## 실제 결과")[0]
    lines = [
        "",
        "## 실제 결과",
        "",
        "동일 검증 138명·816 ROI, FP32·증강 없음. 사전 통과 조건: "
        f"**{'충족' if result['passes_gate'] else '미달'}**.",
        "",
        "| 방법 | Accuracy | Macro P | Macro R | Macro F1 | 높음 P | 높음 R | MAE |",
        "|---|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for name, splits in result["results"].items():
        m, g = splits["valid"], splits["valid"]["per_grade"][2]
        lines.append(
            f"| {name} | {m['accuracy']:.2%} | {m['macro_precision']:.2%} | "
            f"{m['macro_recall']:.2%} | {m['macro_f1']:.2%} | {g['precision']:.2%} | "
            f"{g['recall']:.2%} | {m['mae']:.4f} |"
        )
    m = result["results"]["three_wce_sam"]["valid"]
    lines += [
        "",
        f"선택 epoch {result['summary']['best_epoch']} / 실행 {result['summary']['epochs_run']}, "
        f"학습 {wall['seconds']:.1f}초.",
        "",
        "| 목표 | 정답 ROI | 예측 ROI | Precision | Recall | F1 |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for g in m["per_grade"]:
        label = ["낮음(원본 0·1)", "중간(원본 2·3)", "높음(원본 4·5)"][g["grade"]]
        lines.append(
            f"| {label} | {g['support']} | {g['predicted']} | {g['precision']:.2%} | "
            f"{g['recall']:.2%} | {g['f1']:.2%} |"
        )
    lines += ["", "| 방법 | 학습 F1 | 검증 F1 | 차이(%p) |", "|---|---:|---:|---:|"]
    for name, splits in result["results"].items():
        t, v = (splits[s]["macro_f1"] for s in ("train", "valid"))
        lines.append(f"| {name} | {t:.2%} | {v:.2%} | {(t - v) * 100:.2f} |")
    lines += ["", "3등급 WCE+SAM 검증 혼동행렬(행=정답, 열=예측):", "", "```text"]
    lines += [str(row) for row in m["confusion"]] + ["```", ""]
    correct, predicted = m["confusion"][2][2], m["per_grade"][2]["predicted"]
    lines += [
        f"높음 정답 50개 중 {correct}개를 맞혔고, 높음 예측 {predicted}개 중 "
        f"{predicted - correct}개는 실제 낮음·중간이다.",
        "",
        f"가중치: `ml/runs/{ROOT.name}/pore/inference.bin`",
        "",
        f"SHA-256: `{result['candidate_sha256']}`",
        "",
    ]
    fig, axes = plt.subplots(1, 2, figsize=(11, 4), constrained_layout=True)
    for ax, metric, title in ((axes[0], "macro_f1", "Macro F1"), (axes[1], "accuracy", "Accuracy")):
        ax.plot(
            [h["epoch"] for h in history],
            [h[f"train_eval_{metric}"] for h in history],
            label="Train (eval)",
        )
        ax.plot(
            [h["epoch"] for h in history],
            [h[f"valid_{metric}"] for h in history],
            label="Validation",
        )
        ax.axvline(result["summary"]["best_epoch"], color="grey", ls=":", label="Selected")
        ax.set(title=f"Three-class WCE+SAM: {title}", xlabel="Epoch", ylim=(0, 1))
        ax.legend(fontsize=8)
        ax.grid(alpha=0.25)
    fig.savefig(REPORT.parent / "figures/pore-coarse-experiment.png", dpi=150)
    plt.close(fig)
    lines += [
        "![3등급 학습 곡선](figures/pore-coarse-experiment.png)",
        "",
        "검증셋을 반복 사용한 탐색 결과다. 높음의 검증 인물은 9명이며 원본 5등급은 1명이다. "
        "3등급으로 묶어도 인물 다양성 부족은 남는다. 낮음/중간/높음은 임시 추천 구간이며 "
        "임상 중증도 기준이 아니다. 원본 4와 5를 구분하는 성능은 이 모델에서 평가할 수 없다.",
        "",
        "기존 6등급 Accuracy와 직접 비교할 수 없다. 테스트셋은 평가하지 않았고 "
        "기존 모델·서비스 설정 17개 파일은 보존했다. CPU 합성 입력의 3출력과 엄격한 "
        "체크포인트 로딩을 확인했으며 분류 지표는 sklearn과 교차 검산했다.",
        "",
        "테스트 페이지에는 자동 적용하지 않았다. 연결하려면 `pore_coarse.load_model`과 "
        "명시적 매핑을 사용하고 API·UI·추천 입력의 등급 계약을 함께 변경해야 한다.",
    ]
    REPORT.write_text(prefix + "\n".join(lines) + "\n", encoding="utf-8")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--phase", choices=("preflight", "train", "evaluate", "publish"), required=True
    )
    args = parser.parse_args()
    if args.phase == "preflight":
        print(json.dumps(dict(preserved_files=preflight()[2], preflight="passed")))
    else:
        {"train": train, "evaluate": evaluate, "publish": publish}[args.phase]()

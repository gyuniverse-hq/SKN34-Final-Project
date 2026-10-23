"""Publish aggregate frozen-classifier results; never copy person-level outputs."""

import json

import torch

from skin_analysis.config import PROJECT_ROOT
from skin_analysis.smartphone.classifier_retraining import (
    SIX_ROOT,
    load_candidate,
    preservation,
)
from skin_analysis.smartphone.common import file_hash, load_config, write_json

REPORT = PROJECT_ROOT.parent / "reports/skin-analysis/classifier-retraining.md"
STAGES = {
    "six": (SIX_ROOT, "nia_smartphone_classifier_retraining.toml"),
    "three": (
        PROJECT_ROOT / "runs/nia-smartphone-pore-coarse-seed-42",
        "nia_smartphone_pore_coarse.toml",
    ),
}


def verify_export(root, classes):
    """Run the candidate's explicit loader on a synthetic 256px input on CPU."""
    checkpoint = torch.load(root / "pore/inference.bin", map_location="cpu", weights_only=True)
    model = load_candidate(checkpoint, classes)
    with torch.inference_mode():
        logits = model(torch.zeros(1, 3, 256, 256))
    if logits.shape != (1, classes) or not torch.isfinite(logits).all():
        raise ValueError("Exported inference output is incompatible")
    try:
        load_candidate(checkpoint, 3 if classes == 6 else 6)
    except ValueError:
        return True
    raise ValueError("Wrong target contract was accepted")


def publish():
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    torch.set_num_threads(4)
    stages = {}
    for name, (root, config_name) in STAGES.items():
        if not (root / "comparison.json").exists():
            continue
        comparison = json.loads((root / "comparison.json").read_text(encoding="utf-8"))
        classes = comparison["classes"]
        if (
            comparison["test_set_evaluated"] is not False
            or file_hash(root / "pore/inference.bin") != comparison["candidate_sha256"]
        ):
            raise ValueError("Unexpected test evaluation or changed export")
        config = load_config(PROJECT_ROOT / "configs" / config_name)
        checkpoint = torch.load(root / "pore/inference.bin", map_location="cpu", weights_only=True)
        stages[name] = dict(
            **comparison,
            preservation=dict(files=preservation(config), passed=True),
            strict_target_loader_passed=verify_export(root, classes),
            history=json.loads((root / "pore/history.json").read_text(encoding="utf-8")),
            training_source_hash=checkpoint["environment"]["source_hash"],
            packages=checkpoint["environment"]["packages"],
            settings={k: v for k, v in config["train"].items() if k != "output"},
        )
    if "six" not in stages:
        raise ValueError("Six-class comparison must be recorded first")
    write_json(REPORT.with_suffix(".metrics.json"), stages)
    fig, axes = plt.subplots(
        2,
        len(stages),
        figsize=(6 * len(stages), 7),
        squeeze=False,
        constrained_layout=True,
    )
    lines = ["", "## 실제 비교 결과", "", "동일 검증 138명·816 ROI, 증강 없는 FP32 평가이다.", ""]
    if not stages["six"]["passes_gate"]:
        lines += ["6등급 분류층 재학습은 사전 통과 조건에 미달해 채택하지 않는다.", ""]
        if "three" not in stages:
            lines += ["후속 3등급 학습·평가 결과는 아직 이 보고서에 포함되지 않았다.", ""]
    if "three" in stages:
        lines += [
            "3등급 비교의 통과 조건도 "
            + (
                "충족했다." if stages["three"]["passes_gate"] else "미달했다. 자동 교체하지 않는다."
            ),
            "",
        ]
    for column, (name, result) in enumerate(stages.items()):
        classes = result["classes"]
        b, c = (result["results"][n]["valid"] for n in ("baseline", "candidate"))
        lines += [
            f"### {classes}등급 비교",
            "",
            "| 모델 | Accuracy | Macro Precision | Macro Recall | Macro F1 | "
            "MAE | ±1등급 | 고등급 Recall |",
            "|---|---:|---:|---:|---:|---:|---:|---:|",
        ]
        for variant in ("baseline", "candidate"):
            m = result["results"][variant]["valid"]
            label = "기존 WCE+SAM" if variant == "baseline" else "분류층 균형 재학습"
            lines.append(
                f"| {label} | {m['accuracy']:.2%} | {m['macro_precision']:.2%} | "
                f"{m['macro_recall']:.2%} | {m['macro_f1']:.2%} | {m['mae']:.4f} | "
                f"{m['within_one']:.2%} | {m['high_grade_pooled_recall']:.2%} |"
            )
        summary = result["summary"]
        lines += [
            "",
            f"선택 epoch {summary['best_epoch']} / 실행 {summary['epochs_run']}, "
            f"실행 시간 {summary['seconds']:.1f}초. "
            f"사전 통과 조건: **{'충족' if result['passes_gate'] else '미달'}**.",
            "",
            f"Accuracy 변화 {(c['accuracy'] - b['accuracy']) * 100:+.2f}%p, "
            f"Macro-F1 변화 {(c['macro_f1'] - b['macro_f1']) * 100:+.2f}%p, "
            "고등급 Recall 변화 "
            f"{(c['high_grade_pooled_recall'] - b['high_grade_pooled_recall']) * 100:+.2f}%p.",
            "",
            "| 모델 | 목표 등급 | 실제 ROI | 예측 ROI | Precision | Recall | F1 |",
            "|---|---|---:|---:|---:|---:|---:|",
        ]
        for variant in ("baseline", "candidate"):
            for g in result["results"][variant]["valid"]["per_grade"]:
                label = (
                    str(g["grade"])
                    if classes == 6
                    else ["낮음(0·1)", "중간(2·3)", "높음(4·5)"][g["grade"]]
                )
                lines.append(
                    f"| {variant} | {label} | {g['support']} | {g['predicted']} | "
                    f"{g['precision']:.2%} | {g['recall']:.2%} | {g['f1']:.2%} |"
                )
        lines += [
            "",
            "| 모델 | 학습 Accuracy | 학습 Macro-F1 | 검증 Macro-F1 | F1 차이(%p) |",
            "|---|---:|---:|---:|---:|",
        ]
        for variant in ("baseline", "candidate"):
            t, v = (result["results"][variant][s] for s in ("train", "valid"))
            lines.append(
                f"| {variant} | {t['accuracy']:.2%} | {t['macro_f1']:.2%} | "
                f"{v['macro_f1']:.2%} | {(t['macro_f1'] - v['macro_f1']) * 100:.2f} |"
            )
        lines += ["", "검증 혼동행렬(행=정답, 열=예측):", ""]
        for variant in ("baseline", "candidate"):
            matrix = result["results"][variant]["valid"]["confusion"]
            lines += [f"{variant}:", "", "```text", *[str(row) for row in matrix], "```", ""]
        if classes == 6:
            g = c["per_grade"][5]
            correct = c["confusion"][5][5]
            lines += [
                f"후보는 원본 5등급 {g['support']}개 중 {correct}개를 맞혔지만 "
                f"5등급으로 예측한 {g['predicted']}개 중 "
                f"{g['predicted'] - correct}개가 오탐이다. "
                "균형 샘플링은 출력 분포를 바꿨고 소수 등급 재현율과 전체 정확도 사이의 "
                "손익이 발생했다. 이 설정의 실패가 모든 분류층 재학습이나 데이터셋 자체의 "
                "실패를 증명하는 것은 아니다.",
                "",
                "5등급 검증 사례는 동일 인물의 6개 ROI이므로 Recall 변화는 "
                "독립적인 6명의 개선을 뜻하지 않는다. 고등급 Recall은 원본 4·5를 "
                "각각 정확한 등급으로 맞혀야 성공으로 센다.",
                "",
            ]
        else:
            lines += [
                "기준선은 기존 6등급 softmax 확률을 두 등급씩 합산하고 argmax한 결과다. "
                "단순히 기존 argmax 등급을 2로 나눈 결과와는 다를 수 있다. "
                "높음 Recall은 원본 4·5 중 어느 등급인지는 구분하지 않는다.",
                "3등급 ±1 정확도는 낮음↔높음 오류만 실패로 세므로 특히 관대하다. "
                "MAE 단위도 원본 세부 등급과 다르다.",
                "",
            ]
            g = c["per_grade"][2]
            correct = c["confusion"][2][2]
            lines += [
                f"후보의 높음 정답 {g['support']}개 중 {correct}개를 맞혔으며, "
                f"높음 예측 {g['predicted']}개 중 {g['predicted'] - correct}개는 "
                "실제 낮음·중간이었다. 추천에 활용하려면 재현율과 함께 이 정밀도도 고려해야 한다.",
                "",
            ]
        history = result["history"]
        for row, metric, title in (
            (0, "valid_macro_f1", "Validation macro F1"),
            (1, "valid_accuracy", "Validation accuracy"),
        ):
            ax = axes[row, column]
            ax.plot(
                [h["epoch"] for h in history], [h[metric] for h in history], label="Retrained head"
            )
            key = "macro_f1" if row == 0 else "accuracy"
            ax.axhline(b[key], ls="--", color="grey", label="WCE+SAM reference (same targets)")
            ax.axvline(summary["best_epoch"], ls=":", color="black", label="Selected epoch")
            ax.set(title=f"{classes} classes: {title}", xlabel="Epoch", ylim=(0, 1))
            ax.grid(alpha=0.25)
            ax.legend(fontsize=8)
        lines += [
            f"후보 SHA-256: `{result['candidate_sha256']}`",
            "",
            f"후보 경로: `ml/runs/{STAGES[name][0].name}/pore/inference.bin`",
            "",
        ]
    figure = REPORT.parent / "figures/classifier-retraining.png"
    figure.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(figure, dpi=150)
    plt.close(fig)
    lines += [
        "![분류층 재학습 검증 곡선](figures/classifier-retraining.png)",
        "",
        "## 검증 및 해석 한계",
        "",
        "각 epoch 후와 최종 평가에서 고정된 특징 추출기의 모든 파라미터·BN 버퍼가 "
        "기존 WCE+SAM 가중치와 동일한지 확인했다. 선택된 후보는 CPU에서 "
        "합성 입력 `[1,3,256,256]`으로 계약에 맞는 유한한 출력을 확인했고, 다른 등급 계약으로 "
        "읽으려 하면 거절되는지도 검사했다. 분류 지표는 sklearn 결과와 교차 검산했다.",
        "",
        "복원 추출은 소수 등급을 더 자주 학습시키지만 새로운 인물 정보는 늘리지 않는다. "
        "검증셋을 여러 실험의 선택에 반복 사용했으므로 수치는 탐색 결과이며 "
        "최종 일반화 성능은 별도 테스트로 확정해야 한다. 이번에는 보존된 테스트셋을 "
        "평가하지 않았다. 세부 등급을 묶어도 수치형 측정값이나 임상 중증도는 복원되지 않는다.",
        "",
        "기존 가중치·활성 서비스 설정의 해시 보존 검사를 통과했다. 이 결과는 "
        "모공 후보 모델 비교이며 다른 지표나 테스트 페이지의 활성 모델을 변경하지 않았다.",
        "3등급 후보를 기능에 연결하려면 기존 6등급 API·화면·추천 입력 계약도 "
        "매핑과 함께 변경해야 한다. 기존 6출력 로더에 가중치만 바꾸어 넣으면 안 된다.",
    ]
    prefix = REPORT.read_text(encoding="utf-8").split("\n## 실제 비교 결과")[0]
    REPORT.write_text(prefix + "\n".join(lines) + "\n", encoding="utf-8")
    print(json.dumps({name: r["passes_gate"] for name, r in stages.items()}))


if __name__ == "__main__":
    publish()

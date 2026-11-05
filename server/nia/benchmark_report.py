"""Render aggregate-only Markdown and figures from a completed local benchmark."""
# Report prose and Markdown table strings intentionally keep complete sentences/rows together.
# ruff: noqa: E501

import argparse
import copy
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

NAMES = {
    "class/pore": "모공 등급",
    "class/pigmentation": "색소침착 등급",
    "class/wrinkle": "주름 등급",
    "class/dryness": "입술 건조 등급",
    "class/sagging": "턱선 처짐 등급",
    "regression/pigmentation": "색소침착 회귀",
    "regression/moisture": "수분 회귀",
    "regression/elasticity_R2": "탄력 R2 회귀",
    "regression/wrinkle_Ra": "눈가 주름 Ra 회귀",
    "regression/pore": "모공 회귀",
}
NOTES = {
    "class/pore": "볼의 시각적 모공 등급(0~5)입니다. 실제 모공 개수와 같은 값이 아니며 좌우 부위를 보존합니다.",
    "class/pigmentation": "이마와 양쪽 볼의 시각적 등급(0~5)입니다. 전체 얼굴의 색소 측정 회귀값과 평가 대상이 다릅니다.",
    "class/wrinkle": "이마·미간·양쪽 눈가의 등급(0~6)입니다. 정확 일치와 ±1등급 일치를 구분해야 합니다.",
    "class/dryness": "입술 건조 등급(0~4)입니다. 얼굴 전체의 건성 피부 또는 수분 부족으로 해석하면 안 됩니다. 추천 입력에서 제외했습니다.",
    "class/sagging": "턱 부위 처짐 등급입니다. 현재 체크포인트의 출력은 0~5이며 다른 논문의 등급 수로 바꾸지 않습니다. 추천 입력에서 제외했습니다.",
    "regression/pigmentation": "전체 이미지 입력의 원래 장비 라벨 척도로 출력합니다(학습 정규화 역변환 ×350). 부위별 색소침착 등급과 직접 합치지 않습니다.",
    "regression/moisture": "이마·양쪽 볼·턱의 수분 장비값 추정입니다(×100). 학습 정규화 배율은 퍼센트나 최대값을 뜻하지 않습니다. 현재 추천 입력에서 제외했습니다.",
    "regression/elasticity_R2": "이마·양쪽 볼·턱의 장비 탄력 R2 라벨을 예측합니다(배율 1). 타깃 이름의 R2와 성능 지표인 결정계수 R²는 서로 다른 개념입니다. 추천 입력에서 제외했습니다.",
    "regression/wrinkle_Ra": "양쪽 눈가의 주름 거칠기 Ra 라벨입니다(×50). 시각적 주름 등급으로 변환한 값이 아니며 물리 단위는 별도 근거 없이 단정하지 않습니다.",
    "regression/pore": "양쪽 볼의 연속형 장비 라벨을 예측합니다(×2600). 시각적 모공 등급과 척도가 다릅니다. 임의로 0~100점이나 등급으로 재구간화하지 않습니다.",
}
DEVICES = {"smart_phone": "스마트폰", "digital_camera": "디지털카메라", "smart_pad": "태블릿"}


def number(value, percent=False):
    if value is None:
        return "—"
    return f"{value * 100:.2f}%" if percent else f"{value:.4f}"


def metric_row(name, metric, mode):
    if metric is None:
        return f"| {name} | 평가 표본 없음 |"
    if mode == "class":
        keys = ("accuracy", "macro_precision", "macro_recall", "macro_f1", "within_one")
        return (
            "| "
            + " | ".join(
                [name, str(metric["n"]), *[number(metric.get(key), percent=True) for key in keys]]
            )
            + " |"
        )
    return (
        "| "
        + " | ".join(
            [
                name,
                str(metric["n"]),
                "해당 없음",
                *[number(metric.get(key)) for key in ("mae", "mse", "rmse", "r2")],
            ]
        )
        + " |"
    )


def metric_header(mode):
    if mode == "class":
        return [
            "| 항목 / 기기 | ROI 수 | Accuracy | Precision(Macro) | Recall(Macro) | F1(Macro) | ±1등급 정확도 |",
            "|---|---:|---:|---:|---:|---:|---:|",
        ]
    return [
        "| 항목 / 기기 | ROI 수 | Accuracy | MAE | MSE | RMSE | R² |",
        "|---|---:|---|---:|---:|---:|---:|",
    ]


def figures(report, output, folder):
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import numpy as np

    folder.mkdir(parents=True, exist_ok=True)
    models = [model for model in report["nia"] if model["mode"] == "class"]
    figure, axes = plt.subplots(1, 2, figsize=(12, 4.5), constrained_layout=True)
    for axis, metric, label in zip(
        axes, ("accuracy", "macro_f1"), ("Accuracy", "Macro F1"), strict=True
    ):
        x = np.arange(len(models))
        for index, device in enumerate(report["settings"]["devices"]):
            axis.bar(
                x + (index - 1) * 0.25,
                [model["devices"][device]["metrics"][metric] for model in models],
                width=0.25,
                label=device,
            )
        axis.set_xticks(x, [model["task"].split("/")[1] for model in models])
        axis.set_ylim(0, 1)
        axis.set_ylabel(label)
        axis.grid(axis="y", alpha=0.2)
        axis.legend(fontsize=8)
    figure.savefig(folder / "classification-performance.png", dpi=160)
    plt.close(figure)

    models = [model for model in report["nia"] if model["mode"] == "regression"]
    figure, axes = plt.subplots(2, 3, figsize=(13, 8), constrained_layout=True)
    for axis, model in zip(axes.flat, models, strict=False):
        rows = json.loads(
            (output / (model["task"].replace("/", "-") + "-smart_phone.json")).read_text(
                encoding="utf-8"
            )
        )
        truth, prediction = [r["truth"] for r in rows], [r["prediction"] for r in rows]
        low, high = min(truth + prediction), max(truth + prediction)
        axis.hexbin(truth, prediction, gridsize=24, mincnt=3, cmap="viridis")
        axis.plot([low, high], [low, high], "--", color="black", linewidth=1)
        metric = model["devices"]["smart_phone"]["metrics"]
        axis.set_title(f"{model['task'].split('/')[1]} | R2={number(metric['r2'])}")
        axis.set_xlabel("Ground truth (original label units)")
        axis.set_ylabel("Prediction (original label units)")
        axis.grid(alpha=0.2)
    axes.flat[-1].set_visible(False)
    figure.savefig(folder / "regression-smartphone-density.png", dpi=160)
    plt.close(figure)


def render(report, output, destination):
    if report.get("status") != "complete":
        raise ValueError("A complete benchmark is required; do not publish partial results")
    date_kst = (
        datetime.fromisoformat(report["started_utc"])
        .astimezone(timezone(timedelta(hours=9)))
        .date()
    )
    nia_rois = sum(
        data["metrics"]["n"] for model in report["nia"] for data in model["devices"].values()
    )
    excluded_rois = sum(
        data["audit"]["excluded_rois"]
        for model in report["nia"]
        for data in model["devices"].values()
    )
    acne_images = sum(data["metrics"]["n"] for data in report["acne"]["datasets"].values())
    phone_class = [
        model["devices"]["smart_phone"]["metrics"]
        for model in report["nia"]
        if model["mode"] == "class"
    ]
    phone_regression = [
        model["devices"]["smart_phone"]["metrics"]
        for model in report["nia"]
        if model["mode"] == "regression"
    ]
    below_majority = sum(
        m["accuracy"] <= m["evaluation_majority_constant_accuracy_descriptive_only"]
        for m in phone_class
    )
    nonpositive_r2 = sum(m["r2"] is not None and m["r2"] <= 0 for m in phone_regression)
    lines = [
        "# 전체 피부 분석 모델 성능 평가 보고서",
        "",
        f"평가 기준일(KST): {date_kst}. 대상: 기존 NIA 모델 10개와 현재 선택한 여드름 모델 1개.",
        "학습·가중치 변경·테스트 임계값 조정 없이 현재 가중치를 평가했습니다.",
        f"평가량: NIA {nia_rois:,}건의 모델·ROI 평가(제외 {excluded_rois:,}건), 여드름 {acne_images:,}장. NIA의 같은 사진·인물이 항목과 기기에 걸쳐 반복될 수 있어 고유 사진 수와 다릅니다.",
        "",
        "## 판단 요약",
        "",
        f"- 스마트폰 NIA 분류 {len(phone_class)}종 중 {below_majority}종의 Accuracy가 같은 평가셋의 최빈 정답 상수 비교값보다 높지 않았습니다. Macro F1과 등급별 Recall을 함께 보아야 합니다.",
        f"- 스마트폰 NIA 회귀 {len(phone_regression)}종 중 {nonpositive_r2}종의 R²가 0 이하였습니다. 현재 평가 조건에서 개인별 상태 차이를 설명하는 성능이 부족합니다.",
        "- 여드름의 높은 합성 평가 점수는 실사 정확도를 보장하지 않습니다. 네 항목의 입력 계약 선정과 실제 추천에 필요한 품질 검증을 구분합니다.",
        "",
        "## 평가 범위와 해석",
        "",
        "- NIA: 제공된 seed-1 공식 Test 중 파일과 ROI가 유효한 부분집합, 스마트폰·디지털카메라·태블릿 3종.",
        "- 여드름: 감사 manifest의 내부 Test 및 공식 Validation을 보존한 추가 평가. 두 데이터셋 모두 합성 정면 이미지입니다.",
        "- NIA는 정답 bbox와 기존 NIA 전처리로 평가했습니다. 테스트 페이지의 자동 비율 ROI나 임의 사용자 사진의 정확도 평가가 아닙니다.",
        "- NIA 입력은 공개 평가 코드의 256px 설정을 따릅니다. 아카이브 가중치의 학습 당시 해상도·전처리와의 완전한 일치는 미확인입니다. 낮은 성능의 원인을 모델 자체나 전처리 중 하나로 단정하지 않습니다.",
        "- 표본 수는 부위 이미지(ROI) 수입니다. 같은 인물의 여러 각도·부위·기기가 있으므로 독립 인물 수로 해석하지 않습니다.",
        "- 인물 중복은 제공된 같은 항목의 Train/Validation 분할 목록을 기준으로 계산했습니다. 가중치의 전체 학습 이력이 이 목록과 정확히 대응하는지까지 검증한 것은 아닙니다.",
        "- 공개 학습 코드는 Train과 Val을 합쳐 학습하고 Test를 검증·체크포인트 선택에 사용합니다. 배포 가중치의 실제 실행 로그는 없으므로 이번 Test를 모델 선택에도 사용하지 않은 독립 최종 평가셋으로 확정할 수 없습니다. [가중치 출처·전처리 확인](checkpoint-provenance.md)에 코드와 저장 통계의 대조 근거를 기록했습니다.",
        "- Macro는 체크포인트의 전체 등급을 동등하게 평균하고, 정답·예측이 없는 등급의 P/R/F1은 0으로 둡니다. 등급별 support와 Weighted 평균도 함께 보세요.",
        "- 모델마다 등급 수·라벨 정의·측정 단위·평가 인물이 다릅니다. 지표를 하나의 전체 Accuracy로 합치거나 항목 간 단순 순위로 해석하지 않습니다.",
        "- 회귀 Accuracy는 사전 합의한 허용 오차가 없어 산출하지 않았습니다. MAE·RMSE는 원래 라벨 단위, MSE는 그 제곱 단위입니다. 서로 다른 타깃의 오차 크기를 직접 순위화하지 않습니다.",
        "- Accuracy는 전체 정답 비율입니다. Precision은 해당 등급으로 예측한 것 중 실제 정답 비율, Recall은 실제 해당 등급 중 찾아낸 비율, F1은 Precision과 Recall의 조화평균입니다. 낮은 Recall은 해당 상태를 놓칠 가능성이 크다는 뜻입니다.",
        "- MAE는 절대 오차 평균, MSE는 제곱 오차 평균, RMSE는 MSE의 제곱근입니다. 모두 낮을수록 좋고 MSE·RMSE는 큰 오차에 더 민감합니다. Weighted 평균은 등급별 정답 수로 가중하므로 흔한 등급의 영향이 큽니다.",
        "- R²는 1이 최선, 0은 해당 평가셋 정답 평균을 항상 예측하는 수준, 음수는 그 평균 예측보다 나쁜 제곱 오차를 뜻합니다. 표본 2개 미만·상수 정답이면 정의 불가로 표시합니다.",
        "- 추가 지표는 **RMSE**, **±1등급 정확도** 두 개뿐입니다. ±1등급 정확도는 순서형 NIA 분류에만 적용하며 이진 여드름에는 적용하지 않습니다.",
        "- ±1등급 정확도가 높아도 특정 중간 등급에 예측이 몰릴 수 있습니다. 정확 일치 Accuracy·Macro F1·등급별 Recall을 함께 해석해야 합니다.",
        "- 평가셋의 최빈 정답만 고르는 상수 Accuracy는 불균형 해석용 비교값입니다. 테스트셋에서 정한 값이므로 학습으로 만든 배포 가능한 기준 모델의 성능은 아닙니다.",
        "",
        "## 스마트폰 주요 결과",
        "",
        "### 분류",
        "",
        *metric_header("class"),
    ]
    for model in report["nia"]:
        if model["mode"] == "class":
            lines.append(
                metric_row(
                    NAMES[model["task"]], model["devices"]["smart_phone"]["metrics"], "class"
                )
            )
    lines += ["", "### 회귀", "", *metric_header("regression")]
    for model in report["nia"]:
        if model["mode"] == "regression":
            lines.append(
                metric_row(
                    NAMES[model["task"]], model["devices"]["smart_phone"]["metrics"], "regression"
                )
            )
    lines += [
        "",
        "![기기별 분류 Accuracy와 Macro F1](figures/classification-performance.png)",
        "",
        "![스마트폰 회귀 정답과 예측 밀도](figures/regression-smartphone-density.png)",
        "",
        "두 그림은 동일한 평가 결과의 시각화입니다. 회귀 그림은 개별점 대신 ROI가 3개 이상 모인 구간의 밀도를 표시합니다. 여드름 합성 결과를 NIA 실사 결과와 합치지 않았습니다.",
        "",
        "## 모델별 상세 결과와 주의점",
        "",
    ]
    for model in report["nia"]:
        mode = model["mode"]
        lines += [
            f"### {NAMES[model['task']]} (`{model['task']}`)",
            "",
            NOTES[model["task"]],
            "",
            f"가중치 SHA-256: `{model['checkpoint_sha256']}`.",
            "",
            *metric_header(mode),
        ]
        for device, data in model["devices"].items():
            lines.append(metric_row(DEVICES[device], data["metrics"], mode))
        lines += [
            "",
            "| 기기 | 공식 Test ROI | 평가 ROI | 제외 ROI | 평가 인물 | 제공 Train과 중복 | 제공 Val과 중복 | 양쪽 모두 미중복 인물 |",
            "|---|---:|---:|---:|---:|---:|---:|---:|",
        ]
        for device, data in model["devices"].items():
            audit = data["audit"]
            lines.append(
                f"| {DEVICES[device]} | {audit['official_test_rois']} | {audit['evaluated_rois']} | {audit['excluded_rois']} | {audit['subjects']} | {audit['comparisons']['train']['subject_overlap']} | {audit['comparisons']['val']['subject_overlap']} | {audit['no_train_val_overlap_subjects']} |"
            )
        phone = model["devices"]["smart_phone"]
        lines += ["", "스마트폰 부위별 결과:", "", *metric_header(mode)]
        for area, metric in phone["areas"].items():
            lines.append(metric_row(f"`{area}`", metric, mode))
        independent = phone["no_train_val_subject_overlap_metrics"]
        if independent:
            lines += [
                "",
                "제공된 같은 모델의 학습·검증 분할과 인물이 겹치지 않는 스마트폰 부분집합:",
                "",
                *metric_header(mode),
                metric_row("인물 미중복 부분집합", independent, mode),
                "",
                "분할 목록상 미중복일 뿐 체크포인트 전체 학습 이력과 임의 사용자 환경의 독립성을 확정하지 않습니다. 표본 수가 작으면 특히 불안정합니다.",
            ]
        else:
            lines += ["", "제공된 학습·검증 분할과 인물이 겹치지 않는 평가 부분집합이 없습니다."]
        if mode == "class":
            metric = phone["metrics"]
            most_predicted = max(metric["per_grade"], key=lambda grade: grade["predicted"])
            lines += [
                "",
                f"가장 많이 예측한 등급은 {most_predicted['grade']}등급이며 {most_predicted['predicted']}/{metric['n']}개입니다.",
            ]
            if (
                metric["accuracy"]
                <= metric["evaluation_majority_constant_accuracy_descriptive_only"]
            ):
                lines += [
                    "현재 Accuracy는 이 평가셋의 최빈 정답 상수 비교값보다 높지 않습니다. 다양한 등급을 구분하는 능력을 충분히 확보했다고 판단하지 않습니다."
                ]
            absent = [grade["grade"] for grade in metric["per_grade"] if grade["support"] == 0]
            if absent:
                lines += [
                    f"정답 표본이 없는 등급: {absent}. 해당 등급의 실제 검출 성능을 이 평가로 판단할 수 없습니다."
                ]
            lines += [
                "",
                f"스마트폰 Weighted Precision / Recall / F1: {number(metric['weighted_precision'], True)} / {number(metric['weighted_recall'], True)} / {number(metric['weighted_f1'], True)}.",
                f"같은 평가셋의 최빈 정답 상수 Accuracy(설명용): {number(metric['evaluation_majority_constant_accuracy_descriptive_only'], True)}.",
                "",
                "| 등급 | 정답 수 | 예측 수 | Precision | Recall | F1 |",
                "|---:|---:|---:|---:|---:|---:|",
            ]
            for grade in metric["per_grade"]:
                lines.append(
                    f"| {grade['grade']} | {grade['support']} | {grade['predicted']} | {number(grade['precision'], True)} | {number(grade['recall'], True)} | {number(grade['f1'], True)} |"
                )
            lines += [
                "",
                "혼동행렬(행=정답 등급, 열=예측 등급, 0등급부터 순서대로):",
                "",
                "```json",
                json.dumps(metric["confusion"]),
                "```",
            ]
        else:
            metric = phone["metrics"]
            true, predicted = metric["truth_distribution"], metric["prediction_distribution"]
            lines += [
                "",
                f"스마트폰 정답 범위 {true['min']:.4f}~{true['max']:.4f}, 예측 범위 {predicted['min']:.4f}~{predicted['max']:.4f}.",
                f"정답 / 예측 표준편차: {true['sd']:.4f} / {predicted['sd']:.4f}. 범위 압축 여부와 평균 근처 예측을 함께 확인하세요.",
            ]
            if metric["r2"] is not None and metric["r2"] <= 0:
                lines += [
                    "R²가 0 이하이므로 이 평가 조건에서는 정답 평균을 항상 예측하는 기준 이상의 설명력을 확인하지 못했습니다. 현재 회귀값을 추천 조건의 근거로 사용하지 않는 것이 타당합니다."
                ]
            if true["sd"] and predicted["sd"] < true["sd"] / 2:
                lines += [
                    "예측 표준편차가 정답의 절반 미만입니다. 서로 다른 실제 상태가 비슷한 예측값으로 압축되는 현상을 확인해야 합니다."
                ]
            if true["min"] >= 0 and predicted["min"] < 0:
                lines += [
                    "평가 정답은 모두 0 이상이지만 음수 예측이 관찰됐습니다. 회귀 출력에는 범위 제약이 없으며, 이번 평가는 0으로 보정하지 않은 원본 예측으로 계산했습니다."
                ]
        lines += [""]
    acne = report["acne"]
    lines += [
        "### 여드름 이진 분류",
        "",
        f"가중치 SHA-256: `{acne['checkpoint_sha256']}`. 저장된 임계값 `{acne['threshold']}`를 고정했습니다.",
        "현재 선택한 ImageNet 초기화 모델을 다시 추론했습니다. 정상 0 / 여드름 1이며 아래 P/R/F1의 양성은 여드름입니다.",
        "",
        "| 합성 평가셋 | 이미지 수 | Accuracy | Precision(여드름) | Recall(여드름) | F1(여드름) | Macro F1 |",
        "|---|---:|---:|---:|---:|---:|---:|",
    ]
    for split, data in acne["datasets"].items():
        metric = data["metrics"]
        lines.append(
            "| "
            + " | ".join(
                [
                    split,
                    str(metric["n"]),
                    *[
                        number(metric[key], True)
                        for key in (
                            "accuracy",
                            "precision_acne",
                            "recall_acne",
                            "f1_acne",
                            "macro_f1",
                        )
                    ],
                ]
            )
            + " |"
        )
    lines += [""]
    for split, data in acne["datasets"].items():
        lines += [
            f"{split} 혼동행렬(행=정답, 열=예측, 순서=정상 0/여드름 1):",
            "",
            "```json",
            json.dumps(data["metrics"]["confusion"]),
            "```",
            "",
        ]
    lines += [
        "합성 원본·인물의 독립성은 미확인입니다. 감사 시 유사 이미지 그룹을 분리했지만 실사 일반화를 검증한 것은 아닙니다. 메타데이터 편향이 알려져 있으므로 높은 합성 점수를 실사 성능으로 해석하지 않습니다. 다른 피부질환을 정상으로 판정할 수 있다는 근거도 없습니다. 점수는 중증도나 보정된 확률이 아닙니다.",
        "",
        "## 기능 개발 시 판단",
        "",
        "여드름·모공·색소침착·주름 네 항목의 출력 계약을 선택한 것과 추천에 사용할 정확도를 확보한 것은 별개입니다. 이 보고서에서는 기능 입력 선정이나 모델 가중치를 변경하지 않았습니다.",
        "스마트폰 모공·색소침착·주름 등급은 최빈 정답 상수 Accuracy와 등급별 Recall을 함께 검토해야 합니다. 현재 점수를 정확한 피부 상태로 단정해 추천 강도를 세분화할 근거는 부족합니다. 여드름도 합성 데이터 밖의 정상·여드름 실사 검증이 필요합니다.",
        "다음 개선에서는 원본 학습 전처리·입력 해상도·ROI 계약과 체크포인트 대응을 먼저 확인하고, 인물 단위로 분리한 별도 실사 평가셋을 확보하세요. 모델이나 임계값은 Train/Validation에서 개선하고, 반복해서 확인한 이번 Test를 새로운 최종 검증셋처럼 취급하지 않습니다.",
        "",
        "## 재현과 산출물",
        "",
        "```powershell",
        "uv run --project ml python -m server.nia.benchmark --output ml/runs/full-evaluation-새실행이름 --batch-size 16 --workers 4",
        "uv run --project ml python -m server.nia.benchmark_report --input ml/runs/full-evaluation-새실행이름 --output reports/skin-analysis/full-performance-evaluation.md",
        "```",
        "",
        f"이번 원본 결과: `{output.as_posix()}`. 개별 예측 결과·가중치·개별 ROI ID는 Git에서 제외합니다.",
        "`report.json`에는 전체 기기·부위·등급별 결과와 미중복 부분집합 결과가 있으며, task-device JSON에는 실제 정답·예측이 있습니다. 누락 ROI 수와 split 해시는 report의 audit에 보존했습니다.",
        f"공유 가능한 전체 집계는 [기기·부위·등급별 집계 JSON]({destination.with_suffix('.metrics.json').name})에도 저장했습니다. 개별 인물·ROI 식별자와 사진은 포함하지 않습니다.",
        f"실행 설정: float32, batch {report['settings']['batch_size']}, 전처리 worker {report['settings']['workers']}. 장치: {report['device']}.",
        f"실행 시점 Git HEAD: `{report['source_commit']}`. 실제 실행 코드의 파일별 SHA-256은 `source_sha256`에 기록했습니다(커밋 전 변경도 식별 가능).",
        "",
        "이번 평가는 성능 진단입니다. 운영 사용을 승인하는 판정이나 제품 추천 효과를 검증한 결과는 아닙니다. 모델·분할을 바꿔 개선할 경우 새 실행 폴더와 별도 결과를 만드세요.",
        "",
        "지표 정의 참고: [scikit-learn 분류 P/R/F1](https://scikit-learn.org/stable/modules/generated/sklearn.metrics.precision_recall_fscore_support.html), [회귀 지표](https://scikit-learn.org/stable/modules/model_evaluation.html#regression-metrics), [R² 정의와 예외](https://scikit-learn.org/stable/modules/generated/sklearn.metrics.r2_score.html).",
        "",
    ]
    destination.parent.mkdir(parents=True, exist_ok=True)
    figures(report, output, destination.parent / "figures")
    aggregate = copy.deepcopy(report)
    for model in aggregate["nia"]:
        for data in model["devices"].values():
            data["parity"] = {"checked": data["parity"]["checked"]}
    verification = output / "metric-verification.json"
    if verification.is_file():
        aggregate["metric_verification"] = json.loads(verification.read_text(encoding="utf-8"))
        if aggregate["metric_verification"].get("status") != "passed":
            raise ValueError("Independent metric verification has not passed")
        verified = aggregate["metric_verification"]
        lines += [
            f"실측 정답·예측의 모든 기기별·부위별·미중복 부분집합·기기 통합 지표를 scikit-learn과 독립 대조했습니다. {verified['metric_cohorts_checked']}개 집계, 수치 {verified['numeric_comparisons']:,}개 비교를 통과했습니다. 검증 범위와 결과는 집계 JSON의 `metric_verification`에 보존했습니다.",
            "",
        ]
    destination.with_suffix(".metrics.json").write_text(
        json.dumps(aggregate, ensure_ascii=False, indent=2, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    destination.write_text("\n".join(lines), encoding="utf-8")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", required=True)
    parser.add_argument("--output", default="reports/skin-analysis/full-performance-evaluation.md")
    args = parser.parse_args()
    folder = Path(args.input)
    render(
        json.loads((folder / "report.json").read_text(encoding="utf-8")), folder, Path(args.output)
    )
    print(args.output)


if __name__ == "__main__":
    main()

"""Prepare the four-model bundle layout; build only after both new evaluations."""

import argparse
import importlib.metadata
import importlib.util
import shutil
import sys
from pathlib import Path

import torch

HERE = Path(__file__).resolve().parent
SPEC = importlib.util.spec_from_file_location("skin_binary_expansion", HERE / "experiment.py")
if SPEC is None or SPEC.loader is None:
    raise ImportError("Missing experiment runner")
experiment = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = experiment
SPEC.loader.exec_module(experiment)

OUTPUT = experiment.OUTPUT
BUNDLE = OUTPUT / "bundle"


def final_documents(summaries):
    reports = BUNDLE / "reports"
    reports.mkdir(exist_ok=True)
    for task in experiment.NEW_TASKS:
        shutil.copytree(OUTPUT / task / "report", reports / task, dirs_exist_ok=True)
    pore_report = reports / "pore"
    pore_report.mkdir(exist_ok=True)
    for name in ("report.md", "learning-curves.png", "comparison.png"):
        shutil.copy2(experiment.PORE_RESULT.parent / name, pore_report / name)
    type_report = experiment.ML / "runs/skin-type-roi-mobilenet-20261030/report"
    shutil.copytree(type_report, reports / "skin_type_roi", dirs_exist_ok=True)
    experiment.write_json(
        BUNDLE / "training-setup.json",
        {task: summary["contract"] for task, summary in summaries.items()},
    )
    shutil.copy2(HERE / "PLAN.md", BUNDLE / "EXPERIMENT_PLAN.md")
    versions = {
        name: importlib.metadata.version(name) for name in ("torch", "torchvision", "Pillow")
    }
    (BUNDLE / "requirements.txt").write_text(
        "\n".join(f"{name}=={version}" for name, version in versions.items()) + "\n",
        encoding="utf-8",
    )
    lines = [
        "# 피부 분석 4모델 번들 사양서",
        "",
        "모공·색소침착·주름은 양호/유의 직접 이진 모델이고 피부타입은 기존 ROI 3클래스 모델이다.",
        "입력은 고정 전처리 전의 256×256 RGB 공식 ROI다. "
        "한 얼굴 사진에서 각 부위 ROI를 추출한 뒤 모델별로 사용한다.",
        "",
        "| 모델 | ROI | 학습 정답 / 출력 |",
        "|---|---|---|",
        "| 모공 | 좌·우 볼 | 0~2 양호 / 3~5 유의, sigmoid |",
        "| 색소침착 | 이마·좌·우 볼 | 0~2 양호 / 3~5 유의, sigmoid |",
        "| 주름 | 이마·미간·좌·우 눈가 | 0~2 양호 / 3~6 유의, sigmoid |",
        "| 피부타입 ROI | 이마·좌·우 볼 | 건성·중성·지성, softmax |",
        "",
        "## 공통 구조와 입력",
        "",
        "MobileNetV3-Large, ImageNet1K V2 초기화, Dropout 0.2. "
        "이진 Head는 960→1280→Hardswish→Dropout→1 logit이며 피부타입의 마지막 출력은 3개다.",
        "ROI 256px JPEG RGB → Unsharp radius 1 / 75% / threshold 0 → Contrast ×1.4 → "
        "ImageNet mean [0.485,0.456,0.406], std [0.229,0.224,0.225]. "
        "고정 전처리는 입력에 한 번만 적용한다.",
        "",
        "## 이진 모델 학습",
        "",
        "원본 등급별 제곱근 추가 추출로 매 epoch 원본 전체를 사용한다. "
        "원본 Train 이진 빈도 기준 w=N/(2×n_c) 가중 BCEWithLogitsLoss를 사용한다. "
        "원본 등급은 추가 추출 및 진단용이며 모델은 이진 정답을 직접 학습한다.",
        "Batch 16, head-only 1 epoch 후 전체 미세조정, 최대 100 epoch, patience 10. "
        "AdamW+SAM ρ=0.05, weight decay=0.0001. Head-only LR=0.001, "
        "미세조정 Head LR=0.0001 / Backbone LR=0.00001. "
        "ReduceLROnPlateau factor=0.5 / patience=2 / min LR=1e-7. "
        "학습 seed=42, Validation Macro-F1 최대, 동률이면 비가중 BCE 최소 checkpoint.",
        "Train 증강은 회전 ±5°, 이동 ±2%, 밝기·대비 ±10%, 채도 ±5%이고 "
        "좌우 반전은 사용하지 않았다.",
        "모공의 새 인물 seed42 고정 분할을 세 이진 모델이 공유한다. "
        "0427번은 모공에서만 제외했고 나머지 두 작업에는 원래 Test 소속으로 유지했다.",
        "",
        "| 모델 | Train / Valid / Test ROI | best / 종료 epoch | Validation Macro-F1 |",
        "|---|---|---|---:|",
    ]
    for task, summary in summaries.items():
        splits = summary["contract"]["splits"]
        sizes = " / ".join(str(splits[key]["roi"]) for key in ("train", "valid", "test"))
        lines.append(
            f"| {task} | {sizes} | {summary['best_epoch']} / "
            f"{summary['epochs_run']} | {summary['best_validation']['macro_f1']:.4f} |"
        )
    lines += [
        "",
        "## 피부타입 ROI 모델",
        "",
        "기존 선택 checkpoint(best epoch 20 / 종료 30)를 유지했다. "
        "Train 4,368 / Validation 874 / Test 852 ROI, 인물 488 / 98 / 95명. "
        "건성·중성·지성의 제곱근 추가 추출과 원본 빈도 α=0.5 가중 cross-entropy를 사용했다. "
        "Head/Batch/최대 epoch/patience/AdamW+SAM/LR/Scheduler는 위와 같다. "
        "Validation Macro-F1 0.4602, ROI Test Macro-F1 0.4698 / Accuracy 0.4977. "
        "복합성과 심한 건성은 학습 범위에 포함되지 않는다.",
        "",
        "피부타입은 이전 인물 분할을 유지하므로 새 이진 모델들과 같은 공통 held-out 평가가 아니다.",
        "",
        "## 실행",
        "",
        "```powershell",
        "python predict.py --task pore --image pore_roi.jpg",
        "python predict.py --task pigmentation --image pigmentation_roi.jpg",
        "python predict.py --task wrinkle --image wrinkle_roi.jpg",
        "python predict.py --task skin_type_roi --image forehead_roi.jpg --image cheek_roi.jpg",
        "```",
        "",
        "이진 출력은 label 0(양호)/1(유의), probability_caution, threshold=0.5다. "
        "피부타입은 복수 ROI의 softmax 평균을 출력한다. "
        "점수는 보정되지 않은 모델 점수다. 0~5/6등급 출력 규격과 다르다.",
        "Python·PyTorch·torchvision·Pillow로 독립 실행하며 원본 프로젝트 import가 필요 없다. "
        "자동 얼굴/ROI 추출 및 Expo 앱 통합은 이 번들의 범위 밖이다.",
        "",
        "세부 설정은 [training-setup.json](training-setup.json), "
        "평가는 [통합 성능 문서](INTEGRATED_EVALUATION.md)를 참조한다.",
    ]
    (BUNDLE / "MODEL_SPEC.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    lines = [
        "# 4모델 통합 성능 문서",
        "",
        "각 모델의 고정 Test에서 얻은 지표다. 서로 다른 정답과 ROI를 합쳐 "
        "단일 정확도나 다중출력 전체 정답률로 해석하지 않는다.",
        "",
        "| 모델 | Test ROI | Accuracy | Macro P | Macro R | Macro-F1 | BCE |",
        "|---|---:|---:|---:|---:|---:|---:|",
    ]
    for task, summary in summaries.items():
        row = summary["candidate_test"]
        lines.append(
            f"| {task} | {row['n']} | {row['accuracy']:.4f} | "
            f"{row['macro_precision']:.4f} | {row['macro_recall']:.4f} | "
            f"{row['macro_f1']:.4f} | {row['cross_entropy']:.4f} |"
        )
    lines += [
        "",
        "피부타입의 ROI Test Macro-F1은 0.4698, Accuracy 0.4977이다. "
        "기존 인물별 평균 평가에서는 Macro-F1 0.4769 / Accuracy 0.5158이었다.",
        "",
        "## 이진 클래스 및 원본 등급 분석",
        "",
    ]
    for task, summary in summaries.items():
        result = summary["candidate_test"]
        good, caution = result["per_class"]
        high_miss = result.get("grade4plus_miss_rate", result.get("grade45_miss_rate"))
        lines += [
            f"### {task}",
            "",
            f"양호 Recall {good['recall']:.4f}, 유의 Precision {caution['precision']:.4f}, "
            f"유의 Recall {caution['recall']:.4f}, 4등급 이상 놓침률 {high_miss:.4f}.",
            f"혼동행렬(행=정답/열=예측, 양호/유의): `{result['confusion']}`",
            "",
            "| 원본 등급 | Test 수 | 유의 예측률 |",
            "|---:|---:|---:|",
        ]
        for grade in result["per_original_grade"]:
            value = grade.get("predicted_caution_rate", grade.get("caution_recall"))
            score = f"{value:.4f}" if value is not None else "표본 없음"
            lines.append(f"| {grade['grade']} | {grade['support']} | {score} |")
        lines += [
            "",
            "0~2등급의 유의 예측률은 오탐률, 3등급 이상은 유의 Recall이다.",
            "",
            f"[개별 보고서](reports/{task}/report.md)",
            "",
            f"![학습 곡선](reports/{task}/learning-curves.png)",
            "",
        ]
    lines += [
        "## 피부타입",
        "",
        "[기존 ROI 평가 보고서](reports/skin_type_roi/report.md)",
        "",
        "![피부타입 학습 곡선](reports/skin_type_roi/curves.png)",
        "",
        "피부타입은 이전 분할이므로 번들 전체의 공통 인물 평가 성능은 미측정이다. "
        "모공 Test 5등급은 한 사람의 6 ROI라 해당 Recall의 일반화 해석은 제한된다.",
    ]
    (BUNDLE / "INTEGRATED_EVALUATION.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def prepare():
    if (BUNDLE / "manifest.json").exists():
        raise FileExistsError("Completed bundle already exists")
    BUNDLE.mkdir(parents=True, exist_ok=True)
    (BUNDLE / "weights").mkdir(exist_ok=True)
    shutil.copy2(HERE / "predict.py", BUNDLE / "predict.py")
    old = experiment.read(experiment.OLD_BUNDLE / "manifest.json")
    plan = {
        "status": "prepared_not_complete",
        "models": {
            "pore": {
                "status": "trained_and_evaluated",
                "source": str(experiment.PORE_RESULT / "best.pt"),
                "output": "binary",
            },
            **{
                task: {
                    "status": "pending_training_and_evaluation",
                    "source": str(OUTPUT / task / "best.pt"),
                    "output": "binary",
                }
                for task in experiment.NEW_TASKS
            },
            "skin_type_roi": {
                "status": "reuse_existing",
                "source": str(experiment.OLD_BUNDLE / old["models"]["skin_type_roi"]["file"]),
                "output": "three_class_softmax",
            },
        },
        "binary_threshold": 0.5,
        "binary_classes": ["양호", "유의"],
        "layout": [
            "weights/",
            "manifest.json (written only after build)",
            "predict.py",
            "MODEL_SPEC.md",
            "INTEGRATED_EVALUATION.md",
        ],
    }
    experiment.write_json(BUNDLE / "bundle-plan.json", plan)
    (BUNDLE / "MODEL_SPEC.md").write_text(
        "# 피부 분석 이진 모델 번들 사양서 — 준비본\n\n"
        "모공·색소침착·주름은 양호/유의 직접 이진 모델, "
        "피부타입은 기존 ROI 건성·중성·지성 모델을 포함한다. "
        "새 색소침착·주름 모델은 학습 및 평가 전이며 완성 번들은 아직 생성하지 않았다.\n\n"
        "이진 정답은 원본 등급 <3이면 양호, ≥3이면 유의다. "
        "주름은 원본 0~6등급 중 3~6등급을 유의로 사용한다. "
        "등급 번호를 예측해서 반올림하는 대신 sigmoid 점수 0.5로 직접 판정한다.\n\n"
        "MobileNetV3-Large ImageNet V2, head 960→1280→Hardswish→Dropout(0.2)→1. "
        "RGB 256px 공식 ROI, Unsharp radius 1/75%/threshold 0, contrast ×1.4, ImageNet 정규화. "
        "부위별 정사각형 ROI가 입력이며 한 얼굴 사진은 모공(볼), "
        "색소침착(이마/볼), 주름(이마/미간/눈가)에 맞게 잘라 사용한다. "
        "자동 얼굴 검출·ROI 추출과 앱 연결은 별도 단계다.\n\n"
        "기존 네 모델 번들처럼 독립 실행 predict.py, SHA-256 manifest, "
        "최소 추론 가중치, 사양서와 통합 평가 문서를 구성한다. "
        "전체 학습 설정·데이터 규모는 상위 디렉터리 setup.json 및 실험 PLAN.md를 참조한다.\n",
        encoding="utf-8",
    )
    (BUNDLE / "INTEGRATED_EVALUATION.md").write_text(
        "# 통합 성능 평가 — 준비본\n\n색소침착·주름의 새 학습 및 최종 Test 평가가 끝나면 각 모델의 "
        "Validation/Test Accuracy·Macro Precision/Recall/F1·BCE, "
        "혼동행렬, 원본 등급별 유의 예측률을 채운다. "
        "서로 다른 정답·ROI·Test 표본을 합쳐 단일 통합 정확도로 표시하지 않는다. "
        "기존 피부타입 모델은 다른 인물 분할로 학습됐으므로 "
        "이 번들 전체의 공통 held-out 평가를 했다고 주장하지 않는다.\n",
        encoding="utf-8",
    )
    return plan


def build():
    if (BUNDLE / "manifest.json").exists():
        raise FileExistsError("Completed bundle already exists")
    old = experiment.read(experiment.OLD_BUNDLE / "manifest.json")
    summaries = {"pore": experiment.read(experiment.PORE_RESULT / "summary.json")}
    for task in experiment.NEW_TASKS:
        summaries[task] = experiment.read(OUTPUT / task / "summary.json")
        if summaries[task].get("status") != "evaluated":
            raise ValueError(f"Final evaluation is pending: {task}")
    prepare()
    records = {}
    specs = []
    evaluations = []
    for task, summary in summaries.items():
        source = experiment.PORE_RESULT / "best.pt" if task == "pore" else OUTPUT / task / "best.pt"
        checkpoint = torch.load(source, map_location="cpu", weights_only=True)
        if checkpoint["epoch"] != summary["best_epoch"]:
            raise ValueError("Checkpoint/summary epoch mismatch")
        target = BUNDLE / "weights" / f"{task}.pt"
        torch.save({"model_state": checkpoint["model_state"]}, target)
        records[task] = {
            "file": f"weights/{task}.pt",
            "sha256": experiment.file_hash(target),
            "source_sha256": experiment.file_hash(source),
            "architecture": "mobilenet_v3_large",
            "dropout": 0.2,
            "outputs": 1,
            "classes": ["양호", "유의"],
            "threshold": 0.5,
            "original_grade_mapping": [int(g >= 3) for g in range(7 if task == "wrinkle" else 6)],
            "best_epoch": summary["best_epoch"],
            "contract": summary["contract"],
        }
        result = summary["candidate_test"]
        specs.append(
            f"| {task} | {summary['best_epoch']} | {summary['epochs_run']} | "
            f"{summary['best_validation']['macro_f1']:.4f} | {result['macro_f1']:.4f} |"
        )
        evaluations.append(
            f"| {task} | {result['n']} | {result['accuracy']:.4f} | "
            f"{result['macro_precision']:.4f} | {result['macro_recall']:.4f} | "
            f"{result['macro_f1']:.4f} | {result['cross_entropy']:.4f} |"
        )
    record = dict(old["models"]["skin_type_roi"])
    source = experiment.OLD_BUNDLE / record["file"]
    if experiment.file_hash(source) != record["sha256"]:
        raise ValueError("Existing skin-type weight hash mismatch")
    target = BUNDLE / "weights/skin_type_roi.pt"
    shutil.copy2(source, target)
    record["file"] = "weights/skin_type_roi.pt"
    records["skin_type_roi"] = record
    with (BUNDLE / "MODEL_SPEC.md").open("a", encoding="utf-8") as handle:
        handle.write(
            "\n## 학습 완료 지표\n\n| 모델 | best epoch | 종료 epoch | "
            "Validation Macro-F1 | Test Macro-F1 |\n|---|---:|---:|---:|---:|\n"
            + "\n".join(specs)
            + "\n"
        )
    with (BUNDLE / "INTEGRATED_EVALUATION.md").open("a", encoding="utf-8") as handle:
        handle.write(
            "\n## 이진 모델 Test\n\n| 모델 | Test ROI | Accuracy | Macro P | Macro R | "
            "Macro-F1 | BCE |\n|---|---:|---:|---:|---:|---:|---:|\n"
            + "\n".join(evaluations)
            + "\n\n피부타입의 기존 ROI Test Macro-F1은 0.4698, Accuracy는 0.4977이다. "
            "새 이진 모델과 동일한 인물 분할 평가가 아니다.\n"
        )
    for filename in ("MODEL_SPEC.md", "INTEGRATED_EVALUATION.md"):
        path = BUNDLE / filename
        text = path.read_text(encoding="utf-8").replace("— 준비본", "— 완료본")
        text = text.replace(
            "새 색소침착·주름 모델은 학습 및 평가 전이며 완성 번들은 아직 생성하지 않았다.",
            "색소침착·주름의 학습과 최종 평가를 완료했고 선택 가중치를 포함했다.",
        )
        text = text.replace(
            "색소침착·주름의 새 학습 및 최종 Test 평가가 끝나면 각 모델의 ", "각 모델의 "
        ).replace("를 채운다.", "를 기록했다.")
        path.write_text(text, encoding="utf-8")
    shutil.copy2(experiment.OLD_BUNDLE / "MODEL_SPEC.md", BUNDLE / "PREVIOUS_MODEL_SPEC.md")
    plan = experiment.read(BUNDLE / "bundle-plan.json")
    plan["status"] = "complete"
    for entry in plan["models"].values():
        entry["status"] = "included"
    experiment.write_json(BUNDLE / "bundle-plan.json", plan)
    final_documents(summaries)
    # Write the loadable manifest last so a partial bundle cannot be inferred.
    experiment.write_json(
        BUNDLE / "manifest.json",
        {
            "schema": "skin-binary-three-and-roi-type-v1",
            "models": records,
            "preprocessing": experiment.reference.PIPELINE,
            "input": "task-specific unprocessed 256x256 RGB ROI; preprocessing applied once",
            "outputs": (
                "three independent binary sigmoid scores plus existing three-class ROI "
                "skin-type softmax"
            ),
            "combined_validation": (
                "not established; skin-type retains a different historical subject split"
            ),
        },
    )
    from verify_bundle import verify_bundle

    try:
        verify_bundle(BUNDLE)
    except Exception:
        (BUNDLE / "manifest.json").unlink()
        raise
    shutil.make_archive(str(BUNDLE), "zip", root_dir=BUNDLE.parent, base_dir=BUNDLE.name)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("prepare", "build"), nargs="?", default="prepare")
    args = parser.parse_args()
    (prepare if args.action == "prepare" else build)()


if __name__ == "__main__":
    main()

"""Publish aggregate results without photos, subject IDs or per-ROI predictions."""

import argparse
import hashlib
import json
from pathlib import Path

from .common import DEFAULT_CONFIG, TASKS, load_config, write_json


def percent(value):
    return f"{value * 100:.2f}%"


def publish(config):
    output = Path(config["train"]["output"])
    raw = json.loads((output / "evaluation.json").read_text(encoding="utf-8"))
    public = {
        key: raw[key]
        for key in (
            "schema",
            "data_fingerprint",
            "data",
            "exclusions",
            "source_photo_count",
            "tasks",
            "caveats",
        )
    }
    public["training_settings"] = {
        k: v for k, v in raw["training_settings"].items() if k != "output"
    }
    public["split_settings"] = {
        k: v for k, v in raw["split_settings"].items() if k not in {"root", "output"}
    }
    public["original_evaluation_sha256"] = hashlib.sha256(
        (output / "evaluation.json").read_bytes()
    ).hexdigest()
    directory = Path("reports/skin-analysis")
    write_json(directory / "smartphone-training.metrics.json", public)
    document = directory / "smartphone-training.md"
    text = document.read_text(encoding="utf-8").split("\n## 실제 실행 결과")[0]
    text = text.replace(
        "현재 이 문서는 실행 계획과 재현 방법입니다. 학습·최종 평가가 끝나면 실제 결과와\n"
        "가중치 SHA-256을 추가합니다. 계획만으로 학습 완료나 서비스 반영을 의미하지 않습니다.",
        "세 항목의 학습과 최종 평가를 완료했습니다. 실제 수치·가중치·연결 상태는 아래\n"
        "실행 결과에 기록합니다. 운영 배포나 임의 셀카 정확도 검증을 의미하지 않습니다.",
    )
    lines = [
        "",
        "## 실제 실행 결과",
        "",
        f"원본 스마트폰 사진 {raw['source_photo_count']:,}장을 사용했습니다. "
        "원본에서 라벨·ROI를 확인해 만든 새 인물 단위 분할입니다.",
        "",
        f"데이터 fingerprint: `{raw['data_fingerprint']}`.",
        "",
        "| 항목 | 분할 | 인물 수 | ROI 수 | 등급별 ROI 수 |",
        "|---|---|---:|---:|---|",
    ]
    names = dict(pore="모공", pigmentation="색소침착", wrinkle="주름")
    for task in TASKS:
        for split, stats in raw["data"][task].items():
            lines.append(
                f"| {names[task]} | {split} | {stats['subjects']} | {stats['n']} | "
                f"{stats['grade_support']} |"
            )
    lines += [
        "",
        f"제외 집계: `{json.dumps(raw['exclusions'], ensure_ascii=False)}`.",
        "",
        "### 같은 최종 평가 ROI에서의 비교",
        "",
        "| 항목 | 모델 | Accuracy | macro Precision | macro Recall | macro-F1 | ±1등급 |",
        "|---|---|---:|---:|---:|---:|---:|",
    ]
    for task, result in raw["tasks"].items():
        for variant, label in (
            ("smartphone", "새 스마트폰 모델"),
            ("legacy_nia", "기존 NIA"),
            ("train_majority", "학습 최빈 등급"),
        ):
            m = result[variant]["overall"]
            values = [
                percent(m[k])
                for k in ("accuracy", "macro_precision", "macro_recall", "macro_f1", "within_one")
            ]
            lines.append(f"| {names[task]} | {label} | " + " | ".join(values) + " |")
    lines += [
        "",
        "weighted 지표와 혼동행렬은 [집계 JSON](smartphone-training.metrics.json)에 "
        "기록합니다. ±1등급은 허용 오차를 적용한 적중률이며 정확 일치율과 구분합니다.",
        "",
        "기존 NIA의 학습 인물 노출 가능성이 있어 이 비교를 공정한 완전 독립 모델 대결이나 "
        "논문 재현으로 해석하지 않습니다.",
        "",
        "### 새 모델의 부위별 결과",
        "",
        "| 항목 | 부위 | ROI 수 | Accuracy | macro-F1 | ±1등급 |",
        "|---|---|---:|---:|---:|---:|",
    ]
    for task, result in raw["tasks"].items():
        for area, metrics in result["smartphone"]["areas"].items():
            lines.append(
                f"| {names[task]} | {area} | {metrics['n']} | "
                f"{percent(metrics['accuracy'])} | {percent(metrics['macro_f1'])} | "
                f"{percent(metrics['within_one'])} |"
            )
    lines += [
        "",
        "### 새 모델의 등급별 결과",
        "",
        "| 항목 | 등급 | 실제 수 | 예측 수 | Precision | Recall | F1 |",
        "|---|---:|---:|---:|---:|---:|---:|",
    ]
    for task, result in raw["tasks"].items():
        for grade in result["smartphone"]["overall"]["per_grade"]:
            lines.append(
                f"| {names[task]} | {grade['grade']} | {grade['support']} | "
                f"{grade['predicted']} | {percent(grade['precision'])} | "
                f"{percent(grade['recall'])} | {percent(grade['f1'])} |"
            )
    lines += [
        "",
        "### 선택된 가중치",
        "",
        "| 항목 | 선택 epoch | 실행 epoch 수 | 추론 가중치 SHA-256 |",
        "|---|---:|---:|---|",
    ]
    for task, result in raw["tasks"].items():
        lines.append(
            f"| {names[task]} | {result['best_epoch']} | {result['epochs_run']} | "
            f"`{result['sha256']}` |"
        )
    local_config = json.loads(Path("server/nia/config.local.json").read_text(encoding="utf-8"))
    active = {m["task"]: m["sha256"] for m in local_config["models"]}
    activated = all(
        active.get(f"class/{task}") == result["sha256"] for task, result in raw["tasks"].items()
    )
    public["local_config_activated"] = activated
    write_json(directory / "smartphone-training.metrics.json", public)
    lines += [
        "",
        f"로컬 연구 설정의 세 모델 교체 여부: **{'완료' if activated else '미반영'}**.",
        "새 모델 묶음은 `ml/runs/nia-smartphone-seed-42/recommendation-bundle/`입니다. "
        "새 묶음이 생성된 경우에만 해당 경로를 사용합니다. 기존 "
        "`ml/runs/skin-recommendation-v1/`는 원본 비교용으로 보존합니다.",
        "",
    ]
    document.write_text(text + "\n".join(lines), encoding="utf-8")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    args = parser.parse_args()
    publish(load_config(args.config))


if __name__ == "__main__":
    main()

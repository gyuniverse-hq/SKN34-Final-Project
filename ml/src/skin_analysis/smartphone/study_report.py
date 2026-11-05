"""Readable Korean Markdown, with aggregate-only public machine evidence."""

from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np

from .common import TASKS
from .study_design import atomic_json, optimizer_recipe, recipe_id

NAMES = dict(pore="모공", pigmentation="색소침착", wrinkle="주름")
STAGES = {
    "A": (
        "a-weight-sam-batch.md",
        "A. WCE·SAM·배치 대조",
        "가중치 공식·상한·SAM 효과를 같은 배치에서 분리할 수 있는가?",
    ),
    "B": (
        "b-losses.md",
        "B. 손실함수 대안",
        "같은 학습 예산에서 Focal·CB·순서형 손실보다 선택 후보가 적합한가?",
    ),
    "C": (
        "c-backbones.md",
        "C. Backbone·학습률·SAM 민감도",
        "다른 backbone과 동등한 학습률 탐색에서도 성능과 비용이 유리한가?",
    ),
    "D": (
        "d-confirmation.md",
        "D. 최종 후보 재검증",
        "여러 인물 분할과 학습 seed에서도 선정 근거가 유지되는가?",
    ),
}
STATUS = dict(
    planned="예정",
    running="진행",
    completed="완료",
    invalid="무효",
    failed="실패",
    interrupted="중단",
    scheduled_stop="예약 중단",
)
LOSS_NAMES = {
    "unweighted_cross_entropy": "일반 CE",
    "weighted_cross_entropy": "WCE",
    "weighted_focal": "Weighted Focal",
    "class_balanced_ce": "CB-CE",
    "class_balanced_focal": "CB Focal",
    "weighted_ordinal_cdf": "순서형 CDF",
    "coral": "CORAL",
}


def recipe_label(recipe):
    loss = LOSS_NAMES[recipe["loss"]]
    if recipe["loss"] in ("weighted_cross_entropy", "weighted_focal", "weighted_ordinal_cdf"):
        cap = recipe["class_weight_cap"]
        loss += f"(α={recipe['weight_exponent']:g}, 상한 {'없음' if cap is None else f'{cap:g}'})"
    if "focal_gamma" in recipe:
        loss += f" γ={recipe['focal_gamma']:g}"
    if "cb_beta" in recipe:
        loss += f" β={recipe['cb_beta']:g}"
    optimizer = "AdamW" if recipe["optimizer"] == "adamw" else f"SAM(ρ={recipe['sam_rho']:g})"
    return (
        f"{recipe['backbone']} / {loss} / {optimizer} / 배치{recipe['batch_size']}"
        f" / LR×{recipe['lr_multiplier']:g}"
    )


def percent(value):
    return f"{value * 100:.2f}%"


def mean_std(values, *, percentage=True):
    values = list(values)
    if not values:
        return "—"
    scale = 100 if percentage else 1
    std = np.std(values, ddof=1) if len(values) > 1 else 0.0
    return f"{np.mean(values) * scale:.2f} ± {std * scale:.2f}" + ("%" if percentage else "")


def write_md(path, lines):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".md.tmp")
    temporary.write_text("\n".join(lines) + "\n", encoding="utf-8")
    temporary.replace(path)


def completed_groups(state, run_ids):
    groups = defaultdict(list)
    for identifier in dict.fromkeys(run_ids):
        run = state["runs"][identifier]
        if run["status"] == "completed":
            groups[(run["task"], recipe_id(run["recipe"]))].append(run)
    return groups


def stage_progress(state, key):
    stage = state["stages"][key]
    ids = list(dict.fromkeys(stage["runs"] + stage.get("sensitivity_runs", [])))
    completed = sum(state["runs"][r]["status"] == "completed" for r in ids)
    invalid = sum(any(a["status"] == "invalid" for a in state["runs"][r]["attempts"]) for r in ids)
    return completed, len(ids), invalid


def support_table(state):
    lines = ["| 항목 | 분할 | 인물 수 | ROI 수 | 등급별 ROI 수 |", "|---|---|---:|---:|---|"]
    for task in TASKS:
        for split, stats in state["source_summary"][task].items():
            lines.append(
                f"| {NAMES[task]} | {split} | {stats['subjects']} | {stats['n']:,} | "
                + " / ".join(map(str, stats["grade_support"]))
                + " |"
            )
    return lines


def effects_table(state, task, groups):
    """Seed-paired factorial contrasts; distinguish provisional/incomplete groups."""
    values = {}
    for (_, identifier), runs in groups.items():
        if runs[0]["task"] != task:
            continue
        alias = state["aliases"][f"{task}:{identifier}"]["aliases"]
        recipe = runs[0]["recipe"]
        for name in alias:
            values[name, recipe["optimizer"], recipe["batch_size"]] = {
                r["seed"]: r["result"]["metrics"]["overall"]["macro_f1"] for r in runs
            }
    lines = [
        "",
        "### 같은 조건에서의 효과 분리",
        "",
        "차이는 같은 seed끼리 뺀 Macro-F1 변화다. 3개 seed가 모두 모이기 전에는 판단하지 않는다.",
        "",
        "| 바뀐 요인 | 고정 조건 | 반복 수 | Macro-F1 변화 평균 ± 표준편차 (%p) |",
        "|---|---|---:|---:|",
    ]

    def contrast(label, fixed, left_key, right_key):
        left, right = values.get(left_key, {}), values.get(right_key, {})
        seeds = sorted(set(left) & set(right))
        if not seeds:
            return
        differences = [(left[s] - right[s]) * 100 for s in seeds]
        std = np.std(differences, ddof=1) if len(seeds) > 1 else 0
        value = f"{np.mean(differences):+.2f} ± {std:.2f}" if len(seeds) == 3 else "반복 수 부족"
        lines.append(f"| {label} | {fixed} | {len(seeds)} | {value} |")

    weights = ("ce", "sqrt-cap2", "sqrt-cap4", "sqrt-uncapped", "inverse-cap4", "inverse-uncapped")
    for weight in weights:
        for batch in (16, 32):
            contrast(
                "SAM 추가",
                f"{weight}, 배치{batch}",
                (weight, "sam_adamw", batch),
                (weight, "adamw", batch),
            )
    for optimizer in ("adamw", "sam_adamw"):
        for batch in (16, 32):
            for weight in weights[1:]:
                contrast(
                    "CE → " + weight,
                    f"{optimizer}, 배치{batch}",
                    (weight, optimizer, batch),
                    ("ce", optimizer, batch),
                )
            contrast(
                "제곱근 상한 4 적용",
                f"{optimizer}, 배치{batch}",
                ("sqrt-cap4", optimizer, batch),
                ("sqrt-uncapped", optimizer, batch),
            )
    for weight in weights:
        keys = [
            (weight, o, b)
            for o, b in (("sam_adamw", 16), ("adamw", 16), ("sam_adamw", 32), ("adamw", 32))
        ]
        shared = set.intersection(*(set(values.get(k, {})) for k in keys))
        if len(shared) == 3:
            delta = [
                100
                * (
                    values[keys[0]][s]
                    - values[keys[1]][s]
                    - values[keys[2]][s]
                    + values[keys[3]][s]
                )
                for s in sorted(shared)
            ]
            lines.append(
                f"| SAM×배치 상호작용 | {weight}, SAM 효과 배치16−32 | 3 | "
                f"{np.mean(delta):+.2f} ± {np.std(delta, ddof=1):.2f} |"
            )
    return lines


def metric_details(metrics):
    lines = [
        "",
        "| 등급 | 정답 ROI | 독립 인물 | 예측 ROI | Precision | Recall | F1 |",
        "|---|---:|---:|---:|---:|---:|---:|",
    ]
    for row in metrics["per_grade"]:
        grade = row["grade"]
        people = metrics.get("grade_subject_support", ["—"] * len(metrics["per_grade"]))[grade]
        lines.append(
            f"| {grade} | {row['support']} | {people} | {row['predicted']} | "
            f"{percent(row['precision'])} | {percent(row['recall'])} | {percent(row['f1'])} |"
        )
    lines += [
        "",
        "혼동행렬: 행은 정답, 열은 예측이다.",
        "",
        "```text",
        *[str(row) for row in metrics["confusion"]],
        "```",
        "",
    ]
    return lines


def run_details(run):
    result = run["result"]
    overall = result["metrics"]["overall"]
    lines = [
        f"# {NAMES[run['task']]} 개별 실행 기록",
        "",
        recipe_label(run["recipe"]),
        "",
        f"학습 seed {run['seed']}, "
        + ("기존 train/valid 분할" if run["fold"] is None else f"바깥 fold {run['fold']}"),
        "",
        "## 핵심 결과",
        "",
        "이 기록은 한 번의 학습 결과다. 여러 seed·후보를 비교한 선정 결론과 구분한다.",
        "",
        "| 지표 | 값 |",
        "|---|---:|",
    ]
    for key, label in (
        ("macro_f1", "Macro-F1"),
        ("accuracy", "Accuracy"),
        ("macro_precision", "Macro Precision"),
        ("macro_recall", "Macro Recall"),
        ("weighted_precision", "Weighted Precision"),
        ("weighted_recall", "Weighted Recall"),
        ("weighted_f1", "Weighted F1"),
        ("within_one", "±1등급 정확도"),
        ("high_grade_exact_recall", "고등급 정확 등급 Recall"),
        ("high_grade_detection_recall", "고등급 탐지 Recall"),
        ("high_grade_detection_precision", "고등급 탐지 Precision"),
    ):
        lines.append(f"| {label} | {percent(overall[key])} |")
    lines += [
        f"| MAE | {overall['mae']:.3f}등급 |",
        f"| 인물 / ROI | {overall['subjects']}명 / {overall['n']}개 |",
        f"| 선택 epoch / 실행 epoch | {result['best_epoch']} / {result['epochs_run']} |",
        f"| 전체 실행시간 | {result['execution_wall_seconds'] / 60:.2f}분 |",
        f"| optimizer update | {result['optimizer_steps']:,}회 |",
        f"| GPU 최대 allocated 메모리 | {result['peak_memory_bytes'] / 1024**3:.2f} GiB |",
        f"| batch1 FP32 지연 중앙값 | {result['latency_ms']:.2f} ms |",
        "",
        "고등급은 모공·색소침착 4·5, 주름 5·6이다. 정확 등급 Recall은 각각의 정답 "
        "등급을 맞혀야 하며, 탐지 지표는 상위 두 등급 안으로 예측하면 맞힌다.",
        "",
        "## 등급별 성능",
        *metric_details(overall),
        "## 부위별 성능",
        "",
    ]
    for area, metrics in result["metrics"]["areas"].items():
        lines += [
            f"### {area}",
            "",
            f"{metrics['subjects']}명·{metrics['n']} ROI, "
            f"Macro-F1 {percent(metrics['macro_f1'])}, "
            f"Accuracy {percent(metrics['accuracy'])}, MAE {metrics['mae']:.3f}등급.",
            *metric_details(metrics),
        ]
    lines += [
        "## 재현 정보",
        "",
        f"실행 ID: `{run['id']}`.",
        "",
        f"가중치 SHA-256: `{result['sha256']}`.",
        "",
        f"코드 SHA-256: `{result['source_hash']}`.",
        "",
        f"데이터 fingerprint: `{result['data_fingerprint']}`.",
        "",
        "개별 인물·ROI별 예측과 사진은 공개하지 않는다.",
        "",
        "[해당 실험 진행 보고](../../experiment-summary.md)",
    ]
    if "initialization" in result:
        lines += [
            "",
            f"초기화: `{result['initialization']['source']}`.",
            "",
            f"초기 가중치 SHA-256: `{result['initialization']['sha256']}`.",
        ]
    return lines


def reference_contrasts(state, stage, task, task_groups):
    reference = stage["references"][task]
    lines = [
        "",
        "### 공통 기준선 대비",
        "",
        "같은 optimizer·seed의 기준선과 비교한 Macro-F1 변화다. "
        "세 seed가 모두 모여야 차이를 표시한다.",
        "",
        "| 후보 | 짝지은 반복 수 | Macro-F1 변화 평균 ± 표준편차 (%p) |",
        "|---|---:|---:|",
    ]
    for _, runs in task_groups:
        baseline_recipe = optimizer_recipe(reference, runs[0]["recipe"]["optimizer"])
        baseline = {
            r["seed"]: r["result"]["metrics"]["overall"]["macro_f1"]
            for r in state["runs"].values()
            if r["task"] == task
            and r["recipe"] == baseline_recipe
            and r["fold"] is None
            and not r["delivery"]
            and r["status"] == "completed"
        }
        shared = [r for r in runs if r["seed"] in baseline]
        delta = [
            (r["result"]["metrics"]["overall"]["macro_f1"] - baseline[r["seed"]]) * 100
            for r in shared
        ]
        value = (
            f"{np.mean(delta):+.2f} ± {np.std(delta, ddof=1):.2f}"
            if len(delta) == 3
            else "반복 수 부족"
        )
        lines.append(f"| {recipe_label(runs[0]['recipe'])} | {len(delta)} | {value} |")
    return lines


def stage_report(state, key, updated):
    stage = state["stages"][key]
    _, title, question = STAGES[key]
    done, total, invalid = stage_progress(state, key)
    finished = stage["status"] == "completed"
    lines = [
        f"# {title}",
        "",
        f"갱신: {updated}. 상태: **{STATUS[stage['status']]}**.",
        "",
        "## 핵심 결론",
        "",
        (
            "예정한 비교를 완료했다. 아래 결과와 선정 영향을 함께 해석한다."
            if finished
            else "실험이 완료되지 않아 최종 우열을 판단하지 않는다. 아래 수치는 진행 중 관찰값이다."
        ),
        "",
        f"완료 {done}/{total if total else '다음 단계에서 확정'}회, "
        f"무효 시도를 포함한 실험 {invalid}회.",
        "",
        "## 실험 질문과 이유",
        "",
        question,
        "",
        "과거 단일 seed·일부 항목 비교를 전체 모델의 선정 근거로 확대하지 않기 위한 재검증이다.",
        "",
        "## 비교 조건",
        "",
        "| 공통 조건 | 설정 |",
        "|---|---|",
        "| 입력 | 정답 ROI 256px RGB, ImageNet 정규화, 기존 약한 증강, 반전 없음 |",
        "| 학습 | head 2 + 미세조정 18 epoch 완주, AMP, weight decay 0.0001 |",
        "| 체크포인트 | valid Macro-F1 최대 → MAE 최소 → 이른 epoch |",
        f"| 반복 | {'3개 인물 fold × 5개 학습 seed' if key == 'D' else '학습 seed 17·42·73'} |",
        "| 기존 test | 탐색·재분할 학습에 사용하지 않음 |",
        "",
    ]
    if key == "A":
        lines += [
            "가중 방식 6종 × AdamW/SAM × 배치16/32를 교차한다. "
            "실제 가중치 벡터가 같으면 한 번 학습하고 별칭을 기록한다.",
            "",
        ]
    for task, reference in stage.get("references", {}).items():
        lines += [f"- {NAMES[task]}의 고정 비교 기준: {recipe_label(reference)}"]
    lines += [
        "",
        "## 주요 결과",
        "",
        "평균 ± 표준편차이며, 탐색 단계에서 n은 완료한 학습 seed 수다. "
        "D단계 표의 n은 fold×seed 실행 수로, 서로 독립인 사람 수를 뜻하지 않는다.",
        "",
    ]
    groups = completed_groups(state, stage["runs"])
    appendix = []
    for task in TASKS:
        task_groups = [(identifier, runs) for (t, identifier), runs in groups.items() if t == task]
        task_groups.sort(
            key=lambda pair: (
                -np.mean([r["result"]["metrics"]["overall"]["macro_f1"] for r in pair[1]])
            )
        )
        lines += [f"### {NAMES[task]}", ""]
        if not task_groups:
            lines += ["완료된 실행이 없다.", ""]
            continue
        lines += [
            "| 후보 | n | Macro-F1 | Accuracy | MAE | 고등급 정확 Recall |",
            "|---|---:|---:|---:|---:|---:|",
        ]
        for _identifier, runs in task_groups[:10]:
            metrics = [r["result"]["metrics"]["overall"] for r in runs]
            cells = [mean_std(m[field] for m in metrics) for field in ("macro_f1", "accuracy")]
            cells += [
                mean_std((m["mae"] for m in metrics), percentage=False),
                mean_std(m["high_grade_exact_recall"] for m in metrics),
            ]
            lines.append(
                f"| {recipe_label(runs[0]['recipe'])} | {len(runs)} | " + " | ".join(cells) + " |"
            )
        if len(task_groups) > 10:
            lines += [
                "",
                "본문에는 관찰 평균 상위 10개만 표시하며, 나머지도 아래 전체 실행표에 보존한다.",
            ]
        if key in ("B", "C"):
            lines += reference_contrasts(state, stage, task, task_groups)
        if key == "A":
            lines += effects_table(state, task, groups)
            lines += [
                "",
                "### 가중치와 중복 조건",
                "",
                "| 조건 별칭 | 실제 등급별 학습 가중치 |",
                "|---|---|",
            ]
            seen = set()
            for identifier, _ in task_groups:
                alias = state["aliases"][f"{task}:{identifier}"]
                marker = tuple(alias["aliases"])
                if marker in seen:
                    continue
                seen.add(marker)
                lines.append(
                    f"| {', '.join(alias['aliases'])} | "
                    + " / ".join(f"{v:.4f}" for v in alias["weights"])
                    + " |"
                )
        lines += [
            "",
            "### 학습·추론 비용",
            "",
            "| 후보 | 전체 실행시간 평균 | GPU 최대 메모리 | 파라미터 | batch1 FP32 지연 중앙값 |",
            "|---|---:|---:|---:|---:|",
        ]
        for _, runs in task_groups[:10]:
            results = [r["result"] for r in runs]
            seconds = np.mean([r["execution_wall_seconds"] for r in results])
            memory = max(r["peak_memory_bytes"] for r in results) / 1024**3
            latency = np.median([r["latency_ms"] for r in results])
            lines.append(
                f"| {recipe_label(runs[0]['recipe'])} | {seconds / 60:.1f}분 | "
                f"{memory:.2f} GiB | {results[0]['parameter_count']:,} | {latency:.2f} ms |"
            )
        appendix += [
            f"### {NAMES[task]}: 전체 실행",
            "",
            "| 후보 | seed | fold | Macro-F1 | Accuracy | MAE | 선택 epoch | 실행 ID |",
            "|---|---:|---:|---:|---:|---:|---:|---|",
        ]
        for _, runs in task_groups:
            for run in sorted(
                runs, key=lambda r: (r["seed"], -1 if r["fold"] is None else r["fold"])
            ):
                metrics = run["result"]["metrics"]["overall"]
                fold = "원래 분할" if run["fold"] is None else str(run["fold"])
                appendix.append(
                    f"| {recipe_label(run['recipe'])} | {run['seed']} | {fold} | "
                    f"{percent(metrics['macro_f1'])} | {percent(metrics['accuracy'])} | "
                    f"{metrics['mae']:.3f} | {run['result']['best_epoch']} | "
                    f"[{run['id']}](details/{run['id']}.md) |"
                )
        appendix += [""]
    if key == "C":
        lines += [
            "",
            "### SAM ρ 민감도",
            "",
            "민감도 실행은 최종 후보 순위에 추가하지 않는다. 기본 ρ=0.05를 유지한다.",
            "",
            "| 항목 | 후보 | n | Macro-F1 |",
            "|---|---|---:|---:|",
        ]
        for (task, _), runs in completed_groups(state, stage.get("sensitivity_runs", [])).items():
            score = mean_std(r["result"]["metrics"]["overall"]["macro_f1"] for r in runs)
            lines.append(
                f"| {NAMES[task]} | {recipe_label(runs[0]['recipe'])} | {len(runs)} | {score} |"
            )
    if key == "D" and state["selections"]:
        lines += confirmation_results(state)
    lines += ["", "## 해석과 선정 영향", ""]
    if not finished:
        lines += ["남은 seed·후보가 있으므로 현재 최고점을 최종 모델로 선택하지 않는다."]
    elif key == "A":
        lines += [
            "동일 배치의 SAM 대비와 동일 optimizer의 가중치 대비로 효과를 분리한다. "
            "B단계는 WCE 조건 중 평균 Macro-F1 최고 설정의 가중 방식과 배치를 고정한다. "
            "SAM 효과는 가중 방식·배치별로 해석하며 전체 항목의 일괄 개선을 가정하지 않는다."
        ]
    elif key == "B":
        lines += [
            "C단계는 A·B 후보 중 항목별 평균 Macro-F1 최고 softmax 학습법을 사용한다. "
            "CORAL 결과는 최종 후보 순위에 남지만 backbone 확장에는 포함하지 않는다."
        ]
    elif key == "C":
        lines += [
            "A·B·C 탐색 상위 2개와 일반 CE+AdamW 기준선으로 D단계 후보를 고정한다. "
            "사전학습 recipe가 다르므로 순수한 아키텍처 효과로 단정하지 않는다."
        ]
    else:
        lines += [
            "5개 seed의 통합 OOF Macro-F1을 기준으로 선정한다. 최고 평균과의 paired 구간이 "
            "0을 포함하면 우월 근거가 부족한 후보로 보고 "
            "지연·크기·SAM 없음·일반 CE 순으로 선택한다."
        ]
    lines += [
        "",
        "## 한계와 다음 단계",
        "",
        "- 기존 test 결과는 이미 확인한 상태다. 새 독립 검증이라고 설명하지 않는다.",
        "- 희소 등급은 ROI 수보다 독립 인물 수가 중요하며, seed 반복은 인물을 늘리지 않는다.",
        "- 정확 등급 고등급 Recall과 상위 두 등급 탐지 Recall은 다른 지표다.",
        "- 자동 ROI·임의 셀카·실제 앱 성능을 검증한 결과가 아니다.",
        "",
        "## 재현 정보와 전체 실행",
        "",
        "실행 명령은 [고정 실험 계획](../experiment-plan.md)을 따른다. "
        "실행 ID는 로컬 `ml/runs/nia-reselection-v1-verified/runs/`의 "
        "설정·전체 로그·가중치에 대응한다.",
        "",
        f"코드 SHA-256: `{state['source_hash']}`.",
        "",
        *appendix,
        "### 무효·중단 시도",
        "",
        "| 실행 ID | 시도 | 상태 | 종료 코드 | 원인 |",
        "|---|---:|---|---:|---|",
    ]
    failed = False
    for identifier in stage["runs"] + stage.get("sensitivity_runs", []):
        for attempt in state["runs"][identifier]["attempts"]:
            if attempt["status"] == "invalid":
                failed = True
                lines.append(
                    f"| `{identifier}` | {attempt['number']} | 무효 | {attempt['exit_code']} | "
                    f"{attempt.get('error_summary', '로컬 로그 확인 필요')} |"
                )
    if not failed:
        lines.append("| — | — | 기록된 무효 시도 없음 | — | — |")
    return lines


def confirmation_results(state):
    lines = [
        "",
        "### 통합 OOF 결과와 최종 판단",
        "",
        "표의 평균·표준편차는 각 seed에서 세 바깥 fold를 합친 뒤 계산한 값이다. "
        "차이는 해당 항목 최고 평균 후보를 기준으로 한 내부 탐색적 95% 구간이다.",
        "",
        "| 항목 | 후보 | OOF Macro-F1 | 최고 대비 차이와 95% 구간 (%p) | 판단 |",
        "|---|---|---:|---:|---|",
    ]
    for task, selection in state["selections"].items():
        for candidate in selection["candidates"]:
            interval = candidate["difference_vs_best"]
            decision = "선정" if candidate["id"] == selection["candidate_id"] else "미선정"
            label = recipe_label(candidate["recipe"])
            if decision == "선정":
                label = f"**{label}**"
            lines.append(
                f"| {NAMES[task]} | {label} | "
                f"{candidate['mean_macro_f1'] * 100:.2f} ± "
                f"{candidate['std_macro_f1'] * 100:.2f}% | "
                f"{interval['difference'] * 100:+.2f} "
                f"[{interval['lower'] * 100:+.2f}, {interval['upper'] * 100:+.2f}] | {decision} |"
            )
    return lines


def publish_study(state):
    settings = state["config"]["study"]
    root = Path(settings["reports"])
    for run in state["runs"].values():
        if run["status"] == "completed":
            detail_path = root / "experiments" / "details" / f"{run['id']}.md"
            if not detail_path.exists():
                write_md(detail_path, run_details(run))
    updated = (
        datetime.fromisoformat(state["updated"])
        .astimezone(timezone(timedelta(hours=9)))
        .strftime("%Y-%m-%d %H:%M KST")
    )
    for key, (filename, _, _) in STAGES.items():
        write_md(root / "experiments" / filename, stage_report(state, key, updated))
    lines = [
        "# 피부 등급 모델 재선정 실험 진행 보고",
        "",
        f"갱신: {updated}.",
        "",
        f"전체 상태: **{STATUS[state['status']]}**. "
        + (
            "최종 선정과 기존 test 감사를 완료했다."
            if state["status"] == "completed"
            else "최종 모델 재선정은 아직 완료되지 않았다."
        ),
        "",
        "[고정 실험 계획](experiment-plan.md) · [최종 보고서](final-model-report.md) · "
        "[기존 실험 이력](experiment-summary.previous.md)",
        "",
        "## 진행 상태",
        "",
        "| 단계 | 상태 | 완료/등록 | 무효 시도 포함 실험 | 보고서 |",
        "|---|---|---:|---:|---|",
    ]
    for key, (filename, title, _) in STAGES.items():
        done, total, invalid = stage_progress(state, key)
        lines.append(
            f"| {title} | {STATUS[state['stages'][key]['status']]} | {done}/{total or '미확정'} | "
            f"{invalid} | [상세](experiments/{filename}) |"
        )
    done, total, invalid = stage_progress(state, "delivery")
    lines += [
        f"| 전달용 학습·기존 test 감사 | {STATUS[state['stages']['delivery']['status']]} | "
        f"{done}/{total or '미확정'} | {invalid} | "
        f"감사 상태: {STATUS.get(state['audit_status'], '잠금')} |",
        "",
        "## 핵심 관찰",
        "",
    ]
    completed = [r for r in state["runs"].values() if r["status"] == "completed"]
    if not completed:
        lines += ["완료된 새 실험이 없다. 기존 SAM 채택을 새 실험의 결론으로 사용하지 않는다."]
    else:
        durations = [r["result"]["execution_wall_seconds"] for r in completed]
        lines += [
            f"완료된 고유 실행 {len(completed)}회. 실제 전체 실행시간 중앙값 "
            f"{np.median(durations) / 60:.1f}분, 누적 {sum(durations) / 3600:.1f}시간이다."
        ]
        pending = sum(r["status"] != "completed" for r in state["runs"].values())
        if pending:
            lines += [
                "",
                f"현재 등록된 잔여 {pending}회만 같은 중앙값으로 환산하면 약 "
                f"{pending * np.median(durations) / 3600:.1f}시간이다. "
                "후속 단계의 미등록 실행·모델별 속도·재시도는 포함하지 않아 "
                "전체 완료 예상은 아니다.",
            ]
    if state["status"] == "failed":
        lines += [
            "",
            f"실행기가 `{state.get('failure_type', '오류')}`로 정지했다. "
            "무효 시도와 로컬 로그를 보존했으며 설정을 바꾸지 않고 원인을 확인해야 한다.",
        ]
    lines += [
        "",
        "## 데이터와 해석 범위",
        "",
        *support_table(state),
        "",
        "모공 5등급의 기존 valid는 1명·6 ROI다. 높은 ROI 수나 반복 seed 수를 "
        "독립 인물 수로 해석하지 않는다. 모든 결과는 연구용 정답 ROI 조건이다.",
        "",
        "## 재현",
        "",
        "```powershell",
        "uv run --project ml python -m skin_analysis.smartphone.reselection status",
        "uv run --project ml python -m skin_analysis.smartphone.reselection run",
        "uv run --project ml python -m skin_analysis.smartphone.reselection report",
        "```",
        "",
        "중단 후 같은 명령으로 이어서 실행한다. 기존 설정·코드와 다른 실행은 합치지 않는다.",
    ]
    write_md(root / "experiment-summary.md", lines)
    final = ["# 피부 등급 분류 모델 최종 재선정 보고서", "", f"갱신: {updated}.", "", "## 결론", ""]
    if state["status"] != "completed":
        final += [
            "**재선정 진행 중이다. 새 최종 모델은 아직 확정하지 않았다.**",
            "",
            "기존 WCE+SAM 채택은 이전 연구의 결정이며, 이번 대조 실험의 검증 결과가 아니다. "
            "현재 전달된 가중치와 서비스 설정은 자동 변경하지 않는다.",
            "",
            "[현재 진행 보고](experiment-summary.md) · "
            "[기존 최종 보고서 원문](final-model-report.previous.md)",
        ]
    else:
        final += [
            "세 항목을 Macro-F1과 내부 검증의 불확실성에 따라 각각 선정했다. "
            "기존 test는 선정 이후 감사에만 사용했으며 새 독립 검증은 아니다.",
            *confirmation_results(state),
            "",
            "## 기존 test 감사",
            "",
            "| 항목 | 모델 | Macro-F1 | Accuracy | MAE | 고등급 정확 Recall | 고등급 탐지 Recall |",
            "|---|---|---:|---:|---:|---:|---:|",
        ]
        for task, values in state["audit"]["tasks"].items():
            for name, result in values.items():
                m = result["metrics"]["overall"]
                label = "선정 모델" if name == "selected" else "일반 CE 기준선"
                final.append(
                    f"| {NAMES[task]} | {label} | {percent(m['macro_f1'])} | "
                    f"{percent(m['accuracy'])} | {m['mae']:.3f} | "
                    f"{percent(m['high_grade_exact_recall'])} | "
                    f"{percent(m['high_grade_detection_recall'])} |"
                )
        for task, values in state["audit"]["tasks"].items():
            final += [
                "",
                f"### {NAMES[task]}: 선정 이유와 등급별 결과",
                "",
                recipe_label(state["selections"][task]["recipe"]),
                "",
                "D단계 후보 중 평균 OOF Macro-F1을 비교하고, 최고 평균 후보와 차이가 "
                "불확실한 경우 측정한 추론 지연·크기·학습 복잡성 순으로 선택했다. "
                "탈락 후보별 평균과 차이 구간은 위 표에 기록한다.",
                *metric_details(values["selected"]["metrics"]["overall"]),
                "| 부위 | 인물 수 | ROI 수 | Macro-F1 | Accuracy | MAE |",
                "|---|---:|---:|---:|---:|---:|",
            ]
            for area, m in values["selected"]["metrics"]["areas"].items():
                final.append(
                    f"| {area} | {m['subjects']} | {m['n']} | {percent(m['macro_f1'])} | "
                    f"{percent(m['accuracy'])} | {m['mae']:.3f} |"
                )
    final += ["", "## 검증한 질문과 근거", "", "| 질문 | 근거 문서 |", "|---|---|"]
    for filename, title, question in STAGES.values():
        final.append(f"| {question} | [{title}](experiments/{filename}) |")
    final += [
        "",
        "## 고정 조건과 남은 한계",
        "",
        "- 입력·증강·20 epoch 예산·weight decay·기본 SAM ρ는 고정한 연구 조건이다. "
        "모든 가능한 값의 최적성을 입증한 것은 아니다.",
        "- seed와 인물 분할 반복은 내부 강건성 검증이며 새로운 외부 검증이 아니다.",
        "- 소수 등급 성능과 독립 인물 수를 전체 평균과 함께 해석해야 한다.",
        "- 여드름·자동 ROI·실제 앱·추천 효과는 이번 재선정으로 검증되지 않는다.",
        "- 연구용 가중치를 기존 운영 로더에 자동 연결하지 않는다. "
        "다른 backbone과 CORAL은 별도 추론 계약을 확인해야 한다.",
        "",
        "[실험 계획과 선정 규칙](experiment-plan.md) · [진행·재현 방법](experiment-summary.md)",
    ]
    write_md(root / "final-model-report.md", final)
    # Only aggregate evidence leaves ignored ml/runs. No local paths, ROI or person IDs.
    public_runs = [
        {k: v for k, v in run.items() if k not in ("result", "attempts")}
        | dict(
            result={
                k: v
                for k, v in run.get("result", {}).items()
                if k not in ("checkpoint", "attempt_root")
            },
            attempts=[{k: v for k, v in a.items()} for a in run["attempts"]],
        )
        for run in state["runs"].values()
    ]
    atomic_json(
        root / "reselection.metrics.json",
        dict(
            schema=state["schema"],
            updated=state["updated"],
            status=state["status"],
            source_hash=state["source_hash"],
            data_fingerprint=state["data_fingerprint"],
            runs=public_runs,
            selections=state["selections"],
            audit=state.get("audit"),
        ),
    )

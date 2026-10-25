"""Human-facing reports for the bounded two-seed study; no test-set claims."""

from datetime import datetime, timedelta, timezone
from pathlib import Path
from statistics import mean, stdev

from .common import TASKS
from .reselection_today import CASE_LABELS
from .study_design import atomic_json
from .study_report import NAMES, mean_std, percent, run_details, write_md

KST = timezone(timedelta(hours=9))
STATUS = {
    "planned": "예정",
    "running": "진행",
    "completed": "완료",
    "invalid": "무효",
    "deferred": "마감으로 미실행",
    "interrupted": "중단·체크포인트 보존",
    "paused": "일시 중단",
    "deadline_closed": "학습 마감",
    "failed": "오류로 중단",
}
CONTRASTS = (
    ("현재 WCE의 효과", "sqrt", "ce"),
    ("같은 배치에서 SAM 효과", "sam", "sqrt"),
    ("제곱근 → 역빈도", "inverse", "sqrt"),
    ("모공 상한 4 적용", "sqrt", "uncapped"),
)


def rows_for(state, task, case):
    return sorted(
        [
            r
            for r in state["runs"].values()
            if r["task"] == task and r["case"] == case and r["status"] == "completed"
        ],
        key=lambda r: r["seed"],
    )


def paired_change(state, task, left, right):
    a = {r["seed"]: r for r in rows_for(state, task, left)}
    b = {r["seed"]: r for r in rows_for(state, task, right)}
    if set(a) != {17, 42} or set(b) != {17, 42}:
        return None
    delta = [
        100
        * (
            a[s]["result"]["metrics"]["overall"]["macro_f1"]
            - b[s]["result"]["metrics"]["overall"]["macro_f1"]
        )
        for s in (17, 42)
    ]
    high = mean(
        100
        * (
            a[s]["result"]["metrics"]["overall"]["high_grade_exact_recall"]
            - b[s]["result"]["metrics"]["overall"]["high_grade_exact_recall"]
        )
        for s in (17, 42)
    )
    if all(v >= 0 for v in delta) and any(v > 0 for v in delta):
        direction = "두 seed에서 감소 없이 개선 관찰"
    elif all(v <= 0 for v in delta) and any(v < 0 for v in delta):
        direction = "두 seed에서 증가 없이 악화 관찰"
    elif all(v == 0 for v in delta):
        direction = "차이 없음"
    else:
        direction = "seed별 방향 불일치"
    return dict(
        mean=mean(delta), std=stdev(delta), deltas=delta, high_grade_delta=high, direction=direction
    )


def provisional(state, task):
    candidates = []
    for case in CASE_LABELS:
        rows = rows_for(state, task, case)
        if {r["seed"] for r in rows} == {17, 42}:
            candidates.append(
                (mean(r["result"]["metrics"]["overall"]["macro_f1"] for r in rows), case)
            )
    if not candidates or any(len(rows_for(state, task, c)) != 2 for c in ("ce", "sqrt", "sam")):
        return None
    candidates.sort(key=lambda pair: (-pair[0], pair[1]))
    score, best = candidates[0]
    stable = True
    for _, other in candidates[1:]:
        delta = paired_change(state, task, best, other)
        if any(value < 0 for value in delta["deltas"]):
            stable = False
    return dict(
        case=best,
        mean_macro_f1=score,
        stable_across_two_seeds=stable,
        interpretation="잠정 후보" if stable else "선정 보류: seed별 후보 순위 불일치",
    )


def progress(state):
    core = {
        identifier for group in state["groups"] if group["core"] for identifier in group["runs"]
    }
    done_core = sum(state["runs"][r]["status"] == "completed" for r in core)
    done = sum(r["status"] == "completed" for r in state["runs"].values())
    return done, done_core, len(core)


def result_tables(state):
    lines = []
    for task in TASKS:
        lines += [
            f"### {NAMES[task]}",
            "",
            "| 학습법 | 반복 | Macro-F1 | Accuracy | MAE | 고등급 정확 Recall |",
            "|---|---:|---:|---:|---:|---:|",
        ]
        for case, label in CASE_LABELS.items():
            if case == "uncapped" and task != "pore":
                continue
            rows = rows_for(state, task, case)
            if len(rows) != 2:
                lines.append(f"| {label} | {len(rows)}/2 | 비교 미완료 | — | — | — |")
                continue
            metrics = [r["result"]["metrics"]["overall"] for r in rows]
            cells = [mean_std(m[k] for m in metrics) for k in ("macro_f1", "accuracy")]
            cells += [
                mean_std((m["mae"] for m in metrics), percentage=False),
                mean_std(m["high_grade_exact_recall"] for m in metrics),
            ]
            lines.append(f"| {label} | 2/2 | " + " | ".join(cells) + " |")
        lines += [
            "",
            "변화는 같은 seed끼리 뺀 값이다. 단위는 %p이며 통계적 유의성을 뜻하지 않는다.",
            "",
            "| 질문 | seed17 변화 | seed42 변화 | 평균 변화 | 고등급 Recall 변화 | 판단 |",
            "|---|---:|---:|---:|---:|---|",
        ]
        for label, left, right in CONTRASTS:
            if right == "uncapped" and task != "pore":
                continue
            delta = paired_change(state, task, left, right)
            if delta is None:
                lines.append(f"| {label} | — | — | — | — | 비교 미완료 |")
            else:
                lines.append(
                    f"| {label} | {delta['deltas'][0]:+.2f} | {delta['deltas'][1]:+.2f} | "
                    f"{delta['mean']:+.2f} ± {delta['std']:.2f} | "
                    f"{delta['high_grade_delta']:+.2f} | {delta['direction']} |"
                )
        candidate = provisional(state, task)
        if candidate:
            lines += [
                "",
                f"검증 평균 1위: **{CASE_LABELS[candidate['case']]}** "
                f"({percent(candidate['mean_macro_f1'])}). {candidate['interpretation']}.",
                "",
                "고등급 Recall 손실도 위 표에서 함께 판단한다. 후보 순위가 두 seed에서 "
                "일치해도 새로운 인물·외부 촬영 환경의 일반화가 입증된 것은 아니다.",
            ]
        lines += [""]
    return lines


def publish(state):
    settings = state["settings"]["today"]
    root = Path(settings["reports"])
    updated = (
        datetime.fromisoformat(state["updated"]).astimezone(KST).strftime("%Y-%m-%d %H:%M KST")
    )
    done, core_done, core_total = progress(state)
    closed = state["status"] in ("completed", "deadline_closed")
    for run in state["runs"].values():
        if run["status"] == "completed":
            path = root / "experiments/details" / f"{run['id']}.md"
            if not path.exists():
                write_md(path, run_details(run))
    introduction = [
        f"갱신: {updated}. 상태: **{STATUS[state['status']]}**.",
        "",
        f"핵심 대조 {core_done}/{core_total}회, 전체 {done}/{len(state['runs'])}회 완료. "
        f"기존 동일 조건에서 재사용한 실행 {len(state['reused_runs'])}회 포함.",
        "",
        "학습 마감은 오늘 **23:00**, Markdown 보고 마감은 **23:30(KST)**이다. "
        "마감에 맞지 않는 보강은 생략하고 생략 이유를 기록한다.",
        "",
        "기존 576회 전체 계획은 일시 중단했다. 오늘은 ResNet-50·배치16·20 epoch와 "
        "두 학습 seed를 고정해 WCE·SAM의 대조 근거를 우선 확보한다.",
        "",
    ]
    summary = [
        "# 오늘 마감용 피부 모델 실험 진행 보고",
        "",
        *introduction,
        "[축소 계획](experiment-plan-today.md) · "
        "[상세 결과](experiments/today-results.md) · [잠정 종합보고서](final-model-report.md)",
        "",
        "## 실행 상태",
        "",
        "| 항목 | 조건 | 우선순위 | 완료 | 상태 |",
        "|---|---|---|---:|---|",
    ]
    for group in state["groups"]:
        runs = [state["runs"][r] for r in group["runs"]]
        count = sum(r["status"] == "completed" for r in runs)
        status = (
            "완료"
            if count == 2
            else group.get("deferred_reason")
            or " / ".join(dict.fromkeys(STATUS[r["status"]] for r in runs))
        )
        summary.append(
            f"| {NAMES[group['task']]} | {CASE_LABELS[group['case']]} | "
            f"{'필수' if group['core'] else '보강'} | {count}/2 | {status} |"
        )
    completed = [r for r in state["runs"].values() if r["status"] == "completed"]
    if completed:
        seconds = sum(r["result"]["execution_wall_seconds"] for r in completed)
        summary += [
            "",
            f"완료 실행의 전체 소요시간 누적은 {seconds / 3600:.2f}시간이다. "
            "기존 재사용 실행의 과거 시간도 포함한다.",
        ]
    if state["status"] == "failed":
        summary += [
            "",
            f"`{state.get('failure_type', '실행 오류')}`로 중단했다. "
            "아래 상세 결과의 무효 시도와 로컬 로그를 확인해야 한다.",
        ]
    summary += [
        "",
        "## 해석 범위",
        "",
        "- 두 seed의 평균·표준편차와 차이 방향을 함께 보고한다. 유의성 검정으로 부르지 않는다.",
        "- 기존 valid를 사용한 내부 비교다. 기존 test는 오늘 다시 평가하지 않는다.",
        "- backbone·배치·다른 손실의 최적성, 실사용 정확도는 이번 범위 밖이다.",
        "- 서비스 설정·현재 전달된 모델은 자동 교체하지 않는다.",
        "",
        "## 실행·재현",
        "",
        "```powershell",
        "uv run --project ml python -m skin_analysis.smartphone.reselection_today status",
        "uv run --project ml python -m skin_analysis.smartphone.reselection_today report",
        "```",
        "",
        "[전체 계획 중단 기록](experiments/full-study-paused/experiment-summary.md)",
    ]
    write_md(root / "experiment-summary.md", summary)
    detail = [
        "# 오늘 마감용 WCE·SAM 대조 실험",
        "",
        *introduction,
        "## 핵심 결론",
        "",
        (
            "마감 시점의 완료된 seed 쌍만으로 아래 관찰을 정리했다."
            if closed
            else "진행 중이다. seed 두 개가 완료되지 않은 조건은 우열을 판단하지 않는다."
        ),
        "",
        "## 질문과 비교 조건",
        "",
        "현재 WCE가 일반 CE보다 유리한지, 같은 배치에서 SAM을 추가하면 무엇이 달라지는지 "
        "확인한다. 여유 시간에는 역빈도와 모공 상한 유무를 비교한다.",
        "",
        "| 고정 조건 | 설정 |",
        "|---|---|",
        "| 학습 | ResNet-50 ImageNet V2, batch/effective batch 16, seed 17·42 |",
        "| 예산·선택 | head 2 + 미세조정 18 epoch 완주, valid Macro-F1 → MAE → 이른 epoch |",
        "| 입력·증강·LR·AMP·BN | 기존 전체 계획과 동일, ROI·epoch별 고정 증강 |",
        "| 기존 test | 학습·선정·이번 평가에 사용하지 않음 |",
        "",
        "## 결과와 같은 seed 대조",
        "",
        "성능은 평균 ± 표본 표준편차다. MAE는 등급 단위다. "
        "고등급 정확 Recall은 모공·색소침착 4·5, 주름 5·6의 정확 등급 일치율이다.",
        "",
        *result_tables(state),
        "## 한계와 선정 영향",
        "",
        "이번 결과는 비교한 ResNet-50 학습법의 잠정 근거다. seed 두 번과 같은 valid의 "
        "반복 사용만으로 일반화나 통계적 우월성을 입증하지 않는다. "
        "관찰이 seed마다 엇갈리면 선정 보류로 기록한다.",
        "",
        "다른 backbone·배치·Focal·CORAL·CDF·인물 재분할·ρ 탐색은 오늘 수행하지 않는다. "
        "따라서 해당 기법보다 낫거나 현재 설정이 최적이라는 결론은 내리지 않는다.",
        "",
        "## 재사용과 재현",
        "",
        f"학습 코드 SHA-256: `{state['training_source_hash']}`.",
        "",
        f"오늘 실행기 코드 SHA-256: `{state['source_hash']}`.",
        "",
        "이전 실행 2회는 보존한 소스와 학습 파일의 바이트·전체 학습 설정·데이터 "
        "fingerprint·가중치 해시를 확인한 뒤 재사용했다. 실행기·보고서 코드의 변경과 "
        "학습 계산의 변경을 구분한다.",
        "",
        "### 실행별 상세 기록",
        "",
        "| 항목 | 조건 | seed | 상태 | 선택 epoch | 상세 |",
        "|---|---|---:|---|---:|---|",
    ]
    for run in state["runs"].values():
        completed = run["status"] == "completed"
        epoch = str(run["result"]["best_epoch"]) if completed else "—"
        link = f"[기록](details/{run['id']}.md)" if completed else "—"
        detail.append(
            f"| {NAMES[run['task']]} | {CASE_LABELS[run['case']]} | {run['seed']} | "
            f"{STATUS[run['status']]} | {epoch} | {link} |"
        )
    detail += ["", "### 무효·중단 기록", "", "| 실행 ID | 시도 | 원인 |", "|---|---:|---|"]
    failures = 0
    for run in state["runs"].values():
        for attempt in run["attempts"]:
            if attempt["status"] == "invalid" or "paused_at" in attempt:
                failures += 1
                reason = attempt.get("error_summary", "마감 또는 사용자 요청으로 중단")
                detail.append(f"| `{run['id']}` | {attempt['number']} | {reason} |")
    if not failures:
        detail.append("| — | — | 오늘 실험에서 기록된 무효·중단 없음 |")
    detail += ["", "[고정한 축소 계획](../experiment-plan-today.md)"]
    write_md(root / "experiments/today-results.md", detail)
    final = [
        "# 피부 모델 선정 근거: 오늘 마감용 잠정 보고",
        "",
        *introduction,
        "## 결론",
        "",
        (
            "오늘 범위의 관찰을 정리했다. 새 최종 모델의 독립 검증을 완료한 보고서는 아니다."
            if closed
            else "실험 중이다. 새 최종 모델은 아직 확정하지 않았다."
        ),
        "",
        "## 항목별 관찰과 잠정 후보",
        "",
        *result_tables(state),
        "## 설명할 수 있는 범위",
        "",
        "- WCE·SAM 효과는 같은 배치·seed에서 비교한 값으로 설명한다.",
        "- 제곱근·역빈도·상한의 근거는 실제 완료한 비교에 한정한다.",
        "- ResNet-50·배치16·기본 LR·ρ는 오늘의 고정 연구 조건이며 최적이라는 주장이 아니다.",
        "- seed별 방향이 다르거나 보강을 완료하지 못한 지점은 미입증으로 남긴다.",
        "- 두 seed의 valid 평균과 고등급 성능 손실을 함께 설명한다. "
        "기존 test와 외부 검증은 별도다.",
        "- 원래 전체 계획의 backbone·다른 손실·재분할 검증은 보류했다.",
        "",
        "[전체 상세 결과](experiments/today-results.md) · [축소 계획](experiment-plan-today.md) · "
        "[이전 최종 보고서 원문](final-model-report.previous.md)",
    ]
    write_md(root / "final-model-report.md", final)
    public = dict(
        schema=state["schema"],
        updated=state["updated"],
        status=state["status"],
        training_source_hash=state["training_source_hash"],
        source_hash=state["source_hash"],
        test_access=False,
        reused_runs=state["reused_runs"],
        groups=state["groups"],
        provisional={task: provisional(state, task) for task in TASKS},
        runs=[
            dict(
                id=r["id"],
                task=r["task"],
                case=r["case"],
                recipe=r["recipe"],
                seed=r["seed"],
                status=r["status"],
                inherited_from=r.get("inherited_from"),
                result={
                    k: v
                    for k, v in r.get("result", {}).items()
                    if k not in ("checkpoint", "attempt_root")
                },
                attempts=r["attempts"],
            )
            for r in state["runs"].values()
        ],
    )
    atomic_json(root / "reselection-today.metrics.json", public)

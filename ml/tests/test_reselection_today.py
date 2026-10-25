"""Deadline, matched-pair completeness, source reuse, and two-seed claim limits."""

import subprocess
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from skin_analysis.smartphone import reselection, reselection_today
from skin_analysis.smartphone.reselection import make_run
from skin_analysis.smartphone.reselection_today import cases, group_fits, load_today, run_today
from skin_analysis.smartphone.today_report import paired_change, provisional


def fixture(tmp_path):
    settings = load_today()
    settings["today"]["output"] = str(tmp_path / "today")
    settings["today"]["reports"] = str(tmp_path / "reports")
    settings["config"]["study"]["output"] = settings["today"]["output"]
    return dict(
        schema="skin-reselection-today-v1",
        settings=settings,
        config=settings["config"],
        source_hash="code",
        training_source_hash="training",
        data_fingerprint="data",
        runs={},
        groups=[],
        reused_runs=[],
        status="planned",
        updated="2026-10-24T07:00:00+00:00",
    )


def entry(state, case, seed, score=None):
    row = make_run(state["config"], "pore", cases()[case], seed)
    row["case"] = case
    if score is not None:
        row.update(
            status="completed",
            result=dict(
                best_epoch=13,
                metrics=dict(overall=dict(macro_f1=score, high_grade_exact_recall=0.2)),
                execution_wall_seconds=8 * 60,
            ),
        )
    state["runs"][row["id"]] = row
    return row


def test_today_contains_exactly_26_runs_with_18_core_and_fixed_controls(tmp_path, monkeypatch):
    state = fixture(tmp_path)
    monkeypatch.setattr(reselection_today, "source_fingerprint", lambda: "code")
    monkeypatch.setattr(reselection_today, "original_manifest", lambda c: dict(fingerprint="data"))
    monkeypatch.setattr(reselection_today, "read_json", lambda path: {})

    def reuse(target, previous):
        target["reused_runs"] = []
        target["training_source_hash"] = "training"

    monkeypatch.setattr(reselection_today, "check_reuse", reuse)
    monkeypatch.setattr(reselection_today, "persist", lambda state: None)
    target = reselection_today.initialize(state["settings"])
    assert len(target["runs"]) == 26
    assert sum(len(g["runs"]) for g in target["groups"] if g["core"]) == 18
    assert target["groups"][9]["case"] == "uncapped"
    assert all(
        r["recipe"]["batch_size"] == 16
        and r["fold"] is None
        and r["recipe"]["backbone"] == "resnet50"
        for r in target["runs"].values()
    )
    assert all({target["runs"][r]["seed"] for r in g["runs"]} == {17, 42} for g in target["groups"])


def test_pair_admission_reserves_both_seeds_and_safety_margin(tmp_path):
    state = fixture(tmp_path)
    rows = [entry(state, "sqrt", seed) for seed in (17, 42)]
    group = dict(runs=[r["id"] for r in rows])
    deadline = datetime.fromisoformat(state["settings"]["today"]["training_deadline"])
    assert not group_fits(state, group, deadline - timedelta(minutes=18))
    assert group_fits(state, group, deadline - timedelta(minutes=21))
    rows[0].update(status="completed", result=dict(execution_wall_seconds=8 * 60))
    assert group_fits(state, group, deadline - timedelta(minutes=10))


def test_reuse_rejects_changed_training_source(tmp_path, monkeypatch):
    state = fixture(tmp_path)
    monkeypatch.setattr(
        reselection_today,
        "training_hash",
        lambda root: "old" if "paused-source" in str(root) else "new",
    )
    with pytest.raises(ValueError, match="different training source"):
        reselection_today.check_reuse(state, dict(data_fingerprint="data"))


def test_matched_contrast_waits_for_both_seeds_and_marks_direction_disagreement(tmp_path):
    state = fixture(tmp_path)
    entry(state, "ce", 17, 0.3)
    entry(state, "sqrt", 17, 0.4)
    assert paired_change(state, "pore", "sqrt", "ce") is None
    entry(state, "ce", 42, 0.4)
    entry(state, "sqrt", 42, 0.3)
    delta = paired_change(state, "pore", "sqrt", "ce")
    assert delta["mean"] == pytest.approx(0)
    assert delta["direction"] == "seed별 방향 불일치"
    assert provisional(state, "pore") is None  # SAM core pair not complete yet.


def test_provisional_holds_selection_when_seed_rankings_disagree(tmp_path):
    state = fixture(tmp_path)
    for case, values in dict(ce=(0.2, 0.2), sqrt=(0.5, 0.3), sam=(0.4, 0.5)).items():
        for seed, score in zip((17, 42), values, strict=True):
            entry(state, case, seed, score)
    result = provisional(state, "pore")
    assert result["case"] == "sam"
    assert not result["stable_across_two_seeds"]
    assert "선정 보류" in result["interpretation"]


def test_expired_deadline_never_starts_workers_and_marks_remaining_deferred(tmp_path, monkeypatch):
    state = fixture(tmp_path)
    Path(state["settings"]["today"]["output"]).mkdir(parents=True)
    rows = [entry(state, "ce", seed) for seed in (17, 42)]
    state["groups"] = [dict(core=True, runs=[r["id"] for r in rows])]
    deadline = datetime.fromisoformat(state["settings"]["today"]["training_deadline"])
    monkeypatch.setattr(reselection_today, "now", lambda: deadline + timedelta(seconds=1))
    monkeypatch.setattr(reselection_today, "source_fingerprint", lambda: "code")
    monkeypatch.setattr(reselection_today, "persist", lambda state: None)
    monkeypatch.setattr(
        reselection_today,
        "execute_run",
        lambda *a, **kw: pytest.fail("Must not start after deadline"),
    )
    run_today(state)
    assert state["status"] == "deadline_closed"
    assert all(r["status"] == "deferred" for r in state["runs"].values())


def test_worker_deadline_kills_only_its_process_tree_and_preserves_attempt(tmp_path, monkeypatch):
    state = fixture(tmp_path)
    row = entry(state, "sqrt", 17)
    killed = []

    class Process:
        pid = 123456

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return None

        def wait(self, timeout=None):
            if timeout is not None:
                raise subprocess.TimeoutExpired("owned-worker", timeout)
            return 1

    monkeypatch.setattr(reselection.subprocess, "Popen", lambda *a, **kw: Process())
    monkeypatch.setattr(reselection.subprocess, "run", lambda command, **kw: killed.append(command))
    with pytest.raises(TimeoutError, match="deadline"):
        reselection.execute_run(state, row, persist=lambda state: None, timeout_seconds=60)
    assert killed == [["taskkill", "/PID", "123456", "/T", "/F"]]
    assert row["status"] == "interrupted"
    assert "paused_at" in row["attempts"][0]


def test_today_report_does_not_rank_single_seed_or_publish_local_paths(tmp_path):
    from skin_analysis.smartphone.today_report import publish

    state = fixture(tmp_path)
    row = entry(state, "ce", 17, 0.3)
    row["result"]["checkpoint"] = "C:/private/model.bin"
    # This test isolates the overview/privacy path; detail rendering has its own regression test.
    root = Path(state["settings"]["today"]["reports"])
    detail = root / "experiments/details" / f"{row['id']}.md"
    detail.parent.mkdir(parents=True)
    detail.write_text("fixture", encoding="utf-8")
    publish(state)
    report = (root / "final-model-report.md").read_text(encoding="utf-8")
    assert "비교 미완료" in report and "새 최종 모델은 아직 확정하지 않았다" in report
    assert "C:/private" not in (root / "reselection-today.metrics.json").read_text(encoding="utf-8")

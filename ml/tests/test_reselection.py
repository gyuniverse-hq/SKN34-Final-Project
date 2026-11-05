"""Research validity: weights, isolation, pairing, selection and human reporting."""

import copy
from pathlib import Path

import numpy as np
import pytest
import torch
from torch import nn

from skin_analysis.smartphone.common import TASKS, assert_disjoint
from skin_analysis.smartphone.reselection import (
    DEFAULT_STUDY,
    audit,
    choose_models,
    configure_attempt,
    load_study,
    make_run,
    prepare_stage,
)
from skin_analysis.smartphone.study_design import (
    atomic_json,
    f1_from_confusion,
    factorial_recipes,
    paired_bootstrap,
    prediction_cube,
    recipe_id,
    split_manifest,
)
from skin_analysis.smartphone.study_report import publish_study
from skin_analysis.smartphone.train import GradeModel, class_weights, criterion_for, optimizer_for
from skin_analysis.train import train_epoch


def source_records():
    return [
        dict(
            id=f"{person}:{task}:{grade}",
            subject=str(person),
            group=str(person),
            device=3,
            task=task,
            truth=grade,
            split="test" if person >= 90 else "train",
            image_sha256=f"image-{person}",
            pixel_sha256=f"pixel-{person}",
        )
        for person in range(100)
        for task, specification in TASKS.items()
        for grade in range(specification["classes"])
    ]


def state_fixture(tmp_path):
    config = load_study(DEFAULT_STUDY)
    config["study"]["reports"] = str(tmp_path / "reports")
    config["study"]["output"] = str(tmp_path / "runs")
    return dict(
        config=config,
        schema="skin-reselection-v1",
        created="2026-10-24T00:00:00+00:00",
        updated="2026-10-24T00:00:00+00:00",
        status="planned",
        source_hash="code",
        data_fingerprint="data",
        source_summary={task: {} for task in TASKS},
        stages={key: dict(status="planned", runs=[]) for key in ("A", "B", "C", "D", "delivery")},
        runs={},
        aliases={},
        selections={},
        audit_status="locked",
    )


def recipe():
    return dict(
        backbone="resnet50",
        loss="weighted_cross_entropy",
        weight_exponent=0.5,
        class_weight_cap=None,
        batch_size=16,
        lr_multiplier=1.0,
        optimizer="adamw",
    )


def test_weight_formula_unweighted_uncapped_and_post_normalization_cap():
    labels = [0] * 100 + [1] * 4
    torch.testing.assert_close(class_weights(labels, 2, None, 0), torch.ones(2))
    raw = np.sqrt(104 / np.array([100, 4]))
    expected = raw / np.dot(raw, np.array([100, 4]) / 104)
    np.testing.assert_allclose(class_weights(labels, 2, None), expected, rtol=1e-6)
    np.testing.assert_allclose(class_weights(labels, 2, 2), np.minimum(expected, 2), rtol=1e-6)
    for invalid in (float("nan"), -0.1, 1.1):
        with pytest.raises(ValueError):
            class_weights(labels, 2, None, invalid)


def test_ce_and_cb_ce_values_and_gradients_match_explicit_formulas():
    labels = [0] * 10 + [1] * 2
    x = torch.tensor([[1.0, -1.0], [-0.5, 0.5]], requires_grad=True)
    y = torch.tensor([0, 1])
    ce, _ = criterion_for(labels, 2, dict(loss="unweighted_cross_entropy"), "cpu")
    torch.testing.assert_close(ce(x, y), nn.functional.cross_entropy(x, y))
    cb, spec = criterion_for(labels, 2, dict(loss="class_balanced_ce", cb_beta=0.999), "cpu")
    expected = nn.functional.cross_entropy(x, y, weight=torch.tensor(spec["weights"]))
    torch.testing.assert_close(cb(x, y), expected)
    torch.testing.assert_close(
        torch.autograd.grad(cb(x, y), x)[0], torch.autograd.grad(expected, x)[0]
    )


@pytest.mark.parametrize("backbone", ["resnet50", "resnet18", "efficientnet_b0"])
def test_backbone_heads_freezing_optimizer_groups_and_inference(backbone):
    model = GradeModel(6, backbone=backbone)
    settings = dict(
        head_lr=0.001,
        finetune_head_lr=0.0001,
        backbone_lr=0.00001,
        finetune_epochs=18,
        weight_decay=0.0001,
    )
    opt, _ = optimizer_for(model, settings, True)
    model.train()
    assert sum(p.numel() for p in model.parameters() if p.requires_grad) < 20000
    assert all(not m.training for m in model.modules() if isinstance(m, nn.BatchNorm2d))
    model.eval()
    with torch.inference_mode():
        assert model(torch.zeros(1, 3, 64, 64)).shape == (1, 6)
    opt, _ = optimizer_for(model, settings, False)
    ids = [id(p) for group in opt.param_groups for p in group["params"]]
    assert len(ids) == len(set(ids))
    assert set(ids) == {id(p) for p in model.parameters() if p.requires_grad}


def test_factorial_deduplicates_actual_weights_without_losing_aliases():
    rows = factorial_recipes(source_records(), "pore")
    # Balanced training labels: all six weighting recipes become exactly CE.
    assert len(rows) == 4
    assert all(len(row["aliases"]) == 6 for row in rows)
    assert len({recipe_id(row["recipe"]) for row in rows}) == 4


def test_development_folds_are_reproducible_disjoint_and_exclude_original_test():
    source = dict(records=source_records(), fingerprint="original")
    folds = [split_manifest(source, i) for i in range(3)]
    assert folds[0] == split_manifest(source, 0)
    appearances = {}
    for manifest in folds:
        assert_disjoint(manifest["records"])
        assert all(int(r["subject"]) < 90 for r in manifest["records"])
        for person in {r["subject"] for r in manifest["records"] if r["split"] == "test"}:
            appearances[person] = appearances.get(person, 0) + 1
    assert len(appearances) == 90 and set(appearances.values()) == {1}
    assert source["records"][0]["split"] == "train"


def test_bootstrap_pairs_seeds_and_people_and_uses_all_fixed_classes():
    left = np.zeros((3, 8, 2, 2), dtype=np.int32)
    left[:, :, 0, 0] = 2
    left[:, :, 1, 1] = 2
    right = left.copy()
    right[:, :, 1, 1] = 0
    right[:, :, 1, 0] = 2
    same = paired_bootstrap(left, left, samples=200)
    assert same["lower"] == same["upper"] == same["difference"] == 0
    delta = paired_bootstrap(left, right, samples=200)
    assert delta["lower"] > 0
    assert delta == paired_bootstrap(left, right, samples=200)
    assert f1_from_confusion(np.array([[2, 0], [0, 0]])) == 0.5


def test_oof_predictions_reject_truth_mismatch_and_duplicate_ids():
    row = dict(id="roi", group="person", truth=0, predicted=0)
    with pytest.raises(ValueError, match="Repeated"):
        prediction_cube({17: [row, row]}, 2)
    with pytest.raises(ValueError, match="align"):
        prediction_cube({17: [row], 42: [row | dict(truth=1)]}, 2)


def test_attempt_configuration_keeps_batch_lr_and_fold_provenance(tmp_path):
    state = state_fixture(tmp_path)
    run = make_run(state["config"], "pore", recipe() | dict(lr_multiplier=0.3), 73, fold=2)
    actual = configure_attempt(state, run, tmp_path / "attempt")
    assert actual["train"]["seed"] == 73
    assert actual["train"]["batch_size"] == actual["train"]["effective_batch"] == 16
    assert actual["train"]["backbone_lr"] == pytest.approx(0.000003)
    assert Path(actual["data"]["output"]).parts[-2:] == ("folds", "2")
    assert state["config"]["train"]["seed"] == 42


def test_roi_augmentation_is_epoch_stable_and_preserves_caller_rng(tmp_path):
    from PIL import Image

    from skin_analysis.smartphone.data import GradeDataset

    pixels = np.random.default_rng(1).integers(0, 256, (256, 256, 3), dtype=np.uint8)
    Image.fromarray(pixels).save(tmp_path / "crop.jpg")
    manifest = dict(
        root=str(tmp_path),
        records=[dict(id="private-roi", task="pore", split="train", truth=1, path="crop.jpg")],
    )
    dataset = GradeDataset(manifest, "pore", "train", training=True, training_seed=17)
    rng = torch.get_rng_state()
    first = dataset[0][0]
    assert torch.equal(rng, torch.get_rng_state())
    assert torch.equal(first, dataset[0][0])
    dataset.set_epoch(1)
    assert not torch.equal(first, dataset[0][0])
    resumed = GradeDataset(manifest, "pore", "train", training=True, training_seed=17)
    resumed.set_epoch(1)
    assert torch.equal(dataset[0][0], resumed[0][0])


def test_adamw_overflow_recovery_restores_bn_and_rng_like_sam():
    from torch.utils.data import DataLoader, TensorDataset

    torch.manual_seed(17)
    model = nn.Sequential(nn.BatchNorm1d(2), nn.Dropout(0.1), nn.Linear(2, 2))
    reference = copy.deepcopy(model)
    data = DataLoader(
        TensorDataset(torch.randn(4, 2), torch.tensor([0, 1, 0, 1]), torch.arange(4)), batch_size=2
    )
    calls = 0

    def overflow_once(gradient):
        nonlocal calls
        calls += 1
        return gradient * float("inf") if calls == 1 else gradient

    hook = model[2].weight.register_hook(overflow_once)
    random_state = torch.get_rng_state()
    train_epoch(
        model,
        data,
        torch.optim.AdamW(model.parameters()),
        nn.CrossEntropyLoss(),
        torch.device("cpu"),
        torch.amp.GradScaler("cpu", init_scale=128),
        2,
        False,
    )
    hook.remove()
    torch.set_rng_state(random_state)
    train_epoch(
        reference,
        data,
        torch.optim.AdamW(reference.parameters()),
        nn.CrossEntropyLoss(),
        torch.device("cpu"),
        torch.amp.GradScaler("cpu", init_scale=64),
        2,
        False,
    )
    assert model._amp_overflow_retries == 1
    for key, value in model.state_dict().items():
        torch.testing.assert_close(value, reference.state_dict()[key], rtol=0, atol=0)


def test_report_does_not_claim_unfinished_study_is_selected(tmp_path):
    state = state_fixture(tmp_path)
    publish_study(state)
    reports = Path(state["config"]["study"]["reports"])
    final = (reports / "final-model-report.md").read_text(encoding="utf-8")
    assert "새 최종 모델은 아직 확정하지 않았다" in final
    assert "2026-10-24 09:00 KST" in final
    assert len(list((reports / "experiments").glob("*.md"))) == 4


def test_test_audit_cannot_run_before_selection_is_locked(tmp_path):
    state = state_fixture(tmp_path)
    state["selection_hash"] = "tampered"
    with pytest.raises(ValueError, match="Selection changed"):
        audit(state)


def test_confirmation_selection_prefers_latency_when_paired_interval_is_tied(tmp_path, monkeypatch):
    from skin_analysis.smartphone import reselection

    state = state_fixture(tmp_path)
    state["config"]["study"]["bootstrap_samples"] = 50
    configs = [recipe(), recipe() | dict(backbone="resnet18")]
    state["stages"]["D"]["candidates"] = {"pore": [recipe_id(r) for r in configs]}
    rows = [
        dict(id=f"roi-{i}", group=f"person-{i}", truth=i % 6, predicted=i % 6) for i in range(12)
    ]
    for index, config in enumerate(configs):
        for seed in (17, 42, 73, 101, 202):
            entry = make_run(state["config"], "pore", config, seed, fold=0)
            attempt = tmp_path / f"{index}-{seed}"
            atomic_json(attempt / "predictions.json", rows)
            entry.update(
                status="completed",
                result=dict(
                    attempt_root=str(attempt), latency_ms=5 - index, parameter_count=1000 - index
                ),
            )
            state["runs"][entry["id"]] = entry
            state["stages"]["D"]["runs"].append(entry["id"])
    monkeypatch.setattr(reselection, "save_state", lambda state: None)
    choose_models(state)
    assert state["selections"]["pore"]["recipe"]["backbone"] == "resnet18"


def test_dependent_stage_is_locked_to_completed_seed_group(tmp_path, monkeypatch):
    from skin_analysis.smartphone import reselection

    state = state_fixture(tmp_path)
    for task in TASKS:
        for seed in (17, 42, 73):
            run = make_run(state["config"], task, recipe(), seed)
            run.update(status="completed", result=dict(metrics=dict(overall=dict(macro_f1=0.5))))
            state["runs"][run["id"]] = run
            state["stages"]["A"]["runs"].append(run["id"])
    monkeypatch.setattr(reselection, "save_state", lambda state: None)
    prepare_stage(state, "B")
    assert len(state["stages"]["B"]["runs"]) == 126
    assert all(state["runs"][r]["recipe"]["batch_size"] == 16 for r in state["stages"]["B"]["runs"])


def test_full_pipeline_completes_all_stages_before_single_test_audit(tmp_path, monkeypatch):
    from server.nia.metrics import classification

    from skin_analysis.smartphone import reselection
    from skin_analysis.smartphone.study_design import read_json

    state = state_fixture(tmp_path)
    state["config"]["study"]["bootstrap_samples"] = 20
    Path(state["config"]["study"]["output"]).mkdir(parents=True)
    records = [
        dict(task=task, truth=grade, split="train")
        for task, spec in TASKS.items()
        for grade in range(spec["classes"])
        for _ in range(grade + 1)
    ]
    for task in TASKS:
        for row in factorial_recipes(records, task):
            for seed in state["config"]["study"]["search_seeds"]:
                entry = make_run(state["config"], task, row["recipe"], seed)
                state["runs"][entry["id"]] = entry
                state["stages"]["A"]["runs"].append(entry["id"])
    audit_calls = []

    def fake_execute(state, run):
        if run["status"] == "completed":
            return
        classes = TASKS[run["task"]]["classes"]
        fold = 0 if run["fold"] is None else run["fold"]
        rows = [
            dict(id=f"{fold}-{i}", group=f"{fold}-{i}", truth=i, predicted=i)
            for i in range(classes)
        ]
        attempt = tmp_path / "predictions" / run["id"]
        atomic_json(attempt / "predictions.json", rows)
        metric = classification(list(range(classes)), list(range(classes)), classes)
        run.update(
            status="completed",
            result=dict(
                attempt_root=str(attempt),
                metrics=dict(overall=metric),
                latency_ms=2.0,
                parameter_count=1000,
            ),
        )

    def fake_audit(state):
        assert len(state["selections"]) == 3
        assert all(state["stages"][s]["status"] == "completed" for s in reselection.STAGES)
        audit_calls.append(True)
        atomic_json(tmp_path / "audit-proof.json", dict(selected=state["selection_hash"]))

    monkeypatch.setattr(reselection, "source_fingerprint", lambda: "code")
    monkeypatch.setattr(reselection, "save_state", lambda state: None)
    monkeypatch.setattr(reselection, "execute_run", fake_execute)
    monkeypatch.setattr(reselection, "audit", fake_audit)
    reselection.run_study(state)
    assert state["status"] == "completed"
    assert len(audit_calls) == 1
    assert read_json(tmp_path / "audit-proof.json")["selected"] == state["selection_hash"]
    assert len(state["stages"]["B"]["runs"]) == 126
    assert len(state["stages"]["C"]["sensitivity_runs"]) == 27
    assert len(state["stages"]["D"]["runs"]) <= 135
    assert len(state["stages"]["delivery"]["runs"]) == 3


def test_worker_merges_actual_training_summary_without_duplicate_task(tmp_path, monkeypatch):
    from skin_analysis.smartphone import reselection
    from skin_analysis.smartphone.common import file_hash
    from skin_analysis.smartphone.study_design import read_json

    task_root = tmp_path / "pore"
    task_root.mkdir()
    checkpoint = task_root / "inference.bin"
    checkpoint.write_bytes(b"mock trained checkpoint")
    atomic_json(
        tmp_path / "config.json",
        dict(train=dict(expected_source_hash="code", device_uuid="test", optimizer="adamw")),
    )
    summary = dict(task="pore", epochs_run=20, best_epoch=13, sha256=file_hash(checkpoint))
    atomic_json(task_root / "summary.json", summary)
    monkeypatch.setattr(reselection, "source_fingerprint", lambda: "code")
    monkeypatch.setattr(reselection, "select_cuda", lambda uuid: torch.device("cpu"))
    monkeypatch.setattr(reselection, "load_manifest", lambda config: dict(fingerprint="data"))
    monkeypatch.setattr(reselection, "verify_crops", lambda manifest: None)
    monkeypatch.setattr(
        reselection,
        "evaluate_checkpoint",
        lambda *args: (dict(metrics=dict(overall=dict(macro_f1=0.3))), []),
    )
    reselection.worker(tmp_path, "pore", False)
    result = read_json(tmp_path / "result.json")
    assert result["task"] == "pore" and result["epochs_run"] == 20
    assert result["best_epoch"] == 13 and result["metrics"]["overall"]["macro_f1"] == 0.3


def test_evaluation_rejects_mismatched_checkpoint_before_inference(tmp_path):
    from skin_analysis.smartphone.reselection import evaluate_checkpoint

    checkpoint = tmp_path / "wrong.bin"
    torch.save(
        dict(task="wrinkle", manifest_fingerprint="wrong", preprocessing="wrong", grades=[0, 1]),
        checkpoint,
    )
    with pytest.raises(ValueError, match="contract differs"):
        evaluate_checkpoint(
            checkpoint, dict(fingerprint="expected"), "pore", "valid", torch.device("cpu")
        )


def test_completed_result_renders_detail_and_final_markdown_without_private_paths(tmp_path):
    from server.nia.metrics import classification

    state = state_fixture(tmp_path)
    run = make_run(state["config"], "pore", recipe(), 17)
    metric = classification(list(range(6)), list(range(6)), 6) | dict(
        subjects=6,
        grade_subject_support=[1] * 6,
        high_grade_exact_recall=1.0,
        high_grade_detection_recall=1.0,
        high_grade_detection_precision=1.0,
    )
    run.update(
        status="completed",
        result=dict(
            metrics=dict(overall=metric, areas=dict(pore=metric)),
            epochs_run=20,
            best_epoch=13,
            execution_wall_seconds=10.0,
            optimizer_steps=20,
            peak_memory_bytes=1024,
            latency_ms=2.0,
            parameter_count=1000,
            sha256="weights",
            source_hash="code",
            data_fingerprint="data",
            checkpoint="C:/private/model.bin",
            attempt_root="C:/private/attempt",
        ),
    )
    state["runs"][run["id"]] = run
    state["stages"]["A"]["runs"] = [run["id"]]
    state["aliases"][f"pore:{recipe_id(recipe())}"] = dict(
        aliases=["sqrt-uncapped"], weights=[1.0] * 6
    )
    state["status"] = "completed"
    state["selections"] = dict(
        pore=dict(
            recipe=recipe(),
            candidate_id="chosen",
            candidates=[
                dict(
                    id="chosen",
                    recipe=recipe(),
                    mean_macro_f1=1.0,
                    std_macro_f1=0.0,
                    difference_vs_best=dict(difference=0.0, lower=0.0, upper=0.0),
                )
            ],
        )
    )
    state["audit"] = dict(
        tasks=dict(
            pore=dict(
                selected=dict(metrics=run["result"]["metrics"]),
                ce_baseline=dict(metrics=run["result"]["metrics"]),
            )
        )
    )
    publish_study(state)
    reports = Path(state["config"]["study"]["reports"])
    detail = (reports / "experiments/details" / f"{run['id']}.md").read_text(encoding="utf-8")
    final = (reports / "final-model-report.md").read_text(encoding="utf-8")
    assert "독립 인물" in detail and "고등급 탐지 Precision" in detail
    assert "13 / 20" in detail and "혼동행렬" in detail
    assert "통합 OOF 결과와 최종 판단" in final and "기존 test 감사" in final
    assert "C:/private/" not in (reports / "reselection.metrics.json").read_text(encoding="utf-8")

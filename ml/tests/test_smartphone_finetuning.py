"""Separate running-statistic freezing from parameter-scope freezing."""

import pytest
import torch

from skin_analysis.smartphone.experiment_checks import require_one_factor as require_one_factor
from skin_analysis.smartphone.train import GradeModel, optimizer_for


def settings():
    return dict(
        head_lr=0.001,
        finetune_head_lr=0.0001,
        backbone_lr=0.00001,
        weight_decay=0.0001,
        finetune_epochs=18,
    )


def test_bn_freeze_keeps_affine_and_backbone_trainable_but_buffers_unchanged():
    torch.set_num_threads(4)
    model = GradeModel(6, freeze_bn_stats=True)
    optimizer, _ = optimizer_for(model, settings(), frozen=False)
    model.train()
    buffers = {name: value.clone() for name, value in model.named_buffers()}
    assert all(not m.training for m in model.modules() if isinstance(m, torch.nn.BatchNorm2d))
    assert model.network.bn1.weight.requires_grad and model.network.conv1.weight.requires_grad
    loss = torch.nn.functional.cross_entropy(model(torch.randn(2, 3, 64, 64)), torch.tensor([0, 5]))
    loss.backward()
    assert model.network.bn1.weight.grad is not None
    assert model.network.conv1.weight.grad is not None
    optimizer.step()
    assert all(torch.equal(value, buffers[name]) for name, value in model.named_buffers())
    model.eval()
    model.train()
    assert not model.network.bn1.training


def test_layer4_only_updates_selected_parameters_and_preserves_baseline_bn_behavior():
    torch.set_num_threads(4)
    model = GradeModel(6, finetune_scope="layer4")
    optimizer, _ = optimizer_for(model, settings(), frozen=False)
    expected = {
        id(p) for name, p in model.network.named_parameters() if name.startswith(("layer4.", "fc."))
    }
    actual = {id(p) for group in optimizer.param_groups for p in group["params"]}
    assert actual == expected
    prefix = {n: p.clone() for n, p in model.network.named_parameters() if not p.requires_grad}
    tail = model.network.layer4[0].conv1.weight.detach().clone()
    model.train()
    assert model.network.bn1.training and model.network.layer4[0].bn1.training
    loss = torch.nn.functional.cross_entropy(model(torch.randn(2, 3, 64, 64)), torch.tensor([0, 5]))
    loss.backward()
    assert model.network.conv1.weight.grad is None
    assert model.network.layer4[0].conv1.weight.grad is not None
    optimizer.step()
    assert all(
        torch.equal(p, prefix[n]) for n, p in model.network.named_parameters() if n in prefix
    )
    assert not torch.equal(tail, model.network.layer4[0].conv1.weight)
    # The second experiment must not silently include the first experiment.
    assert model.network.bn1.num_batches_tracked.item() == 1
    assert model.network.layer4[0].bn1.num_batches_tracked.item() == 1


@pytest.mark.parametrize("options", [dict(freeze_bn_stats=True), dict(finetune_scope="layer4")])
def test_head_phase_is_identical_and_eval_train_transitions_reapply_policy(options):
    model = GradeModel(6, **options)
    model.set_stage(True)
    model.train()
    assert all(n.startswith("network.fc.") for n, p in model.named_parameters() if p.requires_grad)
    assert not model.network.bn1.training and model.network.fc.training
    model.set_stage(False)
    model.eval()
    model.train()
    assert model.network.bn1.training is (not options.get("freeze_bn_stats", False))


def test_unknown_scope_is_rejected():
    with pytest.raises(ValueError, match="scope"):
        GradeModel(6, finetune_scope="everything-maybe")


@pytest.mark.parametrize(
    "variant,change",
    [
        ("bn_stats_frozen", dict(freeze_bn_stats=True)),
        ("layer4_only", dict(finetune_scope="layer4")),
    ],
)
def test_ablation_contract_rejects_combined_treatments_and_other_budget_changes(variant, change):
    baseline = dict(output="old", seed=42, batch_size=16, finetune_epochs=18)
    candidate = baseline | dict(output="new", record_train_metrics=True) | change
    require_one_factor(candidate, baseline, variant)
    candidate["finetune_epochs"] = 40
    with pytest.raises(ValueError, match="one predefined treatment"):
        require_one_factor(candidate, baseline, variant)
    candidate["finetune_epochs"] = 18
    candidate.update(freeze_bn_stats=True, finetune_scope="layer4")
    with pytest.raises(ValueError, match="one predefined treatment"):
        require_one_factor(candidate, baseline, variant)

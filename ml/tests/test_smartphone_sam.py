"""SAM's two gradients, exact restoration, BN and scaled-gradient recovery."""

import copy

import pytest
import torch
from torch import nn
from torch.utils.data import DataLoader, TensorDataset

from skin_analysis.smartphone.experiment_checks import (
    require_sam_settings as require_matched_settings,
)
from skin_analysis.smartphone.sam import optimization_spec, train_epoch
from skin_analysis.train import train_epoch as ordinary_epoch


def loader(batch=2, count=6):
    x = torch.arange(count * 2, dtype=torch.float32).reshape(count, 2) / 10
    return DataLoader(
        TensorDataset(x, torch.arange(count) % 2, torch.arange(count)),
        batch_size=batch,
        generator=torch.Generator().manual_seed(42),
    )


def run(model, optimizer, *, rho=0.05, scaler=None, data=None, effective=2):
    return train_epoch(
        model,
        data or loader(),
        optimizer,
        nn.CrossEntropyLoss(),
        torch.device("cpu"),
        scaler or torch.amp.GradScaler("cpu", enabled=False),
        effective,
        False,
        rho=rho,
    )


def test_sam_matches_independent_two_gradient_adamw_reference():
    torch.manual_seed(42)
    model = nn.Linear(2, 2)
    reference = copy.deepcopy(model)
    opt = torch.optim.AdamW(model.parameters(), lr=0.01, weight_decay=0.03)
    ref_opt = torch.optim.AdamW(reference.parameters(), lr=0.01, weight_decay=0.03)
    x, y, _ = next(iter(loader(count=2)))
    initial = [p.detach().clone() for p in reference.parameters()]
    nn.functional.cross_entropy(reference(x), y).backward()
    gradients = [p.grad.detach().clone() for p in reference.parameters()]
    norm = torch.cat([g.flatten() for g in gradients]).norm()
    with torch.no_grad():
        for p, g in zip(reference.parameters(), gradients, strict=True):
            p.add_(0.05 * g / norm)
    ref_opt.zero_grad(set_to_none=True)
    nn.functional.cross_entropy(reference(x), y).backward()
    nn.utils.clip_grad_norm_(reference.parameters(), 1.0)
    with torch.no_grad():
        for p, value in zip(reference.parameters(), initial, strict=True):
            p.copy_(value)
    ref_opt.step()
    run(model, opt, data=loader(count=2))
    for actual, expected in zip(model.parameters(), reference.parameters(), strict=True):
        torch.testing.assert_close(actual, expected, rtol=0, atol=1e-8)


def test_zero_radius_matches_baseline_with_accumulation_and_partial_last_window():
    torch.manual_seed(42)
    model = nn.Linear(2, 2)
    reference = copy.deepcopy(model)
    opt = torch.optim.AdamW(model.parameters(), lr=0.01)
    ref_opt = torch.optim.AdamW(reference.parameters(), lr=0.01)
    run(model, opt, rho=0, data=loader(count=5), effective=4)
    ordinary_epoch(
        reference,
        loader(count=5),
        ref_opt,
        nn.CrossEntropyLoss(),
        torch.device("cpu"),
        torch.amp.GradScaler("cpu", enabled=False),
        4,
        False,
    )
    assert model._sam_steps == 2
    for actual, expected in zip(model.parameters(), reference.parameters(), strict=True):
        torch.testing.assert_close(actual, expected, rtol=0, atol=0)


@pytest.mark.parametrize("overflow_pass", [1, 2])
def test_scaled_gradient_overflow_replays_entire_window_and_updates_bn_once(overflow_pass):
    torch.manual_seed(42)
    model = nn.Sequential(nn.BatchNorm1d(2), nn.Linear(2, 2))
    reference = copy.deepcopy(model)
    opt = torch.optim.AdamW(model.parameters(), lr=0.01)
    ref_opt = torch.optim.AdamW(reference.parameters(), lr=0.01)
    calls = 0

    def inject_once(grad):
        nonlocal calls
        calls += 1
        return grad * float("inf") if calls == overflow_pass else grad

    hook = model[1].weight.register_hook(inject_once)
    scaler = torch.amp.GradScaler("cpu", init_scale=128, growth_interval=100)
    run(model, opt, scaler=scaler)
    hook.remove()
    run(reference, ref_opt, scaler=torch.amp.GradScaler("cpu", init_scale=64))
    assert model._amp_overflow_retries == 1
    assert scaler.get_scale() == 64
    assert model._sam_steps == 3
    assert model[0].num_batches_tracked.item() == 3
    for key, value in model.state_dict().items():
        torch.testing.assert_close(value, reference.state_dict()[key], rtol=0, atol=0)
    assert all(state["step"] == 3 for state in opt.state.values())


def test_second_pass_exception_restores_parameters_bn_and_does_not_step():
    class Broken(nn.Sequential):
        calls = 0

        def forward(self, x):
            value = super().forward(x)
            self.calls += 1
            if self.calls == 2:
                raise RuntimeError("second pass failed")
            return value

    model = Broken(nn.BatchNorm1d(2), nn.Linear(2, 2))
    before = copy.deepcopy(model.state_dict())
    opt = torch.optim.AdamW(model.parameters())
    with pytest.raises(RuntimeError, match="second pass failed"):
        run(model, opt)
    assert not opt.state
    assert all(torch.equal(v, before[k]) for k, v in model.state_dict().items())
    assert all(p.grad is None for p in model.parameters())


def test_checkpoint_round_trip_preserves_next_step_and_frozen_parameters(tmp_path):
    model = nn.Sequential(nn.Linear(2, 2), nn.Linear(2, 2))
    model[0].requires_grad_(False)
    frozen = copy.deepcopy(model[0].state_dict())
    opt = torch.optim.AdamW(model[1].parameters(), lr=0.01)
    scaler = torch.amp.GradScaler("cpu", init_scale=128)
    run(model, opt, scaler=scaler)
    path = tmp_path / "checkpoint.pt"
    torch.save(
        dict(model=model.state_dict(), optimizer=opt.state_dict(), scaler=scaler.state_dict()), path
    )
    restored = copy.deepcopy(model)
    restored_opt = torch.optim.AdamW(restored[1].parameters(), lr=0.01)
    restored_scaler = torch.amp.GradScaler("cpu")
    checkpoint = torch.load(path, weights_only=True)
    restored.load_state_dict(checkpoint["model"])
    restored_opt.load_state_dict(checkpoint["optimizer"])
    restored_scaler.load_state_dict(checkpoint["scaler"])
    run(model, opt, scaler=scaler)
    run(restored, restored_opt, scaler=restored_scaler)
    assert all(torch.equal(v, restored.state_dict()[k]) for k, v in model.state_dict().items())
    assert all(torch.equal(v, frozen[k]) for k, v in model[0].state_dict().items())


def test_optimizer_spec_is_explicit_and_rejects_invalid_settings():
    assert optimization_spec({}) == dict(kind="adamw")
    assert optimization_spec(dict(optimizer="sam_adamw", sam_rho=0.05))["adaptive"] is False
    for settings in (
        dict(optimizer="sgd"),
        dict(sam_rho=0.05),
        dict(optimizer="sam_adamw", sam_rho=float("nan")),
        dict(optimizer="sam_adamw", sam_rho=0),
    ):
        with pytest.raises(ValueError):
            optimization_spec(settings)


def test_sam_comparison_rejects_other_treatments_or_tuned_radius():
    baseline = dict(output="old", seed=42, batch_size=16, amp=True)
    candidate = baseline | dict(
        output="new", record_train_metrics=True, optimizer="sam_adamw", sam_rho=0.05
    )
    require_matched_settings(candidate, baseline)
    for change in (
        dict(batch_size=32),
        dict(freeze_bn_stats=True),
        dict(finetune_scope="layer4"),
        dict(sam_rho=0.1),
        dict(amp=False),
    ):
        with pytest.raises(ValueError, match="only treatment"):
            require_matched_settings(candidate | change, baseline)

"""Opt-in L2 SAM over the existing AdamW optimizer, including AMP recovery.

No persistent perturbation/optimizer wrapper: checkpoints contain ordinary AdamW
state, and every completed step restores the original weights before updating.
"""

import math

import torch
from torch import nn


def optimization_spec(settings):
    kind = settings.get("optimizer", "adamw")
    if kind not in ("adamw", "sam_adamw"):
        raise ValueError("Optimizer must be adamw or sam_adamw")
    if kind == "adamw":
        if "sam_rho" in settings:
            raise ValueError("sam_rho requires sam_adamw")
        return dict(kind=kind)
    rho = settings["sam_rho"]
    if not math.isfinite(rho) or rho <= 0:
        raise ValueError("SAM rho must be finite and positive")
    return dict(
        kind=kind,
        base_optimizer="adamw",
        rho=rho,
        adaptive=False,
        norm="global_l2_trainable_optimizer_parameters",
        bn_policy="second_pass_batch_statistics_without_persistent_buffer_update",
        amp_policy="manual_first_unscale_then_scaler_second_unscale",
        gradient_clip="second_gradient_global_norm_1",
        stages="head_and_finetune",
    )


def bn_snapshot(model):
    return [
        (buffer, buffer.detach().clone())
        for module in model.modules()
        if isinstance(module, nn.modules.batchnorm._BatchNorm)
        for buffer in module.buffers(recurse=False)
    ]


@torch.no_grad()
def restore(values):
    for tensor, value in values:
        tensor.copy_(value)


def train_epoch(model, loader, optimizer, criterion, device, scaler, effective_batch, amp, *, rho):
    """Replay the same augmented accumulation window for both SAM gradients.

    First gradients are unscaled manually so GradScaler.unscale_ is called only
    once per update (on the second gradient). Nonfinite gradients retry the whole
    window at half scale, restoring weights, BN buffers and torch RNG first.
    """
    if (
        not len(loader.dataset)
        or effective_batch < 1
        or effective_batch % getattr(loader, "micro_batch_size", loader.batch_size)
        or not math.isfinite(rho)
        or rho < 0
    ):
        raise ValueError("SAM requires a nonempty dataset, divisible batch and finite rho >= 0")
    model.train()
    parameters = [p for g in optimizer.param_groups for p in g["params"] if p.requires_grad]
    model._amp_overflow_retries = 0
    model._sam_steps = 0
    perturbed_total = 0.0

    def backward(batches, samples):
        total = 0.0
        for cpu_images, cpu_targets in batches:
            images = cpu_images.to(device, non_blocking=True)
            targets = cpu_targets.to(device, non_blocking=True)
            with torch.amp.autocast(device.type, dtype=torch.float16, enabled=amp):
                loss = criterion(model(images), targets)
            if not torch.isfinite(loss):
                raise RuntimeError("Non-finite SAM training loss")
            scaler.scale(loss * (len(images) / samples)).backward()
            total += float(loss.detach()) * len(images)
        return total

    def optimize(batches, samples):
        before_bn = bn_snapshot(model)
        before_cpu = torch.get_rng_state()
        before_cuda = torch.cuda.get_rng_state(device) if device.type == "cuda" else None

        def rewind():
            restore(before_bn)
            torch.set_rng_state(before_cpu)
            if before_cuda is not None:
                torch.cuda.set_rng_state(before_cuda, device)

        for attempt in range(17):
            originals = []
            optimizer.zero_grad(set_to_none=True)
            try:
                first_loss = backward(batches, samples)
                gradients = [p for p in parameters if p.grad is not None]
                if not gradients:
                    raise RuntimeError("SAM requires connected trainable parameters")
                # Do not consume GradScaler's one unscale_ call before second backward.
                with torch.no_grad():
                    for p in gradients:
                        p.grad.div_(scaler.get_scale())
                norm = torch.linalg.vector_norm(
                    torch.stack([torch.linalg.vector_norm(p.grad.float()) for p in gradients])
                )
                if torch.isfinite(norm):
                    originals = [(p, p.detach().clone()) for p in gradients]
                    with torch.no_grad():
                        for p in gradients:
                            p.add_(p.grad * (rho / (norm + 1e-12)))
                    optimizer.zero_grad(set_to_none=True)
                    after_first_bn = bn_snapshot(model)
                    # Reuse stochastic masks too; the successful update consumes one
                    # forward's RNG stream. ResNet50 currently has no dropout.
                    after_first_cpu = torch.get_rng_state()
                    after_first_cuda = (
                        torch.cuda.get_rng_state(device) if device.type == "cuda" else None
                    )
                    torch.set_rng_state(before_cpu)
                    if before_cuda is not None:
                        torch.cuda.set_rng_state(before_cuda, device)
                    try:
                        second_loss = backward(batches, samples)
                    finally:
                        restore(after_first_bn)
                        torch.set_rng_state(after_first_cpu)
                        if after_first_cuda is not None:
                            torch.cuda.set_rng_state(after_first_cuda, device)
                        restore(originals)
                    scaler.unscale_(optimizer)
                    norm = nn.utils.clip_grad_norm_(parameters, 1.0)
                    if torch.isfinite(norm):
                        scaler.step(optimizer)
                        scaler.update()
                        optimizer.zero_grad(set_to_none=True)
                        model._sam_steps += 1
                        return first_loss, second_loss
                rewind()
                optimizer.zero_grad(set_to_none=True)
                if not scaler.is_enabled() or attempt == 16:
                    raise RuntimeError("Non-finite SAM gradients after AMP scale recovery")
                # Also clears any second-pass unscale_ bookkeeping on failed steps.
                scaler.update(new_scale=scaler.get_scale() * 0.5)
                model._amp_overflow_retries += 1
            except BaseException:
                restore(originals)
                rewind()
                optimizer.zero_grad(set_to_none=True)
                raise
        raise RuntimeError("Unreachable SAM recovery state")

    seen, group_seen, total_loss = 0, 0, 0.0
    group_target = min(effective_batch, len(loader.dataset))
    window = []
    for images, targets, _ in loader:
        window.append((images, targets))
        seen += len(images)
        group_seen += len(images)
        if group_seen == group_target:
            first, second = optimize(window, group_target)
            total_loss += first
            perturbed_total += second
            window = []
            group_seen = 0
            group_target = min(effective_batch, len(loader.dataset) - seen)
    expected_steps = math.ceil(len(loader.dataset) / effective_batch)
    if seen != len(loader.dataset) or group_seen or model._sam_steps != expected_steps:
        raise RuntimeError(
            f"Incomplete SAM epoch: seen={seen}/{len(loader.dataset)}, "
            f"pending={group_seen}, steps={model._sam_steps}/{expected_steps}"
        )
    model._sam_perturbed_loss = perturbed_total / seen
    return total_loss / seen

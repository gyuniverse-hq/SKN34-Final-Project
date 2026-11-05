from pathlib import Path

import numpy as np
import pytest
import torch
from PIL import Image, ImageOps
from torch import nn
from torch.utils.data import DataLoader, TensorDataset

import skin_analysis.evaluate as evaluation_module
import skin_analysis.train as training_module
from skin_analysis.audit import audit_dataset
from skin_analysis.config import read_json
from skin_analysis.metrics import select_thresholds
from skin_analysis.model import ARCHITECTURE, SkinAnalysisModel
from skin_analysis.predict import predict
from skin_analysis.runtime import (
    capture_rng,
    load_checkpoint,
    model_from_checkpoint,
    restore_rng,
    save_checkpoint,
)
from skin_analysis.train import positive_weights, train_epoch
from skin_analysis.transforms import PREPROCESSING, make_transform


def test_resnet_logits_backprop_and_batchnorm_freeze():
    model = SkinAnalysisModel(3, pretrained=False)
    model.set_stage(True)
    model.train()
    images = torch.randn(2, 3, 32, 32)
    labels = torch.tensor([[1.0, 1.0, 0.0], [0.0, 0.0, 1.0]])
    before = model.backbone.bn1.running_mean.clone()
    logits = model(images)
    assert logits.shape == (2, 3)
    loss = nn.BCEWithLogitsLoss()(logits, labels)
    loss.backward()
    assert torch.isfinite(loss)
    assert model.head[0].weight.grad is not None
    assert model.backbone.conv1.weight.grad is None
    assert torch.equal(before, model.backbone.bn1.running_mean)
    model.set_stage(False)
    assert model.backbone.conv1.weight.requires_grad
    assert not model.backbone.bn1.training
    with torch.no_grad():
        model.head[-1].weight.zero_()
        model.head[-1].bias.copy_(torch.tensor([2.0, 2.0, -2.0]))
        scores = model(images).sigmoid()
    assert (scores[:, :2] > 0.5).all()  # No softmax or mutually exclusive normalization.


def test_checkpoint_reload_and_single_image_scores(tmp_path):
    model = SkinAnalysisModel(3, pretrained=False).eval()
    image_path = tmp_path / "face.png"
    pixels = np.random.default_rng(4).integers(0, 256, (32, 48, 3), dtype=np.uint8)
    Image.fromarray(pixels).save(image_path)
    checkpoint = {
        "schema_version": 1,
        "kind": "inference",
        "architecture": ARCHITECTURE,
        "model_state": model.state_dict(),
        "classes": ["a", "b", "c"],
        "preprocessing": PREPROCESSING,
        "score_type": "sigmoid_uncalibrated",
        "thresholds": [0.5] * 3,
        "model_id": "synthetic-model",
        "research_success": False,
    }
    checkpoint_path = tmp_path / "inference.pt"
    save_checkpoint(checkpoint_path, checkpoint)
    with Image.open(image_path) as image, torch.inference_mode():
        inputs = make_transform()(image).unsqueeze(0)
        expected = model(inputs).sigmoid().squeeze(0)
    loaded = load_checkpoint(checkpoint_path)
    reloaded = model_from_checkpoint(loaded, torch.device("cpu"))
    with torch.inference_mode():
        torch.testing.assert_close(
            reloaded(inputs).sigmoid().squeeze(0), expected, atol=1e-6, rtol=0
        )
    result = predict(checkpoint_path, image_path)
    np.testing.assert_allclose(result["scores"], expected.numpy(), atol=1e-6)
    assert result["classes"] == ["a", "b", "c"]
    assert result["score_type"] == "sigmoid_uncalibrated"


def test_train_only_positive_weights_and_unknown_rejection():
    weights = positive_weights([[1, 1], [0, 1], [0, 0], [0, 1]])
    torch.testing.assert_close(weights, torch.tensor([3.0, 1 / 3]))
    with pytest.raises(ValueError):
        positive_weights([[1, None], [0, 1]])
    with pytest.raises(ValueError):
        positive_weights([[1], [1]])


def test_accumulation_matches_full_batch_including_partial_group():
    torch.manual_seed(12)
    x, y = torch.randn(49, 3), torch.randint(0, 2, (49, 2)).float()
    dataset = TensorDataset(x, y, torch.arange(49))
    full, micro = nn.Linear(3, 2), nn.Linear(3, 2)
    micro.load_state_dict(full.state_dict())
    for model, size in ((full, 32), (micro, 8)):
        optimizer = torch.optim.SGD(model.parameters(), lr=0.1)
        train_epoch(
            model,
            DataLoader(dataset, batch_size=size),
            optimizer,
            nn.BCEWithLogitsLoss(),
            torch.device("cpu"),
            torch.amp.GradScaler("cuda", enabled=False),
            32,
            False,
        )
    torch.testing.assert_close(full.weight, micro.weight, atol=1e-6, rtol=0)
    torch.testing.assert_close(full.bias, micro.bias, atol=1e-6, rtol=0)


def test_rng_restores_shuffle_and_dropout():
    generator = torch.Generator().manual_seed(42)
    state = capture_rng(generator)
    expected = torch.rand(4), torch.randperm(10, generator=generator), np.random.rand(2)
    restore_rng(state, generator)
    torch.testing.assert_close(torch.rand(4), expected[0])
    torch.testing.assert_close(torch.randperm(10, generator=generator), expected[1])
    np.testing.assert_array_equal(np.random.rand(2), expected[2])


def test_amp_overflow_replays_window_without_discarding_samples():
    model = nn.Linear(3, 2)
    before = model.weight.detach().clone()
    attempts = []

    def inject_first_overflow(gradient):
        attempts.append(1)
        return torch.full_like(gradient, float("inf")) if len(attempts) == 1 else gradient

    model.weight.register_hook(inject_first_overflow)
    inputs = torch.ones(2, 3)
    labels = torch.tensor([[1.0, 1.0], [0.0, 0.0]])
    loader = DataLoader(TensorDataset(inputs, labels, torch.arange(2)), batch_size=2)
    optimizer = torch.optim.SGD(model.parameters(), lr=0.1)
    scaler = torch.amp.GradScaler("cpu", enabled=True)
    loss = train_epoch(
        model, loader, optimizer, nn.BCEWithLogitsLoss(), torch.device("cpu"), scaler, 32, False
    )
    assert np.isfinite(loss) and model._amp_overflow_retries == 1
    assert len(attempts) == 2 and not torch.equal(model.weight, before)


def test_small_batch_can_overfit_without_augmentation():
    x = torch.tensor([[1.0, 0.0, 0.0], [0.0, 1.0, 0.0], [0.0, 0.0, 1.0], [1.0, 1.0, 0.0]])
    y = torch.tensor([[1.0, 0.0], [0.0, 1.0], [0.0, 0.0], [1.0, 1.0]])
    model = nn.Linear(3, 2)
    loader = DataLoader(TensorDataset(x, y, torch.arange(4)), batch_size=4)
    optimizer = torch.optim.SGD(model.parameters(), lr=1.0)
    criterion = nn.BCEWithLogitsLoss()
    initial = float(criterion(model(x), y).detach())
    scaler = torch.amp.GradScaler("cuda", enabled=False)
    for _ in range(60):
        train_epoch(model, loader, optimizer, criterion, torch.device("cpu"), scaler, 32, False)
    assert float(criterion(model(x), y).detach()) < initial * 0.35


def test_exif_is_applied_before_deterministic_transform(tmp_path):
    path = tmp_path / "rotated.jpg"
    image = Image.fromarray(np.random.default_rng(1).integers(0, 255, (32, 48, 3), dtype=np.uint8))
    exif = image.getexif()
    exif[274] = 6
    image.save(path, exif=exif)
    with Image.open(path) as source:
        transposed = ImageOps.exif_transpose(source).convert("RGB")
        assert transposed.size == (32, 48)
        first, second = make_transform()(transposed), make_transform()(transposed)
    torch.testing.assert_close(first, second, atol=0, rtol=0)


class TinyModel(nn.Module):
    def __init__(self, classes, *, pretrained=False):
        super().__init__()
        self.backbone = nn.Sequential(nn.AdaptiveAvgPool2d(1), nn.Flatten(), nn.Linear(3, 4))
        self.head = nn.Linear(4, classes)

    def forward(self, images):
        return self.head(self.backbone(images))

    def set_stage(self, frozen):
        self.backbone.requires_grad_(not frozen)


def patch_cpu_training(monkeypatch):
    monkeypatch.setattr(training_module, "SkinAnalysisModel", TinyModel)
    monkeypatch.setattr(training_module, "select_cuda", lambda uuid: torch.device("cpu"))
    monkeypatch.setattr(torch.cuda, "reset_peak_memory_stats", lambda device: None)
    monkeypatch.setattr(torch.cuda, "max_memory_allocated", lambda device: 0)
    monkeypatch.setattr(torch.cuda, "max_memory_reserved", lambda device: 0)
    monkeypatch.setattr(torch.cuda, "synchronize", lambda device: None)


@pytest.mark.parametrize("interrupted_epoch", [0, 1])
def test_training_resume_matches_uninterrupted_run(
    synthetic_export, monkeypatch, interrupted_epoch
):
    patch_cpu_training(monkeypatch)
    training_module.train(synthetic_export)
    run = Path(synthetic_export["train"]["output"])
    expected = load_checkpoint(run / "last.pt")
    real_save = training_module.save_checkpoint
    interrupted = {"done": False}

    def interrupt_after_first(path, value):
        real_save(path, value)
        if (
            path.name == "last.pt"
            and value["epoch"] == interrupted_epoch
            and not interrupted["done"]
        ):
            interrupted["done"] = True
            raise KeyboardInterrupt

    synthetic_export["train"]["output"] = str(run.parent / "resumed")
    monkeypatch.setattr(training_module, "save_checkpoint", interrupt_after_first)
    with pytest.raises(KeyboardInterrupt):
        training_module.train(synthetic_export)
    monkeypatch.setattr(training_module, "save_checkpoint", real_save)
    resumed_path = Path(synthetic_export["train"]["output"]) / "last.pt"
    training_module.train(synthetic_export, str(resumed_path))
    actual = load_checkpoint(resumed_path)
    assert actual["epoch"] == expected["epoch"]
    assert actual["scheduler_state"] == expected["scheduler_state"]
    for name, value in expected["model_state"].items():
        torch.testing.assert_close(actual["model_state"][name], value, atol=0, rtol=0)


def test_end_to_end_evaluation_calibrates_only_on_validation(synthetic_export, monkeypatch):
    patch_cpu_training(monkeypatch)
    training_module.train(synthetic_export)
    run = Path(synthetic_export["train"]["output"])

    def tiny_from_checkpoint(checkpoint, device):
        model = TinyModel(len(checkpoint["classes"]))
        model.load_state_dict(checkpoint["model_state"])
        return model.eval().to(device)

    monkeypatch.setattr(evaluation_module, "model_from_checkpoint", tiny_from_checkpoint)
    output = run / "evaluation"
    result = evaluation_module.evaluate(synthetic_export, run / "best.pt", output)
    assert result["threshold_source"] == "validation_only"
    assert (output / "test-pr-curves.png").is_file()
    assert load_checkpoint(output / "inference.pt")["thresholds"] == result["thresholds"]
    assert read_json(output / "evaluation.json")["classes"] == ["Acne", "Pores", "Normal Skin"]
    _, manifest = audit_dataset(synthetic_export)
    valid = training_module.SkinDataset(manifest, "valid")
    checkpoint = load_checkpoint(run / "best.pt")
    y, scores, _ = training_module.predict_loader(
        tiny_from_checkpoint(checkpoint, torch.device("cpu")),
        training_module.make_loader(valid, 32, 0, 42),
        torch.device("cpu"),
    )
    assert result["thresholds"] == select_thresholds(y, scores)
    with pytest.raises(FileExistsError):
        evaluation_module.evaluate(synthetic_export, run / "best.pt", output)

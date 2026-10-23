from unittest.mock import patch

import pytest
import torch
from torch import nn
from torchvision.models import resnet50

from skin_analysis.acne.common import file_hash, load_config, write_json
from skin_analysis.acne.model import initialize
from skin_analysis.acne.train import train
from skin_analysis.train import train_epoch


def test_nia_transfer_preserves_backbone_and_uses_identical_new_head(tmp_path):
    backbone = resnet50(weights=None, num_classes=6)
    path = tmp_path / "nia.bin"
    torch.save({"model_state": backbone.state_dict()}, path)
    original_hash = file_hash(path)
    setup = tmp_path / "nia.json"
    write_json(setup, {"models": [{"task": "class/pore", "checkpoint": str(path),
                                   "sha256": original_hash, "source": "synthetic fixture"}]})
    config = load_config()
    config["initialization"]["nia_config"] = str(setup)
    transferred, provenance = initialize("nia", config)
    for key, value in backbone.state_dict().items():
        if not key.startswith("fc."):
            assert torch.equal(transferred.backbone.state_dict()[key], value)
    with patch("skin_analysis.acne.model.resnet50", return_value=resnet50(weights=None)), patch(
            "skin_analysis.acne.model.file_hash", return_value="fixture-no-download"):
        baseline, _ = initialize("imagenet", config)
    assert torch.equal(baseline.head.weight, transferred.head.weight)
    assert torch.equal(baseline.head.bias, transferred.head.bias)
    assert provenance["discarded_keys"] == ["fc.weight", "fc.bias"]
    assert file_hash(path) == original_hash
    write_json(setup, {"models": [{"task": "class/pore", "checkpoint": str(path),
                                   "sha256": "0" * 64, "source": "fixture"}]})
    with pytest.raises(ValueError, match="hash mismatch"):
        initialize("nia", config)


class TinyModel(nn.Module):
    """CPU-only training state fixture, not a substitute for ResNet performance testing."""
    def __init__(self):
        super().__init__()
        self.backbone = nn.Module()
        self.backbone.layer4 = nn.Linear(3, 4)
        self.head = nn.Linear(4, 1)

    def forward(self, x):
        return self.head(self.backbone.layer4(x).relu())

    def set_stage(self, frozen):
        self.backbone.requires_grad_(not frozen)
        self.head.requires_grad_(True)


class TinyDataset(torch.utils.data.Dataset):
    def __init__(self, manifest, split, training=False):
        self.x = torch.tensor([[1., 0., 0.], [0., 1., 0.], [2., 0., 1.], [0., 2., 1.]])
        self.y = torch.tensor([[0.], [1.], [0.], [1.]])

    def __len__(self):
        return 4

    def __getitem__(self, index):
        return self.x[index], self.y[index], index

    def close(self):
        pass


def test_interrupted_training_resumes_to_identical_optimizer_rng_and_weights(tmp_path):
    config = load_config()
    config["train"].update(output=str(tmp_path / "full"), batch_size=2, effective_batch=4,
                            freeze_epochs=1, finetune_epochs=2, num_workers=0, amp=False)
    manifest = {"fingerprint": "fixture", "limitations": ["synthetic test only"]}
    with patch("skin_analysis.acne.train.load_manifest", return_value=manifest), patch(
            "skin_analysis.acne.train.select_cuda", return_value=torch.device("cpu")), patch(
            "skin_analysis.acne.train.AcneDataset", TinyDataset), patch(
            "skin_analysis.acne.train.AcneModel", TinyModel), patch(
            "skin_analysis.acne.train.initialize", side_effect=lambda *_: (TinyModel(), {})), patch(
            "torch.cuda.get_device_name", return_value="CPU fixture"), patch(
            "torch.cuda.synchronize"), patch("torch.cuda.reset_peak_memory_stats"), patch(
            "torch.cuda.max_memory_allocated", return_value=0):
        full = train(config, "imagenet")
        expected = torch.load(full / "last.pt", weights_only=True)
        config["train"]["output"] = str(tmp_path / "interrupted")
        calls = 0

        def interrupt_after_first(*args, **kwargs):
            nonlocal calls
            calls += 1
            if calls == 2:
                raise RuntimeError("simulated interruption")
            return train_epoch(*args, **kwargs)

        with patch("skin_analysis.acne.train.train_epoch", side_effect=interrupt_after_first):
            with pytest.raises(RuntimeError, match="simulated interruption"):
                train(config, "imagenet")
        resume = tmp_path / "interrupted/imagenet-seed-42/last.pt"
        actual_path = train(config, "imagenet", str(resume))
        actual = torch.load(actual_path / "last.pt", weights_only=True)
        assert actual["epoch"] == expected["epoch"] == 2
        for key in expected["model_state"]:
            torch.testing.assert_close(actual["model_state"][key], expected["model_state"][key],
                                       rtol=0, atol=0)
        assert actual["best_key"] == expected["best_key"]
        assert (actual["optimizer_state"]["param_groups"]
                == expected["optimizer_state"]["param_groups"])
        assert torch.equal(actual["rng_state"]["loader"], expected["rng_state"]["loader"])
        config["train"]["head_lr"] *= 2
        with pytest.raises(ValueError, match="Resume requires"):
            train(config, "imagenet", str(resume))

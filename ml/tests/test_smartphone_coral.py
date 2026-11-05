"""Ordinal mathematics, decoding, frozen backbone and checkpoint contracts."""

import pytest
import torch
from torch.nn import functional as F

from skin_analysis.smartphone.common import PREPROCESSING, file_hash
from skin_analysis.smartphone.coral import (
    ARCHITECTURE,
    DECODING,
    CoralHead,
    CoralLoss,
    decode_coral,
    load_coral_checkpoint,
    ordinal_levels,
)
from skin_analysis.smartphone.train import GradeModel, criterion_for, predict, require_coral_gate


def test_all_grades_have_cumulative_targets():
    levels = ordinal_levels(torch.arange(6), 6)
    assert levels.shape == (6, 5)
    assert levels[3].tolist() == [1, 1, 1, 0, 0]
    assert levels[0].sum() == 0 and levels[-1].sum() == 5
    assert levels.sum(1).tolist() == list(range(6))


@pytest.mark.parametrize("targets", [torch.tensor([-1]), torch.tensor([6]), torch.tensor([1.5])])
def test_invalid_ordinal_labels_rejected(targets):
    with pytest.raises(ValueError):
        ordinal_levels(targets, 6)


def test_loss_matches_author_example_and_manual_binary_likelihood():
    logits = torch.tensor([[2.1, 1.8, -2.1, -1.8], [1.9, -1, -1.5, -1.3], [1.9, 1.8, 1.7, 1.6]])
    targets = torch.tensor([2, 1, 4])
    levels = ordinal_levels(targets, 5)
    p = logits.sigmoid()
    manual = -(levels * p.log() + (1 - levels) * (1 - p).log()).sum(1).mean()
    torch.testing.assert_close(CoralLoss()(logits, targets), manual)
    assert CoralLoss()(logits, targets).item() == pytest.approx(0.6920, abs=5e-5)


def test_loss_is_finite_for_extreme_half_precision_logits_and_gradient():
    logits = torch.tensor([[1000, -1000], [1000, -1000]], dtype=torch.float16, requires_grad=True)
    loss = CoralLoss()(logits, torch.tensor([0, 2]))
    loss.backward()
    assert loss.dtype == torch.float32 and torch.isfinite(loss)
    assert torch.isfinite(logits.grad).all()


def test_decode_counts_crossed_thresholds_instead_of_argmax():
    logits = torch.tensor(
        [[4, 3, 2, -1, -2], [-1, -2, -3, -4, -5], [5, 4, 3, 2, 1], [0, -1, -2, -3, -4]]
    )
    labels, probabilities = decode_coral(logits)
    assert labels.tolist() == [3, 0, 5, 0]
    assert probabilities.shape == (4, 5)
    with pytest.raises(ValueError, match="rank consistent"):
        decode_coral(torch.tensor([[0.0, 1.0]]))


def test_shared_score_head_and_frozen_bn_are_trainable_correctly():
    model = GradeModel(6, ordinal=True)
    assert isinstance(model.network.fc, CoralHead)
    head = model.network.fc
    logits = head(torch.randn(3, 2048))
    torch.testing.assert_close(logits[:, 0] - logits[:, 1], (head.bias[0] - head.bias[1]).expand(3))
    model.set_stage(True)
    model.train()
    assert not model.network.bn1.training
    assert not model.network.conv1.weight.requires_grad
    assert all(p.requires_grad for p in head.parameters())
    CoralLoss()(logits, torch.tensor([0, 3, 5])).backward()
    assert torch.isfinite(head.score.weight.grad).all() and torch.isfinite(head.bias.grad).all()


def test_coral_criterion_has_no_old_class_weights_or_focal_modulation():
    criterion, spec = criterion_for([0] * 10 + [1], 2, dict(loss="coral"), "cpu")
    assert isinstance(criterion, CoralLoss)
    assert spec["legacy_sqrt_class_weights_used"] is False
    logits, target = torch.zeros(2, 1), torch.tensor([0, 1])
    torch.testing.assert_close(
        criterion(logits, target),
        F.binary_cross_entropy_with_logits(logits, target[:, None].float()),
    )


def test_prediction_path_uses_ordinal_decoder():
    class Fake(torch.nn.Module):
        def forward(self, images):
            return images

    loader = [
        (
            torch.tensor([[3.0, 2.0, -1.0], [-1.0, -2.0, -3.0]]),
            torch.tensor([2, 0]),
            torch.arange(2),
        )
    ]
    truth, predicted, probabilities, loss = predict(Fake(), loader, "cpu", ordinal=True)
    assert truth == predicted == [2, 0]
    assert len(probabilities[0]) == 3 and loss > 0


def test_coral_checkpoint_roundtrip_and_rejects_wrong_hash_or_architecture(tmp_path):
    torch.set_num_threads(4)
    network = GradeModel(6, ordinal=True).network.eval()
    state = dict(
        architecture=ARCHITECTURE,
        task="pore",
        resolution=256,
        preprocessing=PREPROCESSING,
        decoding=DECODING,
        grades=list(range(6)),
        model_state=network.state_dict(),
    )
    path = tmp_path / "inference.bin"
    torch.save(state, path)
    restored, _ = load_coral_checkpoint(path, file_hash(path))
    image = torch.zeros(1, 3, 256, 256)
    with torch.inference_mode():
        torch.testing.assert_close(restored(image), network(image), rtol=0, atol=0)
    with pytest.raises(ValueError, match="hash"):
        load_coral_checkpoint(path, "0" * 64)
    state["architecture"] = "resnet50"
    torch.save(state, path)
    with pytest.raises(ValueError, match="contract"):
        load_coral_checkpoint(path, file_hash(path))


def test_expansion_requires_real_passing_pore_metrics_and_matching_split(tmp_path):
    import json

    config = dict(
        train=dict(loss="coral", output=str(tmp_path)),
        comparison=dict(policy="same-policy"),
    )
    manifest = dict(fingerprint="same-split")
    require_coral_gate(config, manifest, "pore")
    with pytest.raises(ValueError, match="pore first"):
        require_coral_gate(config, manifest, "all")
    with pytest.raises(ValueError, match="pore first"):
        require_coral_gate(config, manifest, "pigmentation")
    baseline = dict(
        accuracy=0.5,
        macro_f1=0.3,
        per_grade=[dict(grade=0, support=10), dict(grade=1, support=10)],
        confusion=[[5, 5], [5, 5]],
    )
    candidate = dict(
        accuracy=0.6,
        macro_f1=0.4,
        per_grade=baseline["per_grade"],
        confusion=[[6, 4], [4, 6]],
    )
    result = dict(
        schema="nia-coral-validation-v1",
        data_fingerprint="same-split",
        selection_policy="same-policy",
        test_set_evaluated=False,
        qualifies_for_expansion=True,
        results=dict(ce=dict(metrics=baseline), coral=dict(metrics=candidate)),
    )
    path = tmp_path / "pore-comparison.json"
    path.write_text(json.dumps(result), encoding="utf-8")
    require_coral_gate(config, manifest, "wrinkle")
    candidate["accuracy"] = 0.4
    path.write_text(json.dumps(result), encoding="utf-8")
    with pytest.raises(ValueError, match="expansion policy"):
        require_coral_gate(config, manifest, "wrinkle")
    candidate["accuracy"] = 0.6
    manifest["fingerprint"] = "different-split"
    path.write_text(json.dumps(result), encoding="utf-8")
    with pytest.raises(ValueError, match="expansion policy"):
        require_coral_gate(config, manifest, "pigmentation")

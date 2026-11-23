"""Same-face ranking loss, face batching and face split for finetune_astra (no weights download)."""
import random
import sys
from pathlib import Path

import torch

HERE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HERE))
from finetune_astra import face_batches, rank_loss, split_faces  # noqa: E402


def test_rank_loss_only_compares_same_face():
    targets = [1.0, 0.2, 0.9, 0.1]
    faces = ["a", "a", "b", "c"]
    right = rank_loss(torch.tensor([2.0, -2.0, 0.0, 9.0]), targets, faces)
    wrong = rank_loss(torch.tensor([-2.0, 2.0, 0.0, 9.0]), targets, faces)
    assert right < 0.2 < wrong


def test_rank_loss_ignores_small_gaps():
    loss = rank_loss(torch.tensor([0.0, 5.0], requires_grad=True), [0.5, 0.3], ["a", "a"])
    assert float(loss.detach()) == 0


def test_face_batches_keep_faces_together():
    faces = ["a", "a", "b", "c", "c", "c"]
    batches = list(face_batches(faces, 2, random.Random(0)))
    assert sorted(i for b in batches for i in b) == list(range(6))
    for b in batches:
        for face in {faces[i] for i in b}:
            assert {i for i, f in enumerate(faces) if f == face} <= set(b)


def test_split_faces_has_no_face_in_both():
    faces = [f"f{i // 3}" for i in range(30)]
    train, val = split_faces(faces, 0.2, 1)
    assert not {faces[i] for i in train} & {faces[i] for i in val}
    assert len(train) + len(val) == 30

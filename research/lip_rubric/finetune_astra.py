"""Fine-tune EfficientNet-B0 on Astra lip labels; test once on R5 human labels.

Loss = MSE on the checklist total + logistic ranking loss between images of the same face
(the pool has current + defect renders per face, so same-face pairs come from Astra scores alone).
The epoch is chosen on held-out Astra faces; R5 checklist (98) and R5 A/B (476 decisive pairs)
are scored only for the chosen weights.

  ml/.venv/Scripts/python.exe research/lip_rubric/finetune_astra.py [--epochs 8] [--device cuda]
"""
from __future__ import annotations

import argparse
import json
import os
import random
from collections import defaultdict

import numpy as np

from common import read_csv
from learn import OUT as R5_OUT
from learn import SEED
from learn_astra import OUT, _bootstrap_ci, _spearman, load_astra

SIZE = 224
MEAN = (0.485, 0.456, 0.406)
STD = (0.229, 0.224, 0.225)
FROZEN_BLOCKS = 5
MIN_GAP = 0.4


def build_model():
    import torch
    from torchvision import models

    model = models.efficientnet_b0(weights=models.EfficientNet_B0_Weights.IMAGENET1K_V1)
    model.classifier = torch.nn.Sequential(torch.nn.Dropout(0.3), torch.nn.Linear(1280, 1))
    for block in model.features[:FROZEN_BLOCKS]:
        block.requires_grad_(False)
    return model


def load_images(paths):
    """Whole crop squeezed to SIZE x SIZE (no centre crop: lip edges carry defects)."""
    import torch
    from PIL import Image

    out = torch.empty((len(paths), 3, SIZE, SIZE), dtype=torch.uint8)
    for n, path in enumerate(paths):
        image = Image.open(path).convert("RGB").resize((SIZE, SIZE), Image.BICUBIC)
        out[n] = torch.from_numpy(np.asarray(image).copy()).permute(2, 0, 1)
    return out


def normalize(batch, augment):
    import torch

    x = batch.float() / 255
    if augment:
        flip = torch.rand(len(x)) < 0.5
        x[flip] = x[flip].flip(-1)
        x = x * (1 + (torch.rand(len(x), 1, 1, 1) - 0.5) * 0.2)
        x = x.clamp(0, 1)
    mean = torch.tensor(MEAN).view(1, 3, 1, 1)
    std = torch.tensor(STD).view(1, 3, 1, 1)
    return (x - mean) / std


def rank_loss(scores, targets, faces):
    import torch

    losses = []
    for face in set(faces):
        idx = [i for i, f in enumerate(faces) if f == face]
        for a in idx:
            for b in idx:
                if targets[a] - targets[b] >= MIN_GAP:
                    losses.append(torch.nn.functional.softplus(scores[b] - scores[a]))
    return torch.stack(losses).mean() if losses else scores.sum() * 0


def face_batches(faces, batch_images, rng):
    by_face = defaultdict(list)
    for i, f in enumerate(faces):
        by_face[f].append(i)
    groups = list(by_face.values())
    rng.shuffle(groups)
    batch = []
    for g in groups:
        batch.extend(g)
        if len(batch) >= batch_images:
            yield batch
            batch = []
    if batch:
        yield batch


def predict(model, images, device, batch=64):
    import torch

    model.eval()
    out = []
    with torch.inference_mode():
        for i in range(0, len(images), batch):
            out.append(model(normalize(images[i:i + batch], False).to(device)).squeeze(1).float().cpu())
    return torch.cat(out).numpy() * 5


def split_faces(faces, fraction, seed):
    unique = sorted(set(faces))
    random.Random(seed).shuffle(unique)
    held = set(unique[: max(1, round(len(unique) * fraction))])
    train = [i for i, f in enumerate(faces) if f not in held]
    val = [i for i, f in enumerate(faces) if f in held]
    return train, val


def main(argv=None):
    import torch

    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--epochs", type=int, default=8)
    p.add_argument("--batch", type=int, default=32)
    p.add_argument("--rank-weight", type=float, default=1.0)
    p.add_argument("--device", default=None)
    a = p.parse_args(argv)

    torch.manual_seed(SEED)
    torch.set_num_threads(os.cpu_count() or 4)
    device = a.device or ("cuda" if torch.cuda.is_available() else "cpu")
    rng = random.Random(SEED)

    astra = load_astra()
    faces = [r["face_id"] for r in astra]
    targets = torch.tensor([r["total"] / 5 for r in astra], dtype=torch.float32)
    images = load_images([r["crop_path"] for r in astra])
    train_idx, val_idx = split_faces(faces, 0.15, SEED)
    print(f"astra train {len(train_idx)} / val {len(val_idx)} images, device {device}", flush=True)

    model = build_model().to(device)
    params = [{"params": model.features.parameters(), "lr": 1e-4}, {"params": model.classifier.parameters(), "lr": 1e-3}]
    optim = torch.optim.AdamW([g for g in params], weight_decay=1e-4)
    best = (-2.0, None, None)
    history = []
    val_y = targets[val_idx].numpy() * 5
    for epoch in range(1, a.epochs + 1):
        model.train()
        for block in model.features[:FROZEN_BLOCKS]:
            block.eval()
        losses = []
        train_faces = [faces[i] for i in train_idx]
        for batch in face_batches(train_faces, a.batch, rng):
            idx = [train_idx[i] for i in batch]
            x = normalize(images[idx], True).to(device)
            y = targets[idx].to(device)
            s = model(x).squeeze(1)
            loss = torch.nn.functional.mse_loss(s, y) + a.rank_weight * rank_loss(s, y.tolist(), [faces[i] for i in idx])
            optim.zero_grad()
            loss.backward()
            optim.step()
            losses.append(float(loss.detach()))
        val_rho = _spearman(val_y, predict(model, images[val_idx], device))
        history.append({"epoch": epoch, "train_loss": round(float(np.mean(losses)), 4), "astra_val_spearman": val_rho})
        print(json.dumps(history[-1]), flush=True)
        if val_rho is not None and val_rho > best[0]:
            best = (val_rho, epoch, {k: v.detach().cpu().clone() for k, v in model.state_dict().items()})

    model.load_state_dict(best[2])
    OUT.mkdir(parents=True, exist_ok=True)
    torch.save(best[2], OUT / "finetune_b0.pt")

    r5 = read_csv(R5_OUT / "labels_absolute.csv")
    r5_pred = predict(model, load_images([r["crop_path"] for r in r5]), device)
    r5_y = np.array([float(r["total"]) for r in r5])
    r5_faces = np.array([r["face_id"] for r in r5])
    kinds = np.array([r["kind"] for r in r5])
    render = kinds == "render"

    pairs = [r for r in read_csv(R5_OUT / "pairs.csv") if float(r["pref_left"]) != 0.5]
    left = predict(model, load_images([r["left_crop"] for r in pairs]), device)
    right = predict(model, load_images([r["right_crop"] for r in pairs]), device)
    truth = np.array([float(r["pref_left"]) > 0.5 for r in pairs])

    summary = {
        "model": "efficientnet_b0 ImageNet1K_V1, first 5 blocks frozen",
        "loss": f"mse + {a.rank_weight} * same-face ranking (gap >= {MIN_GAP})",
        "epochs": a.epochs,
        "chosen_epoch": best[1],
        "astra_val_spearman": best[0],
        "history": history,
        "r5_spearman": _spearman(r5_y, r5_pred),
        "r5_spearman_ci": _bootstrap_ci(r5_y, r5_pred, r5_faces),
        "r5_render_spearman": _spearman(r5_y[render], r5_pred[render]),
        "r5_pred_mean_by_kind": {k: round(float(r5_pred[kinds == k].mean()), 3) for k in sorted(set(kinds.tolist()))},
        "r5_ab": {"pairs": len(pairs), "accuracy": round(float(((left > right) == truth).mean()), 4)},
        "device": device,
    }
    (OUT / "finetune_b0_summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf8")
    print(json.dumps({k: v for k, v in summary.items() if k != "history"}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

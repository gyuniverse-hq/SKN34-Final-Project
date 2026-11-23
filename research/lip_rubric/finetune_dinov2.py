"""Fine-tune a DINOv2-ViT-S/14 score head with weighted MSE + AdamW (absolute scores).

Backbone stays frozen (research CPU-friendly). Sample weights boost low/high totals so the
head is less stuck in the mid-range. Epoch chosen on held-out Astra faces; R5 scored once.

  ml/.venv/Scripts/python.exe research/lip_rubric/finetune_dinov2.py
  ml/.venv/Scripts/python.exe research/lip_rubric/finetune_dinov2.py --epochs 12 --batch 64
"""
from __future__ import annotations

import argparse
import json
import os
import random

import numpy as np
import torch
import torch.nn as nn

from common import read_csv
from finetune_astra import face_batches, load_images, normalize, split_faces
from learn import OUT as R5_OUT
from learn import SEED
from learn_astra import OUT, _bootstrap_ci, _spearman, load_astra

EMB_DIM = 384
PASS_LINE = 4.68


def score_weights(y_0_to_5: torch.Tensor) -> torch.Tensor:
    """Higher weight on sparse tails and near the human pass band."""
    w = torch.ones_like(y_0_to_5)
    w = torch.where(y_0_to_5 <= 1.0, torch.full_like(w, 2.5), w)
    w = torch.where((y_0_to_5 > 1.0) & (y_0_to_5 < 2.0), torch.full_like(w, 1.5), w)
    w = torch.where(y_0_to_5 >= 4.0, torch.full_like(w, 3.0), w)
    w = torch.where(y_0_to_5 >= PASS_LINE, torch.full_like(w, 3.5), w)
    return w


def weighted_mse(pred: torch.Tensor, target: torch.Tensor, weights: torch.Tensor) -> torch.Tensor:
    return (weights * (pred - target) ** 2).sum() / weights.sum().clamp_min(1e-8)


class ScoreHead(nn.Module):
    def __init__(self, dim: int = EMB_DIM, dropout: float = 0.3):
        super().__init__()
        self.net = nn.Sequential(nn.Dropout(dropout), nn.Linear(dim, 1))

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        return self.net(x).squeeze(-1)


def load_dinov2(device: str):
    model = torch.hub.load("facebookresearch/dinov2", "dinov2_vits14", trust_repo=True)
    model.eval().requires_grad_(False).to(device)
    return model


@torch.inference_mode()
def embed_images(backbone, images: torch.Tensor, device: str, batch: int = 32) -> torch.Tensor:
    """images: uint8 NCHW → L2-normalized float embeddings."""
    outs = []
    for i in range(0, len(images), batch):
        x = normalize(images[i:i + batch], False).to(device)
        feat = backbone(x).float()
        feat = feat / (feat.norm(dim=-1, keepdim=True) + 1e-9)
        outs.append(feat.cpu())
    return torch.cat(outs, 0)


def predict_scores(head: ScoreHead, emb: torch.Tensor, device: str, batch: int = 256) -> np.ndarray:
    head.eval()
    outs = []
    with torch.inference_mode():
        for i in range(0, len(emb), batch):
            outs.append(head(emb[i:i + batch].to(device)).float().cpu())
    return (torch.cat(outs).numpy() * 5.0)


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--epochs", type=int, default=12)
    p.add_argument("--batch", type=int, default=64)
    p.add_argument("--lr", type=float, default=1e-3)
    p.add_argument("--weight-decay", type=float, default=1e-4)
    p.add_argument("--dropout", type=float, default=0.3)
    p.add_argument("--embed-batch", type=int, default=16)
    p.add_argument("--device", default=None)
    a = p.parse_args(argv)

    torch.manual_seed(SEED)
    torch.set_num_threads(os.cpu_count() or 4)
    device = a.device or ("cuda" if torch.cuda.is_available() else "cpu")
    rng = random.Random(SEED)

    astra = load_astra()
    faces = [r["face_id"] for r in astra]
    y5 = torch.tensor([float(r["total"]) for r in astra], dtype=torch.float32)
    targets = y5 / 5.0
    print(f"loading {len(astra)} astra crops…", flush=True)
    images = load_images([r["crop_path"] for r in astra])
    train_idx, val_idx = split_faces(faces, 0.15, SEED)
    print(f"astra train {len(train_idx)} / val {len(val_idx)}, device {device}", flush=True)

    print("embedding with frozen dinov2_vits14…", flush=True)
    backbone = load_dinov2(device)
    emb = embed_images(backbone, images, device, batch=a.embed_batch)
    del backbone, images
    if device.startswith("cuda"):
        torch.cuda.empty_cache()

    head = ScoreHead(emb.shape[1], a.dropout).to(device)
    optim = torch.optim.AdamW(head.parameters(), lr=a.lr, weight_decay=a.weight_decay)

    best = (-2.0, None, None)
    history = []
    val_y = y5[val_idx].numpy()
    train_faces = [faces[i] for i in train_idx]

    for epoch in range(1, a.epochs + 1):
        head.train()
        losses = []
        for batch in face_batches(train_faces, a.batch, rng):
            idx = [train_idx[i] for i in batch]
            x = emb[idx].to(device)
            y = targets[idx].to(device)
            w = score_weights(y5[idx].to(device))
            pred = head(x)
            loss = weighted_mse(pred, y, w)
            optim.zero_grad()
            loss.backward()
            optim.step()
            losses.append(float(loss.detach()))
        val_pred = predict_scores(head, emb[val_idx], device)
        val_rho = _spearman(val_y, val_pred)
        val_mae = float(np.mean(np.abs(val_y - val_pred)))
        row = {
            "epoch": epoch,
            "train_w_mse": round(float(np.mean(losses)), 4),
            "astra_val_spearman": val_rho,
            "astra_val_mae": round(val_mae, 4),
        }
        history.append(row)
        print(json.dumps(row), flush=True)
        if val_rho is not None and val_rho > best[0]:
            best = (val_rho, epoch, {k: v.detach().cpu().clone() for k, v in head.state_dict().items()})

    head.load_state_dict(best[2])
    OUT.mkdir(parents=True, exist_ok=True)
    torch.save({"head": best[2], "emb_dim": int(emb.shape[1]), "pass_line": PASS_LINE}, OUT / "finetune_dinov2_head.pt")

    r5 = read_csv(R5_OUT / "labels_absolute.csv")
    print(f"embedding R5 {len(r5)}…", flush=True)
    backbone = load_dinov2(device)
    r5_images = load_images([r["crop_path"] for r in r5])
    r5_emb = embed_images(backbone, r5_images, device, batch=a.embed_batch)
    del backbone, r5_images

    r5_pred = predict_scores(head, r5_emb, device)
    r5_y = np.array([float(r["total"]) for r in r5])
    r5_faces = np.array([r["face_id"] for r in r5])
    kinds = np.array([r["kind"] for r in r5])
    render = kinds == "render"

    summary = {
        "model": "dinov2_vits14 frozen + Dropout+Linear head",
        "optimizer": f"AdamW lr={a.lr} weight_decay={a.weight_decay}",
        "loss": "weighted_mse on total/5; weights boost y<=1, y>=4, y>=4.68",
        "epochs": a.epochs,
        "batch": a.batch,
        "chosen_epoch": best[1],
        "astra_val_spearman": best[0],
        "history": history,
        "r5_spearman": _spearman(r5_y, r5_pred),
        "r5_spearman_ci": _bootstrap_ci(r5_y, r5_pred, r5_faces),
        "r5_mae": round(float(np.mean(np.abs(r5_y - r5_pred))), 4),
        "r5_bias_pred_minus_human": round(float((r5_pred - r5_y).mean()), 4),
        "r5_pred_mean": round(float(r5_pred.mean()), 4),
        "r5_human_mean": round(float(r5_y.mean()), 4),
        "r5_render_spearman": _spearman(r5_y[render], r5_pred[render]),
        "r5_render_mae": round(float(np.mean(np.abs(r5_y[render] - r5_pred[render]))), 4),
        "r5_pred_mean_by_kind": {
            k: round(float(r5_pred[kinds == k].mean()), 3) for k in sorted(set(kinds.tolist()))
        },
        "r5_human_mean_by_kind": {
            k: round(float(r5_y[kinds == k].mean()), 3) for k in sorted(set(kinds.tolist()))
        },
        "frozen_ridge_baseline_r5_spearman": 0.5147,
        "device": device,
        "weights": str(OUT / "finetune_dinov2_head.pt"),
    }
    (OUT / "finetune_dinov2_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf8"
    )
    print("SUMMARY", json.dumps({k: v for k, v in summary.items() if k != "history"}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

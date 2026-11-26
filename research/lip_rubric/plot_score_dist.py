"""Histogram + scatter of frozen encoder + Ridge scores vs R5 human totals.

  ml/.venv/Scripts/python.exe research/lip_rubric/plot_score_dist.py
  ml/.venv/Scripts/python.exe research/lip_rubric/plot_score_dist.py --encoder dinov2_vits14
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np

from common import read_csv, write_csv
from learn import OUT as R5_OUT
from learn import _emb_map
from learn_astra import ENCODERS, OUT, _ridge, _spearman, embedding_paths, load_astra


def predict_r5(encoder: str):
    summary = json.loads(
        (OUT / ("fit_summary.json" if encoder == "resnet18" else f"fit_summary_{encoder}.json")).read_text(
            encoding="utf8"
        )
    )
    alpha = float(summary["targets"]["total"]["alpha"])
    astra = load_astra()
    a_path, r_path = embedding_paths(encoder)
    a_emb, r_emb = _emb_map(a_path), _emb_map(r_path)
    r5 = read_csv(R5_OUT / "labels_absolute.csv")
    Xa = np.stack([a_emb[r["image_id"]] for r in astra])
    ya = np.array([float(r["total"]) for r in astra])
    Xr = np.stack([r_emb[r["image_id"]] for r in r5])
    model = _ridge(alpha).fit(Xa, ya)
    pred = model.predict(Xr)
    rows = []
    for i, r in enumerate(r5):
        y = float(r["total"])
        p = float(pred[i])
        rows.append({
            "image_id": r["image_id"],
            "face_id": r["face_id"],
            "kind": r["kind"],
            "human_total": round(y, 4),
            "pred_total": round(p, 4),
            "residual": round(p - y, 4),
            "abs_error": round(abs(p - y), 4),
        })
    y = np.array([r["human_total"] for r in rows])
    p = np.array([r["pred_total"] for r in rows])
    stats = {
        "encoder": encoder,
        "alpha": alpha,
        "n": len(rows),
        "human_mean": round(float(y.mean()), 4),
        "human_std": round(float(y.std()), 4),
        "pred_mean": round(float(p.mean()), 4),
        "pred_std": round(float(p.std()), 4),
        "bias_pred_minus_human": round(float((p - y).mean()), 4),
        "mae": round(float(np.mean(np.abs(p - y))), 4),
        "spearman": _spearman(y, p),
        "by_kind": {},
    }
    for kind in sorted({r["kind"] for r in rows}):
        m = np.array([r["kind"] == kind for r in rows])
        stats["by_kind"][kind] = {
            "n": int(m.sum()),
            "human_mean": round(float(y[m].mean()), 4),
            "pred_mean": round(float(p[m].mean()), 4),
            "mae": round(float(np.mean(np.abs(p[m] - y[m]))), 4),
        }
    # score-bin error (human bins)
    bins = [(0, 1), (1, 2), (2, 3), (3, 4), (4, 5.01)]
    stats["by_human_bin"] = {}
    for lo, hi in bins:
        m = (y >= lo) & (y < hi)
        key = f"{lo:.0f}-{hi:.0f}" if hi <= 5 else "4-5"
        if not m.any():
            stats["by_human_bin"][key] = {"n": 0}
            continue
        stats["by_human_bin"][key] = {
            "n": int(m.sum()),
            "human_mean": round(float(y[m].mean()), 4),
            "pred_mean": round(float(p[m].mean()), 4),
            "mae": round(float(np.mean(np.abs(p[m] - y[m]))), 4),
        }
    return rows, stats


def plot(rows: list[dict], stats: dict, out: Path) -> list[str]:
    import matplotlib.pyplot as plt

    out.mkdir(parents=True, exist_ok=True)
    y = np.array([r["human_total"] for r in rows])
    p = np.array([r["pred_total"] for r in rows])
    kinds = np.array([r["kind"] for r in rows])
    colors = {"real": "#2a9d8f", "render": "#e9c46a", "sticker": "#e76f51"}
    paths = []

    # 1) scatter human vs pred
    fig, ax = plt.subplots(figsize=(5.5, 5.2))
    for kind, color in colors.items():
        m = kinds == kind
        if m.any():
            ax.scatter(y[m], p[m], c=color, s=28, alpha=0.85, label=f"{kind} (n={m.sum()})")
    lim = (-0.2, 5.2)
    ax.plot(lim, lim, "k--", lw=1, alpha=0.5, label="y = x")
    ax.set_xlim(lim)
    ax.set_ylim(lim)
    ax.set_xlabel("R5 human total")
    ax.set_ylabel(f"{stats['encoder']} pred")
    ax.set_title(f"Scatter  Spearman={stats['spearman']}  MAE={stats['mae']}")
    ax.legend(loc="upper left", fontsize=8)
    ax.set_aspect("equal", adjustable="box")
    fig.tight_layout()
    p1 = out / "scatter_human_vs_pred.png"
    fig.savefig(p1, dpi=140)
    plt.close(fig)
    paths.append(str(p1))

    # 2) overlapping histograms
    fig, ax = plt.subplots(figsize=(6, 3.8))
    bins = np.linspace(0, 5, 11)
    ax.hist(y, bins=bins, alpha=0.55, label=f"human (μ={stats['human_mean']})", color="#264653")
    ax.hist(p, bins=bins, alpha=0.55, label=f"pred (μ={stats['pred_mean']})", color="#f4a261")
    ax.set_xlabel("score (0–5)")
    ax.set_ylabel("count")
    ax.set_title(f"Score distribution  bias={stats['bias_pred_minus_human']}")
    ax.legend()
    fig.tight_layout()
    p2 = out / "hist_scores.png"
    fig.savefig(p2, dpi=140)
    plt.close(fig)
    paths.append(str(p2))

    # 3) residual histogram
    fig, ax = plt.subplots(figsize=(6, 3.8))
    resid = p - y
    ax.hist(resid, bins=12, color="#6d597a", alpha=0.85)
    ax.axvline(0, color="k", lw=1)
    ax.axvline(resid.mean(), color="#e76f51", lw=1.5, label=f"mean={resid.mean():.2f}")
    ax.set_xlabel("pred − human")
    ax.set_ylabel("count")
    ax.set_title("Residual distribution")
    ax.legend()
    fig.tight_layout()
    p3 = out / "hist_residual.png"
    fig.savefig(p3, dpi=140)
    plt.close(fig)
    paths.append(str(p3))

    # 4) kind means bar
    fig, ax = plt.subplots(figsize=(5.2, 3.6))
    order = [k for k in ("sticker", "render", "real") if k in stats["by_kind"]]
    x = np.arange(len(order))
    h = [stats["by_kind"][k]["human_mean"] for k in order]
    pr = [stats["by_kind"][k]["pred_mean"] for k in order]
    ax.bar(x - 0.18, h, 0.36, label="human", color="#264653")
    ax.bar(x + 0.18, pr, 0.36, label="pred", color="#f4a261")
    ax.set_xticks(x)
    ax.set_xticklabels(order)
    ax.set_ylim(0, 5.2)
    ax.set_ylabel("mean score")
    ax.set_title("Mean by kind")
    ax.legend()
    fig.tight_layout()
    p4 = out / "bar_by_kind.png"
    fig.savefig(p4, dpi=140)
    plt.close(fig)
    paths.append(str(p4))

    return paths


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--encoder", choices=ENCODERS, action="append")
    args = p.parse_args(argv)
    encoders = args.encoder or ["dinov2_vits14", "resnet18"]
    index = []
    for enc in encoders:
        rows, stats = predict_r5(enc)
        out = OUT / "dist_plots" / enc
        paths = plot(rows, stats, out)
        write_csv(out / "points.csv", rows)
        (out / "stats.json").write_text(json.dumps(stats, ensure_ascii=False, indent=2), encoding="utf8")
        index.append({"encoder": enc, "out": str(out), "plots": paths, **{k: stats[k] for k in (
            "n", "spearman", "mae", "human_mean", "pred_mean", "bias_pred_minus_human"
        )}})
        print(json.dumps({"encoder": enc, "stats": stats, "plots": paths}, ensure_ascii=False, indent=2))
    (OUT / "dist_plots" / "index.json").write_text(json.dumps(index, ensure_ascii=False, indent=2), encoding="utf8")
    print("INDEX", json.dumps(index, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

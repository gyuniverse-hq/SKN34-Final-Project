"""Distillation check: learn lip naturalness from Astra (OpenAI) labels, test on R5 human labels.

Astra scored new expansion_v3_openai_pool images with the v2 rubric. A frozen ResNet18 + Ridge head
is trained on those labels only, then evaluated on data Astra never saw:
  - R5 checklist absolute scores (98 images, packs 01-03)
  - R5 same-face A/B choices (v3 ab_pack, decisive pairs)

  python learn_astra.py embed
  python learn_astra.py fit
  python learn_astra.py all

Run with the ML venv (torch + torchvision + sklearn):
  ml/.venv/Scripts/python.exe research/lip_rubric/learn_astra.py all
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np

from common import DATA, HERE, checks, load_json, read_csv, score, sha256
from learn import OUT as R5_OUT
from learn import SEED, _emb_map, _group_folds, _load_encoder

ASTRA = DATA / "astra"
POOL = DATA / "expansion_v3_openai_pool"
OUT = DATA / "learn_astra"
ALPHAS = (1.0, 10.0, 100.0, 1000.0, 3000.0, 10000.0, 30000.0)
MATTE_NA = ("q3_2", "q3_3", "q3_4")


def load_astra() -> list[dict]:
    rubric = load_json(HERE / "rubric.json")
    ids = [c["id"] for c in checks(rubric)]
    key = {r["image_id"]: r for r in read_csv(POOL / "key.csv")}
    rows = []
    for r in read_csv(ASTRA / "ratings.csv"):
        k = key.get(r["image_id"])
        if k is None:
            raise ValueError(f"{r['image_id']}: not in pool key.csv")
        answers = {c: r[c] for c in ids}
        if k["finish"] == "matte":
            answers.update({c: "na" for c in MATTE_NA})
        rows.append({
            "image_id": r["image_id"],
            "face_id": k["face_id"],
            "kind": k["kind"],
            "finish": k["finish"],
            "variant": k["variant"],
            "human_label": k["human_label"],
            "total": score(rubric, answers, k["finish"])["total"],
            "overall": float(r["overall"]),
            "crop_path": str(POOL / "images" / f"{r['image_id']}_crop.png"),
        })
    return rows


ENCODERS = ("resnet18", "efficientnet_b0", "efficientnet_b3", "convnext_tiny", "dinov2_vits14")


def load_encoder(name: str, device: str):
    if name == "resnet18":
        return _load_encoder(device)
    import torch
    from torchvision import models

    if name == "efficientnet_b0":
        weights = models.EfficientNet_B0_Weights.IMAGENET1K_V1
        model = models.efficientnet_b0(weights=weights)
        model.classifier = torch.nn.Identity()
        transform = weights.transforms()
    elif name == "efficientnet_b3":
        weights = models.EfficientNet_B3_Weights.IMAGENET1K_V1
        model = models.efficientnet_b3(weights=weights)
        model.classifier = torch.nn.Identity()
        transform = weights.transforms()
    elif name == "convnext_tiny":
        weights = models.ConvNeXt_Tiny_Weights.IMAGENET1K_V1
        model = models.convnext_tiny(weights=weights)
        model.classifier[-1] = torch.nn.Identity()
        transform = weights.transforms()
    elif name == "dinov2_vits14":
        # Apache-2.0 weights via torch.hub (research-only; not shipped in the app).
        from torchvision import transforms as TR

        model = torch.hub.load("facebookresearch/dinov2", "dinov2_vits14", trust_repo=True)
        transform = TR.Compose([
            TR.Resize(256, antialias=True),
            TR.CenterCrop(224),
            TR.ToTensor(),
            TR.Normalize(mean=(0.485, 0.456, 0.406), std=(0.229, 0.224, 0.225)),
        ])
    else:
        raise ValueError(f"unknown encoder {name}; choose from {ENCODERS}")
    model.eval().requires_grad_(False).to(device)
    return model, transform


def embedding_paths(encoder: str) -> tuple[Path, Path]:
    """(Astra pool, R5 checklist + A/B) embedding files for one encoder."""
    if encoder == "resnet18":
        return OUT / "astra_embeddings.npz", R5_OUT / "embeddings.npz"
    return OUT / f"astra_{encoder}.npz", OUT / f"r5_{encoder}.npz"


def _embed_rows(rows, path, encoder, device):
    import torch
    from PIL import Image

    model, transform = load_encoder(encoder, device)
    ids, vecs = [], []
    with torch.inference_mode():
        for n, (image_id, crop) in enumerate(rows):
            image = Image.open(crop).convert("RGB")
            feat = model(transform(image).unsqueeze(0).to(device))[0].float().cpu().numpy()
            ids.append(image_id)
            vecs.append(feat / (np.linalg.norm(feat) + 1e-9))
            if (n + 1) % 200 == 0:
                print(f"embedded {n + 1}/{len(rows)}", flush=True)
    path.parent.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(path, image_ids=np.array(ids), embeddings=np.stack(vecs).astype(np.float32))
    print(json.dumps({"n": len(ids), "encoder": encoder, "device": device, "path": str(path)}))


def embed(encoder: str = "resnet18", device: str | None = None) -> None:
    import torch

    device = device or ("cuda" if torch.cuda.is_available() else "cpu")
    astra_path, r5_path = embedding_paths(encoder)
    _embed_rows([(r["image_id"], r["crop_path"]) for r in load_astra()], astra_path, encoder, device)
    if not r5_path.exists():
        r5_rows = [(r["image_id"], r["crop_path"]) for r in read_csv(R5_OUT / "image_index.csv")]
        _embed_rows(r5_rows, r5_path, encoder, device)


def _ridge(alpha):
    from sklearn.linear_model import Ridge
    from sklearn.pipeline import make_pipeline
    from sklearn.preprocessing import StandardScaler

    return make_pipeline(StandardScaler(), Ridge(alpha=alpha))


def _spearman(a, b):
    from scipy.stats import spearmanr

    rho = spearmanr(a, b).correlation
    return None if rho != rho else round(float(rho), 4)


def _bootstrap_ci(y, p, groups, n=2000):
    """Face-level bootstrap CI for Spearman."""
    rng = np.random.default_rng(SEED)
    faces = np.unique(groups)
    index = {f: np.flatnonzero(groups == f) for f in faces}
    stats = []
    for _ in range(n):
        pick = np.concatenate([index[f] for f in rng.choice(faces, len(faces))])
        rho = _spearman(y[pick], p[pick])
        if rho is not None:
            stats.append(rho)
    return [round(float(np.percentile(stats, 2.5)), 4), round(float(np.percentile(stats, 97.5)), 4)]


def _ab_accuracy(model, emb):
    pairs = [r for r in read_csv(R5_OUT / "pairs.csv") if float(r["pref_left"]) != 0.5]
    pairs = [r for r in pairs if r["left"] in emb and r["right"] in emb]
    left = model.predict(np.stack([emb[r["left"]] for r in pairs]))
    right = model.predict(np.stack([emb[r["right"]] for r in pairs]))
    truth = np.array([float(r["pref_left"]) > 0.5 for r in pairs])
    correct = (left > right) == truth
    return {"pairs": len(pairs), "accuracy": round(float(correct.mean()), 4)}


def fit(encoder: str = "resnet18") -> dict:
    astra = load_astra()
    astra_path, r5_path = embedding_paths(encoder)
    a_emb = _emb_map(astra_path)
    r_emb = _emb_map(r5_path)
    r5 = read_csv(R5_OUT / "labels_absolute.csv")

    Xa = np.stack([a_emb[r["image_id"]] for r in astra])
    fa = np.array([r["face_id"] for r in astra])
    Xr = np.stack([r_emb[r["image_id"]] for r in r5])
    yr = np.array([float(r["total"]) for r in r5])
    fr = np.array([r["face_id"] for r in r5])
    kr = np.array([r["kind"] for r in r5])

    results = {"encoder": encoder, "astra_n": len(astra), "astra_faces": int(len(set(fa))), "r5_n": len(r5), "targets": {}}
    for target in ("total", "overall"):
        ya = np.array([float(r[target]) for r in astra])
        folds, _ = _group_folds(fa.tolist(), 5, SEED)
        cv = {}
        for alpha in ALPHAS:
            pred = np.zeros_like(ya)
            for tr, te in folds:
                pred[te] = _ridge(alpha).fit(Xa[tr], ya[tr]).predict(Xa[te])
            cv[alpha] = _spearman(ya, pred)
        alpha = max(cv, key=lambda a: cv[a])
        model = _ridge(alpha).fit(Xa, ya)
        pr = model.predict(Xr)
        by_kind = {
            k: {"n": int((kr == k).sum()), "label_mean": round(float(yr[kr == k].mean()), 3),
                "pred_mean": round(float(pr[kr == k].mean()), 3)}
            for k in sorted(set(kr.tolist()))
        }
        render = kr == "render"
        kind_order = [k for k, _ in sorted(by_kind.items(), key=lambda kv: kv[1]["pred_mean"])]
        label_order = [k for k, _ in sorted(by_kind.items(), key=lambda kv: kv[1]["label_mean"])]
        results["targets"][target] = {
            "astra_label_mean": round(float(ya.mean()), 3),
            "alpha": alpha,
            "astra_cv_spearman": cv[alpha],
            "r5_spearman": _spearman(yr, pr),
            "r5_spearman_ci": _bootstrap_ci(yr, pr, fr),
            "r5_mae": round(float(np.mean(np.abs(yr - pr))), 4),
            "r5_render_spearman": _spearman(yr[render], pr[render]),
            "r5_render_mae": round(float(np.mean(np.abs(yr[render] - pr[render]))), 4),
            "r5_by_kind": by_kind,
            "kind_order_pred": kind_order,
            "kind_order_label": label_order,
            "kind_order_ok": kind_order == label_order,
        }

    # R5-only baseline and Astra + R5 combined, both evaluated on held-out R5 faces.
    ya_total = np.array([r["total"] for r in astra])
    r5_folds, _ = _group_folds(fr.tolist(), 5, SEED)
    alpha = results["targets"]["total"]["alpha"]
    only, both = np.zeros_like(yr), np.zeros_like(yr)
    for tr, te in r5_folds:
        only[te] = _ridge(10.0).fit(Xr[tr], yr[tr]).predict(Xr[te])
        X = np.vstack([Xa, Xr[tr]])
        y = np.concatenate([ya_total, yr[tr]])
        both[te] = _ridge(alpha).fit(X, y).predict(Xr[te])
    results["r5_only_cv_spearman"] = _spearman(yr, only)
    results["astra_plus_r5_cv_spearman"] = _spearman(yr, both)
    results["inputs"] = {"astra_ratings_sha256": sha256(ASTRA / "ratings.csv"), "pool_key_sha256": sha256(POOL / "key.csv")}

    OUT.mkdir(parents=True, exist_ok=True)
    name = "fit_summary.json" if encoder == "resnet18" else f"fit_summary_{encoder}.json"
    (OUT / name).write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf8")
    print(json.dumps(results, ensure_ascii=False, indent=2))
    return results


def score_card(results: dict) -> dict:
    """Absolute-score metrics only (A/B ignored)."""
    t = results["targets"]["total"]
    return {
        "encoder": results["encoder"],
        "r5_spearman": t["r5_spearman"],
        "r5_spearman_ci": t["r5_spearman_ci"],
        "r5_mae": t["r5_mae"],
        "r5_render_spearman": t["r5_render_spearman"],
        "r5_render_mae": t["r5_render_mae"],
        "kind_order_ok": t["kind_order_ok"],
        "kind_order_pred": t["kind_order_pred"],
        "astra_cv_spearman": t["astra_cv_spearman"],
        "r5_only_cv_spearman": results.get("r5_only_cv_spearman"),
    }


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("command", choices=("embed", "fit", "all"))
    p.add_argument("--encoder", choices=ENCODERS, default="resnet18")
    p.add_argument("--device", default=None)
    a = p.parse_args(argv)
    if a.command in ("embed", "all"):
        embed(a.encoder, a.device)
    if a.command in ("fit", "all"):
        results = fit(a.encoder)
        print("SCORE_CARD", json.dumps(score_card(results), ensure_ascii=False))


if __name__ == "__main__":
    main()

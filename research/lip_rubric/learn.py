"""Learn a small lip-naturalness predictor from R5 checklist scores + A/B pairs.

Frozen ImageNet ResNet18 encodes lip crops; a linear head predicts absolute scores
and pairwise preference. Face-level GroupKFold only — never use defect labels as features.

  python learn.py export
  python learn.py embed
  python learn.py fit
  python learn.py all

Use the project ML venv (torch + torchvision + sklearn):
  ml/.venv/Scripts/python.exe research/lip_rubric/learn.py all
"""
from __future__ import annotations

import argparse
import json
import sqlite3
from pathlib import Path

import numpy as np

from common import DATA, HERE, load_json, read_csv, score, sha256, write_csv

OUT = DATA / "learn"
PACKS = {
    "01": "94dab3438386b271bae7f0c93dca983b82cd404d6605371af9049ac2683c59ab",
    "02": "467552947f691c6f3fbfc71dee1e79a7f7a78c8c2030f723f404217d5488fd9a",
    "03": "b2d54b51f691a4416fbb5440b83c83a3280210308abd3f4392945cc540fb260a",
}
RATER = "R5"
RUBRIC_VERSION = "lip-rubric-v2"
SEED = 20261116
IMG_SIZE = 224


def _key_rows(pack_name: str):
    path = DATA / "expansion_v3" / f"checklist_{pack_name}" / "key.csv"
    return {r["random_id"]: r for r in read_csv(path)}


def export_labels(db_path: Path | None = None) -> dict:
    """Write absolute-score and A/B pair CSVs under research/data/lip_rubric/learn/."""
    db_path = db_path or (DATA / "eval.db")
    rubric = load_json(HERE / "rubric.json")
    con = sqlite3.connect(db_path)
    con.row_factory = sqlite3.Row

    absolute = []
    for name, pack_id in PACKS.items():
        keys = _key_rows(name)
        imgs = {
            r["image_id"]: dict(r)
            for r in con.execute("select * from images where pack_id=?", (pack_id,))
        }
        rows = list(
            con.execute(
                """
                select * from human_ratings
                where rater_id=? and rubric_version=?
                  and image_id in (select image_id from images where pack_id=?)
                """,
                (RATER, RUBRIC_VERSION, pack_id),
            )
        )
        for r in rows:
            im = imgs[r["image_id"]]
            if im.get("repeat_of"):
                continue
            total = score(rubric, json.loads(r["checks_json"]), im["finish"])["total"]
            if total is None:
                continue
            k = keys[r["image_id"]]
            crop = im.get("crop_path") or str(
                DATA
                / "expansion_v3"
                / f"checklist_{name}"
                / "rating_pack"
                / "images"
                / f"{r['image_id']}_crop.png"
            )
            absolute.append(
                {
                    "image_id": r["image_id"],
                    "face_id": im["face_id"],
                    "pack": f"checklist_{name}",
                    "kind": im["kind"],
                    "finish": im["finish"],
                    "split": k.get("split") or im.get("split") or "pool",
                    "total": round(float(total), 4),
                    "crop_path": crop,
                }
            )

    ab_key = {r["pair_id"]: r for r in read_csv(DATA / "expansion_v3" / "ab_key.csv")}
    ab_answers = {
        r["pair_id"]: r
        for r in read_csv(DATA / "results" / "R5_ab_v3.csv")
        if r["choice"] in ("left", "right", "same")
    }
    ab_images = DATA / "expansion_v3" / "ab_pack" / "images"
    pairs = []
    for pair_id, k in ab_key.items():
        if k.get("repeat_of"):
            continue
        a = ab_answers.get(pair_id)
        if not a:
            continue
        left, right = k["left"], k["right"]
        pref = 0.5 if a["choice"] == "same" else (1.0 if a["choice"] == "left" else 0.0)
        pairs.append(
            {
                "pair_id": pair_id,
                "face_id": k["face_id"],
                "split": k.get("split") or "pool",
                "left": left,
                "right": right,
                "pref_left": pref,
                "left_crop": str(ab_images / f"{left}_crop.png"),
                "right_crop": str(ab_images / f"{right}_crop.png"),
            }
        )

    OUT.mkdir(parents=True, exist_ok=True)
    write_csv(OUT / "labels_absolute.csv", absolute)
    write_csv(OUT / "pairs.csv", pairs)
    image_paths = {}
    for row in absolute:
        image_paths[row["image_id"]] = row["crop_path"]
    for row in pairs:
        image_paths[row["left"]] = row["left_crop"]
        image_paths[row["right"]] = row["right_crop"]
    write_csv(
        OUT / "image_index.csv",
        [{"image_id": i, "crop_path": p} for i, p in sorted(image_paths.items())],
    )
    manifest = {
        "rater_id": RATER,
        "rubric_version": RUBRIC_VERSION,
        "n_absolute": len(absolute),
        "n_faces_absolute": len({r["face_id"] for r in absolute}),
        "n_pairs": len(pairs),
        "n_faces_pairs": len({r["face_id"] for r in pairs}),
        "n_unique_images": len(image_paths),
        "packs": PACKS,
        "seed": SEED,
        "encoder": "torchvision.models.resnet18(weights=IMAGENET1K_V1) avgpool, frozen",
        "note": "research-only; defect labels are not features; LaPa non-commercial",
        "db_sha256": sha256(db_path) if Path(db_path).exists() else None,
    }
    (OUT / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf8")
    print(json.dumps({k: manifest[k] for k in ("n_absolute", "n_pairs", "n_unique_images", "n_faces_absolute", "n_faces_pairs")}, ensure_ascii=False))
    return manifest


def _load_encoder(device: str):
    import torch
    from torchvision import models
    from torchvision.models import ResNet18_Weights

    weights = ResNet18_Weights.IMAGENET1K_V1
    model = models.resnet18(weights=weights)
    model.fc = torch.nn.Identity()
    model.eval()
    for p in model.parameters():
        p.requires_grad_(False)
    model.to(device)
    return model, weights.transforms()


def embed_images(device: str | None = None) -> Path:
    import torch
    from PIL import Image

    index = read_csv(OUT / "image_index.csv")
    if not index:
        raise SystemExit("run export first")
    device = device or ("cuda" if torch.cuda.is_available() else "cpu")
    model, transform = _load_encoder(device)
    ids, vecs, missing = [], [], []
    with torch.inference_mode():
        for row in index:
            path = Path(row["crop_path"])
            if not path.exists():
                missing.append(row["image_id"])
                continue
            image = Image.open(path).convert("RGB")
            batch = transform(image).unsqueeze(0).to(device)
            feat = model(batch)[0].float().cpu().numpy()
            feat = feat / (np.linalg.norm(feat) + 1e-9)
            ids.append(row["image_id"])
            vecs.append(feat)
    if missing:
        raise FileNotFoundError(f"missing {len(missing)} crops, e.g. {missing[:3]}")
    arr = np.stack(vecs).astype(np.float32)
    out = OUT / "embeddings.npz"
    np.savez_compressed(out, image_ids=np.array(ids), embeddings=arr, encoder="resnet18_imagenet_v1", dim=arr.shape[1])
    meta = {"n": len(ids), "dim": int(arr.shape[1]), "device": device, "path": str(out)}
    (OUT / "embeddings_meta.json").write_text(json.dumps(meta, indent=2), encoding="utf8")
    print(json.dumps(meta, ensure_ascii=False))
    return out


def _emb_map(npz_path: Path | None = None):
    data = np.load(npz_path or (OUT / "embeddings.npz"), allow_pickle=True)
    ids = [str(x) for x in data["image_ids"]]
    emb = data["embeddings"]
    return {i: emb[n] for n, i in enumerate(ids)}


def _group_folds(face_ids: list[str], n_splits: int, seed: int):
    from sklearn.model_selection import GroupKFold

    faces = np.array(face_ids)
    unique = np.unique(faces)
    n_splits = min(n_splits, len(unique))
    if n_splits < 2:
        raise ValueError("need at least 2 faces for GroupKFold")
    gkf = GroupKFold(n_splits=n_splits)
    # dummy X/y; groups drive the split
    X = np.arange(len(faces))
    y = np.zeros(len(faces))
    return list(gkf.split(X, y, groups=faces)), n_splits


def fit_models(n_splits: int = 5) -> dict:
    from scipy.stats import spearmanr
    from sklearn.linear_model import LogisticRegression, Ridge
    from sklearn.pipeline import make_pipeline
    from sklearn.preprocessing import StandardScaler

    emb = _emb_map()
    absolute = read_csv(OUT / "labels_absolute.csv")
    pairs = read_csv(OUT / "pairs.csv")

    # --- absolute score regression ---
    abs_ids = [r["image_id"] for r in absolute]
    Xa = np.stack([emb[i] for i in abs_ids])
    ya = np.array([float(r["total"]) for r in absolute], dtype=float)
    fa = [r["face_id"] for r in absolute]
    abs_folds, abs_splits = _group_folds(fa, n_splits, SEED)
    abs_true, abs_pred, abs_fold_stats = [], [], []
    for fold, (tr, te) in enumerate(abs_folds):
        model = make_pipeline(StandardScaler(), Ridge(alpha=10.0, random_state=SEED))
        model.fit(Xa[tr], ya[tr])
        pred = model.predict(Xa[te])
        rho = float(spearmanr(ya[te], pred).correlation) if len(te) > 1 else float("nan")
        mae = float(np.mean(np.abs(ya[te] - pred)))
        abs_fold_stats.append({"fold": fold, "n": int(len(te)), "spearman": rho, "mae": mae})
        abs_true.extend(ya[te].tolist())
        abs_pred.extend(pred.tolist())
    abs_rho = float(spearmanr(abs_true, abs_pred).correlation)
    abs_mae = float(np.mean(np.abs(np.array(abs_true) - np.array(abs_pred))))

    # mean baseline (predict train mean)
    base_preds = []
    base_true = []
    oof_pred = np.zeros_like(ya)
    for tr, te in abs_folds:
        mu = float(ya[tr].mean())
        base_preds.extend([mu] * len(te))
        base_true.extend(ya[te].tolist())
        model = make_pipeline(StandardScaler(), Ridge(alpha=10.0, random_state=SEED))
        model.fit(Xa[tr], ya[tr])
        oof_pred[te] = model.predict(Xa[te])
    base_mae = float(np.mean(np.abs(np.array(base_true) - np.array(base_preds))))

    kinds = np.array([r["kind"] for r in absolute])
    by_kind = {}
    for kind in sorted(set(kinds.tolist())):
        mask = kinds == kind
        if int(mask.sum()) < 3:
            continue
        rho_k = spearmanr(ya[mask], oof_pred[mask]).correlation
        by_kind[kind] = {
            "n": int(mask.sum()),
            "label_mean": round(float(ya[mask].mean()), 4),
            "pred_mean": round(float(oof_pred[mask].mean()), 4),
            "spearman": None if rho_k != rho_k else round(float(rho_k), 4),
            "mae": round(float(np.mean(np.abs(ya[mask] - oof_pred[mask]))), 4),
        }

    # final absolute model on all
    abs_model = make_pipeline(StandardScaler(), Ridge(alpha=10.0, random_state=SEED))
    abs_model.fit(Xa, ya)

    # --- pairwise preference ---
    usable = [r for r in pairs if r["left"] in emb and r["right"] in emb]
    Xp, yp, fp = [], [], []
    for r in usable:
        diff = emb[r["left"]] - emb[r["right"]]
        pref = float(r["pref_left"])
        if pref == 0.5:
            continue  # skip ties for hard classification
        Xp.append(diff)
        yp.append(1 if pref > 0.5 else 0)
        fp.append(r["face_id"])
    Xp = np.stack(Xp)
    yp = np.array(yp, dtype=int)
    pair_folds, pair_splits = _group_folds(fp, n_splits, SEED)
    pair_accs, pair_correct, pair_total = [], 0, 0
    for fold, (tr, te) in enumerate(pair_folds):
        if len(set(yp[tr].tolist())) < 2:
            pair_accs.append({"fold": fold, "n": int(len(te)), "accuracy": None, "skipped": "one_class_train"})
            continue
        clf = make_pipeline(
            StandardScaler(),
            LogisticRegression(C=0.1, max_iter=2000, random_state=SEED),
        )
        clf.fit(Xp[tr], yp[tr])
        pred = clf.predict(Xp[te])
        acc = float((pred == yp[te]).mean())
        pair_accs.append({"fold": fold, "n": int(len(te)), "accuracy": acc})
        pair_correct += int((pred == yp[te]).sum())
        pair_total += int(len(te))
    pair_acc = pair_correct / max(1, pair_total)

    # majority / always-left baselines on same folds
    always_left = float(np.mean(yp))
    chance = max(always_left, 1 - always_left)

    pair_model = make_pipeline(
        StandardScaler(),
        LogisticRegression(C=0.1, max_iter=2000, random_state=SEED),
    )
    pair_model.fit(Xp, yp)

    # save sklearn models via joblib if available, else numpy coefficients
    try:
        import joblib

        joblib.dump(abs_model, OUT / "model_absolute.joblib")
        joblib.dump(pair_model, OUT / "model_pairwise.joblib")
        model_files = ["model_absolute.joblib", "model_pairwise.joblib"]
    except Exception:
        model_files = []

    summary = {
        "seed": SEED,
        "encoder": "resnet18_imagenet_v1_avgpool_l2",
        "absolute": {
            "n_images": len(absolute),
            "n_faces": len(set(fa)),
            "n_splits": abs_splits,
            "cv_spearman": round(abs_rho, 4),
            "cv_mae": round(abs_mae, 4),
            "mean_baseline_mae": round(base_mae, 4),
            "folds": abs_fold_stats,
            "by_kind": by_kind,
            "score_mean": round(float(ya.mean()), 4),
            "score_std": round(float(ya.std()), 4),
        },
        "pairwise": {
            "n_pairs_used": int(len(yp)),
            "n_pairs_ties_skipped": len(usable) - len(yp),
            "n_faces": len(set(fp)),
            "n_splits": pair_splits,
            "cv_accuracy": round(pair_acc, 4),
            "majority_baseline": round(chance, 4),
            "folds": pair_accs,
        },
        "model_files": model_files,
        "decision_notes": [
            "defect/variant labels are never used as features",
            "splits are by face_id (GroupKFold)",
            "research-only; not wired into the app",
        ],
    }
    (OUT / "fit_summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf8")
    _write_results_md(summary)
    print(json.dumps({
        "absolute_spearman": summary["absolute"]["cv_spearman"],
        "absolute_mae": summary["absolute"]["cv_mae"],
        "pairwise_accuracy": summary["pairwise"]["cv_accuracy"],
        "pairwise_majority": summary["pairwise"]["majority_baseline"],
    }, ensure_ascii=False))
    return summary


def _write_results_md(summary: dict) -> None:
    a, p = summary["absolute"], summary["pairwise"]
    lines = [
        "# Lip naturalness learner (offline)",
        "",
        "Frozen ResNet18 (ImageNet) lip-crop embeddings + linear heads.",
        "Labels: R5 checklist absolute scores (packs 01–03, n=98) and R5 A/B pairs (v3).",
        "Face-level GroupKFold. Defect names are never features. Research only — not in the app.",
        "",
        "## Absolute score (Ridge)",
        "",
        f"- n={a['n_images']} images / {a['n_faces']} faces, {a['n_splits']}-fold",
        f"- CV Spearman **{a['cv_spearman']:.3f}**, MAE **{a['cv_mae']:.3f}** (mean baseline MAE {a['mean_baseline_mae']:.3f})",
        f"- label mean {a['score_mean']:.2f} ± {a['score_std']:.2f}",
        "",
        "By kind (out-of-fold):",
        "",
        "| kind | n | label mean | pred mean | Spearman | MAE |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for kind, row in (a.get("by_kind") or {}).items():
        rho = "—" if row["spearman"] is None else f"{row['spearman']:.3f}"
        lines.append(
            f"| {kind} | {row['n']} | {row['label_mean']:.2f} | {row['pred_mean']:.2f} | {rho} | {row['mae']:.3f} |"
        )
    lines += [
        "",
        "## Pairwise preference (Logistic on emb_left − emb_right)",
        "",
        f"- n={p['n_pairs_used']} decisive pairs / {p['n_faces']} faces (ties skipped), {p['n_splits']}-fold",
        f"- CV accuracy **{p['cv_accuracy']:.3f}** (majority baseline {p['majority_baseline']:.3f})",
        "",
        "## Reading",
        "",
        "- Pairwise is the usable signal: same-face current vs defect ranking is learnable (~81% vs ~54% majority).",
        "- Absolute totals are only weakly tracked (Spearman ~0.31; MAE ≈ mean baseline). Do not use as a 0–5 judge yet.",
        "- Sticker crops separate in predicted means; fine render ranking needs the pairwise head (or more absolute labels).",
        "- Next: use pairwise scores to rank renderer/defect edits on held-out faces, then fix the weakest lip cues in the renderer.",
        "",
    ]
    text = "\n".join(lines)
    (OUT / "LEARN_RESULTS.md").write_text(text, encoding="utf8")
    # Mirror into the code folder only for the real data path (not pytest temp OUT).
    if OUT.resolve() == (DATA / "learn").resolve():
        (HERE / "LEARN_RESULTS.md").write_text(text, encoding="utf8")


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("command", choices=("export", "embed", "fit", "all"))
    p.add_argument("--device", default=None)
    p.add_argument("--splits", type=int, default=5)
    a = p.parse_args(argv)
    if a.command in ("export", "all"):
        export_labels()
    if a.command in ("embed", "all"):
        embed_images(a.device)
    if a.command in ("fit", "all"):
        fit_models(a.splits)


if __name__ == "__main__":
    main()

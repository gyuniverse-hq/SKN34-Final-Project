"""Measure paired lip renders and make local-only sticker controls and comparison sheets.

Inputs: run_b.py renders and matching lip_texture face polygon JSON.
Outputs: research/data/ar_model_compare/b/current/ and results/b_summary.json.
Run: research/ar_evaluation/.venv/Scripts/python.exe research/ar_model_compare/analyze_b.py
"""
import csv
import json
import sys
from pathlib import Path

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "research/lip_texture"))
import metrics as M  # noqa: E402
import render as R  # noqa: E402
import sheet as S  # noqa: E402

SRC = ROOT / "research/data/lip_texture/renders/ar_model_compare_b"
OUT = ROOT / "research/data/ar_model_compare/b/current"
RESULT = ROOT / "research/ar_model_compare/results/b_summary.json"
CONFIGS = ("current", "detail", "wide", "anisotropic")
METRICS = ("L_spread", "flat_frac", "texture", "upper_lower_L", "hl_area_pct", "hl_peak", "hl_lower_frac", "tex_ratio", "tex_corr", "gl_corr")


def read(path):
    image = cv2.imread(str(path))
    if image is None:
        raise FileNotFoundError(path)
    return image


def corr(a, b):
    if np.std(a) < 1e-9 or np.std(b) < 1e-9:
        return None
    return float(np.corrcoef(a, b)[0, 1])


def values(img, bare, ng, core, upper, lower, width):
    lab = cv2.cvtColor(img.astype(np.float32) / 255, cv2.COLOR_BGR2LAB)
    L = lab[:, :, 0]
    data = L[core]
    median = float(np.median(data))
    sigma = max(0.8, 0.012 * width)
    high = L - cv2.GaussianBlur(L, (0, 0), sigma)
    weight = core.astype(np.float32)
    broad = max(1.5, 0.06 * width)
    mean = cv2.GaussianBlur(L * weight, (0, 0), broad) / np.maximum(cv2.GaussianBlur(weight, (0, 0), broad), 1e-3)
    local = L - mean
    hl = core & (local > max(5, 2 * float(local[core].std()))) & (L > np.percentile(data, 75))
    fb = M.fine(M.lum(M.to_lin(bare)))[core]
    fi = M.fine(M.lum(M.to_lin(img)))[core]
    gl_corr = None if ng is None else corr((M.lum(M.to_lin(img)) - M.lum(M.to_lin(ng)))[core], fb)
    return {"L_spread": float(np.percentile(data, 90) - np.percentile(data, 10)),
            "flat_frac": float(np.mean(np.abs(data - median) < 3)),
            "texture": float(high[core].std()),
            "upper_lower_L": float(L[upper].mean() / max(float(L[lower].mean()), 1e-3)) if upper.any() and lower.any() else None,
            "hl_area_pct": float(100 * hl.sum() / core.sum()),
            "hl_peak": float(np.percentile(data, 99) - median),
            "hl_lower_frac": float((hl & lower).sum() / hl.sum()) if hl.any() else None,
            "tex_ratio": float(fi.std() / max(fb.std(), 1e-9)), "tex_corr": corr(fi, fb), "gl_corr": gl_corr}


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    rows, complete = [], []
    for face in R.FACES:
        bare = read(SRC / f"{face}__off.png")
        info = json.loads((R.DATA / "faces" / f"{face}.json").read_text())
        outer = np.array(info["outer"], np.float32); outer[:, 0] = bare.shape[1] - 1 - outer[:, 0]
        inner = np.array(info["inner"], np.float32); inner[:, 0] = bare.shape[1] - 1 - inner[:, 0]
        shape = bare.shape[:2]
        upper = np.zeros(shape, np.uint8); lower = np.zeros(shape, np.uint8)
        cv2.fillPoly(upper, [np.round(np.concatenate((outer[:11], inner[:11][::-1]))).astype(np.int32)], 1)
        cv2.fillPoly(lower, [np.round(np.concatenate((outer[10:], outer[:1], inner[:1], inner[:9:-1]))).astype(np.int32)], 1)
        lip = np.zeros(shape, np.uint8); cv2.fillPoly(lip, [np.round(outer).astype(np.int32)], 1); cv2.fillPoly(lip, [np.round(inner).astype(np.int32)], 0)
        width = info["mouthWidthPx"]
        radius = max(1, round(width * 0.03))
        kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2 * radius + 1, 2 * radius + 1))
        cells = []
        for shade, spec in R.SHADES.items():
            base = read(SRC / f"{face}__{shade}__current.png")
            changed = np.abs(base.astype(np.int16) - bare.astype(np.int16)).sum(axis=2) > 24
            paint = changed & (lip > 0)
            core = cv2.erode(paint.astype(np.uint8), kernel) > 0
            if core.sum() < 20:
                print(f"SKIP: insufficient core for {face}/{shade}: {core.sum()} pixels")
                continue
            u, l = core & (upper > 0), core & (lower > 0)
            sticker = bare.copy(); hexv = spec["hex"].lstrip("#")
            sticker[paint] = [int(hexv[i:i+2], 16) for i in (4, 2, 0)]
            cv2.imwrite(str(OUT / f"{face}__{shade}__sticker.png"), sticker)
            entries = {"bare": bare, "sticker": sticker, **{cfg: read(SRC / f"{face}__{shade}__{cfg}.png") for cfg in CONFIGS}}
            ng = read(SRC / f"{face}__{shade}__nogloss.png")
            for name, image in entries.items():
                row = {"face": face, "shade": shade, "config": name, "core_source": "landmark_and_changed_no_ground_truth", "core_pixels": int(core.sum())}
                row.update(values(image, bare, ng if name == "current" else None, core, u, l, width)); rows.append(row)
            sl = S.crop_box(face, bare.shape[1])
            rating_dir = ROOT / "research/data/ar_model_compare/rating"
            rating_dir.mkdir(parents=True, exist_ok=True)
            for name, img in entries.items():
                cv2.imwrite(str(rating_dir / f"{face}__{shade}__{name}.png"), img[sl])
            tiles = [cv2.resize(img[sl], (300, 175), interpolation=cv2.INTER_CUBIC) for img in entries.values()]
            label = np.full((175, 130, 3), 255, np.uint8); cv2.putText(label, shade, (5, 90), cv2.FONT_HERSHEY_SIMPLEX, .48, (0, 0, 0), 1)
            cells.append(np.concatenate([label] + tiles, axis=1)); complete.append(f"{face}/{shade}")
        if cells:
            head = np.full((35, cells[0].shape[1], 3), 255, np.uint8)
            for i, name in enumerate(["bare", "sticker", *CONFIGS]): cv2.putText(head, name, (130 + i * 300 + 5, 24), cv2.FONT_HERSHEY_SIMPLEX, .6, (0, 0, 0), 1)
            cv2.imwrite(str(OUT / f"sheet_{face}.png"), np.concatenate([head] + cells))
    with (OUT / "metrics.csv").open("w", encoding="utf-8", newline="") as f:
        if rows:
            w = csv.DictWriter(f, fieldnames=rows[0].keys()); w.writeheader(); w.writerows(rows)
    summary = {"status": "exploratory_no_real_reference", "unit": "face x shade", "pairs": len(complete),
               "source": "research/data/ar_model_compare/b/current/metrics.csv", "note": "No ground-truth lip mask; landmark polygon intersected with rendered pixel change >24, then eroded 3% of lip width. gl_corr computed only for current; edge_w_pct not measured.", "medians": {}}
    for cfg in ("bare", "sticker", *CONFIGS):
        summary["medians"][cfg] = {key: float(np.median([r[key] for r in rows if r["config"] == cfg and r[key] is not None])) for key in METRICS if any(r[key] is not None for r in rows if r["config"] == cfg)}
    # A proximity-to-bare proxy only: bare lips are not real lipstick. Clip to [0, 1]
    # and omit metrics where sticker and bare have indistinguishable values.
    scores = {key: [] for key in METRICS}
    for face_shade in complete:
        face, shade = face_shade.split("/")
        pair = {r["config"]: r for r in rows if r["face"] == face and r["shade"] == shade}
        for key in METRICS:
            b, s, c = (pair[name][key] for name in ("bare", "sticker", "current"))
            if None not in (b, s, c) and abs(s-b) > 1e-9:
                scores[key].append(float(np.clip(1-abs(c-b)/abs(s-b), 0, 1)))
    summary["current_proximity_to_bare_not_realism"] = {key: {"median": float(np.median(v)), "n": len(v)} for key, v in scores.items() if v}
    RESULT.parent.mkdir(parents=True, exist_ok=True); RESULT.write_text(json.dumps(summary, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"measured {len(complete)} pairs; {OUT}; {RESULT}")


if __name__ == "__main__":
    main()

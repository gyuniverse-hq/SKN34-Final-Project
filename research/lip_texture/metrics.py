"""Lip texture metrics on render.py output, inside the lip core only (outline eroded, teeth out).

For each face x shade and each config pair "name:name_without_gloss":
  tex_ratio   std of fine relative contrast (Y / blur(Y, 3 px) - 1) in the render / the same in the bare lip
  tex_corr    correlation of that fine contrast with the bare lip's (the same wrinkles, not new ones)
  gl_corr     correlation of the gloss layer (render - render with gloss terms off) with the bare lip's fine contrast
  gl_blobs    connected pieces of the gloss layer above half its p99 (1 = one patch; more = broken by the lip's lines)
  gl_area     share of the lip core where the gloss layer is above half its p99
  gl_peak     p99 of the gloss layer in L* units
  dE_mean     CIEDE2000 between the lip-core mean colour of this config and of the first config
Run: research/ar_evaluation/.venv/Scripts/python.exe research/lip_texture/metrics.py --tag before --pairs base:nogloss
"""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "research" / "data" / "lip_texture"


def to_lin(img_bgr: np.ndarray) -> np.ndarray:
    c = img_bgr[..., ::-1].astype(np.float64) / 255.0
    return np.where(c <= 0.04045, c / 12.92, ((c + 0.055) / 1.055) ** 2.4)


def lum(lin: np.ndarray) -> np.ndarray:
    return lin @ np.array([0.2126, 0.7152, 0.0722])


def lab_of(lin_rgb: np.ndarray) -> np.ndarray:
    m = np.array([[0.4124, 0.3576, 0.1805], [0.2126, 0.7152, 0.0722], [0.0193, 0.1192, 0.9505]])
    xyz = lin_rgb @ m.T / np.array([0.95047, 1.0, 1.08883])
    f = np.where(xyz > (6 / 29) ** 3, np.cbrt(xyz), xyz / (3 * (6 / 29) ** 2) + 4 / 29)
    return np.stack([116 * f[..., 1] - 16, 500 * (f[..., 0] - f[..., 1]), 200 * (f[..., 1] - f[..., 2])], -1)


def l_star(y: np.ndarray) -> np.ndarray:
    return np.where(y > (6 / 29) ** 3, 116 * np.cbrt(y) - 16, y * (29 / 3) ** 3)


def de2000(a: np.ndarray, b: np.ndarray) -> float:
    l1, a1, b1 = a
    l2, a2, b2 = b
    c1, c2 = np.hypot(a1, b1), np.hypot(a2, b2)
    cm = (c1 + c2) / 2
    g = 0.5 * (1 - np.sqrt(cm**7 / (cm**7 + 25**7)))
    a1p, a2p = (1 + g) * a1, (1 + g) * a2
    c1p, c2p = np.hypot(a1p, b1), np.hypot(a2p, b2)
    h1p, h2p = np.degrees(np.arctan2(b1, a1p)) % 360, np.degrees(np.arctan2(b2, a2p)) % 360
    dl, dc = l2 - l1, c2p - c1p
    dh = h2p - h1p
    if c1p * c2p == 0:
        dh = 0
    elif dh > 180:
        dh -= 360
    elif dh < -180:
        dh += 360
    dH = 2 * np.sqrt(c1p * c2p) * np.sin(np.radians(dh / 2))
    lm, cmp_ = (l1 + l2) / 2, (c1p + c2p) / 2
    hs = h1p + h2p
    if c1p * c2p == 0:
        hm = hs
    elif abs(h1p - h2p) > 180:
        hm = (hs + 360) / 2 if hs < 360 else (hs - 360) / 2
    else:
        hm = hs / 2
    t = 1 - 0.17 * np.cos(np.radians(hm - 30)) + 0.24 * np.cos(np.radians(2 * hm)) + 0.32 * np.cos(np.radians(3 * hm + 6)) - 0.20 * np.cos(np.radians(4 * hm - 63))
    sl = 1 + 0.015 * (lm - 50) ** 2 / np.sqrt(20 + (lm - 50) ** 2)
    sc, sh = 1 + 0.045 * cmp_, 1 + 0.015 * cmp_ * t
    rt = -2 * np.sqrt(cmp_**7 / (cmp_**7 + 25**7)) * np.sin(np.radians(60 * np.exp(-(((hm - 275) / 25) ** 2))))
    return float(np.sqrt((dl / sl) ** 2 + (dc / sc) ** 2 + (dH / sh) ** 2 + rt * (dc / sc) * (dH / sh)))


def lip_core(face: str, shape: tuple[int, int]) -> np.ndarray:
    j = json.loads((DATA / "faces" / f"{face}.json").read_text())
    w = shape[1]
    outer = np.array(j["outer"])
    inner = np.array(j["inner"])
    outer[:, 0] = w - 1 - outer[:, 0]  # the page renders the selfie mirrored
    inner[:, 0] = w - 1 - inner[:, 0]
    m = np.zeros(shape, np.uint8)
    cv2.fillPoly(m, [outer.astype(np.int32)], 1)
    cv2.fillPoly(m, [inner.astype(np.int32)], 0)
    k = max(3, int(round(j["mouthWidthPx"] * 0.03)))
    return cv2.erode(m, np.ones((k, k), np.uint8)) > 0


def fine(y: np.ndarray) -> np.ndarray:
    return y / np.maximum(cv2.GaussianBlur(y, (0, 0), 3.0), 1e-4) - 1.0


def fine_l(lab: np.ndarray) -> np.ndarray:
    """L* above its 1.5 px blur: the lip's small lines and wet sparkles as the eye sees them."""
    return lab[..., 0] - cv2.GaussianBlur(lab[..., 0], (0, 0), 1.5)


def sparkles(lab: np.ndarray, core: np.ndarray) -> np.ndarray:
    """Small spots brighter than their 2 px surround by > 3 L* and less saturated than it (a reflection, not pigment)."""
    L = lab[..., 0]
    c = np.hypot(lab[..., 1], lab[..., 2])
    up = L - cv2.GaussianBlur(L, (0, 0), 2.0)
    desat = c < cv2.GaussianBlur(c, (0, 0), 2.0)
    return core & (up > 3.0) & desat


def corr(a: np.ndarray, b: np.ndarray) -> float:
    a, b = a - a.mean(), b - b.mean()
    return float((a * b).sum() / max(np.sqrt((a * a).sum() * (b * b).sum()), 1e-12))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--tag", required=True)
    ap.add_argument("--pairs", nargs="+", required=True, help="config:config_without_gloss")
    args = ap.parse_args()
    d = DATA / "renders" / args.tag
    rows = []
    for off in sorted(d.glob("*__off.png")):
        face = off.name.split("__")[0]
        bare = to_lin(cv2.imread(str(off)))
        core = lip_core(face, bare.shape[:2])
        yb = lum(bare)
        fb = fine(yb)[core]
        lab_b = lab_of(bare)
        flb = fine_l(lab_b)[core]
        spb = sparkles(lab_b, core)
        shades = sorted({p.name.split("__")[1] for p in d.glob(f"{face}__*__*.png")})
        for shade in shades:
            ref_lab = None
            for pair in args.pairs:
                name, ng = pair.split(":")
                rp, gp = d / f"{face}__{shade}__{name}.png", d / f"{face}__{shade}__{ng}.png"
                if not rp.exists() or not gp.exists():
                    continue
                r, g = to_lin(cv2.imread(str(rp))), to_lin(cv2.imread(str(gp)))
                yr, yg = lum(r), lum(g)
                fr = fine(yr)[core]
                layer = (l_star(yr) - l_star(yg))
                lay = layer[core]
                p99 = float(np.percentile(lay, 99))
                # Added light in linear units for the correlations: L* rises more for the same light on a darker pixel.
                lin_lay = (yr - yg)[core]
                hot = np.zeros(core.shape, np.uint8)
                hot[core & (layer > 0.5 * p99)] = 1
                n_blobs = cv2.connectedComponentsWithStats(hot, 8)[0] - 1 if p99 > 0.5 else 0
                n_blobs_big = 0
                if p99 > 0.5:
                    _, _, st, _ = cv2.connectedComponentsWithStats(hot, 8)
                    n_blobs_big = int((st[1:, cv2.CC_STAT_AREA] >= 4).sum())
                lab = lab_of(r[core].mean(0))
                ref_lab = lab if ref_lab is None else ref_lab
                lab_r = lab_of(r)
                flr = fine_l(lab_r)[core]
                spr = sparkles(lab_r, core)
                rows.append({
                    "face": face, "shade": shade, "config": name,
                    "fineL_ratio": round(float(flr.std() / max(flb.std(), 1e-6)), 3),
                    "fineL_corr": round(corr(flr, flb), 3),
                    "spark_ratio": round(float(spr.sum() / max(spb.sum(), 1)), 3),
                    "spark_same": round(float((spr & spb).sum() / max(spb.sum(), 1)), 3),
                    "tex_ratio": round(float(fr.std() / max(fb.std(), 1e-6)), 3),
                    "tex_corr": round(corr(fr, fb), 3),
                    "gl_corr": round(corr(lin_lay, fb), 3) if p99 > 0.5 else "",
                    # Inside the shine only: does it brighten on the bare lip's ridges and dim in its creases?
                    "gl_in": round(corr(lin_lay[lay > 0.2 * p99], fb[lay > 0.2 * p99]), 3) if p99 > 0.5 and (lay > 0.2 * p99).sum() > 20 else "",
                    "gl_blobs": n_blobs_big,
                    "gl_area": round(float((lay > 0.5 * p99).mean()), 3) if p99 > 0.5 else 0,
                    "gl_peak": round(p99, 2),
                    "dE_mean": round(de2000(ref_lab, lab), 2),
                })
    out = d / "metrics.csv"
    with out.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)
    # Summary: median per shade family x config.
    keys = ["fineL_ratio", "fineL_corr", "spark_ratio", "spark_same", "gl_corr", "gl_in", "gl_blobs", "gl_area", "gl_peak", "dE_mean"]
    fams = sorted({(r["shade"].split("_")[0], r["config"]) for r in rows})
    print(f"{'finish':8} {'config':12} " + " ".join(f"{k[:9]:>9}" for k in keys))
    for fam, cfg in fams:
        sel = [r for r in rows if r["shade"].startswith(fam) and r["config"] == cfg]
        vals = []
        for k in keys:
            v = [float(r[k]) for r in sel if r[k] != ""]
            vals.append(f"{np.median(v):9.3f}" if v else f"{'-':>9}")
        print(f"{fam:8} {cfg:12} " + " ".join(vals))
    print("rows", len(rows), "->", out)


if __name__ == "__main__":
    main()

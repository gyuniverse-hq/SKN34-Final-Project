"""Build a SQLite reference table of real lip texture/volume/highlight stats from Pexels & Unsplash photos.

Files live in research/data/reference/lip_texture/ (git-ignored).
Photos where MediaPipe finds a face are measured with the exact lip landmarks (same as the AR page);
macro lip close-ups where no full face is visible use a redness mask over the central region.
In pexels-mart-production-7290642.jpg the lipstick tube touches the left corner (x < 0.42 of the lip box),
so that side is masked out before measuring.
"""
from __future__ import annotations

import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
from PIL import Image, ImageFilter

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "research" / "makeup_detection"))
import build_db as bd  # noqa: E402
import mediapipe as mp  # noqa: E402
from mediapipe.tasks.python import BaseOptions, vision  # noqa: E402

REF_DIR = ROOT / "research" / "data" / "reference" / "lip_texture"
DB_PATH = REF_DIR / "lip_texture.sqlite"

CATALOG = [
    ("pexels-angela-roma-7479972.jpg", "bare", "Pexels 7479972 (Angela Roma)", "macro lip close-up"),
    ("photo-1584457361626-06effef61a7c.png", "bare", "Unsplash 1584457361626", "lower-face close-up"),
    ("pexels-15988655.jpg", "bare", "Pexels 15988655 (Alexander Krivitskiy)", "full face, natural"),
    ("pexels-3762410.jpg", "satin", "Pexels 3762410 (Shiny Diamond)", "full face, soft pink sheen"),
    ("pexels-shiny-diamond-3762442.jpg", "satin", "Pexels 3762442 (Shiny Diamond)", "lower-face, rosy balm"),
    ("pexels-mart-production-7290642.jpg", "matte", "Pexels 7290642 (MART PRODUCTION)", "tube masked on left"),
    ("pexels-7322123.jpg", "matte", "Pexels 7322123 (cottonbro studio)", "full face, deep matte"),
    ("pexels-765191.jpg", "matte", "Pexels 765191 (Min An)", "full face, brick matte"),
    ("pexels-28578570.jpg", "matte", "Pexels 28578570 (Shahin Mren)", "full face, berry matte"),
    ("pexels-29639510.jpg", "glossy", "Pexels 29639510 (Ulas Ocakli)", "full face, glossy red"),
    ("pexels-julija-sileikaite-271243221-12829921.jpg", "glossy", "Pexels 12829921 (Julija Sileikaite)", "macro gloss"),
    ("photo-1549153052-247abe00d6d9.png", "glossy", "Unsplash 1549153052", "lower-face coral gloss"),
    ("photo-1758605456769-7f3d0939f623.png", "shimmer", "Unsplash 1758605456769", "macro glitter"),
]


def stats_from_crop(crop: Image.Image, lip: np.ndarray, upper: np.ndarray | None, lower: np.ndarray | None) -> dict:
    lin = bd.srgb_to_linear(np.asarray(crop, dtype=np.float64) / 255.0)
    lum = bd.luminance(lin)
    lip_lum = lum[lip]
    med = float(np.median(lip_lum))
    q10, q25, q75, q90 = [float(v) for v in np.quantile(lip_lum / max(med, 1e-6), [0.10, 0.25, 0.75, 0.90])]
    p = np.pad(lum, 1, mode="edge")
    blur = sum(p[dy:dy + lum.shape[0], dx:dx + lum.shape[1]] for dy in range(3) for dx in range(3)) / 9
    hp = np.abs(lum - blur)[lip] / max(med, 1e-6)
    lo, hi = np.quantile(lip_lum, [0.05, 0.95])
    lab = np.median(bd.linear_to_lab(lin[lip & (lum >= lo) & (lum <= hi)]), axis=0)
    ul_ratio = None
    if upper is not None and lower is not None and upper.sum() > 50 and lower.sum() > 50:
        ul_ratio = float(np.median(lum[upper]) / max(np.median(lum[lower]), 1e-6))
    return {
        "lip_px": int(lip.sum()),
        "lip_L": float(lab[0]), "lip_C": float(np.hypot(lab[1], lab[2])),
        "shade_iqr": q75 - q25,
        "shade_90_10": q90 - q10,
        "upper_lower_ratio": ul_ratio,
        "highlight_13": float((lip_lum > 1.3 * med).mean()),
        "highlight_15": float((lip_lum > 1.5 * med).mean()),
        "peak_99": float(np.quantile(lip_lum, 0.99) / max(med, 1e-6)),
        "texture": float((lum - blur)[lip].std() / max(med, 1e-6)),
        "glint_frac": float((hp > 0.04).mean()),
    }


def measure_photo(path: Path, landmarker, mask_left: float = 0.0) -> dict:
    img = bd.load_image(path)
    rgb8 = np.asarray(img, dtype=np.uint8)
    res = landmarker.detect(mp.Image(image_format=mp.ImageFormat.SRGB, data=np.ascontiguousarray(rgb8)))
    if res.face_landmarks:
        lm = np.array([[p.x * img.width, p.y * img.height] for p in res.face_landmarks[0]])
        mouth_w = np.linalg.norm(lm[291] - lm[61])
        scale = bd.MOUTH_WIDTH_PX / max(mouth_w, 1.0)
        pad = 0.3 * mouth_w
        x0, y0 = lm[bd.LIPS_OUTER].min(0) - pad
        x1, y1 = lm[bd.LIPS_OUTER].max(0) + pad
        box = tuple(int(round(v)) for v in (max(x0, 0), max(y0, 0), min(x1, img.width), min(y1, img.height)))
        crop = img.crop(box)
        size = (max(1, round(crop.width * scale)), max(1, round(crop.height * scale)))
        crop = crop.resize(size, Image.LANCZOS)
        shift = np.array(box[:2])
        outer = (lm[bd.LIPS_OUTER] - shift) * scale
        inner = (lm[bd.LIPS_INNER] - shift) * scale
        outer_m = np.asarray(bd.polygon_mask(size, outer).filter(ImageFilter.MinFilter(5))) > 0
        inner_m = np.asarray(bd.polygon_mask(size, inner).filter(ImageFilter.MaxFilter(5))) > 0
        lip = outer_m & ~inner_m
        if mask_left > 0:
            xs = np.arange(size[0])[None, :]
            lip &= xs >= int(size[0] * mask_left)
        mid_y = float(((lm[13] + lm[14]) / 2 - shift)[1] * scale)
        yy = np.arange(size[1])[:, None]
        return {"method": "landmarks", **stats_from_crop(crop, lip, lip & (yy < mid_y), lip & (yy >= mid_y))}

    scale = 260.0 / img.width
    crop = img.resize((260, max(1, round(img.height * scale))), Image.LANCZOS)
    lin = bd.srgb_to_linear(np.asarray(crop, dtype=np.float64) / 255.0)
    lum = bd.luminance(lin)
    red = (lin[..., 0] - lin[..., 1]) / (lin.sum(-1) + 1e-4)
    h, w = lum.shape
    yy, xx = np.ogrid[:h, :w]
    central = (xx > w * 0.1) & (xx < w * 0.9) & (yy > h * 0.15) & (yy < h * 0.85)
    thr = np.quantile(red[central], 0.60)
    lip = central & (red >= thr) & (lum > np.quantile(lum[central], 0.08))
    ys = np.nonzero(lip)[0]
    mid_y = float(np.median(ys)) if len(ys) else h / 2
    return {"method": "redness_macro", **stats_from_crop(crop, lip, lip & (yy < mid_y), lip & (yy >= mid_y))}


SCHEMA = """
CREATE TABLE source (note TEXT, created_at TEXT);
CREATE TABLE photos (
  file TEXT PRIMARY KEY, finish TEXT, source TEXT, note TEXT, method TEXT, lip_px INTEGER,
  lip_L REAL, lip_C REAL, shade_iqr REAL, shade_90_10 REAL, upper_lower_ratio REAL,
  highlight_13 REAL, highlight_15 REAL, peak_99 REAL, texture REAL, glint_frac REAL);
CREATE TABLE finish_targets (
  finish TEXT PRIMARY KEY, n INTEGER,
  shade_iqr_med REAL, shade_90_10_med REAL, upper_lower_med REAL,
  highlight_13_med REAL, highlight_15_med REAL, peak_99_med REAL, texture_med REAL, glint_med REAL);
"""


def main() -> None:
    lmk = vision.FaceLandmarker.create_from_options(vision.FaceLandmarkerOptions(
        base_options=BaseOptions(model_asset_path=str(bd.MODEL)), num_faces=1))
    if DB_PATH.exists():
        DB_PATH.unlink()
    db = sqlite3.connect(DB_PATH)
    db.executescript(SCHEMA)
    db.execute("INSERT INTO source VALUES (?, ?)", (
        "Pexels & Unsplash lip texture reference (research only, git-ignored)",
        datetime.now(timezone.utc).isoformat(timespec="seconds")))

    cols = ["file", "finish", "source", "note", "method", "lip_px", "lip_L", "lip_C", "shade_iqr",
            "shade_90_10", "upper_lower_ratio", "highlight_13", "highlight_15", "peak_99", "texture", "glint_frac"]
    for fname, finish, src, note in CATALOG:
        p = REF_DIR / fname
        if not p.exists():
            print("MISSING", fname); continue
        m = measure_photo(p, lmk, mask_left=0.42 if "7290642" in fname else 0.0)
        row = {"file": fname, "finish": finish, "source": src, "note": note, **m}
        db.execute(f"INSERT INTO photos VALUES ({','.join('?' * len(cols))})", [row[c] for c in cols])

    for finish in ["bare", "matte", "satin", "glossy", "shimmer"]:
        rows = db.execute("""SELECT shade_iqr, shade_90_10, upper_lower_ratio, highlight_13, highlight_15,
                             peak_99, texture, glint_frac FROM photos WHERE finish = ?""", (finish,)).fetchall()
        if not rows:
            continue
        arr = np.array([[np.nan if v is None else v for v in r] for r in rows], dtype=float)
        meds = [float(np.nanmedian(arr[:, i])) for i in range(arr.shape[1])]
        db.execute("INSERT INTO finish_targets VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", (finish, len(rows), *meds))
    db.commit()

    print(f"{'file':44s} {'finish':7s} {'method':13s} {'iqr':>5s} {'90-10':>5s} {'U/L':>5s} {'hl13':>6s} {'tex':>6s} {'glint':>6s}")
    for r in db.execute("SELECT file, finish, method, shade_iqr, shade_90_10, upper_lower_ratio, highlight_13, texture, glint_frac FROM photos"):
        print(f"{r[0][:44]:44s} {r[1]:7s} {r[2]:13s} {r[3]:5.2f} {r[4]:5.2f} {(r[5] or 0):5.2f} {r[6]:6.3f} {r[7]:6.4f} {r[8]:6.3f}")
    print("\n=== TARGET MEDIANS BY FINISH ===")
    print(f"{'finish':8s} {'n':>2s} {'shade_iqr':>9s} {'90-10':>7s} {'U/L':>6s} {'hl>1.3':>8s} {'hl>1.5':>8s} {'texture':>8s} {'glint':>7s}")
    for r in db.execute("SELECT * FROM finish_targets"):
        print(f"{r[0]:8s} {r[1]:2d} {r[2]:9.2f} {r[3]:7.2f} {r[4]:6.2f} {r[5]:8.3f} {r[6]:8.3f} {r[7]:8.4f} {r[8]:7.3f}")
    db.close()


if __name__ == "__main__":
    main()

"""Kaggle "Makeup Detection Face Dataset" -> lip measurements in SQLite (research only).

Source: https://www.kaggle.com/datasets/tapakah68/makeup-detection-dataset (CC BY-NC-ND 4.0).
Images stay in research/data/ (git-ignored) and are never copied into the DB or the app (AR_SPEC 1-13).
The pairs are not shot under controlled light, so use them for the direction of change
(darker? more saturated? less texture?), not as ground truth for a1 or color.

Usage:
  python research/makeup_detection/build_db.py --zip <archive.zip>
  python research/makeup_detection/build_db.py --dir <extracted folder>
"""
from __future__ import annotations

import argparse
import csv
import sqlite3
import zipfile
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageOps

import mediapipe as mp
from mediapipe.tasks.python import BaseOptions, vision

ROOT = Path(__file__).resolve().parents[2]
OUT_DIR = ROOT / "research" / "data" / "reference" / "makeup_detection"
MODEL = ROOT / "research" / "data" / "models" / "face_landmarker.task"
DB_PATH = OUT_DIR / "makeup_detection.sqlite"

SOURCE = {
    "name": "Makeup Detection Face Dataset (Kaggle, tapakah68)",
    "url": "https://www.kaggle.com/datasets/tapakah68/makeup-detection-dataset",
    "license": "CC BY-NC-ND 4.0",
    "note": "Research reference only. No redistribution of images or derived images.",
}

# Same landmark loops as components/ar/faceTrackerHtml.ts.
LIPS_OUTER = [61, 185, 40, 39, 37, 0, 267, 269, 270, 409, 291, 375, 321, 405, 314, 17, 84, 181, 91, 146]
LIPS_INNER = [78, 191, 80, 81, 82, 13, 312, 311, 310, 415, 308, 324, 318, 402, 317, 14, 87, 178, 88, 95]
CHEEKS = [(50, 116, 205), (280, 345, 425)]
MOUTH_WIDTH_PX = 200        # lips are rescaled to this corner-to-corner width before measuring texture
TRIM = 0.05                 # drop darkest and brightest 5% of lip pixels for the representative color
HIGHLIGHT_RATIO = 1.3       # = TUNING.diffuseCap: brighter than this × lip median counts as highlight


# --- color (same formulas as the app: exact sRGB EOTF, D65, CIEDE2000) ---

def srgb_to_linear(c: np.ndarray) -> np.ndarray:
    return np.where(c <= 0.04045, c / 12.92, ((c + 0.055) / 1.055) ** 2.4)


def linear_to_lab(rgb: np.ndarray) -> np.ndarray:
    m = np.array([[0.4124564, 0.3575761, 0.1804375],
                  [0.2126729, 0.7151522, 0.0721750],
                  [0.0193339, 0.1191920, 0.9503041]])
    xyz = rgb @ m.T / np.array([0.95047, 1.0, 1.08883])
    f = np.where(xyz > (6 / 29) ** 3, np.cbrt(xyz), xyz / (3 * (6 / 29) ** 2) + 4 / 29)
    return np.stack([116 * f[..., 1] - 16, 500 * (f[..., 0] - f[..., 1]), 200 * (f[..., 1] - f[..., 2])], -1)


def luminance(rgb: np.ndarray) -> np.ndarray:
    return rgb @ np.array([0.2126, 0.7152, 0.0722])


def delta_e2000(lab1, lab2) -> float:
    L1, a1, b1 = lab1
    L2, a2, b2 = lab2
    C1, C2 = np.hypot(a1, b1), np.hypot(a2, b2)
    Cb7 = ((C1 + C2) / 2) ** 7
    G = 0.5 * (1 - np.sqrt(Cb7 / (Cb7 + 25 ** 7)))
    a1p, a2p = a1 * (1 + G), a2 * (1 + G)
    C1p, C2p = np.hypot(a1p, b1), np.hypot(a2p, b2)
    h1p = np.degrees(np.arctan2(b1, a1p)) % 360 if C1p else 0.0
    h2p = np.degrees(np.arctan2(b2, a2p)) % 360 if C2p else 0.0
    dLp, dCp = L2 - L1, C2p - C1p
    dh = h2p - h1p
    if C1p * C2p == 0:
        dh = 0.0
    elif dh > 180:
        dh -= 360
    elif dh < -180:
        dh += 360
    dHp = 2 * np.sqrt(C1p * C2p) * np.sin(np.radians(dh / 2))
    Lbp, Cbp = (L1 + L2) / 2, (C1p + C2p) / 2
    if C1p * C2p == 0:
        hbp = h1p + h2p
    elif abs(h1p - h2p) <= 180:
        hbp = (h1p + h2p) / 2
    else:
        hbp = (h1p + h2p + 360) / 2 if h1p + h2p < 360 else (h1p + h2p - 360) / 2
    T = (1 - 0.17 * np.cos(np.radians(hbp - 30)) + 0.24 * np.cos(np.radians(2 * hbp))
         + 0.32 * np.cos(np.radians(3 * hbp + 6)) - 0.20 * np.cos(np.radians(4 * hbp - 63)))
    dTheta = 30 * np.exp(-(((hbp - 275) / 25) ** 2))
    Rc = 2 * np.sqrt(Cbp ** 7 / (Cbp ** 7 + 25 ** 7))
    Sl = 1 + 0.015 * (Lbp - 50) ** 2 / np.sqrt(20 + (Lbp - 50) ** 2)
    Sc, Sh = 1 + 0.045 * Cbp, 1 + 0.015 * Cbp * T
    Rt = -np.sin(np.radians(2 * dTheta)) * Rc
    return float(np.sqrt((dLp / Sl) ** 2 + (dCp / Sc) ** 2 + (dHp / Sh) ** 2 + Rt * (dCp / Sc) * (dHp / Sh)))


# --- measurement ---

def polygon_mask(size, pts) -> Image.Image:
    m = Image.new("L", size, 0)
    ImageDraw.Draw(m).polygon([tuple(p) for p in pts], fill=255)
    return m


def measure(img: Image.Image, landmarker) -> dict:
    rgb8 = np.asarray(img, dtype=np.uint8)
    result = landmarker.detect(mp.Image(image_format=mp.ImageFormat.SRGB, data=np.ascontiguousarray(rgb8)))
    out = {"width": img.width, "height": img.height, "face_found": 0}
    if not result.face_landmarks:
        return out
    lm = np.array([[p.x * img.width, p.y * img.height] for p in result.face_landmarks[0]])
    out["face_found"] = 1

    # Normalize scale: crop around the lips and resize to a fixed mouth width.
    mouth_w = np.linalg.norm(lm[291] - lm[61])
    scale = MOUTH_WIDTH_PX / max(mouth_w, 1.0)
    pad = 0.3 * mouth_w
    x0, y0 = lm[LIPS_OUTER].min(0) - pad
    x1, y1 = lm[LIPS_OUTER].max(0) + pad
    box = tuple(int(round(v)) for v in (max(x0, 0), max(y0, 0), min(x1, img.width), min(y1, img.height)))
    crop = img.crop(box)
    size = (max(1, round(crop.width * scale)), max(1, round(crop.height * scale)))
    crop = crop.resize(size, Image.LANCZOS)
    shift = np.array(box[:2])
    outer = (lm[LIPS_OUTER] - shift) * scale
    inner = (lm[LIPS_INNER] - shift) * scale

    outer_m = polygon_mask(size, outer)
    inner_m = polygon_mask(size, inner).filter(ImageFilter.MaxFilter(5))
    lip = np.asarray(outer_m.filter(ImageFilter.MinFilter(5))) > 0
    lip &= ~(np.asarray(inner_m) > 0)
    out["mouth_open"] = float((np.asarray(polygon_mask(size, inner)) > 0).sum() / max((np.asarray(outer_m) > 0).sum(), 1))
    out["lip_px"] = int(lip.sum())
    if out["lip_px"] < 200:
        return out

    lin = srgb_to_linear(np.asarray(crop, dtype=np.float64) / 255.0)
    lum = luminance(lin)
    lip_lum = lum[lip]
    lo, hi = np.quantile(lip_lum, [TRIM, 1 - TRIM])
    keep = lip & (lum >= lo) & (lum <= hi)
    lab = np.median(linear_to_lab(lin[keep]), axis=0)
    out.update(lip_L=lab[0], lip_a=lab[1], lip_b=lab[2],
               lip_C=float(np.hypot(lab[1], lab[2])), lip_h=float(np.degrees(np.arctan2(lab[2], lab[1])) % 360))

    med = float(np.median(lip_lum))
    out["highlight_frac"] = float((lip_lum > HIGHLIGHT_RATIO * med).mean())
    # Texture: relative std of the 3×3 high-pass of linear luminance inside the lip.
    p = np.pad(lum, 1, mode="edge")
    blur = sum(p[dy:dy + lum.shape[0], dx:dx + lum.shape[1]] for dy in range(3) for dx in range(3)) / 9
    out["texture"] = float((lum - blur)[lip].std() / max(med, 1e-6))

    # Cheek reference on the full image (light / white balance of this photo).
    full_lin = srgb_to_linear(rgb8.astype(np.float64) / 255.0)
    cheek_px = []
    for inner_i, outer_i, low_i in CHEEKS:
        a, b, c = lm[inner_i], lm[outer_i], lm[low_i]
        center = (a + 0.4 * (b - a)) * 0.75 + c * 0.25
        r = 0.3 * np.linalg.norm(b - a)
        yy, xx = np.ogrid[:img.height, :img.width]
        disk = (xx - center[0]) ** 2 + (yy - center[1]) ** 2 <= r * r
        cheek_px.append(full_lin[disk])
    cheek = np.concatenate(cheek_px)
    if len(cheek) >= 50:
        cl = np.median(linear_to_lab(cheek), axis=0)
        out.update(cheek_L=cl[0], cheek_a=cl[1], cheek_b=cl[2])
    return {k: (float(v) if isinstance(v, np.floating) else v) for k, v in out.items()}


# --- database ---

SCHEMA = """
CREATE TABLE source (name TEXT, url TEXT, license TEXT, note TEXT, imported_at TEXT);
CREATE TABLE pairs (
  pair_id INTEGER PRIMARY KEY, no_makeup_path TEXT, with_makeup_path TEXT,
  part TEXT, gender TEXT, age INTEGER, country TEXT);
CREATE TABLE measurements (
  pair_id INTEGER REFERENCES pairs(pair_id), state TEXT CHECK (state IN ('bare', 'applied')),
  width INTEGER, height INTEGER, face_found INTEGER, lip_px INTEGER, mouth_open REAL,
  lip_L REAL, lip_a REAL, lip_b REAL, lip_C REAL, lip_h REAL,
  cheek_L REAL, cheek_a REAL, cheek_b REAL,
  highlight_frac REAL, texture REAL,
  PRIMARY KEY (pair_id, state));
CREATE TABLE pair_deltas (
  pair_id INTEGER PRIMARY KEY REFERENCES pairs(pair_id),
  dL REAL, dC REAL, dh REAL, dE2000 REAL,
  dL_rel_cheek REAL, dC_rel_cheek REAL, cheek_dE2000 REAL,
  texture_ratio REAL, highlight_diff REAL, usable INTEGER, reason TEXT);
"""
MEASURE_COLS = ["width", "height", "face_found", "lip_px", "mouth_open", "lip_L", "lip_a", "lip_b", "lip_C",
                "lip_h", "cheek_L", "cheek_a", "cheek_b", "highlight_frac", "texture"]
CHEEK_DE_MAX = 8.0   # cheek color differing more than this means the two photos' light differs too much
MOUTH_OPEN_MAX = 0.15


def deltas(bare: dict, applied: dict) -> dict:
    reasons = []
    if not (bare.get("face_found") and applied.get("face_found")):
        reasons.append("no_face")
    if "lip_L" not in bare or "lip_L" not in applied:
        reasons.append("lip_too_small")
    if reasons:
        return {"usable": 0, "reason": ",".join(reasons)}
    lb = (bare["lip_L"], bare["lip_a"], bare["lip_b"])
    la = (applied["lip_L"], applied["lip_a"], applied["lip_b"])
    dh = (applied["lip_h"] - bare["lip_h"] + 180) % 360 - 180
    d = {"dL": la[0] - lb[0], "dC": applied["lip_C"] - bare["lip_C"], "dh": dh, "dE2000": delta_e2000(lb, la),
         "texture_ratio": applied["texture"] / max(bare["texture"], 1e-6),
         "highlight_diff": applied["highlight_frac"] - bare["highlight_frac"]}
    if "cheek_L" in bare and "cheek_L" in applied:
        cb = (bare["cheek_L"], bare["cheek_a"], bare["cheek_b"])
        ca = (applied["cheek_L"], applied["cheek_a"], applied["cheek_b"])
        d["dL_rel_cheek"] = d["dL"] - (ca[0] - cb[0])
        d["dC_rel_cheek"] = d["dC"] - (np.hypot(ca[1], ca[2]) - np.hypot(cb[1], cb[2]))
        d["cheek_dE2000"] = delta_e2000(cb, ca)
        if d["cheek_dE2000"] > CHEEK_DE_MAX:
            reasons.append("light_differs")
    else:
        reasons.append("no_cheek")
    if max(bare.get("mouth_open", 0), applied.get("mouth_open", 0)) > MOUTH_OPEN_MAX:
        reasons.append("mouth_open")
    d["usable"] = 0 if reasons else 1
    d["reason"] = ",".join(reasons) or None
    return {k: (float(v) if isinstance(v, np.floating) else v) for k, v in d.items()}


def find_csv(root: Path) -> Path:
    found = sorted(root.rglob("*.csv"))
    if not found:
        raise SystemExit(f"CSV not found under {root}")
    return found[0]


def rel(path: Path) -> str:
    path = path.resolve()
    return str(path.relative_to(ROOT)) if path.is_relative_to(ROOT) else str(path)


def load_image(path: Path) -> Image.Image:
    return ImageOps.exif_transpose(Image.open(path)).convert("RGB")


def main() -> None:
    ap = argparse.ArgumentParser()
    src = ap.add_mutually_exclusive_group(required=True)
    src.add_argument("--zip", type=Path)
    src.add_argument("--dir", type=Path)
    args = ap.parse_args()

    if not MODEL.exists():
        raise SystemExit(f"Model missing: {MODEL}\nDownload: https://storage.googleapis.com/mediapipe-models/"
                         "face_landmarker/face_landmarker/float16/1/face_landmarker.task")
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    if args.zip:
        raw = OUT_DIR / "raw"
        with zipfile.ZipFile(args.zip) as z:
            z.extractall(raw)
    else:
        raw = args.dir
    csv_path = find_csv(raw)
    base = csv_path.parent
    with csv_path.open(encoding="utf-8-sig", newline="") as f:
        rows = list(csv.DictReader(f))

    landmarker = vision.FaceLandmarker.create_from_options(vision.FaceLandmarkerOptions(
        base_options=BaseOptions(model_asset_path=str(MODEL)), num_faces=1))

    if DB_PATH.exists():
        DB_PATH.unlink()
    db = sqlite3.connect(DB_PATH)
    db.executescript(SCHEMA)
    db.execute("INSERT INTO source VALUES (?, ?, ?, ?, ?)", (SOURCE["name"], SOURCE["url"], SOURCE["license"],
               SOURCE["note"], datetime.now(timezone.utc).isoformat(timespec="seconds")))

    missing = []
    for i, row in enumerate(rows):
        paths = {"bare": base / row["no_makeup"], "applied": base / row["with_makeup"]}
        if not all(p.exists() for p in paths.values()):
            missing.append(i)
            continue
        age = row.get("age", "").strip()
        db.execute("INSERT INTO pairs VALUES (?, ?, ?, ?, ?, ?, ?)", (
            i, rel(paths["bare"]), rel(paths["applied"]),
            row.get("part"), row.get("gender"), int(float(age)) if age else None, row.get("country")))
        m = {state: measure(load_image(p), landmarker) for state, p in paths.items()}
        for state, vals in m.items():
            db.execute(f"INSERT INTO measurements (pair_id, state, {', '.join(MEASURE_COLS)}) "
                       f"VALUES (?, ?, {', '.join('?' * len(MEASURE_COLS))})",
                       (i, state, *[vals.get(c) for c in MEASURE_COLS]))
        d = deltas(m["bare"], m["applied"])
        cols = list(d)
        db.execute(f"INSERT INTO pair_deltas (pair_id, {', '.join(cols)}) VALUES (?, {', '.join('?' * len(cols))})",
                   (i, *[d[c] for c in cols]))
    db.commit()

    print(f"DB: {DB_PATH.relative_to(ROOT)}")
    print(f"pairs: {len(rows) - len(missing)} / {len(rows)}" + (f" (missing files: {missing})" if missing else ""))
    for part, n, usable in db.execute(
            "SELECT p.part, COUNT(*), SUM(d.usable) FROM pairs p JOIN pair_deltas d USING (pair_id) GROUP BY p.part"):
        print(f"  part={part}: {n} pairs, usable {usable}")
    for reason, n in db.execute("SELECT reason, COUNT(*) FROM pair_deltas WHERE usable = 0 GROUP BY reason"):
        print(f"  excluded ({reason}): {n}")
    row = db.execute("""SELECT COUNT(*), AVG(dL), AVG(dC), AVG(dE2000), AVG(dL_rel_cheek), AVG(dC_rel_cheek),
                        AVG(texture_ratio), AVG(highlight_diff)
                        FROM pair_deltas d JOIN pairs p USING (pair_id) WHERE usable = 1 AND p.part = 'lips'""").fetchone()
    if row[0]:
        print("usable lip pairs, mean: n={} dL={:+.2f} dC={:+.2f} dE2000={:.2f} dL_rel={:+.2f} dC_rel={:+.2f} "
              "texture_ratio={:.2f} highlight_diff={:+.3f}".format(*row))
    db.close()


if __name__ == "__main__":
    main()

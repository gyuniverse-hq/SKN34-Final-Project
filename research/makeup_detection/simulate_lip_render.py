"""Offline copy of the AR lip shader (components/ar/faceTrackerHtml.ts, MESH_FRAG lip branch) for tuning.

Paints a lipstick onto a bare-lip photo with the same per-pixel math as the shader and measures the result
with the same stats as measure_lip_reference.py, so the renderer can be compared with real lipstick photos
(lip_texture.sqlite). Real photos differ in person and light, so compare the change from bare lips
(ratio to the bare photo) rather than absolute values.

Simplifications: light color 1, one upper and one lower normal, no edge refinement,
no inner/corner fade, camera blur 1. Lip-shaped shade, UV grooves and coloured sheen follow
faceTrackerHtml.ts. Keep MATERIALS / TUNING below in sync with that file.

  python research/makeup_detection/simulate_lip_render.py <bare.jpg> [--out <dir>] [--hex B3122E]
"""
from __future__ import annotations

import argparse
import sqlite3
import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFilter
from scipy.ndimage import shift as nd_shift

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "research" / "makeup_detection"))
import build_db as bd  # noqa: E402
import measure_lip_reference as ml  # noqa: E402
import mediapipe as mp  # noqa: E402
from mediapipe.tasks.python import BaseOptions, vision  # noqa: E402

DB_PATH = ml.DB_PATH

TUNING = {
    "layersPerIntensity": 3, "grainMax": 0.2, "lipGlint": 1.5, "glintThreshold": 0.04,
    "diffuseCap": 1.3, "camHighlightGain": 2.0, "skinRefLum": 0.34, "exposureRange": (0.2, 1.6),
    "specMax": 0.85, "specFill": 0.7, "lipRecess": 0.35, "pigmentHeadroom": 0.78,
}
# Keep in sync with components/ar/faceTrackerHtml.ts MATERIALS.
MATERIALS = {
    "matte":  {"roughness": 0.90, "specular": 0.35, "a1": 0.72, "translucent": 0.0, "detail": 1.15, "volume": 1.25},
    "satin":  {"roughness": 0.42, "specular": 0.85, "a1": 0.50, "translucent": 0.12, "detail": 1.15, "volume": 1.15},
    "glossy": {"roughness": 0.16, "specular": 1.15, "a1": 0.46, "translucent": 0.28, "detail": 0.95, "volume": 0.85},
}
BEFORE_TUNING = {**TUNING, "specFill": 0.0, "lipRecess": 0.0}
BEFORE_MATERIALS = {
    "matte":  {"roughness": 0.90, "specular": 0.3, "a1": 0.90, "translucent": 0.0, "detail": 0.6, "volume": 1.0},
    "satin":  {"roughness": 0.45, "specular": 0.8, "a1": 0.75, "translucent": 0.1, "detail": 0.9, "volume": 1.0},
    "glossy": {"roughness": 0.15, "specular": 1.2, "a1": 0.55, "translucent": 0.3, "detail": 1.0, "volume": 1.0},
}
INTENSITY = {"light": 0.35, "medium": 0.6, "deep": 0.85}


def hex_to_linear(h: str) -> np.ndarray:
    return bd.srgb_to_linear(np.array([int(h[i:i + 2], 16) for i in (0, 2, 4)], dtype=np.float64) / 255.0)


def trimmed_mean(v: np.ndarray) -> float:
    v = np.sort(v)
    lo = int(len(v) * 0.25)
    hi = max(lo + 1, int(np.ceil(len(v) * 0.75)))
    return float(v[lo:hi].mean())


def prepare(path: Path, landmarker) -> dict:
    """Crop the mouth at MOUTH_WIDTH_PX like measure_lip_reference, plus the app's lip/skin reference values."""
    img = bd.load_image(path)
    rgb8 = np.asarray(img, dtype=np.uint8)
    res = landmarker.detect(mp.Image(image_format=mp.ImageFormat.SRGB, data=np.ascontiguousarray(rgb8)))
    if not res.face_landmarks:
        raise SystemExit(f"no face in {path}")
    lm = np.array([[p.x * img.width, p.y * img.height] for p in res.face_landmarks[0]])
    full_lum = bd.luminance(bd.srgb_to_linear(rgb8 / 255.0))

    def lum_at(pts):
        xs = np.clip(np.round(pts[:, 0]).astype(int), 0, img.width - 1)
        ys = np.clip(np.round(pts[:, 1]).astype(int), 0, img.height - 1)
        return full_lum[ys, xs]

    outer_full = np.asarray(bd.polygon_mask(img.size, lm[bd.LIPS_OUTER])) > 0
    inner_full = np.asarray(bd.polygon_mask(img.size, lm[bd.LIPS_INNER])) > 0
    lip_full = outer_full & ~inner_full
    # App: lipVerts = mesh vertices well inside the lip mask (> 0.6), so the contour rings drop out.
    core_full = np.asarray(Image.fromarray(lip_full.astype(np.uint8) * 255).filter(ImageFilter.MinFilter(5))) > 0
    ix = np.clip(np.round(lm[:468]).astype(int), 0, [img.width - 1, img.height - 1])
    lip_verts = np.nonzero(core_full[ix[:, 1], ix[:, 0]])[0]
    ring = set(bd.LIPS_OUTER) | set(bd.LIPS_INNER)
    skin_verts = [i for i in range(468) if not lip_full[ix[i, 1], ix[i, 0]] and i not in ring]

    mouth_w = np.linalg.norm(lm[291] - lm[61])
    scale = bd.MOUTH_WIDTH_PX / max(mouth_w, 1.0)
    pad = 0.3 * mouth_w
    x0, y0 = lm[bd.LIPS_OUTER].min(0) - pad
    x1, y1 = lm[bd.LIPS_OUTER].max(0) + pad
    box = tuple(int(round(v)) for v in (max(x0, 0), max(y0, 0), min(x1, img.width), min(y1, img.height)))
    crop = img.crop(box)
    size = (max(1, round(crop.width * scale)), max(1, round(crop.height * scale)))
    crop = crop.resize(size, Image.LANCZOS)
    shift_xy = np.array(box[:2])
    outer = (lm[bd.LIPS_OUTER] - shift_xy) * scale
    inner = (lm[bd.LIPS_INNER] - shift_xy) * scale
    outer_m = np.asarray(bd.polygon_mask(size, outer).filter(ImageFilter.MinFilter(5))) > 0
    inner_m = np.asarray(bd.polygon_mask(size, inner).filter(ImageFilter.MaxFilter(5))) > 0
    lip = outer_m & ~inner_m
    paint = (np.asarray(bd.polygon_mask(size, outer)) > 0) & ~(np.asarray(bd.polygon_mask(size, inner)) > 0)
    mid_y = float(((lm[13] + lm[14]) / 2 - shift_xy)[1] * scale)
    yy = np.arange(size[1])[:, None]

    lin = bd.srgb_to_linear(np.asarray(crop, dtype=np.float64) / 255.0)
    lum = bd.luminance(lin)
    # Camera grain like measureCamera(): 3×3 high-pass std on a cheek patch, relative to its mean.
    cx, cy = lm[bd.CHEEKS[0][0]]
    r = int(max(6, 0.08 * mouth_w))
    patch = full_lum[int(cy) - r:int(cy) + r, int(cx) - r:int(cx) + r]
    p = np.pad(patch, 1, mode="edge")
    blur = sum(p[dy:dy + patch.shape[0], dx:dx + patch.shape[1]] for dy in range(3) for dx in range(3)) / 9
    grain = float(np.clip((patch - blur).std() / max(patch.mean(), 1e-3), 0, TUNING["grainMax"]))

    # App (new): points between the outer and inner lip line, mouth corners skipped.
    ring_pts = np.array([lm[o] + t * (lm[i] - lm[o])
                         for k, (o, i) in enumerate(zip(bd.LIPS_OUTER, bd.LIPS_INNER)) if k not in (0, 10)
                         for t in (1 / 3, 1 / 2, 2 / 3)])

    return {
        "lip_mean_ring": trimmed_mean(lum_at(ring_pts)),
        "img": img, "box": box, "crop": crop, "lin": lin, "lum": lum, "lip": lip, "paint": paint,
        "upper": lip & (yy < mid_y), "lower": lip & (yy >= mid_y),
        "lip_mean_vert": trimmed_mean(lum_at(lm[lip_verts])) if len(lip_verts) else float(np.median(full_lum[lip_full])),
        "lip_median_px": float(np.median(full_lum[lip_full])),
        "skin_mean": trimmed_mean(lum_at(lm[skin_verts])),
        "grain": grain, "n_lip_verts": int(len(lip_verts)),
    }


def ggx_lobe(n: np.ndarray, light: np.ndarray, view: np.ndarray, rough: float) -> float:
    h = light + view
    h = h / max(float(np.linalg.norm(h)), 1e-6)
    nl = max(float(np.dot(n, light)), 0.0)
    nv = max(float(np.dot(n, view)), 0.0)
    a2 = (rough * rough) ** 2
    d = max(float(np.dot(n, h)), 0.0)
    d = d * d * (a2 - 1.0) + 1.0
    D = a2 / (3.14159 * max(d * d, 1e-4))
    k = (rough + 1.0) ** 2 / 8.0
    G = (nl / (nl * (1.0 - k) + k)) * (nv / (nv * (1.0 - k) + k))
    F = 0.04 + 0.96 * (1.0 - max(float(np.dot(h, view)), 0.0)) ** 5
    return D * G * F / (4.0 * max(nv, 1e-4)) * nl


def render(prep: dict, mat: dict, tuning: dict, hex_color: str, intensity: float, mean_lum: float,
           seed: int = 7) -> np.ndarray:
    """Shader lip branch, per pixel, in linear RGB. Returns the painted linear crop."""
    cam = prep["lin"]
    lum = prep["lum"]
    if "lN" not in prep:
        o = 1.5
        prep["lN"] = 0.25 * sum(nd_shift(lum, s, order=1, mode="nearest") for s in ((0, o), (0, -o), (o, 0), (-o, 0)))
    lN = prep["lN"]
    meanL = max(mean_lum, 1e-3)
    hp = lum - lN
    g_amp = prep["grain"] * np.sqrt(max(0.0, 1 - mat["detail"] ** 2))
    rng = np.random.default_rng(seed)
    g = (rng.random(lum.shape) - 0.5) * 3.464
    recess = float(np.clip(meanL / max(prep["skin_mean"], 1e-3), 0.5, 1.0))
    recess_mix = 1.0 + (recess - 1.0) * tuning.get("lipRecess", 0.0)
    alb = hex_to_linear(hex_color)
    peak = float(alb.max())
    alb = alb * min(1.0, tuning.get("pigmentHeadroom", 0.78) / max(peak, 1e-4))
    h, w = lum.shape
    xs = np.linspace(-1.0, 1.0, w)[None, :]
    lower_w = prep["lower"].astype(np.float64)
    center = np.clip(1.0 - np.abs(xs) / 0.95, 0.0, 1.0)
    # Horizontal neighborhood, same role as the shader's wideH (7px on the mouth crop).
    if "wide_h" not in prep:
        prep["wide_h"] = 0.5 * (
            nd_shift(lum, (0, 7), order=1, mode="nearest") + nd_shift(lum, (0, -7), order=1, mode="nearest")
        )
    rel = lN / np.maximum(prep["wide_h"], 1e-4)
    cam_crease = np.clip(1.0 + (rel - 1.0) * mat["detail"], 0.64, 1.22)
    lines = np.sin(xs * 46.0) * 0.65 + np.sin(xs * 81.0 + 1.7) * 0.35
    proc_amp = np.where(np.abs(rel - 1.0) > 0.10, 0.08, np.where(np.abs(rel - 1.0) < 0.03, 0.22, 0.15))
    proc = np.clip(1.0 + lines * proc_amp * mat["detail"], 0.70, 1.18)
    crease = np.clip(cam_crease * proc, 0.58, 1.28)
    form_cam = np.clip(np.power(np.maximum(np.minimum(lN / meanL, tuning["diffuseCap"]), 1e-4), mat.get("volume", 1.0)), 0.75, 1.20)
    form_shape = np.where(prep["upper"], 0.84, 0.98).astype(np.float64)
    form_shape = form_shape * (0.90 + 0.10 * center) + lower_w * center * 0.12
    # Default light (0, 0.3, 0.95) vs upper/lower shell normals, mixed at 0.55.
    form_geom = np.where(prep["upper"], 0.72, 0.98)
    volume = form_shape * (1.0 + (form_geom - 1.0) * 0.55) * (1.0 + (form_cam - 1.0) * 0.35)
    shade = np.clip(volume * crease * (1.0 + g * g_amp), 0.58, 1.32)
    applied = alb[None, None, :] * shade[..., None] * recess_mix
    smooth1 = 1 - mat["roughness"]
    n_upper = np.array([0.0, -0.25, 0.97]); n_upper /= np.linalg.norm(n_upper)
    n_lower = np.array([0.0, 0.20, 0.98]); n_lower /= np.linalg.norm(n_lower)
    light = np.array([0.0, 0.3, 0.95]); light /= np.linalg.norm(light)
    view = np.array([0.0, 0.0, 1.0])
    half_l = light + view
    half_l = half_l / np.linalg.norm(half_l)
    ndh = max(float(np.dot(n_lower, half_l)), 0.0)
    broad = ndh ** (5.0 + 11.0 * mat["roughness"])
    sheen = lower_w * center * broad * (0.08 + smooth1 * mat["specular"] * 0.42)
    applied = applied * (1.0 + (sheen * crease)[..., None])
    layers = max(0.3, intensity * tuning["layersPerIntensity"])
    cov = (1 - (1 - mat["a1"]) ** layers) * prep["paint"][..., None]
    painted = cam + (applied - cam) * cov
    filt = alb / max(alb.max(), 1e-4)
    tinted = cam * (1 + (filt[None, None, :] - 1) * cov)
    col = painted + (tinted - painted) * mat["translucent"]
    camHL = np.maximum(lN - tuning["diffuseCap"] * meanL, 0)
    glint = np.maximum(hp - tuning["glintThreshold"] * meanL, 0) * tuning["lipGlint"] * smooth1 ** 2
    spec_cam = camHL * tuning["camHighlightGain"]
    exposure = float(np.clip(prep["skin_mean"] / tuning["skinRefLum"], *tuning["exposureRange"]))
    pbr_u = ggx_lobe(n_upper, light, view, mat["roughness"]) * exposure * tuning["skinRefLum"]
    pbr_l = ggx_lobe(n_lower, light, view, mat["roughness"]) * exposure * tuning["skinRefLum"]
    spec_pbr = np.where(prep["upper"], pbr_u, pbr_l)
    fill = tuning.get("specFill", 0.0)
    spec_mix = spec_cam * (1.0 - fill) + spec_pbr * fill
    gloss = smooth1 ** 2
    spec = np.minimum((spec_mix * gloss + glint) * mat["specular"], tuning["specMax"]) * crease
    return col + (spec * prep["paint"])[..., None]


def stats(prep: dict, lin: np.ndarray) -> dict:
    srgb = np.clip(lin, 0, 1)
    srgb = np.where(srgb <= 0.0031308, srgb * 12.92, 1.055 * srgb ** (1 / 2.4) - 0.055)
    crop = Image.fromarray(np.round(srgb * 255).astype(np.uint8))
    return ml.stats_from_crop(crop, prep["lip"], prep["upper"], prep["lower"])


def to_image(lin: np.ndarray) -> Image.Image:
    c = np.clip(lin, 0, 1)
    c = np.where(c <= 0.0031308, c * 12.92, 1.055 * c ** (1 / 2.4) - 0.055)
    return Image.fromarray(np.round(c * 255).astype(np.uint8))


KEYS = ["shade_iqr", "highlight_13", "highlight_15", "peak_99", "texture"]
# Underexposed (lip L* 16): relative stats blow up in the noise floor.
EXCLUDE = {"pexels-7322123.jpg"}


def targets() -> dict:
    """Per-finish medians from lip_texture.sqlite, without EXCLUDE."""
    db = sqlite3.connect(DB_PATH)
    rows = db.execute(f"SELECT file, finish, {', '.join(KEYS)} FROM photos").fetchall()
    db.close()
    out = {}
    for finish in {r[1] for r in rows}:
        vals = np.array([r[2:] for r in rows if r[1] == finish and r[0] not in EXCLUDE], dtype=float)
        out[finish] = dict(zip(KEYS, np.median(vals, axis=0)))
    return out


def loss(sim_r: dict, tgt_r: dict) -> float:
    return float(sum(np.log(max(sim_r[k], 1e-3) / tgt_r[k]) ** 2 for k in KEYS))


def fit(prep: dict, tuning: dict, hex_color: str, mean_key: str) -> dict:
    """Grid search volume / detail / specular per finish against real/bare ratios (roughness, a1 kept)."""
    tg = targets()
    bare = stats(prep, prep["lin"])
    best = {}
    for finish, mat in MATERIALS.items():
        tgt_r = {k: tg[finish][k] / tg["bare"][k] for k in KEYS}
        scored = []
        for vol in np.arange(0.6, 1.51, 0.1):
            for det in np.arange(0.4, 1.21, 0.2):
                for spec in np.arange(0.2, 1.61, 0.2):
                    m = {**mat, "volume": round(vol, 2), "detail": round(det, 2), "specular": round(spec, 2)}
                    s = stats(prep, render(prep, m, tuning, hex_color, INTENSITY["medium"], prep[mean_key]))
                    scored.append((loss({k: s[k] / bare[k] for k in KEYS}, tgt_r), m))
        scored.sort(key=lambda t: t[0])
        best[finish] = scored[0][1]
        print(finish, f"loss {scored[0][0]:.3f}", {k: scored[0][1][k] for k in ("volume", "detail", "specular")})
    return best


def report(prep: dict, materials: dict, tuning: dict, hex_color: str, mean_key: str) -> dict:
    tg = targets()
    bare = stats(prep, prep["lin"])
    print(f"lip mean (vertex trimmed mean) {prep['lip_mean_vert']:.4f}  ring {prep['lip_mean_ring']:.4f}  "
          f"lip median px {prep['lip_median_px']:.4f}  "
          f"lip verts {prep['n_lip_verts']}  skin {prep['skin_mean']:.4f}  grain {prep['grain']:.3f}")
    print(f"{'':16s} " + " ".join(f"{k:>13s}" for k in KEYS))
    print(f"{'bare photo':16s} " + " ".join(f"{bare[k]:13.3f}" for k in KEYS))
    out = {}
    for finish, mat in materials.items():
        s = stats(prep, render(prep, mat, tuning, hex_color, INTENSITY["medium"], prep[mean_key]))
        sim_r = {k: s[k] / max(bare[k], 1e-6) for k in KEYS}
        tgt_r = {k: tg[finish][k] / max(tg["bare"][k], 1e-6) for k in KEYS}
        out[finish] = loss(sim_r, tgt_r)
        print(f"{finish + ' sim/bare':16s} " + " ".join(f"{sim_r[k]:13.2f}" for k in KEYS))
        print(f"{finish + ' real/bare':16s} " + " ".join(f"{tgt_r[k]:13.2f}" for k in KEYS) + f"   loss {out[finish]:.3f}")
    return out


def paste_crop(prep: dict, lin: np.ndarray) -> Image.Image:
    x0, y0, x1, y1 = prep["box"]
    painted = to_image(lin).resize((x1 - x0, y1 - y0), Image.LANCZOS)
    out = prep["img"].copy()
    out.paste(painted, (x0, y0))
    return out


def mouth_zoom(img: Image.Image, prep: dict, pad: float = 0.55) -> Image.Image:
    x0, y0, x1, y1 = prep["box"]
    w, h = x1 - x0, y1 - y0
    z0 = max(0, int(x0 - pad * w))
    z1 = min(img.width, int(x1 + pad * w))
    z2 = max(0, int(y0 - pad * h))
    z3 = min(img.height, int(y1 + pad * h))
    return img.crop((z0, z2, z1, z3))


def label(img: Image.Image, text: str) -> Image.Image:
    canvas = Image.new("RGB", (img.width, img.height + 28), (20, 20, 20))
    canvas.paste(img, (0, 28))
    ImageDraw.Draw(canvas).text((8, 6), text, fill=(255, 255, 255))
    return canvas


def save_compare(prep: dict, hex_color: str, out_dir: Path) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    bare = prep["img"]
    rows = []
    for finish in ("satin", "matte", "glossy"):
        tiles = [label(mouth_zoom(bare, prep), f"{finish} bare")]
        for name, mats, tun, mean_key, intensity in (
            ("before 보통", BEFORE_MATERIALS, BEFORE_TUNING, "lip_mean_vert", INTENSITY["medium"]),
            ("after 보통", MATERIALS, TUNING, "lip_mean_ring", INTENSITY["medium"]),
            ("before 진하게", BEFORE_MATERIALS, BEFORE_TUNING, "lip_mean_vert", INTENSITY["deep"]),
            ("after 진하게", MATERIALS, TUNING, "lip_mean_ring", INTENSITY["deep"]),
        ):
            lin = render(prep, mats[finish], tun, hex_color, intensity, prep[mean_key])
            face = paste_crop(prep, lin)
            face.save(out_dir / f"{finish}_{name.replace(' ', '_')}.jpg", quality=92)
            tiles.append(label(mouth_zoom(face, prep), f"{finish} {name}"))
        h = max(t.height for t in tiles)
        tiles = [t.resize((int(t.width * h / t.height), h), Image.LANCZOS) for t in tiles]
        row = Image.new("RGB", (sum(t.width for t in tiles), h))
        x = 0
        for t in tiles:
            row.paste(t, (x, 0)); x += t.width
        rows.append(row)
    grid = Image.new("RGB", (max(r.width for r in rows), sum(r.height for r in rows)))
    y = 0
    for r in rows:
        grid.paste(r, (0, y)); y += r.height
    grid.save(out_dir / "compare_grid.jpg", quality=92)
    print("wrote", out_dir / "compare_grid.jpg")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("photo", type=Path)
    ap.add_argument("--hex", default="B3122E")
    ap.add_argument("--mean", choices=["vert", "ring"], default="ring", help="app lip mean: old vertices or lip-line points")
    ap.add_argument("--fit", action="store_true", help="grid search volume/detail/specular per finish")
    ap.add_argument("--out", type=Path, help="write before/after comparison crops")
    args = ap.parse_args()
    lmk = vision.FaceLandmarker.create_from_options(vision.FaceLandmarkerOptions(
        base_options=BaseOptions(model_asset_path=str(bd.MODEL)), num_faces=1))
    prep = prepare(args.photo, lmk)
    key = f"lip_mean_{args.mean}"
    print("--- before (vertex mean, old materials) ---")
    report(prep, BEFORE_MATERIALS, BEFORE_TUNING, args.hex, "lip_mean_vert")
    print("--- after (lip-body mean, new materials) ---")
    report(prep, MATERIALS, TUNING, args.hex, key)
    if args.fit:
        report(prep, fit(prep, TUNING, args.hex, key), TUNING, args.hex, key)
    if args.out:
        save_compare(prep, args.hex, args.out)


if __name__ == "__main__":
    main()

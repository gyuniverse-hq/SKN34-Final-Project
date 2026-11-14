# /// script
# requires-python = ">=3.11"
# dependencies = ["mediapipe>=0.10.14", "opencv-python>=4.9", "numpy>=1.26"]
# ///
"""Compare lip rendering of our AR against other try-on apps from screenshots only.

Input folder holds `<condition>__<source>.<png|jpg>` files, e.g.
`coral-matte-front__ours.png`, `coral-matte-front__youcam.png`.
Sources: ours, youcam, deepar, bare (bare lips, optional), and before / after
for our own change (e.g. TUNING.lightMatch off / on).

Only output pixels are compared (black-box). Nothing here touches another
app's code or assets. Face photos stay under `research/data/` (git-ignored).

    uv run research/vto_benchmark/compare_lips.py research/data/vto_benchmark/2026-11-03
"""

from __future__ import annotations

import argparse
import csv
import sys
from dataclasses import asdict, dataclass
from pathlib import Path

import cv2
import mediapipe as mp
import numpy as np
from mediapipe.tasks.python import BaseOptions, vision

MODEL_URL = (
    "https://storage.googleapis.com/mediapipe-models/face_landmarker/"
    "face_landmarker/float16/1/face_landmarker.task"
)
DEFAULT_MODEL = Path("research/data/models/face_landmarker.task")
SOURCES = ("ours", "youcam", "deepar", "bare", "before", "after")
REFERENCES = ("youcam", "deepar")
IMAGE_EXT = {".png", ".jpg", ".jpeg", ".webp"}

OUTER_UPPER = [61, 185, 40, 39, 37, 0, 267, 269, 270, 409, 291]
OUTER_LOWER = [291, 375, 321, 405, 314, 17, 84, 181, 91, 146, 61]
INNER_UPPER = [78, 191, 80, 81, 82, 13, 312, 311, 310, 415, 308]
INNER_LOWER = [308, 324, 318, 402, 317, 14, 87, 178, 88, 95, 78]
OUTER_LOOP = OUTER_UPPER[:-1] + OUTER_LOWER[:-1]
CORNERS = (61, 291)


@dataclass
class LipMetrics:
    condition: str
    source: str
    file: str
    mouth_px: float
    L_mean: float
    C_mean: float
    hue_deg: float
    L_spread: float
    upper_lower_L: float
    flat_frac: float
    texture: float
    hl_area_pct: float
    hl_peak: float
    hl_lower_frac: float
    hl_cx: float
    edge_w_pct: float
    edge_n: int


def load_landmarker(model: Path) -> vision.FaceLandmarker:
    if not model.exists():
        sys.exit(f"Missing {model}. Download: {MODEL_URL}")
    options = vision.FaceLandmarkerOptions(
        base_options=BaseOptions(model_asset_path=str(model)),
        running_mode=vision.RunningMode.IMAGE,
        num_faces=1,
    )
    return vision.FaceLandmarker.create_from_options(options)


def read_rgb(path: Path) -> np.ndarray:
    data = np.fromfile(path, dtype=np.uint8)
    bgr = cv2.imdecode(data, cv2.IMREAD_COLOR)
    if bgr is None:
        raise ValueError(f"cannot read {path}")
    return np.ascontiguousarray(cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB))


def detect(landmarker: vision.FaceLandmarker, rgb: np.ndarray) -> np.ndarray | None:
    result = landmarker.detect(mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb))
    if not result.face_landmarks:
        return None
    h, w = rgb.shape[:2]
    return np.array([(p.x * w, p.y * h) for p in result.face_landmarks[0]], dtype=np.float32)


def polygon_mask(shape: tuple[int, int], pts: np.ndarray) -> np.ndarray:
    mask = np.zeros(shape, dtype=np.uint8)
    cv2.fillPoly(mask, [np.round(pts).astype(np.int32)], 255)
    return mask


def to_lab(rgb: np.ndarray) -> np.ndarray:
    return cv2.cvtColor(rgb.astype(np.float32) / 255.0, cv2.COLOR_RGB2Lab)


def edge_width(lab: np.ndarray, pts: np.ndarray, lip_lab: np.ndarray, skin_lab: np.ndarray, w: float) -> tuple[float, int]:
    """Median 80%→20% lip-to-skin transition width along outer contour normals, in % of mouth width."""
    axis = lip_lab - skin_lab
    denom = float(axis @ axis)
    if denom < 25.0:
        return float("nan"), 0
    loop = pts[OUTER_LOOP]
    center = loop.mean(axis=0)
    offsets = np.linspace(-0.06 * w, 0.06 * w, 61, dtype=np.float32)
    widths = []
    for i, idx in enumerate(OUTER_LOOP):
        if idx in CORNERS:
            continue
        tangent = loop[(i + 1) % len(loop)] - loop[i - 1]
        normal = np.array([tangent[1], -tangent[0]], dtype=np.float32)
        normal /= np.linalg.norm(normal) + 1e-6
        if normal @ (loop[i] - center) < 0:
            normal = -normal
        xs = (loop[i][0] + offsets * normal[0]).reshape(-1, 1)
        ys = (loop[i][1] + offsets * normal[1]).reshape(-1, 1)
        profile = cv2.remap(lab, xs, ys, cv2.INTER_LINEAR).reshape(-1, 3)
        t = (profile - skin_lab) @ axis / denom
        t = np.convolve(t, np.ones(3) / 3, mode="same")
        inside = np.where(t[: len(t) // 2 + 8] >= 0.8)[0]
        if inside.size == 0:
            continue
        start = inside[-1]
        outside = np.where(t[start:] <= 0.2)[0]
        if outside.size == 0:
            continue
        widths.append(float(offsets[start + outside[0]] - offsets[start]))
    if not widths:
        return float("nan"), 0
    return float(np.median(widths) / w * 100.0), len(widths)


def measure(rgb: np.ndarray, pts: np.ndarray, condition: str, source: str, file: str) -> tuple[LipMetrics, dict]:
    h, w_img = rgb.shape[:2]
    lab = to_lab(rgb)
    w = float(np.linalg.norm(pts[61] - pts[291]))
    upper = polygon_mask((h, w_img), np.vstack([pts[OUTER_UPPER], pts[INNER_UPPER][::-1]]))
    lower = polygon_mask((h, w_img), np.vstack([pts[OUTER_LOWER], pts[INNER_LOWER][::-1]]))
    lips = cv2.bitwise_or(upper, lower)
    k = max(1, round(0.02 * w))
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2 * k + 1, 2 * k + 1))
    core = cv2.erode(lips, kernel) > 0
    upper_core = cv2.erode(upper, kernel) > 0
    lower_core = cv2.erode(lower, kernel) > 0
    if core.sum() < 50:
        core, upper_core, lower_core = lips > 0, upper > 0, lower > 0

    L, a, b = lab[..., 0], lab[..., 1], lab[..., 2]
    C = np.hypot(a, b)
    Lc, Cc = L[core], C[core]

    near = cv2.dilate(lips, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (int(0.08 * w) * 2 + 1,) * 2))
    far = cv2.dilate(lips, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (int(0.25 * w) * 2 + 1,) * 2))
    ring = (far > 0) & (near == 0) & (L > 15)
    skin_lab = np.median(lab[ring], axis=0) if ring.any() else lab[core].mean(axis=0)
    lip_lab = np.median(lab[core], axis=0)

    L_med = float(np.median(Lc))
    weight = core.astype(np.float32)
    broad = max(1.5, 0.06 * w)
    local_mean = cv2.GaussianBlur(L * weight, (0, 0), broad) / np.maximum(cv2.GaussianBlur(weight, (0, 0), broad), 1e-3)
    local = L - local_mean
    hl = core & (local > max(5.0, 2.0 * float(local[core].std()))) & (L > np.percentile(Lc, 75))
    hl_n = int(hl.sum())
    if hl_n:
        _, xs = np.nonzero(hl)
        mid_x = float((pts[61][0] + pts[291][0]) / 2)
        hl_cx = float(np.mean(np.abs(xs - mid_x)) / (w / 2))
        hl_lower = float((hl & lower_core).sum() / hl_n)
    else:
        hl_cx = hl_lower = float("nan")

    sigma = max(0.8, 0.012 * w)
    highpass = L - cv2.GaussianBlur(L, (0, 0), sigma)
    edge_pct, edge_n = edge_width(lab, pts, lip_lab, skin_lab, w)

    metrics = LipMetrics(
        condition=condition,
        source=source,
        file=file,
        mouth_px=round(w, 1),
        L_mean=round(float(Lc.mean()), 2),
        C_mean=round(float(Cc.mean()), 2),
        hue_deg=round(float(np.degrees(np.arctan2(b[core].mean(), a[core].mean())) % 360), 1),
        L_spread=round(float(np.percentile(Lc, 90) - np.percentile(Lc, 10)), 2),
        upper_lower_L=round(float(L[upper_core].mean() / max(L[lower_core].mean(), 1e-3)), 3),
        flat_frac=round(float(np.mean(np.abs(Lc - L_med) < 3.0)), 3),
        texture=round(float(highpass[core].std()), 3),
        hl_area_pct=round(hl_n / core.sum() * 100.0, 2),
        hl_peak=round(float(np.percentile(Lc, 99) - L_med), 2),
        hl_lower_frac=round(hl_lower, 3),
        hl_cx=round(hl_cx, 3),
        edge_w_pct=round(edge_pct, 2),
        edge_n=edge_n,
    )
    return metrics, {"lips": lips, "hl": hl, "outer": pts[OUTER_LOOP]}


def hints(ours: LipMetrics, ref: LipMetrics) -> list[str]:
    out = []
    if ours.L_spread < 0.75 * ref.L_spread:
        out.append(f"명암 폭이 좁음(평평함): {ours.L_spread} vs {ref.L_spread}")
    if ours.texture < 0.75 * ref.texture:
        out.append(f"주름 결이 약함: {ours.texture} vs {ref.texture}")
    if ours.flat_frac > ref.flat_frac + 0.1:
        out.append(f"같은 밝기 면이 넓음(스티커 느낌): {ours.flat_frac} vs {ref.flat_frac}")
    if ours.upper_lower_L > ref.upper_lower_L + 0.05:
        out.append(f"윗입술 그늘이 약함(위/아래 밝기비): {ours.upper_lower_L} vs {ref.upper_lower_L}")
    if ref.hl_area_pct > 0.5 and ours.hl_area_pct < 0.5 * ref.hl_area_pct:
        out.append(f"윤기 면적이 작음: {ours.hl_area_pct}% vs {ref.hl_area_pct}%")
    if ours.hl_area_pct > 2.0 * max(ref.hl_area_pct, 0.5):
        out.append(f"윤기 면적이 넓음: {ours.hl_area_pct}% vs {ref.hl_area_pct}%")
    if ours.hl_peak > ref.hl_peak + 8:
        out.append(f"윤기가 하얗게 튐(최고 밝기 차): {ours.hl_peak} vs {ref.hl_peak}")
    elif ours.hl_peak < ref.hl_peak - 8:
        out.append(f"윤기가 약함(최고 밝기 차): {ours.hl_peak} vs {ref.hl_peak}")
    if np.isfinite(ours.edge_w_pct) and np.isfinite(ref.edge_w_pct):
        if ours.edge_w_pct < 0.6 * ref.edge_w_pct:
            out.append(f"경계가 칼같음(입 너비 대비 %): {ours.edge_w_pct} vs {ref.edge_w_pct}")
        elif ours.edge_w_pct > 1.6 * ref.edge_w_pct:
            out.append(f"경계가 번짐(입 너비 대비 %): {ours.edge_w_pct} vs {ref.edge_w_pct}")
    return out


def crop_panel(rgb: np.ndarray, overlay: dict, pts: np.ndarray, width: int = 360) -> np.ndarray:
    x0, y0 = pts[OUTER_LOOP].min(axis=0)
    x1, y1 = pts[OUTER_LOOP].max(axis=0)
    pad = 0.35 * (x1 - x0)
    h, w = rgb.shape[:2]
    x0, y0 = int(max(0, x0 - pad)), int(max(0, y0 - pad))
    x1, y1 = int(min(w, x1 + pad)), int(min(h, y1 + pad))
    base = rgb[y0:y1, x0:x1].copy()
    vis = base.copy()
    vis[overlay["hl"][y0:y1, x0:x1]] = (0, 255, 255)
    contour = np.round(overlay["outer"] - (x0, y0)).astype(np.int32)
    cv2.polylines(vis, [contour], True, (0, 255, 0), 1, cv2.LINE_AA)
    scale = width / base.shape[1]
    size = (width, int(base.shape[0] * scale))
    return np.vstack([cv2.resize(base, size, interpolation=cv2.INTER_CUBIC), cv2.resize(vis, size, interpolation=cv2.INTER_NEAREST)])


def label(panel: np.ndarray, m: LipMetrics) -> np.ndarray:
    bar = np.full((70, panel.shape[1], 3), 255, dtype=np.uint8)
    lines = [
        f"{m.source}  L {m.L_mean} C {m.C_mean} spread {m.L_spread}",
        f"tex {m.texture} flat {m.flat_frac} up/low {m.upper_lower_L}",
        f"hl {m.hl_area_pct}% peak {m.hl_peak} edge {m.edge_w_pct}%",
    ]
    for i, text in enumerate(lines):
        cv2.putText(bar, text, (6, 20 + 22 * i), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (0, 0, 0), 1, cv2.LINE_AA)
    return np.vstack([bar, panel])


def collect(folder: Path) -> dict[str, dict[str, Path]]:
    groups: dict[str, dict[str, Path]] = {}
    for path in sorted(folder.iterdir()):
        if path.suffix.lower() not in IMAGE_EXT or "__" not in path.stem:
            continue
        condition, source = path.stem.rsplit("__", 1)
        if source not in SOURCES:
            print(f"skip {path.name}: source must be one of {SOURCES}")
            continue
        groups.setdefault(condition, {})[source] = path
    return groups


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("folder", type=Path)
    parser.add_argument("--out", type=Path, help="default: <folder>/_out")
    parser.add_argument("--model", type=Path, default=DEFAULT_MODEL)
    args = parser.parse_args()
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    groups = collect(args.folder)
    if not groups:
        sys.exit(f"No `<condition>__<source>` images in {args.folder}")
    out = args.out or args.folder / "_out"
    out.mkdir(parents=True, exist_ok=True)
    landmarker = load_landmarker(args.model)

    rows: list[LipMetrics] = []
    summary = ["# 입술 비교 결과", ""]
    for condition, files in groups.items():
        measured: dict[str, LipMetrics] = {}
        panels = []
        for source in SOURCES:
            if source not in files:
                continue
            rgb = read_rgb(files[source])
            pts = detect(landmarker, rgb)
            if pts is None:
                print(f"{files[source].name}: 얼굴을 찾지 못함")
                continue
            m, overlay = measure(rgb, pts, condition, source, files[source].name)
            measured[source] = m
            rows.append(m)
            panels.append(label(crop_panel(rgb, overlay, pts), m))
        if panels:
            height = max(p.shape[0] for p in panels)
            padded = [np.vstack([p, np.full((height - p.shape[0], p.shape[1], 3), 255, np.uint8)]) for p in panels]
            sheet = cv2.cvtColor(np.hstack(padded), cv2.COLOR_RGB2BGR)
            cv2.imencode(".png", sheet)[1].tofile(str(out / f"{condition}_sheet.png"))

        summary.append(f"## {condition}")
        pairs = [("ours", r) for r in REFERENCES if "ours" in measured and r in measured][:1]
        if "after" in measured and "before" in measured:
            pairs.append(("after", "before"))
        if not pairs:
            summary.append("- 비교 불가: ours + youcam/deepar, 또는 before + after가 있어야 함")
        for subject, ref_name in pairs:
            found = hints(measured[subject], measured[ref_name])
            summary.extend(f"- ({subject}, {ref_name} 기준) {h}" for h in found)
            if not found:
                summary.append(f"- ({subject}, {ref_name} 기준) 큰 차이 없음")
        summary.append("")

    with open(out / "metrics.csv", "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=list(asdict(rows[0]).keys()) if rows else ["condition"])
        writer.writeheader()
        writer.writerows(asdict(r) for r in rows)
    (out / "summary.md").write_text("\n".join(summary), encoding="utf-8")
    print("\n".join(summary))
    print(f"saved: {out}")


if __name__ == "__main__":
    main()

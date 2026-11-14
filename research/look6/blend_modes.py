"""Offline look-mode blend experiment on the Sullyoon bare frame: which compositing modes move the AR toward the video.

Exploratory only. The masks are landmark polygons, not the WebView masks, and the formulas run on a still photo.
"""

from __future__ import annotations

from pathlib import Path

import cv2
import mediapipe as mp
import numpy as np
from mediapipe.tasks.python import BaseOptions, vision

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "research" / "data" / "look6"
BASE = DATA / "e1gSkUdG6Bo" / "baseline"
OUT = DATA / "e1gSkUdG6Bo" / "blend_modes"
FINAL = DATA / "manual" / "e1gSkUdG6Bo_0002_final.png"

FACE_OVAL = [10, 338, 297, 332, 284, 251, 389, 356, 454, 323, 361, 288, 397, 365, 379, 378, 400, 377, 152, 148, 176,
             149, 150, 136, 172, 58, 132, 93, 234, 127, 162, 21, 54, 103, 67, 109]
EYES = ([33, 7, 163, 144, 145, 153, 154, 155, 133, 173, 157, 158, 159, 160, 161, 246],
        [263, 249, 390, 373, 374, 380, 381, 382, 362, 398, 384, 385, 386, 387, 388, 466])
BROWS = ([46, 53, 52, 65, 55, 107, 66, 105, 63, 70], [276, 283, 282, 295, 285, 336, 296, 334, 293, 300])
LIPS = [61, 146, 91, 181, 84, 17, 314, 405, 321, 375, 291, 409, 270, 269, 267, 0, 37, 39, 40, 185]

# Product hex of the look's blush (catalog) and a pinker look colour picked by eye from the finished frame (assumption).
BLUSH_PRODUCT = "#FF928F"
BLUSH_LOOK = "#F2A7B4"
SKIN_TINT = "#FFE4EA"


def hex_rgb(value: str) -> np.ndarray:
    return np.array([int(value[i:i + 2], 16) for i in (1, 3, 5)], np.float32) / 255.0


def to_lin(c):
    return np.where(c <= 0.04045, c / 12.92, ((c + 0.055) / 1.055) ** 2.4)


def to_srgb(c):
    c = np.clip(c, 0, 1)
    return np.where(c <= 0.0031308, c * 12.92, 1.055 * c ** (1 / 2.4) - 0.055)


def lum(c):
    return c[..., 0] * 0.2126 + c[..., 1] * 0.7152 + c[..., 2] * 0.0722


# Separable blend modes on sRGB-encoded values (their usual definition).
def multiply(b, c):
    return b * c


def screen(b, c):
    return 1 - (1 - b) * (1 - c)


def overlay(b, c):
    return np.where(b < 0.5, 2 * b * c, 1 - 2 * (1 - b) * (1 - c))


def soft_light(b, c):
    d = np.where(b <= 0.25, ((16 * b - 12) * b + 4) * b, np.sqrt(b))
    return np.where(c <= 0.5, b - (1 - 2 * c) * b * (1 - b), b + (2 * c - 1) * (d - b))


def current_powder(srgb, color, skin_mean_lum):
    """The renderer's powder(): 0.6 x product shaded by camera brightness + 0.4 x skin filtered by the pigment (linear)."""
    cam = to_lin(srgb)
    albedo = to_lin(color)
    shade = np.clip(lum(cam) / max(skin_mean_lum, 1e-3), 0, 1.6)[..., None]
    layer = albedo * shade
    tint = cam * np.sqrt(np.clip(albedo / 0.85, 0, 1))
    return to_srgb(0.6 * layer + 0.4 * tint)


def compose(base, mode_result, alpha):
    return base + (mode_result - base) * alpha[..., None]


def landmarks(detector, rgb_u8):
    h, w = rgb_u8.shape[:2]
    result = detector.detect(mp.Image(image_format=mp.ImageFormat.SRGB, data=np.ascontiguousarray(rgb_u8)))
    if not result.face_landmarks:
        raise RuntimeError("no face")
    return np.array([[p.x * w, p.y * h] for p in result.face_landmarks[0]], np.float32)


def poly_mask(shape, pts, groups, dilate=0):
    m = np.zeros(shape, np.uint8)
    for g in groups:
        cv2.fillPoly(m, [np.round(pts[g]).astype(np.int32)], 255)
    if dilate:
        m = cv2.dilate(m, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (dilate, dilate)))
    return m.astype(np.float32) / 255.0


def skin_mask(shape, pts, face_w):
    face = poly_mask(shape, pts, [FACE_OVAL])
    holes = poly_mask(shape, pts, [*EYES, *BROWS, LIPS], dilate=max(3, int(face_w * 0.05)))
    m = np.clip(face - holes, 0, 1)
    return cv2.GaussianBlur(m, (0, 0), face_w * 0.02)


def cheek_mask(shape, pts, face_w, placement):
    m = np.zeros(shape, np.float32)
    for under, apple in ((118, 50), (347, 280)):
        if placement == "under_eye":
            c, axes = 0.6 * pts[under] + 0.4 * pts[apple], (face_w * 0.17, face_w * 0.085)
        else:
            c, axes = pts[apple], (face_w * 0.11, face_w * 0.08)
        cv2.ellipse(m, (int(c[0]), int(c[1])), (int(axes[0]), int(axes[1])), 0, 0, 360, 1.0, -1)
    if placement == "under_eye":
        # A faint band over the nose bridge between the cheeks (the "draped" flush in the video).
        c = pts[197]
        cv2.ellipse(m, (int(c[0]), int(c[1])), (int(face_w * 0.07), int(face_w * 0.03)), 0, 0, 360, 0.5, -1)
    return cv2.GaussianBlur(m, (0, 0), face_w * (0.06 if placement == "under_eye" else 0.035))


def glow_mask(shape, pts, face_w):
    m = np.zeros(shape, np.float32)
    for idx, axes in ((6, (0.025, 0.09)), (195, (0.02, 0.04)), (116, (0.07, 0.03)), (345, (0.07, 0.03)), (151, (0.08, 0.04))):
        c = pts[idx]
        cv2.ellipse(m, (int(c[0]), int(c[1])), (int(face_w * axes[0]), int(face_w * axes[1])), 0, 0, 360, 1.0, -1)
    return cv2.GaussianBlur(m, (0, 0), face_w * 0.03)


def crop(img, pts, pad=0.25):
    x0, y0 = pts.min(axis=0)
    x1, y1 = pts.max(axis=0)
    px, py = (x1 - x0) * pad, (y1 - y0) * pad
    h, w = img.shape[:2]
    return img[max(0, int(y0 - py)):min(h, int(y1 + py)), max(0, int(x0 - px)):min(w, int(x1 + px))]


def tile(img, label, height=420):
    u8 = np.clip(img * 255 if img.dtype != np.uint8 else img, 0, 255).astype(np.uint8)
    t = cv2.resize(u8, (round(u8.shape[1] * height / u8.shape[0]), height), interpolation=cv2.INTER_AREA)
    t = cv2.copyMakeBorder(t, 0, 30, 0, 0, cv2.BORDER_CONSTANT, value=(255, 255, 255))
    cv2.putText(t, label, (6, height + 21), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (0, 0, 0), 1, cv2.LINE_AA)
    return t


def sheet(tiles, path):
    width = max(t.shape[1] for t in tiles)
    tiles = [cv2.copyMakeBorder(t, 0, 0, 0, width - t.shape[1], cv2.BORDER_CONSTANT, value=(255, 255, 255)) for t in tiles]
    rows = [np.hstack(tiles[i:i + 4]) for i in range(0, len(tiles), 4)]
    rows = [cv2.copyMakeBorder(r, 0, 0, 0, rows[0].shape[1] - r.shape[1], cv2.BORDER_CONSTANT, value=(255, 255, 255)) for r in rows]
    cv2.imwrite(str(path), cv2.cvtColor(np.vstack(rows), cv2.COLOR_RGB2BGR), [cv2.IMWRITE_JPEG_QUALITY, 88])


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    read = lambda p: cv2.cvtColor(cv2.imread(str(p)), cv2.COLOR_BGR2RGB)  # noqa: E731
    bare_u8, ar_u8, final_u8 = read(BASE / "off.png"), read(BASE / "all.png"), read(FINAL)
    opts = vision.FaceLandmarkerOptions(
        base_options=BaseOptions(model_asset_path=str(ROOT / "research/data/models/face_landmarker.task")), num_faces=1)
    with vision.FaceLandmarker.create_from_options(opts) as det:
        pts, final_pts = landmarks(det, bare_u8), landmarks(det, final_u8)
    face_w = float(np.linalg.norm(pts[234] - pts[454]))
    shape = bare_u8.shape[:2]
    bare, ar = bare_u8.astype(np.float32) / 255, ar_u8.astype(np.float32) / 255
    skin = skin_mask(shape, pts, face_w)
    skin_mean = float((lum(to_lin(bare)) * skin).sum() / skin.sum())
    final_crop = crop(final_u8, final_pts)

    # 1) Blush: compositing mode and placement, product colour vs a look colour.
    tiles = [tile(crop(bare, pts), "bare"), tile(final_crop, "video final")]
    apple, under = cheek_mask(shape, pts, face_w, "apple"), cheek_mask(shape, pts, face_w, "under_eye")
    for color_name, color in (("product", hex_rgb(BLUSH_PRODUCT)), ("look", hex_rgb(BLUSH_LOOK))):
        c = np.broadcast_to(color, bare.shape)
        variants = [
            ("current powder, apple", compose(bare, current_powder(bare, color, skin_mean), apple * 0.27)),
            ("current powder, under-eye", compose(bare, current_powder(bare, color, skin_mean), under * 0.27)),
            ("multiply, under-eye", compose(bare, multiply(bare, c), under * 0.55)),
            ("soft light, under-eye", compose(bare, soft_light(bare, c), under * 0.9)),
            ("overlay, under-eye", compose(bare, overlay(bare, c), under * 0.45)),
        ]
        tiles += [tile(crop(img, pts), f"{color_name}: {name}") for name, img in variants]
    sheet(tiles, OUT / "blush_modes.jpg")

    # 2) Look-mode skin tone and glow on top of the current AR render (blush, lips, eyes stay as rendered).
    tint = np.broadcast_to(hex_rgb(SKIN_TINT), ar.shape)
    glow = glow_mask(shape, pts, face_w)
    soft = compose(ar, soft_light(ar, tint), skin * 0.8)
    over = compose(ar, overlay(ar, tint), skin * 0.35)
    scr = compose(ar, screen(ar, tint), skin * 0.3)
    glowed = compose(soft, screen(soft, np.ones_like(soft)), glow * 0.22)
    smooth_src = (glowed * 255).astype(np.uint8)
    smoothed = cv2.bilateralFilter(smooth_src, 9, 28, 7).astype(np.float32) / 255
    textured = compose(glowed, smoothed, skin * 0.6)
    tiles = [tile(crop(ar, pts), "current AR (all zones)"),
             tile(crop(over, pts), "skin: overlay pink-white"),
             tile(crop(scr, pts), "skin: screen pink-white"),
             tile(crop(soft, pts), "skin: soft light pink-white"),
             tile(crop(glowed, pts), "soft light + screen glow"),
             tile(crop(textured, pts), "+ skin texture smoothing"),
             tile(final_crop, "video final")]
    sheet(tiles, OUT / "skin_modes.jpg")
    print(f"skin mean luminance {skin_mean:.3f}; wrote {OUT / 'blush_modes.jpg'} and {OUT / 'skin_modes.jpg'}")


if __name__ == "__main__":
    main()

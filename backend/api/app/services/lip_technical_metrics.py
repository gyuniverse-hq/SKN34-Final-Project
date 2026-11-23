"""Lip triad technical metrics for admin immediate scoring.

Ported from research/eval_matrix/make_tech_pass_gallery.py (ΔE00, SSIM, MAE).
mIoU uses a makeup-change mask approximation when no GT lip mask exists.
LPIPS is optional (report_only) when torch+lpips are unavailable.
Images are never written to disk by this module.
"""

from __future__ import annotations

import io
import math
from typing import Any

import numpy as np
from PIL import Image

TECHNICAL_VERSION = "technical-admin-v1.0"
TEAM_EYE_LINES = {
    "delta_e": {"rule": "<=", "value": 1.8, "direction": "lower_better"},
    "ssim": {"rule": ">=", "value": 0.95, "direction": "higher_better"},
    "mae": {"rule": "<=", "value": 0.04, "direction": "lower_better"},
    "miou": {"rule": ">=", "value": 0.85, "direction": "higher_better"},
    "lpips": {"rule": None, "value": None, "direction": "lower_better", "absolute": "report_only"},
}
MAX_SIDE = 512
MAX_BYTES = 8 * 1024 * 1024


def _rgb01(data: bytes) -> np.ndarray:
    if len(data) > MAX_BYTES:
        raise ValueError("image too large")
    image = Image.open(io.BytesIO(data)).convert("RGB")
    w, h = image.size
    scale = min(1.0, MAX_SIDE / max(w, h))
    if scale < 1.0:
        image = image.resize((max(1, int(w * scale)), max(1, int(h * scale))), Image.BILINEAR)
    return np.asarray(image, dtype=np.float64) / 255.0


def _fit(x: np.ndarray, shape: tuple[int, int]) -> np.ndarray:
    h, w = shape
    if x.shape[:2] == (h, w):
        return x
    im = Image.fromarray((np.clip(x, 0, 1) * 255).astype(np.uint8))
    im = im.resize((w, h), Image.BILINEAR)
    return np.asarray(im, dtype=np.float64) / 255.0


def _srgb_to_lab(rgb: np.ndarray) -> np.ndarray:
    a = np.where(rgb <= 0.04045, rgb / 12.92, ((rgb + 0.055) / 1.055) ** 2.4)
    m = np.array(
        [
            [0.4124564, 0.3575761, 0.1804375],
            [0.2126729, 0.7151522, 0.0721750],
            [0.0193339, 0.1191920, 0.9503041],
        ]
    )
    xyz = a @ m.T
    w = np.array([0.95047, 1.0, 1.08883])
    x = xyz / w
    f = np.where(x > 0.008856, np.cbrt(x), (903.3 * x + 16) / 116)
    L = 116 * f[..., 1] - 16
    A = 500 * (f[..., 0] - f[..., 1])
    B = 200 * (f[..., 1] - f[..., 2])
    return np.stack([L, A, B], axis=-1)


def delta_e00(lab1: np.ndarray, lab2: np.ndarray) -> float:
    L1, a1, b1 = map(float, lab1)
    L2, a2, b2 = map(float, lab2)
    C1, C2 = math.hypot(a1, b1), math.hypot(a2, b2)
    Cab = (C1 + C2) / 2
    G = 0.5 * (1 - math.sqrt(Cab**7 / (Cab**7 + 25**7))) if Cab else 0.0
    a1p, a2p = (1 + G) * a1, (1 + G) * a2
    C1p, C2p = math.hypot(a1p, b1), math.hypot(a2p, b2)
    h1p = (math.degrees(math.atan2(b1, a1p)) + 360) % 360
    h2p = (math.degrees(math.atan2(b2, a2p)) + 360) % 360
    dLp = L2 - L1
    dCp = C2p - C1p
    if C1p * C2p == 0:
        dhp = 0.0
    else:
        dh = h2p - h1p
        if abs(dh) > 180:
            dh -= 360 * (1 if dh > 0 else -1)
        dhp = dh
    dHp = 2 * math.sqrt(max(C1p * C2p, 0)) * math.sin(math.radians(dhp) / 2)
    Lp = (L1 + L2) / 2
    Cp = (C1p + C2p) / 2
    if C1p * C2p == 0:
        hp = h1p + h2p
    else:
        if abs(h1p - h2p) <= 180:
            hp = (h1p + h2p) / 2
        else:
            hp = (h1p + h2p + 360) / 2 if (h1p + h2p) < 360 else (h1p + h2p - 360) / 2
    T = (
        1
        - 0.17 * math.cos(math.radians(hp - 30))
        + 0.24 * math.cos(math.radians(2 * hp))
        + 0.32 * math.cos(math.radians(3 * hp + 6))
        - 0.20 * math.cos(math.radians(4 * hp - 63))
    )
    dRo = 30 * math.exp(-(((hp - 275) / 25) ** 2))
    Rc = 2 * math.sqrt(Cp**7 / (Cp**7 + 25**7)) if Cp else 0.0
    Sl = 1 + (0.015 * (Lp - 50) ** 2) / math.sqrt(20 + (Lp - 50) ** 2)
    Sc = 1 + 0.045 * Cp
    Sh = 1 + 0.015 * Cp * T
    Rt = -math.sin(math.radians(2 * dRo)) * Rc
    return math.sqrt(
        (dLp / Sl) ** 2 + (dCp / Sc) ** 2 + (dHp / Sh) ** 2 + Rt * (dCp / Sc) * (dHp / Sh)
    )


def ssim_gray(a: np.ndarray, b: np.ndarray) -> float:
    if a.shape != b.shape:
        b = _fit(np.stack([b, b, b], -1), a.shape)[..., 0]
    c1, c2 = (0.01**2), (0.03**2)
    mu_a, mu_b = a.mean(), b.mean()
    sig_a, sig_b = a.var(), b.var()
    sig_ab = ((a - mu_a) * (b - mu_b)).mean()
    return float(
        ((2 * mu_a * mu_b + c1) * (2 * sig_ab + c2))
        / ((mu_a**2 + mu_b**2 + c1) * (sig_a + sig_b + c2))
    )


def _makeup_mask(base: np.ndarray, other: np.ndarray, threshold: float = 0.08) -> np.ndarray:
    diff = np.mean(np.abs(other - base), axis=-1)
    return diff >= threshold


def miou_approx(bare: np.ndarray, real: np.ndarray, ar: np.ndarray) -> float:
    ref = _makeup_mask(bare, real)
    pred = _makeup_mask(bare, ar)
    inter = np.logical_and(ref, pred).sum()
    union = np.logical_or(ref, pred).sum()
    if union == 0:
        return 1.0 if inter == 0 else 0.0
    return float(inter / union)


def _optional_lpips(
    ar: np.ndarray, real: np.ndarray, bare: np.ndarray
) -> tuple[float | None, float | None]:
    try:
        import lpips  # type: ignore
        import torch

        loss = lpips.LPIPS(net="alex")

        def t(x: np.ndarray):
            return torch.from_numpy(x).permute(2, 0, 1).unsqueeze(0).float() * 2 - 1

        with torch.no_grad():
            return (
                round(float(loss(t(ar), t(real)).item()), 4),
                round(float(loss(t(bare), t(real)).item()), 4),
            )
    except Exception:
        return None, None


def _verdict(metric: str, value: float | None) -> str:
    line = TEAM_EYE_LINES[metric]
    if value is None or line.get("absolute") == "report_only" or line["value"] is None:
        return "report_only"
    rule, threshold = line["rule"], float(line["value"])
    if rule == "<=":
        return "pass" if value <= threshold else "fail"
    if rule == ">=":
        return "pass" if value >= threshold else "fail"
    return "report_only"


def score_triad(bare_bytes: bytes, real_bytes: bytes, ar_bytes: bytes) -> dict[str, Any]:
    ar = _rgb01(ar_bytes)
    h, w = ar.shape[:2]
    real = _fit(_rgb01(real_bytes), (h, w))
    bare = _fit(_rgb01(bare_bytes), (h, w))

    lab_ar = _srgb_to_lab(ar).reshape(-1, 3).mean(0)
    lab_real = _srgb_to_lab(real).reshape(-1, 3).mean(0)
    lab_bare = _srgb_to_lab(bare).reshape(-1, 3).mean(0)
    g_ar, g_real, g_bare = ar.mean(-1), real.mean(-1), bare.mean(-1)

    delta_e = round(delta_e00(lab_ar, lab_real), 4)
    delta_e_bare = round(delta_e00(lab_bare, lab_real), 4)
    ssim = round(ssim_gray(g_ar, g_real), 4)
    ssim_bare = round(ssim_gray(g_bare, g_real), 4)
    mae = round(float(np.mean(np.abs(ar - real))), 5)
    mae_bare = round(float(np.mean(np.abs(bare - real))), 5)
    miou = round(miou_approx(bare, real, ar), 4)
    lpips_ar, lpips_bare = _optional_lpips(ar, real, bare)

    items = {
        "delta_e": {
            "value": delta_e,
            "bareValue": delta_e_bare,
            "beatsBare": delta_e < delta_e_bare,
            "passLine": TEAM_EYE_LINES["delta_e"]["value"],
            "verdict": _verdict("delta_e", delta_e),
        },
        "ssim": {
            "value": ssim,
            "bareValue": ssim_bare,
            "beatsBare": ssim > ssim_bare,
            "passLine": TEAM_EYE_LINES["ssim"]["value"],
            "verdict": _verdict("ssim", ssim),
        },
        "mae": {
            "value": mae,
            "bareValue": mae_bare,
            "beatsBare": mae < mae_bare,
            "passLine": TEAM_EYE_LINES["mae"]["value"],
            "verdict": _verdict("mae", mae),
        },
        "miou": {
            "value": miou,
            "bareValue": None,
            "beatsBare": None,
            "passLine": TEAM_EYE_LINES["miou"]["value"],
            "verdict": _verdict("miou", miou),
            "method": "makeup_change_mask_iou",
        },
        "lpips": {
            "value": lpips_ar,
            "bareValue": lpips_bare,
            "beatsBare": (
                None
                if lpips_ar is None or lpips_bare is None
                else lpips_ar < lpips_bare
            ),
            "passLine": None,
            "verdict": _verdict("lpips", lpips_ar),
        },
    }
    judged = [v["verdict"] for v in items.values() if v["verdict"] in ("pass", "fail")]
    overall = (
        "pass"
        if judged and all(v == "pass" for v in judged)
        else "fail"
        if judged
        else "report_only"
    )
    return {
        "criteriaVersion": TECHNICAL_VERSION,
        "overall": overall,
        "items": items,
    }

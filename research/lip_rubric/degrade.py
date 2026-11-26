"""Image-space lip defects applied to a rendered frame, with controlled strength.

Renderer TUNING changes barely move the output (the page measures camera blur and light and compensates), so
quality spread is created after rendering, inside the app lip polygon only. Levels are sampling design, not labels.
Each defect targets one rubric question; 'sticker_blend' moves the whole lip toward a flat sticker.
"""
import cv2
import numpy as np

from build_pack import LIPS_INNER, LIPS_OUTER, mirrored_ring, sticker_image

DEFECTS = {
    'sticker_blend': 'q5', 'texture_loss': 'q1', 'flat_shade': 'q2', 'gloss_blob': 'q3',
    'edge_spill': 'q4', 'edge_gap': 'q4', 'misalign': 'q4', 'oversharp': 'q5', 'cool_cast': 'q5',
}
LEVELS = {'light': 0.25, 'mild': 0.5, 'strong': 1.0}


def lip_mask(page, shape, feather=1.0):
    h, w = shape[:2]; outer = mirrored_ring(page, LIPS_OUTER, w); inner = mirrored_ring(page, LIPS_INNER, w)
    m = np.zeros((h, w), np.uint8)
    cv2.fillPoly(m, [np.rint(outer).astype(np.int32)], 255); cv2.fillPoly(m, [np.rint(inner).astype(np.int32)], 0)
    width = float(outer[:, 0].max() - outer[:, 0].min())
    soft = cv2.GaussianBlur(m.astype(np.float32) / 255, (0, 0), feather) if feather > 0 else m.astype(np.float32) / 255
    return m > 0, soft, width, outer


def blend(base, top, alpha):
    a = alpha[..., None] if alpha.ndim == 2 else alpha
    return np.clip(base.astype(np.float32) * (1 - a) + top.astype(np.float32) * a, 0, 255).astype(np.uint8)


def apply(render, off, page, hexcolor, defect, strength, seed=0):
    """Return the render with one defect at strength in (0, 1]."""
    rng = np.random.default_rng(seed)
    hard, soft, width, outer = lip_mask(page, render.shape)
    s = float(strength)
    if defect == 'sticker_blend':
        return blend(render, sticker_image(off, page, hexcolor), soft * (0.85 * s))
    lab = cv2.cvtColor(render, cv2.COLOR_BGR2LAB).astype(np.float32)
    if defect == 'texture_loss':
        ys, xs = np.where(soft > 0.01)
        if not len(xs):
            return render.copy()
        pad = int(0.1 * width) + 8
        y0, y1 = max(0, ys.min() - pad), min(render.shape[0], ys.max() + pad + 1)
        x0, x1 = max(0, xs.min() - pad), min(render.shape[1], xs.max() + pad + 1)
        smooth = render.copy()
        patch = cv2.bilateralFilter(render[y0:y1, x0:x1], 9, 40, max(3.0, 0.05 * width))
        smooth[y0:y1, x0:x1] = cv2.GaussianBlur(patch, (0, 0), max(1.5, 0.02 * width))
        return blend(render, smooth, soft * (0.7 + 0.3 * s))
    if defect == 'flat_shade':
        L = lab[..., 0]; mean = L[hard].mean() if hard.any() else L.mean()
        flat = lab.copy(); flat[..., 0] = mean + (L - mean) * (1 - 0.85 * s)
        return blend(render, cv2.cvtColor(np.clip(flat, 0, 255).astype(np.uint8), cv2.COLOR_LAB2BGR), soft)
    if defect == 'gloss_blob':
        ys, xs = np.where(hard)
        if not len(xs):
            return render.copy()
        k = rng.integers(len(xs)); cy, cx = ys[k], xs[k]
        yy, xx = np.mgrid[:render.shape[0], :render.shape[1]]
        r = (0.06 + 0.05 * s) * width
        spot = np.exp(-(((xx - cx) / (r * 1.6)) ** 2 + ((yy - cy) / r) ** 2)) * soft * (0.6 + 0.4 * s)
        return blend(render, np.full_like(render, 250), spot)
    if defect in ('edge_spill', 'edge_gap'):
        px = max(2, int(round((0.02 + 0.04 * s) * width)))
        kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2 * px + 1, 2 * px + 1))
        m8 = hard.astype(np.uint8) * 255
        if defect == 'edge_spill':
            ring = (cv2.dilate(m8, kernel) > 0) & ~hard
            paint = sticker_image(off, page, hexcolor)
            alpha = cv2.GaussianBlur(ring.astype(np.float32), (0, 0), 1.0) * 0.85
            return blend(render, paint, alpha)
        ring = hard & ~(cv2.erode(m8, kernel) > 0)
        alpha = cv2.GaussianBlur(ring.astype(np.float32), (0, 0), 1.0)
        return blend(render, off, alpha)
    if defect == 'misalign':
        dx = (0.03 + 0.05 * s) * width * (1 if rng.random() < .5 else -1); dy = (0.02 + 0.03 * s) * width
        M = np.float32([[1, 0, dx], [0, 1, dy]])
        moved_lips = cv2.warpAffine(render, M, (render.shape[1], render.shape[0]), borderMode=cv2.BORDER_REFLECT)
        moved_mask = cv2.warpAffine(soft, M, (render.shape[1], render.shape[0]))
        base = blend(render, off, soft)
        return blend(base, moved_lips, moved_mask)
    if defect == 'oversharp':
        blur = cv2.GaussianBlur(render, (0, 0), 2.0)
        sharp = cv2.addWeighted(render, 1 + 1.5 * s, blur, -1.5 * s, 0)
        return blend(render, sharp, soft)
    if defect == 'cool_cast':
        cast = lab.copy(); cast[..., 1] -= 12 * s; cast[..., 2] -= 22 * s
        return blend(render, cv2.cvtColor(np.clip(cast, 0, 255).astype(np.uint8), cv2.COLOR_LAB2BGR), soft)
    raise ValueError(defect)

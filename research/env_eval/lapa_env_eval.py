"""AR environment checks on LaPa faces (11-19): the renderer's scene measures, recomputed offline.

Mirrors components/ar/faceTrackerHtml.ts:
  - toLin / lumOf (sRGB -> linear, Rec.709 Y)
  - sampleScene: 128 px wide frame, skin mean luminance, blown share (max channel > clipLin 0.92)
  - measureCamera: 24 px cheek patch at camera resolution, relative 3x3 high-pass std (grain)
  - bgColorSums: background pixels (LaPa label 0 stands in for the segmenter's class 0), blown / dark (< 0.02)
    excluded; Gray World sum and Gray-Edge sum (|right| + |down| neighbour differences, first order, p = 1)
For each image it writes one row per condition (normal + synthetic changes) to a CSV.

    python research/env_eval/lapa_env_eval.py <lapa_test_dir> <out.csv> [n_images]

LaPa is non-commercial research data kept only under the git-ignored research/data/. Nothing is uploaded.
"""
import csv
import glob
import math
import os
import sys

import cv2
import numpy as np

CLIP_LIN = 0.92
DARK_LUM = 0.02
rng = np.random.default_rng(7)


def to_lin(u8):
    c = u8.astype(np.float32) / 255.0
    return np.where(c <= 0.04045, c / 12.92, ((c + 0.055) / 1.055) ** 2.4)


def to_srgb_u8(lin):
    lin = np.clip(lin, 0, 1)
    c = np.where(lin <= 0.0031308, lin * 12.92, 1.055 * np.power(lin, 1 / 2.4) - 0.055)
    return np.clip(np.round(c * 255), 0, 255).astype(np.uint8)


def lum(rgb):
    return 0.2126 * rgb[..., 0] + 0.7152 * rgb[..., 1] + 0.0722 * rgb[..., 2]


def trimmed_mean(v, cut=0.1):
    v = np.sort(v.ravel())
    k = int(len(v) * cut)
    v = v[k:len(v) - k] if len(v) > 2 * k + 2 else v
    return float(v.mean()) if len(v) else float('nan')


def angle(a, b):
    a = np.asarray(a, float); b = np.asarray(b, float)
    c = np.dot(a, b) / (np.linalg.norm(a) * np.linalg.norm(b) + 1e-12)
    return math.degrees(math.acos(max(-1.0, min(1.0, c))))


def bg_sums(rgb_lin, bgmask):
    """rgb_lin: (h, w, 3) linear at 128 px; bgmask: bool. Returns gray-world and gray-edge colour (normalised)."""
    ok = bgmask & (rgb_lin.max(2) <= CLIP_LIN) & (lum(rgb_lin) >= DARK_LUM)
    n = int(ok.sum())
    gw = rgb_lin[ok].sum(0) if n else np.zeros(3)
    e = np.zeros(3)
    okr = ok[:, :-1] & ok[:, 1:]
    e += np.abs(rgb_lin[:, 1:] - rgb_lin[:, :-1])[okr].sum(0)
    okd = ok[:-1, :] & ok[1:, :]
    e += np.abs(rgb_lin[1:, :] - rgb_lin[:-1, :])[okd].sum(0)
    return gw, e, n


def norm_col(c):
    y = 0.2126 * c[0] + 0.7152 * c[1] + 0.0722 * c[2]
    return c / y if y > 0 else np.array([1.0, 1.0, 1.0])


def grain_at(rgb_u8_full, skin_full):
    """measureCamera: 24 px patch on a cheek (largest skin square near the skin centroid), relative high-pass std."""
    N = 24
    ys, xs = np.nonzero(skin_full)
    if len(xs) < N * N:
        return float('nan')
    er = cv2.erode(skin_full.astype(np.uint8), np.ones((N, N), np.uint8)) > 0
    cy, cx = ys.mean(), xs.mean()
    ey, ex = np.nonzero(er)
    if not len(ex):
        return float('nan')
    # cheek: below the skin centroid and off the midline
    score = -np.abs(ey - (cy + 0.1 * (ys.max() - ys.min()))) - 0.5 * np.abs(np.abs(ex - cx) - 0.25 * (xs.max() - xs.min()))
    i = int(np.argmax(score))
    y0, x0 = ey[i] - N // 2, ex[i] - N // 2
    p = to_lin(rgb_u8_full[y0:y0 + N, x0:x0 + N])
    L = lum(p)
    m = cv2.blur(L, (3, 3), borderType=cv2.BORDER_REFLECT)
    hp = (L - m)[1:-1, 1:-1]
    return float(hp.std() / max(1e-3, L[1:-1, 1:-1].mean()))


def tone_of(small_u8):
    """Tone values of the 128 px frame (11-19 tone check): gamma-encoded luma Y' (0..255) percentiles, highlight and shadow
    shares, the log-average linear luminance (the 'key', Reinhard et al. 2002), dynamic range in stops and the effective
    gamma log(mean linear) / log(mean encoded). Mirrors envMeasureScene's tone histogram (64 bins of Y')."""
    enc = small_u8.astype(np.float32)
    yp = 0.2126 * enc[..., 0] + 0.7152 * enc[..., 1] + 0.0722 * enc[..., 2]
    lin = lum(to_lin(small_u8))
    hist = np.bincount(np.clip((yp / 4).astype(int), 0, 63).ravel(), minlength=64).astype(float)
    cdf = np.cumsum(hist) / hist.sum()
    pct = lambda q: (int(np.searchsorted(cdf, q)) + 0.5) * 4
    p2, p50, p98 = pct(0.02), pct(0.5), pct(0.98)
    def lin_of(v):
        c = v / 255.0
        return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4
    me = float(yp.mean()) / 255
    ml = float(lin.mean())
    return dict(t_black=p2, t_mid=p50, t_white=p98, t_hl=float((yp > 235).mean()), t_shadow=float((yp < 16).mean()),
                t_key=float(np.exp(np.log(lin + 1e-4).mean())), t_dr=math.log2(max(lin_of(p98), 1e-4) / max(lin_of(p2), 1e-3)),
                t_gamma=math.log(max(ml, 1e-6)) / math.log(min(max(me, 1e-6), 0.999)))


def measure(rgb_u8, label, ita_rgb=None):
    """rgb_u8: BGR->RGB uint8 at camera scale; label: LaPa classes (0 bg, 1 skin, 10 hair)."""
    H, W = label.shape
    sw, sh = 128, max(1, round(128 * H / W))
    small = cv2.resize(rgb_u8, (sw, sh), interpolation=cv2.INTER_AREA)
    lab_s = cv2.resize(label, (sw, sh), interpolation=cv2.INTER_NEAREST)
    lin = to_lin(small)
    skin = lab_s == 1
    bg = lab_s == 0
    L = lum(lin)
    skin_l = trimmed_mean(L[skin]) if skin.sum() > 30 else float('nan')
    bg_l = trimmed_mean(L[bg]) if bg.sum() > 30 else float('nan')
    frame_l = float(L.mean())
    blown = float((lin[skin].max(1) > CLIP_LIN).mean()) if skin.sum() else float('nan')
    # left / right skin brightness split by the nose (label 6) centroid
    nose = np.nonzero(lab_s == 6)
    mid = nose[1].mean() if len(nose[1]) else np.nonzero(skin)[1].mean()
    xs = np.arange(sw)[None, :].repeat(sh, 0)
    left = skin & (xs < mid); right = skin & (xs >= mid)
    lr = (trimmed_mean(L[left]) / max(1e-4, trimmed_mean(L[right]))) if left.sum() > 20 and right.sum() > 20 else float('nan')
    gw, ge, n = bg_sums(lin, bg)
    gwn, gen = norm_col(gw), norm_col(ge)
    grain = grain_at(rgb_u8, label == 1)
    sk = [trimmed_mean(lin[..., j][skin]) if skin.sum() > 30 else float('nan') for j in range(3)]
    return dict(**tone_of(small), skin_r=sk[0], skin_g=sk[1], skin_b=sk[2], skin_l=skin_l, bg_l=bg_l, frame_l=frame_l, blown=blown, lr=lr, grain=grain, bg_frac=float(bg.mean()),
                gw_r=gwn[0], gw_g=gwn[1], gw_b=gwn[2], ge_r=gen[0], ge_g=gen[1], ge_b=gen[2], bg_n=n)


def ita_of(rgb_u8, label):
    skin = label == 1
    if skin.sum() < 50:
        return float('nan')
    px = rgb_u8[skin].reshape(-1, 1, 3)
    labv = cv2.cvtColor(px, cv2.COLOR_RGB2LAB).reshape(-1, 3).astype(np.float32)
    Lm = np.median(labv[:, 0]) * 100 / 255
    bm = np.median(labv[:, 2]) - 128
    return math.degrees(math.atan2(Lm - 50, bm))


def noisy(lin, photons):
    """Shot + read noise at a photon scale (lower = darker sensor signal)."""
    sig = rng.poisson(np.clip(lin, 0, None) * photons).astype(np.float32) / photons
    return sig + rng.normal(0, 2.0 / photons, lin.shape).astype(np.float32)


def conditions(rgb_u8, label):
    lin = to_lin(rgb_u8)
    bg = (label == 0)[..., None]
    face = ~bg
    out = {'normal': rgb_u8}
    # Dark room, camera did not compensate: 1/5 of the light, sensor noise.
    out['dark'] = to_srgb_u8(noisy(lin * 0.2, 400))
    # Dark room, auto exposure brought the face back (x5 gain): bright enough but noisy.
    out['dark_ae'] = to_srgb_u8(noisy(lin * 0.2, 400) * 5.0)
    # Backlight: background x3 (clipped), face at 0.35.
    out['backlight'] = to_srgb_u8(np.where(bg, lin * 3.0, lin * 0.35))
    # Side light: horizontal gain 1.7 .. 0.55 across the frame.
    W = lin.shape[1]
    g = np.linspace(1.7, 0.55, W, dtype=np.float32)[None, :, None]
    out['uneven'] = to_srgb_u8(lin * g)
    # Warm (about 2700 K) and cool light over the whole scene.
    out['warm'] = to_srgb_u8(lin * np.array([1.0, 0.78, 0.5], np.float32))
    out['cool'] = to_srgb_u8(lin * np.array([0.72, 0.9, 1.2], np.float32))
    # Blown: x2.5 over the face.
    out['blown'] = to_srgb_u8(np.where(face, lin * 2.5, lin))
    return out


def wall(rgb_u8, label, colour):
    """A painted wall: 60 % of the background (the side away from the face centre) becomes a flat colour that keeps the
    original shading (luminance), same illuminant. The light did not change, so a light-colour estimate should not move."""
    lin = to_lin(rgb_u8)
    bg = label == 0
    H, W = label.shape
    xs = np.arange(W)[None, :].repeat(H, 0)
    fx = np.nonzero(label == 1)[1].mean() if (label == 1).any() else W / 2
    side = (xs < fx - 0.15 * W) | (xs > fx + 0.15 * W)
    m = bg & side
    shade = cv2.GaussianBlur(lum(lin), (0, 0), 6)[..., None]
    c = np.array(colour, np.float32)
    c = c / (0.2126 * c[0] + 0.7152 * c[1] + 0.0722 * c[2])
    paint = shade * c * (0.97 + 0.06 * rng.random(lin.shape[:2])[..., None])   # faint texture, few edges
    out = np.where(m[..., None], paint, lin)
    return to_srgb_u8(out)


WALLS = {'red': (0.55, 0.12, 0.10), 'green': (0.15, 0.45, 0.2), 'blue': (0.12, 0.2, 0.55), 'beige': (0.7, 0.55, 0.38)}


def main():
    root, out_csv = sys.argv[1], sys.argv[2]
    n_img = int(sys.argv[3]) if len(sys.argv) > 3 else 400
    files = sorted(glob.glob(os.path.join(root, 'labels', '*.png')))
    idx = rng.choice(len(files), size=min(n_img, len(files)), replace=False)
    rows = []
    for k, i in enumerate(sorted(idx)):
        lf = files[i]
        imf = lf.replace(os.sep + 'labels' + os.sep, os.sep + 'images' + os.sep).replace('labels/', 'images/')[:-4] + '.jpg'
        bgr = cv2.imread(imf); label = cv2.imread(lf, 0)
        if bgr is None or label is None:
            continue
        s = 720 / min(label.shape)
        if s < 1:
            bgr = cv2.resize(bgr, None, fx=s, fy=s, interpolation=cv2.INTER_AREA)
            label = cv2.resize(label, (bgr.shape[1], bgr.shape[0]), interpolation=cv2.INTER_NEAREST)
        rgb = cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)
        ita = ita_of(rgb, label)
        name = os.path.basename(lf)[:-4]
        for cond, img in conditions(rgb, label).items():
            rows.append(dict(img=name, ita=ita, cond=cond, **measure(img, label)))
        for wn, col in WALLS.items():
            rows.append(dict(img=name, ita=ita, cond='wall_' + wn, **measure(wall(rgb, label, col), label)))
        if k % 50 == 0:
            print(k, name, flush=True)
    with open(out_csv, 'w', newline='') as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader(); w.writerows(rows)
    print('rows', len(rows))


if __name__ == '__main__':
    main()

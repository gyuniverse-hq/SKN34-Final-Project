"""Which shader term makes each lip finish look wrong (lip finish plan, 2026-11-23).

    python research/makeup_gen/finish_metrics.py <finish dir> <out_json> [face ...]

<finish dir>/r_<face>/ holds off.png and <P>_<config>.png from ar_tune_render.mjs (P = G glossy, S satin, M matte). The
lip core comes from MediaPipe landmarks on that face's own off.png (outer minus inner lip, eroded 3 % of the mouth width,
as research/lip_texture). Definitions reused from research/lip_texture/metrics.py: fine (relative fine luminance), sparkles
(spots > 3 L* above their 2 px surround and less saturated), corr.

Per face x product:
  base        frost      = share of the lip core that is a sparkle, render minus the bare frame's own share (+ = added)
              patch_L / patch_C = std of the 6 px low-pass L* / chroma in the core (uneven colour, "얼룩")
              tex_ratio / tex_corr = fine luminance std vs bare, and its correlation with bare (wrinkles kept)
  <config>    layer      = L*(base) - L*(base with that term off), i.e. what the term adds
              area       = share of the core where the layer > 2 L*;  p99 = its 99th percentile (L*)
              upper_band = share of the positive layer that sits in the top 30 % of the upper lip (the band in the captures)
              follows    = correlation of the layer (linear light) with the bare lip's fine luminance (follows the lines)
"""
import json
import os
import sys

import cv2
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, '..', 'lip_texture'))
from eval_makeup import INNER, OUTER, landmarks  # noqa: E402
from metrics import corr, fine, l_star, lab_of, lum, sparkles, to_lin  # noqa: E402  (research/lip_texture)

UPPER_OUT = [61, 185, 40, 39, 37, 0, 267, 269, 270, 409, 291]
UPPER_IN = [308, 415, 310, 311, 312, 13, 82, 81, 80, 191, 78]


def masks(off_bgr):
    lm = landmarks(cv2.cvtColor(off_bgr, cv2.COLOR_BGR2RGB))
    h, w = off_bgr.shape[:2]
    m = np.zeros((h, w), np.uint8)
    cv2.fillPoly(m, [lm[OUTER].astype(np.int32)], 1)
    cv2.fillPoly(m, [lm[INNER].astype(np.int32)], 0)
    mw = float(np.linalg.norm(lm[291] - lm[61]))
    k = max(3, int(round(mw * 0.03)))
    core = cv2.erode(m, np.ones((k, k), np.uint8)) > 0
    up = np.zeros((h, w), np.uint8)
    cv2.fillPoly(up, [np.concatenate([lm[UPPER_OUT], lm[UPPER_IN]]).astype(np.int32)], 1)
    upper = (up > 0) & core
    band = np.zeros((h, w), bool)
    for x in np.where(upper.any(0))[0]:
        ys = np.where(upper[:, x])[0]
        top, bot = ys.min(), ys.max()
        band[ys[ys <= top + 0.3 * (bot - top + 1)], x] = True
    return core, upper, band, mw


def main():
    d, out_json = sys.argv[1], sys.argv[2]
    faces = sys.argv[3:] or sorted(x[2:] for x in os.listdir(d) if x.startswith('r_'))
    res = {}
    for face in faces:
        fd = os.path.join(d, 'r_' + face)
        off = cv2.imread(os.path.join(fd, 'off.png'))
        core, upper, band, mw = masks(off)
        bare = to_lin(off)
        yb = lum(bare)
        lab_b = lab_of(bare)
        fb = fine(yb)[core]
        sp_b = sparkles(lab_b, core)[core].mean()
        # an evenly spread layer would put this share in the band: the baseline for upper_band
        res[face] = {'mouth_px': round(mw, 1), 'band_share_of_core': round(float(band.sum() / core.sum()), 3)}
        for P in ('G', 'S', 'M'):
            bp = os.path.join(fd, f'{P}_base.png')
            if not os.path.exists(bp):
                continue
            base = to_lin(cv2.imread(bp))
            yr = lum(base)
            lab_r = lab_of(base)
            lowL = cv2.GaussianBlur(lab_r[..., 0], (0, 0), 6)
            lowC = cv2.GaussianBlur(np.hypot(lab_r[..., 1], lab_r[..., 2]), (0, 0), 6)
            fr = fine(yr)[core]
            r = {'base': {'frost': round(float(sparkles(lab_r, core)[core].mean() - sp_b), 4),
                          'patch_L': round(float(lowL[core].std()), 2), 'patch_C': round(float(lowC[core].std()), 2),
                          'tex_ratio': round(float(fr.std() / max(fb.std(), 1e-9)), 3), 'tex_corr': round(corr(fr, fb), 3)}}
            for f in sorted(os.listdir(fd)):
                if not f.startswith(P + '_') or f == f'{P}_base.png':
                    continue
                cfg = f[2:-4]
                g = to_lin(cv2.imread(os.path.join(fd, f)))
                yg = lum(g)
                layer = l_star(yr) - l_star(yg)
                lay = layer[core]
                pos = np.clip(layer, 0, None)
                r[cfg] = {'area': round(float((lay > 2).mean()), 4), 'p99': round(float(np.percentile(lay, 99)), 2),
                          'mean': round(float(lay.mean()), 2),
                          'upper_band': round(float(pos[band].sum() / max(pos[core].sum(), 1e-9)), 3),
                          'follows': round(corr((yr - yg)[core], fb), 3) if lay.std() > 1e-6 else None}
            res[face][P] = r
    json.dump({'rows': res}, open(out_json, 'w', encoding='utf-8'), indent=1)
    print('band share of the core (even spread):', {f: v['band_share_of_core'] for f, v in res.items()})
    # mean over faces
    agg = {}
    for face, fr_ in res.items():
        for P, r in fr_.items():
            if P in ('mouth_px', 'band_share_of_core'):
                continue
            for cfg, v in r.items():
                for k, x in v.items():
                    if x is not None:
                        agg.setdefault((P, cfg, k), []).append(x)
    for P in ('M', 'G', 'S'):
        print('==', P)
        for cfg in ['base'] + sorted({c for (p, c, _) in agg if p == P and c != 'base'}):
            ks = [k for (p, c, k) in agg if p == P and c == cfg]
            print('  ', cfg.ljust(12), ' '.join(f'{k}={np.mean(agg[(P, cfg, k)]):.3f}' for k in ks))


if __name__ == '__main__':
    main()

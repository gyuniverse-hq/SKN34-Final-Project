"""Score the lip finish candidates (lip finish plan step 3, 2026-11-23).

    python research/makeup_gen/finish_candidates.py <finish dir> <out_json>

<finish dir>/c_<face>/<P>_<candidate>.png from ar_tune_render.mjs with patches.json (experimental glossScale / sheenScale /
rimTilt material fields), scored against the same face's step-2 renders in r_<face>/: off.png (bare) and <P>_alloff.png (every
shine term off, the colour alone). Per candidate, same definitions as finish_metrics.py:
  shine layer = L*(candidate) - L*(colour alone): area (> 2 L*), p99, mean, upper_band (share in the top 30 % of the upper
  lip; an even spread gives the face's band_share_of_core), follows (correlation with the bare lip's fine luminance)
  frost, tex_ratio, tex_corr as in finish_metrics.py
  dE_colour = CIEDE2000 of the lip-core mean colour against the A_base candidate (the colour must not move)
"""
import json
import os
import sys

import cv2
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, '..', 'lip_texture'))
from finish_metrics import masks  # noqa: E402
from metrics import corr, de2000, fine, l_star, lab_of, lum, sparkles, to_lin  # noqa: E402  (research/lip_texture)


def main():
    d, out_json = sys.argv[1:3]
    faces = sorted(x[2:] for x in os.listdir(d) if x.startswith('c_'))
    rows = {}
    for face in faces:
        off = cv2.imread(os.path.join(d, 'r_' + face, 'off.png'))
        core, upper, band, mw = masks(off)
        bare = to_lin(off)
        fb = fine(lum(bare))[core]
        sp_b = sparkles(lab_of(bare), core)[core].mean()
        rows[face] = {'band_share_of_core': round(float(band.sum() / core.sum()), 3)}
        for P in ('M', 'G', 'S'):
            ref = to_lin(cv2.imread(os.path.join(d, 'r_' + face, f'{P}_alloff.png')))
            y0 = lum(ref)
            base_mean = None
            for f in sorted(x for x in os.listdir(os.path.join(d, 'c_' + face)) if x.startswith(P + '_') and x.endswith('.png')):
                cand = f[2:-4]
                img = to_lin(cv2.imread(os.path.join(d, 'c_' + face, f)))
                y = lum(img)
                lab = lab_of(img)
                mean_lab = lab[core].mean(0)
                if cand == 'A_base':
                    base_mean = mean_lab
                layer = l_star(y) - l_star(y0)
                lay = layer[core]
                pos = np.clip(layer, 0, None)
                fr = fine(y)[core]
                rows[face].setdefault(P, {})[cand] = {
                    'area': round(float((lay > 2).mean()), 4), 'p99': round(float(np.percentile(lay, 99)), 2),
                    'mean': round(float(lay.mean()), 2),
                    'upper_band': round(float(pos[band].sum() / max(pos[core].sum(), 1e-9)), 3),
                    'follows': round(corr((y - y0)[core], fb), 3),
                    'frost': round(float(sparkles(lab, core)[core].mean() - sp_b), 4),
                    'tex_ratio': round(float(fr.std() / max(fb.std(), 1e-9)), 3), 'tex_corr': round(corr(fr, fb), 3),
                    'dE_colour': round(de2000(base_mean, mean_lab), 2) if base_mean is not None else None}
    json.dump(rows, open(out_json, 'w', encoding='utf-8'), indent=1)
    keys = ['area', 'p99', 'mean', 'upper_band', 'follows', 'frost', 'tex_ratio', 'dE_colour']
    print('even-spread band share:', {f: v['band_share_of_core'] for f, v in rows.items()})
    for P in ('M', 'G', 'S'):
        print('==', P, ' '.join(k.rjust(10) for k in keys))
        cands = sorted({c for f in rows for c in rows[f].get(P, {})})
        for c in cands:
            vals = [np.mean([rows[f][P][c][k] for f in rows if rows[f][P][c][k] is not None]) for k in keys]
            print('  ', c.ljust(32), ' '.join(f'{v:10.3f}' for v in vals))


if __name__ == '__main__':
    main()

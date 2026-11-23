"""How far an AR lip render is from the FPMT "really applied" target on the same frame (8회차 멘토링 후속 5단계, 2026-11-23).

    python research/makeup_gen/fpmt_gap.py <bare AR-off frame> <target colour-only> <target full> <out_json> <render> [<render> ...]

Target = FPMT (reference: the worn photo E) run on the AR's own bare frame, put back on the frame (`fpmt_in_ar/`,
`out_fpmt_ar/`); colour-only keeps the bare skin and lip outline and takes FPMT's lip colour (region_composite delta).
Per render, inside the bare frame's lip mask:
  pix_dE00_vs_target   mean per-pixel CIEDE2000 to the colour-only target (colour and texture together, lower = closer)
  lip_dE00_vs_target   CIEDE2000 of the lip medians (colour only)
  outside_dE00         mean CIEDE2000 to the bare frame on the face outside the lip (dilated 7 px): must stay ~0
  wrinkle_corr / wrinkle_strength (no gloss spots) and gloss_spot_share against the bare frame, texture_metric.py's
  definitions; the same three for the full FPMT target are the texture the render should approach.
"""
import json
import os
import sys

import cv2
import numpy as np
from skimage.color import deltaE_ciede2000, rgb2lab

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from eval_makeup import landmarks, lip_lab, lip_mask, load  # noqa: E402
from texture_metric import measure, prep  # noqa: E402


def main():
    bare_p, tgt_p, full_p, out_json, *renders = sys.argv[1:]
    bare = load(bare_p)
    lm = landmarks(bare)
    m = lip_mask(bare, lm)
    ref = prep(bare)
    tgt = load(tgt_p)
    tgt_lab = rgb2lab(tgt)
    t_med = lip_lab(tgt, m)[0]

    hull = np.zeros(m.shape, np.uint8)
    cv2.fillPoly(hull, [cv2.convexHull(lm.astype(np.int32))], 1)
    outside = (hull > 0) & ~(cv2.dilate(m.astype(np.uint8), np.ones((15, 15), np.uint8)) > 0)
    bare_lab = rgb2lab(bare)

    def row(img):
        lab = rgb2lab(img)
        r, _ = measure(img, ref, False)
        return {'outside_dE00': round(float(deltaE_ciede2000(lab[outside], bare_lab[outside]).mean()), 3),
                'pix_dE00_vs_target': round(float(deltaE_ciede2000(lab[m], tgt_lab[m]).mean()), 2),
                'lip_dE00_vs_target': round(float(deltaE_ciede2000(lip_lab(img, m)[0][None], t_med[None])[0]), 2),
                'lip_lab_median': [round(float(v), 1) for v in lip_lab(img, m)[0]],
                'wrinkle_corr': r['wrinkle_corr_nohl'], 'wrinkle_strength': r['wrinkle_energy_nohl'],
                'gloss_spot_share': r['highlight_share']}

    res = {'bare': bare_p, 'target_colour_only': tgt_p, 'target_lip_lab_median': [round(float(v), 1) for v in t_med],
           'target_full_texture': {k: v for k, v in row(load(full_p)).items() if k in ('wrinkle_corr', 'wrinkle_strength', 'gloss_spot_share')},
           'bare_vs_target': row(bare), 'rows': {}}
    for p in renders:
        res['rows'][os.path.basename(p)] = row(load(p))
    json.dump(res, open(out_json, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    print('target lip Lab', res['target_lip_lab_median'], '| FPMT texture', res['target_full_texture'])
    print('bare'.ljust(34), res['bare_vs_target'])
    for k, v in res['rows'].items():
        print(k.ljust(34), v)


if __name__ == '__main__':
    main()

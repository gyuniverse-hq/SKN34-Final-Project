"""Lip texture kept or wiped (8회차 멘토링 후속 2단계, 2026-11-23).

    python research/makeup_gen/texture_metric.py <root=research/data/makeup_gen> <out_json> [fig.png]

For each variant and its bare baseline (AR: the AR-off frame of the same session; models and composites: the bare crop A):
  1. The output is aligned to the baseline on the 40 lip landmarks when it is a model output (its face moved); AR frames and
     composites already share the baseline's pixels.
  2. Both are cropped to the baseline's lip box and resampled to a 400 px wide lip, so every variant is measured at one scale.
  3. Inside the baseline lip mask, eroded 3 px so the lip outline does not dominate, CIELAB L* is split into two bands:
       fine    = L - G(sigma 2)            pores, fine lines
       wrinkle = G(sigma 2) - G(sigma 6)   vertical lip lines, the scale the eye reads as "lip texture"
  4. corr   = Pearson correlation of the band with the baseline's band (1 = the same texture, 0 = unrelated)
     energy = std of the band / the baseline's std (1 = as strong, < 1 = flattened, > 1 = added)
     *_nohl = the same without highlight pixels (L* raised > 8 above the lip's median change): a gloss spot adds band energy
              that is not the lip's own texture (seen in the 11-23 figure).
E (the worn photo) is another capture, so only its energy against A is given (no alignment, different light and camera).
"""
import glob
import json
import os
import sys

import cv2
import numpy as np
from PIL import Image
from skimage.color import rgb2lab

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from eval_makeup import OUTER, landmarks, lip_mask, load  # noqa: E402
from region_composite import align  # noqa: E402

LIP_W = 400


def lip_box(lm, shape):
    x0, y0 = lm[OUTER].min(0)
    x1, y1 = lm[OUTER].max(0)
    px, py = 0.15 * (x1 - x0), 0.3 * (y1 - y0)
    h, w = shape[:2]
    return [max(0, int(x0 - px)), max(0, int(y0 - py)), min(w, int(x1 + px)), min(h, int(y1 + py))]


def bands(img, box, size):
    crop = np.asarray(Image.fromarray(img).crop(box).resize(size, Image.LANCZOS))
    L = rgb2lab(crop)[..., 0]
    g2 = cv2.GaussianBlur(L, (0, 0), 2)
    g6 = cv2.GaussianBlur(L, (0, 0), 6)
    return {'fine': L - g2, 'wrinkle': g2 - g6}, crop


def prep(base):
    lm = landmarks(base)
    box = lip_box(lm, base.shape)
    size = (LIP_W, max(8, round(LIP_W * (box[3] - box[1]) / (box[2] - box[0]))))
    m = np.asarray(Image.fromarray(lip_mask(base, lm).astype(np.uint8) * 255).crop(box).resize(size, Image.NEAREST)) > 127
    m = cv2.erode(m.astype(np.uint8), np.ones((7, 7), np.uint8)) > 0
    b, crop = bands(base, box, size)
    return {'lm': lm, 'box': box, 'size': size, 'mask': m, 'bands': b, 'L': rgb2lab(crop)[..., 0]}


def measure(img, ref, do_align):
    if do_align:
        img, _, _ = align(img, landmarks(img), ref['lm'])
    o, crop = bands(img, ref['box'], ref['size'])
    m = ref['mask']
    # highlight pixels: lifted more than 8 L* above the lip's typical change (a gloss spot, not texture)
    dL = rgb2lab(crop)[..., 0] - ref['L']
    hl = dL > np.median(dL[m]) + 8
    out = {'highlight_share': round(float(hl[m].mean()), 3)}
    for k in ('fine', 'wrinkle'):
        for tag, mm in (('', m), ('_nohl', m & ~hl)):
            a, b = ref['bands'][k][mm], o[k][mm]
            out[k + '_corr' + tag] = round(float(np.corrcoef(a, b)[0, 1]), 3)
            out[k + '_energy' + tag] = round(float(b.std() / max(a.std(), 1e-6)), 3)
    return out, o['wrinkle']


def main():
    root, out_json = sys.argv[1], sys.argv[2]
    fig = sys.argv[3] if len(sys.argv) > 3 else None
    A = load(os.path.join(root, 'input/bare_crop_1024.png'))
    A5 = np.asarray(Image.fromarray(A).resize((512, 512), Image.LANCZOS))
    refs = {'A1024': prep(A), 'A512': prep(A5),
            'off_default': prep(load(os.path.join(root, 'ar_out/ar_off_0.png'))),
            'off_sweep': prep(load(os.path.join(root, 'ar_out_sweep/ar_off_0.png')))}
    items = []   # (group, name, path, ref, align)
    for p in sorted(glob.glob(os.path.join(root, 'ar_out/ar_lip_*.png'))):
        items.append(('B AR default #C77276 glossy 0.65', os.path.basename(p), p, 'off_default', False))
    for p in sorted(glob.glob(os.path.join(root, 'ar_out_sweep/sweep_*.png'))):
        if 'glow' in p:   # glow is not a lip texture; it rendered as matte (11-20 report)
            continue
        tag = os.path.basename(p)[6:-4]
        hexv = '#C77276' if tag.startswith('off_') else '#A26263'
        _, _, tex, inten = tag.split('_')
        items.append((f'B AR {hexv} {tex} {int(inten) / 100:.2f}', os.path.basename(p), p, 'off_sweep', False))
    for p in sorted(glob.glob(os.path.join(root, 'out_magicmakeup/magicmakeup_seed*.png'))):
        items.append(('C MagicMakeup (lip)', os.path.basename(p), p, 'A1024', True))
    for p in sorted(glob.glob(os.path.join(root, 'out_stable_makeup/stablemakeup_seed*.png'))):
        items.append(('D Stable-Makeup raw (512)', os.path.basename(p), p, 'A512', True))
    for kind, label in (('paste', 'A paste'), ('delta', 'B colour only')):
        for p in sorted(glob.glob(os.path.join(root, f'out_composite/stablemakeup_{kind}_seed*_512.png'))):
            items.append((f'D Stable-Makeup + {label} (512)', os.path.basename(p), p, 'A512', False))
    fp = os.path.join(root, 'out_fpmt/fpmt_seed0.png')   # FPMT mapped back onto the bare 512 frame (run_fpmt.py _srcframe)
    if os.path.exists(fp):
        items.append(('F FPMT raw (512)', 'fpmt_srcframe', fp, 'A512', False))
        for kind, label in (('paste', 'A paste'), ('delta', 'B colour only')):
            p = os.path.join(root, f'out_composite_fpmt/fpmt_{kind}_seed0_512.png')
            if os.path.exists(p):
                items.append((f'F FPMT + {label} (512)', os.path.basename(p), p, 'A512', False))
    res = {'method': __doc__.strip().split('\n\n')[2] if __doc__ else '', 'lip_width_px': LIP_W, 'rows': {}, 'groups': {}}
    maps = {}
    for group, name, p, ref, al in items:
        r, wm = measure(load(p), refs[ref], al)
        res['rows'][name] = dict(group=group, **r)
        maps.setdefault(group, wm)
    keys = ['highlight_share', 'fine_corr', 'fine_energy', 'wrinkle_corr', 'wrinkle_energy',
            'wrinkle_corr_nohl', 'wrinkle_energy_nohl']
    for g in dict.fromkeys(i[0] for i in items):
        rows = [v for v in res['rows'].values() if v['group'] == g]
        res['groups'][g] = {k: [round(float(np.mean([r[k] for r in rows])), 3), round(float(np.min([r[k] for r in rows])), 3),
                                round(float(np.max([r[k] for r in rows])), 3)] for k in keys} | {'n': len(rows)}
    # E: another capture; energy only, against A's own lip at the same 400 px scale
    E = load(os.path.join(root, 'input/ref_crop_1024.png'))
    eref = prep(E)
    res['E_worn_energy_vs_A'] = {k: round(float(eref['bands'][k][eref['mask']].std() / refs['A1024']['bands'][k][refs['A1024']['mask']].std()), 3)
                                 for k in ('fine', 'wrinkle')}
    json.dump(res, open(out_json, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    for g, v in res['groups'].items():
        print(g.ljust(42), json.dumps(v))
    print('E worn energy vs A', res['E_worn_energy_vs_A'])
    if fig:   # wrinkle band of the baseline and one sample per group, same grey scale
        pick = ['B AR default #C77276 glossy 0.65', 'B AR #A26263 matte 0.50', 'C MagicMakeup (lip)',
                'D Stable-Makeup raw (512)', 'D Stable-Makeup + B colour only (512)']
        tiles = [('A bare (AR-off frame)', refs['off_default']['bands']['wrinkle'])] + [(g, maps[g]) for g in pick if g in maps]
        rows = []
        for label, wm in tiles:
            t = np.clip(128 + wm * 25, 0, 255).astype(np.uint8)
            t = cv2.resize(t, (LIP_W, round(LIP_W * t.shape[0] / t.shape[1])))
            bar = np.full((24, LIP_W), 255, np.uint8)
            cv2.putText(bar, label[:52], (4, 17), cv2.FONT_HERSHEY_SIMPLEX, 0.42, 0, 1, cv2.LINE_AA)
            rows.append(np.vstack([bar, t]))
        h = max(r.shape[0] for r in rows)
        rows = [np.vstack([r, np.full((h - r.shape[0], LIP_W), 255, np.uint8)]) for r in rows]
        grid = [np.hstack(rows[i:i + 3] + [np.full((h, LIP_W), 255, np.uint8)] * (3 - len(rows[i:i + 3]))) for i in range(0, len(rows), 3)]
        Image.fromarray(np.vstack(grid)).save(fig)


if __name__ == '__main__':
    main()

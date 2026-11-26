"""Put only the lip region of a whole-face makeup transfer back onto the bare face (8회차 멘토링, 2026-11-23).

    python research/makeup_gen/region_composite.py <root=research/data/makeup_gen> <src_dir> <prefix> <out_dir> [noalign]

`noalign`: the output already sits on the bare photo's pixels (FPMT _srcframe). Landmarks on a recoloured lip move ~1 px and a
lip-landmark fit then shifts the image by up to 4 px (11-23 FPMT check), so it is skipped.

e.g. src_dir=out_stable_makeup, prefix=stablemakeup_seed -> uses stablemakeup_seed0..2.png (any size; each is resized to the
bare-face size first). Two post-processes, both on the bare face A (the model input crop), never on the model output:

  paste (A): the output's lip pixels, aligned to A's lip landmarks (partial affine on the 40 lip points), feathered alpha.
  delta (B): colour only. Inside the lip, Lab difference (output - A): L* as one shift (difference of the lip medians), a*/b* per pixel smoothed
             (normalised Gaussian, sigma 2 px @512) so the output's own lip texture is not carried over; A keeps its texture.

Both are post-processing results, not model outputs. Metrics are eval_makeup.compare against A at 512 and at 1024, the same
rows and definitions as the 11-20 report (lip dE00 vs the worn photo E, outside-lip dE00 / SSIM, IoU, boundary F1, bleed).
"""
import json
import os
import sys

import cv2
import numpy as np
from PIL import Image
from skimage.color import lab2rgb, rgb2lab

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from eval_makeup import INNER, OUTER, compare, face_mask_from, landmarks, lip_lab, lip_mask, load, pix_sha  # noqa: E402

LIP_IDX = OUTER + INNER


def align(out, out_lm, base_lm):
    """Warp the output so its lip landmarks sit on the bare face's (rotation + scale + shift only)."""
    M, _ = cv2.estimateAffinePartial2D(out_lm[LIP_IDX], base_lm[LIP_IDX], method=cv2.LMEDS)
    h, w = out.shape[:2]
    warped = cv2.warpAffine(out, M, (w, h), flags=cv2.INTER_LANCZOS4, borderMode=cv2.BORDER_REFLECT)
    shift = float(np.linalg.norm(out_lm[LIP_IDX] - base_lm[LIP_IDX], axis=1).mean())
    return warped, M, shift


def feather(mask, px):
    return cv2.GaussianBlur(mask.astype(np.float32), (0, 0), px)


def smooth_in_mask(v, mask, sigma):
    m = mask.astype(np.float32)
    num = cv2.GaussianBlur(v * m, (0, 0), sigma)
    den = cv2.GaussianBlur(m, (0, 0), sigma)
    return np.where(den > 1e-3, num / np.maximum(den, 1e-3), 0)


def composite(base, out, base_lm, do_align=True):
    out_lm = landmarks(out)
    if do_align:
        warped, M, shift = align(out, out_lm, base_lm)
    else:
        from eval_makeup import OUTER as _O, INNER as _I
        warped, M = out, np.float32([[1, 0, 0], [0, 1, 0]])
        shift = float(np.linalg.norm(out_lm[_O + _I] - base_lm[_O + _I], axis=1).mean())
    s = base.shape[0] / 512
    m = lip_mask(base, base_lm)
    alpha = feather(m, 1.5 * s)[..., None]          # about 3 px wide edge at 512
    paste = np.clip(base * (1 - alpha) + warped * alpha, 0, 255).round().astype(np.uint8)

    lab_b, lab_o = rgb2lab(base), rgb2lab(warped)
    d = lab_o - lab_b
    shift_lab = np.zeros_like(lab_b)
    # one brightness shift = difference of the lip medians (a median of per-pixel differences ran ~1 L* darker)
    shift_lab[..., 0] = np.median(lab_o[..., 0][m]) - np.median(lab_b[..., 0][m])
    shift_lab[..., 1] = smooth_in_mask(d[..., 1], m, 2 * s)
    shift_lab[..., 2] = smooth_in_mask(d[..., 2], m, 2 * s)
    delta_rgb = (lab2rgb(lab_b + shift_lab) * 255)
    delta = np.clip(base * (1 - alpha) + delta_rgb * alpha, 0, 255).round().astype(np.uint8)
    info = {'lip_landmark_shift_px_before_align': round(shift, 2),
            'affine': [[round(float(x), 4) for x in row] for row in M],
            'L_shift_median': round(float(shift_lab[..., 0][m][0]), 2) if m.any() else None,
            'ab_shift_mean_in_lip': [round(float(shift_lab[..., 1][m].mean()), 2), round(float(shift_lab[..., 2][m].mean()), 2)]}
    return paste, delta, info


def lip_crop(img, pad=0.35, size=(360, 180)):
    lm = landmarks(img)
    x0, y0 = lm[OUTER].min(0)
    x1, y1 = lm[OUTER].max(0)
    w, h = x1 - x0, y1 - y0
    cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
    half_w = w * (0.5 + pad)
    half_h = half_w * size[1] / size[0]
    box = [int(cx - half_w), int(cy - half_h), int(cx + half_w), int(cy + half_h)]
    return np.asarray(Image.fromarray(img).crop(box).resize(size, Image.LANCZOS))


def make_fig(panels, path):
    """panels: [(label, image)] -> one row of lip close-ups with a caption strip (cv2 text, ASCII labels)."""
    tiles = []
    for label, img in panels:
        t = lip_crop(img).copy()
        bar = np.full((28, t.shape[1], 3), 255, np.uint8)
        cv2.putText(bar, label, (6, 20), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 0, 0), 1, cv2.LINE_AA)
        tiles.append(np.vstack([bar, t]))
    Image.fromarray(np.hstack(tiles)).save(path)


def main():
    root, src, prefix, out_dir = sys.argv[1:5]
    do_align = 'noalign' not in sys.argv[5:]
    os.makedirs(out_dir, exist_ok=True)
    inp = os.path.join(root, 'input')
    A = load(os.path.join(inp, 'bare_crop_1024.png'))
    E = load(os.path.join(inp, 'ref_crop_1024.png'))
    E_lab = lip_lab(E, lip_mask(E, landmarks(E)))[0]
    face_mask = os.path.join(root, 'out_magicmakeup/masks/bare_crop_1024.png')
    bases = {1024: A, 512: np.asarray(Image.fromarray(A).resize((512, 512), Image.LANCZOS))}   # 512 = the 11-20 D baseline
    res = {'inputs': {}, 'rows': {}, 'info': {}}
    for seed in range(3):
        p = os.path.join(root, src, f'{prefix}{seed}.png')
        if not os.path.exists(p):
            continue
        raw = load(p)
        res['inputs'][f'{prefix}{seed}'] = {'size': list(raw.shape[:2][::-1]), 'pixel_sha256': pix_sha(raw)}
        for size, base in bases.items():
            base_lm = landmarks(base)
            face = face_mask_from(face_mask, base.shape[:2])
            out = raw if raw.shape[0] == size else np.asarray(Image.fromarray(raw).resize((size, size), Image.LANCZOS))
            paste, delta, info = composite(base, out, base_lm, do_align)
            res['info'][f'seed{seed}_{size}'] = info
            for tag, img in (('raw', out), ('paste', paste), ('delta', delta)):
                name = f'{tag}_seed{seed}_{size}'
                if tag != 'raw':
                    Image.fromarray(img).save(os.path.join(out_dir, f'{prefix.removesuffix("_seed")}_{name}.png'))
                r, _ = compare(name, img, base, base_lm, face, E_lab)
                res['rows'][name] = r
    keys = ['dE00_lip_vs_E_real', 'dE00_lip_vs_bare', 'change_dE00_mean_outside_lip(face)', 'SSIM_outside_lip(face)',
            'lip_shape_IoU_vs_bare', 'bleed_ratio(changed outside lip / all changed)']
    summ = {}
    for tag in ('raw', 'paste', 'delta'):
        for size in (512, 1024):
            rows = [v for k, v in res['rows'].items() if k.startswith(tag + '_') and k.endswith(f'_{size}') and 'error' not in v]
            if rows:
                summ[f'{tag}_{size}'] = {k: [round(float(np.mean([r[k] for r in rows])), 3), round(float(np.min([r[k] for r in rows])), 3),
                                             round(float(np.max([r[k] for r in rows])), 3)] for k in keys}
    res['summary_mean_min_max'] = summ
    # seed 0 at 1024: bare / raw output / paste / delta / worn photo
    stem = prefix.removesuffix('_seed')
    raw0 = os.path.join(root, src, f'{prefix}0.png')
    if os.path.exists(raw0):
        r0 = np.asarray(Image.fromarray(load(raw0)).resize((1024, 1024), Image.LANCZOS))
        make_fig([('A bare', A), ('raw output', r0),
                  ('paste (A)', load(os.path.join(out_dir, f'{stem}_paste_seed0_1024.png'))),
                  ('colour only (B)', load(os.path.join(out_dir, f'{stem}_delta_seed0_1024.png'))), ('E worn', E)],
                 os.path.join(out_dir, f'fig_{stem}_lip_zoom.png'))
    json.dump(res, open(os.path.join(out_dir, 'metrics_composite.json'), 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    for k, v in summ.items():
        print(k, json.dumps(v, ensure_ascii=False))


if __name__ == '__main__':
    main()

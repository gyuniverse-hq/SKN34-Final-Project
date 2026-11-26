"""Still faces for lip finish checks (2026-11-23, lip finish plan step 1).

    python research/makeup_gen/prep_faces.py <lapa test images dir> <out_dir> [n=4] [scan=400] [names=a.jpg,b.jpg,...]

Scans the first `scan` LaPa test images (sorted, deterministic) with MediaPipe Face Landmarker and keeps faces that are
frontal (nose tip within 6 % of the eye-to-eye distance from the eye midline), mouth closed (inner lip gap < 4 % of the
mouth width) and large enough (source mouth width >= 90 px). Each is cropped to a 3:4 selfie frame with the face about
half the frame width and resized to 720x960, like a phone front camera; where that frame runs past the photo (LaPa crops are tight)
the border pixels are replicated, at most a quarter of the frame width. Picks `n` across the range of cheek lightness
(L*), so pale to deep skin and different lip shapes are covered. Writes <name>.png and faces.json (source, crop, L*).
With names the automatic pick is replaced by that list (still checked by the same filters). 11-23 choice by eye from the
passed faces: adults only (the automatic pick included a child) and no beard over the lips:
12036895386_1 (pale), 12819972853_0 (medium), 3013103_0 (East Asian), 2741926959_0 (deep; the only deep-skin adult among 75 passed).
LaPa is non-commercial research data; the crops stay under the git-ignored research/data/.
"""
import glob
import json
import os
import sys

import numpy as np
from PIL import Image
from skimage.color import rgb2lab

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from eval_makeup import INNER, OUTER, landmarks  # noqa: E402


def main():
    src, out = sys.argv[1], sys.argv[2]
    n = int(sys.argv[3]) if len(sys.argv) > 3 else 4
    scan = int(sys.argv[4]) if len(sys.argv) > 4 else 400
    os.makedirs(out, exist_ok=True)
    cands = []
    stats = {'noface': 0, 'yaw': 0, 'mouth': 0, 'pad': 0}
    names = sys.argv[5].split(',') if len(sys.argv) > 5 else None
    files = [os.path.join(src, x) for x in names] if names else sorted(glob.glob(os.path.join(src, '*.jpg')))[:scan]
    for p in files:
        img = np.asarray(Image.open(p).convert('RGB'))
        lm = landmarks(img)
        if lm is None:
            stats['noface'] += 1
            continue
        eyeL, eyeR, nose = lm[33], lm[263], lm[1]
        iod = np.linalg.norm(eyeR - eyeL)
        mid = (eyeL + eyeR) / 2
        axis = (eyeR - eyeL) / iod
        if abs(np.dot(nose - mid, axis)) > 0.06 * iod:
            stats['yaw'] += 1
            continue
        mouth_w = np.linalg.norm(lm[291] - lm[61])
        if mouth_w < 90 or np.linalg.norm(lm[13] - lm[14]) > 0.04 * mouth_w:
            stats['mouth'] += 1
            continue
        x0, y0 = lm[:, 0].min(), lm[:, 1].min()
        x1, y1 = lm[:, 0].max(), lm[:, 1].max()
        fw = x1 - x0
        W = fw / 0.5
        H = W * 4 / 3
        cx, cy = (x0 + x1) / 2, (y0 + y1) / 2 + 0.05 * H
        box = [int(cx - W / 2), int(cy - H / 2), int(cx + W / 2), int(cy + H / 2)]
        pad = max(0, -box[0], -box[1], box[2] - img.shape[1], box[3] - img.shape[0])
        if pad > (0.4 if names else 0.25) * W:   # most of the frame would be invented border (hand-picked faces: lips are central, 0.4)
            stats['pad'] += 1
            continue
        cheek = img[int(lm[50][1]) - 3:int(lm[50][1]) + 4, int(lm[50][0]) - 3:int(lm[50][0]) + 4]
        L = float(rgb2lab(cheek.reshape(-1, 1, 3) / 255.0)[..., 0].mean())
        cands.append({'source': os.path.basename(p), 'crop': box, 'cheek_L': round(L, 1), 'mouth_w_src': round(float(mouth_w), 1)})
    cands.sort(key=lambda c: c['cheek_L'])
    print('dropped', stats)
    if not cands:
        raise SystemExit('no face passed')
    if names:
        if len(cands) != len(names):
            raise SystemExit('a named face failed the filters: ' + str(stats))
        pick = sorted(cands, key=lambda c: names.index(c['source']))
    else:
        pick = [cands[round(i * (len(cands) - 1) / max(n - 1, 1))] for i in range(n)]
    for i, c in enumerate(pick):
        a = np.asarray(Image.open(os.path.join(src, c['source'])).convert('RGB'))
        x0, y0, x1, y1 = c['crop']
        P = max(0, -x0, -y0, x1 - a.shape[1], y1 - a.shape[0])
        a = np.pad(a, ((P, P), (P, P), (0, 0)), mode='edge')   # border replicated where the frame runs past the photo
        im = Image.fromarray(a[y0 + P:y1 + P, x0 + P:x1 + P]).resize((720, 960), Image.LANCZOS)
        c['name'] = f'lapa{i}'
        im.save(os.path.join(out, c['name'] + '.png'))
    json.dump({'scanned': scan, 'passed': len(cands), 'faces': pick}, open(os.path.join(out, 'faces.json'), 'w'), indent=1)
    print(len(cands), 'passed;', [(c['name'], c['source'], c['cheek_L']) for c in pick])


if __name__ == '__main__':
    main()

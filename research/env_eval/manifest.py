"""Source list and fixed split for the AR environment experiments (11-19, rerun for the threshold report).

Rebuilds exactly the images the measurement scripts pick, hashes them, and assigns each ORIGINAL image to one split
(select 60 % / tune 20 % / test 20 %, fixed seed). Synthetic variants of an image always stay in its split, because the
split key is the image name, not the variant.

    python research/env_eval/manifest.py <lapa_test_dir> <skin_tone_dir> <out_dir>

Writes <out_dir>/manifest.csv: dataset, img (name used in the measurement CSVs), tone, path, sha1, split, source, license.
- LaPa: the same 400 the measurement script draws (numpy default_rng(7), first draw = rng.choice over the sorted labels).
- Roboflow skin-tone-9drvk: per class (dark / fair / light) the first 200 of the sorted file list, split per class.
  No person ID exists in that set, so the same person could sit in two splits (a stated limit).
"""
import csv
import glob
import hashlib
import os
import sys

import numpy as np

SEED_SPLIT = 20261119
FRACTIONS = (0.6, 0.2, 0.2)


def sha1(path):
    h = hashlib.sha1()
    with open(path, 'rb') as f:
        for chunk in iter(lambda: f.read(1 << 20), b''):
            h.update(chunk)
    return h.hexdigest()


def assign(names, seed):
    order = np.random.default_rng(seed).permutation(len(names))
    n = len(names)
    a, b = int(round(n * FRACTIONS[0])), int(round(n * (FRACTIONS[0] + FRACTIONS[1])))
    split = {}
    for rank, i in enumerate(order):
        split[names[i]] = 'select' if rank < a else 'tune' if rank < b else 'test'
    return split


def main():
    lapa_root, skin_root, out_dir = sys.argv[1:4]
    os.makedirs(out_dir, exist_ok=True)
    rows = []
    # LaPa: mirror lapa_env_eval.main (rng = default_rng(7); idx = rng.choice(len(files), 400, replace=False)).
    files = sorted(glob.glob(os.path.join(lapa_root, 'labels', '*.png')))
    rng = np.random.default_rng(7)
    idx = sorted(rng.choice(len(files), size=min(400, len(files)), replace=False))
    names = [os.path.basename(files[i])[:-4] for i in idx]
    sp = assign(names, SEED_SPLIT)
    for n in names:
        p = os.path.join(lapa_root, 'images', n + '.jpg')
        rows.append(dict(dataset='lapa', img=n, tone='', path=os.path.relpath(p), sha1=sha1(p), split=sp[n],
                         source='LaPa test (Liu et al., AAAI 2020)', license='research, non-commercial'))
    # Roboflow skin tone: mirror skin_tone_env_eval.main (sorted(glob(root/*/cls/*))[:200]).
    for k, cls in enumerate(['dark', 'fair', 'light']):
        fs = sorted(glob.glob(os.path.join(skin_root, '*', cls, '*')))[:200]
        sp = assign([os.path.basename(f) for f in fs], SEED_SPLIT + 1 + k)
        for f in fs:
            b = os.path.basename(f)
            rows.append(dict(dataset='roboflow_skin_tone', img=b[:40], tone=cls, path=os.path.relpath(f), sha1=sha1(f),
                             split=sp[b], source='Roboflow Universe face-detection-beautysense/skin-tone-9drvk v1',
                             license='CC BY 4.0'))
    with open(os.path.join(out_dir, 'manifest.csv'), 'w', newline='', encoding='utf-8') as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
        w.writeheader(); w.writerows(rows)
    from collections import Counter
    print('rows', len(rows), dict(Counter((r['dataset'], r['tone'], r['split']) for r in rows)))


if __name__ == '__main__':
    main()

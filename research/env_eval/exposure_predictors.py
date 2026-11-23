"""Step 5-b (11-19): which measure can stand in for 'how bright is the light' in uExposure without reading the skin tone as dim light.

    python research/env_eval/exposure_predictors.py <run_dir> <out.json>

Today uExposure = skin / 0.34 (clamped 0.2..1.6): a dark skin tone in normal light already reads 0.3, a dark room on fair skin 0.2.
What the makeup should follow is the brightness of the CAMERA PICTURE the light gives, independent of the skin's reflectance:
  - normal light: 1 for every skin tone;
  - dark room, no auto exposure (synthetic light x0.2): 0.2 of the same photo's normal value;
  - dark room with auto exposure (picture brightened back): about 1 (the picture looks normal, only noisier).
Candidates (no fitted constants besides the 0.18 mid-grey an auto-exposed picture aims at):
  S  skin / 0.34                      (today)
  F  frame / 0.18                     (whole picture mean, linear)
  Q  bg-or-frame: background mean / 0.18 where the segmenter background is big enough, else F
  M  sqrt(S * F)
  R  session-relative skin: skin / skin at the first settled sample, floored by F   (min(skin/ref, F))
Per skin tone (dark / fair / light from Roboflow, LaPa as one group), test split only, medians and p10-p90 of the value in
normal light, and the ratio dark/normal and dark_ae/normal per photo.
"""
import csv
import json
import os
import sys

import numpy as np

run = sys.argv[1]
man = {r['img']: r for r in csv.DictReader(open(os.path.join(run, 'manifest.csv')))}
rows = list(csv.DictReader(open(os.path.join(run, 'skin_env.csv')))) + [dict(r, tone='lapa') for r in csv.DictReader(open(os.path.join(run, 'lapa_env.csv')))]
by = {}
for r in rows:
    if man.get(r['img'], {}).get('split') != 'test':
        continue
    by.setdefault(r['img'], {})[r['cond']] = r


def pred(r, name, ref=None):
    s, f, bg, bgf = float(r['skin_l']), float(r['frame_l']), float(r['bg_l']), float(r['bg_frac'])
    S = s / 0.34
    F = f / 0.18
    if name == 'S': return S
    if name == 'F': return F
    if name == 'Q': return bg / 0.18 if bgf > 0.15 and bg == bg else F
    if name == 'M': return (S * F) ** 0.5
    if name == 'R': return min(s / ref, F)


names = ['S', 'F', 'Q', 'M', 'R']
res = {}
for img, c in by.items():
    if 'normal' not in c or 'dark' not in c or 'dark_ae' not in c:
        continue
    g = c['normal']['tone'] if c['normal']['tone'] else 'lapa'
    refskin = float(c['normal']['skin_l']) / 1.0    # R: the session reference = the first settled (normal) sample of this photo
    for n in names:
        a, b, d = (pred(c[k], n, refskin) for k in ['normal', 'dark', 'dark_ae'])
        res.setdefault((g, n), []).append((a, b / max(a, 1e-6), d / max(a, 1e-6)))
out = {}
for (g, n), v in sorted(res.items()):
    v = np.array(v)
    q = lambda x, p: float(np.quantile(x, p))
    out[f'{g}|{n}'] = dict(n=len(v), normal_p50=q(v[:, 0], .5), normal_p10=q(v[:, 0], .1), normal_p90=q(v[:, 0], .9),
                           dark_ratio_p50=q(v[:, 1], .5), dark_ratio_p10=q(v[:, 1], .1), dark_ratio_p90=q(v[:, 1], .9),
                           ae_ratio_p50=q(v[:, 2], .5), ae_ratio_p10=q(v[:, 2], .1), ae_ratio_p90=q(v[:, 2], .9))
json.dump(out, open(sys.argv[2], 'w'), indent=1)
print('pred  tone   n | normal p10/p50/p90 (ideal 1, equal across tones) | dark/normal p10/p50/p90 (ideal 0.2) | ae/normal p10/p50/p90 (ideal ~1)')
for k, o in out.items():
    g, n = k.split('|')
    print(n, g.ljust(5), str(o['n']).rjust(3), '| %.2f %.2f %.2f | %.2f %.2f %.2f | %.2f %.2f %.2f' % (
        o['normal_p10'], o['normal_p50'], o['normal_p90'], o['dark_ratio_p10'], o['dark_ratio_p50'], o['dark_ratio_p90'],
        o['ae_ratio_p10'], o['ae_ratio_p50'], o['ae_ratio_p90']))

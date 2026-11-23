"""Step 6 (11-19) simulation, no renderer change. python research/env_eval/step6_sim.py <run_dir> <out.json>

6-1  Light colour on a wall without colour clues. The page's colour path (faceTrackerHtml.ts runSegmenter, replicated here):
     est = Gray World + 0.75 (Gray-Edge - Gray World) of the background, clamped 0.75..1.3, normalised to luminance;
     ok = background >= 15 % and max/min channel <= 1.6; light.color += kc (est - color), colorConf += kc (ok - colorConf),
     kc 0.6 per sample (auto white balance, one sample per second); shader colour = 1 + colorConf (color - 1).
     Variants after a trusted start (normal light, 20 s):
       V0 today;
       V1 hold: a sample that is not ok does not move light.color, and the shader keeps the last trusted colour at full weight;
       V2 hold 20 s, then fade to no correction like today.
     Scenes (the light is the same as at the start unless said): painted wall red / green / blue / beige (LaPa only; the
     Roboflow close-ups have almost no background), and the cost case: a warm lamp switched on in front of the beige wall
     (wall estimate x the warm gains, so the light DID change). Error = max channel gap of the shader colour from the
     right one (start colour; warm case: the warm colour) 10 s and 40 s after the change.
6-2  Colour light when the face fills the frame (background < 15 %, today's warm / cool rule cannot run). Candidate: the
     skin's red / blue ratio against this session's reference skin (the normal-light skin of the same photo), warm if
     ratio > X, cool if < Y. X and Y chosen on the select split, each the loosest with false alarms (normal, dark,
     dark_ae, backlight, uneven, blown, walls) <= 1 % in every skin tone (2 % together); test split reported.
"""
import csv
import json
import os
import sys

import numpy as np

run, outp = sys.argv[1], sys.argv[2]
man = {r['img']: r for r in csv.DictReader(open(os.path.join(run, 'manifest.csv')))}
rows = list(csv.DictReader(open(os.path.join(run, 'skin_env.csv')))) + [dict(r, tone='lapa') for r in csv.DictReader(open(os.path.join(run, 'lapa_env.csv')))]
by = {}
for r in rows:
    if r['img'] in man:
        by.setdefault(r['img'], {})[r['cond']] = r
lum = lambda c: 0.2126 * c[0] + 0.7152 * c[1] + 0.0722 * c[2]
WARM = np.array([1.0, 0.78, 0.5])


def sample(r, gain=None):
    gw = np.array([float(r['gw_r']), float(r['gw_g']), float(r['gw_b'])]); ge = np.array([float(r['ge_r']), float(r['ge_g']), float(r['ge_b'])])
    est = gw + 0.75 * (ge - gw)
    if gain is not None:
        est = est * gain
        est = est / lum(est)
    bgf = float(r['bg_frac'])
    chroma = est.max() / max(1e-6, est.min())
    c = np.clip(est, 0.75, 1.3); c = c / lum(c)
    return c, (1.0 if bgf >= 0.15 and chroma <= 1.6 else 0.0)


def shader(seq, variant):
    """seq: list of (color, ok) per second. Returns shader colours per second."""
    color, conf, trusted, lastOk, out = np.ones(3), 0.0, None, -1e9, []
    for t, (c, ok) in enumerate(seq):
        kc = 1.0 if t == 0 else 0.6
        if variant == 'V0' or ok:
            color = color + kc * (c - color)
        conf = conf + kc * (ok - conf)
        if ok and conf > 0.5:
            trusted, lastOk = color.copy(), t
        if variant == 'V0' or trusted is None:
            out.append(1 + conf * (color - 1))
        elif variant == 'V1' or t - lastOk <= 20:
            out.append(trusted)
        else:   # V2 after 20 s: fade toward no correction with the confidence, as today
            out.append(1 + conf * (trusted - 1))
    return out


res61 = {}
for img, c in by.items():
    if man[img]['split'] != 'test' or 'normal' not in c:
        continue
    g = c['normal']['tone'] or 'lapa'
    n_col, n_ok = sample(c['normal'])
    if not n_ok:
        continue   # no trusted start possible (face fills the frame)
    start = [sample(c['normal'])] * 20
    scenes = {w: ([sample(c[w])] * 41, n_col) for w in ['wall_red', 'wall_green', 'wall_blue', 'wall_beige'] if w in c}
    if 'wall_beige' in c:
        wc, wok = sample(c['wall_beige'], WARM)
        truth = sample(c['normal'], WARM)[0]
        scenes['warm lamp on beige wall'] = ([(wc, wok)] * 41, truth)
    for name, (after, truth) in scenes.items():
        for v in ['V0', 'V1', 'V2']:
            sh = shader(start + after, v)
            k = f'{name}|{v}|{g}'
            o = res61.setdefault(k, {'n': 0, 'err10': [], 'err40': []})
            o['n'] += 1
            o['err10'].append(float(np.abs(sh[30] - truth).max()))
            o['err40'].append(float(np.abs(sh[60] - truth).max()))
out61 = {k: {'n': o['n'], 'err10_p50': round(float(np.median(o['err10'])), 3), 'err10_p90': round(float(np.quantile(o['err10'], .9)), 3),
             'err40_p50': round(float(np.median(o['err40'])), 3), 'err40_p90': round(float(np.quantile(o['err40'], .9)), 3)} for k, o in res61.items()}

# 6-2
NEG = ['normal', 'dark', 'dark_ae', 'backlight', 'uneven', 'blown', 'wall_red', 'wall_green', 'wall_blue', 'wall_beige']
def rb(r): return float(r['skin_r']) / max(1e-6, float(r['skin_b']))
def feats(split):
    d = {}
    for img, c in by.items():
        if man[img]['split'] != split or 'normal' not in c:
            continue
        g = c['normal']['tone'] or 'lapa'
        ref = rb(c['normal'])
        for cond, r in c.items():
            d.setdefault(g, []).append((cond, rb(r) / ref, float(r['bg_frac'])))
    return d
sel, tst = feats('select'), feats('test')
def rates(d, X, small_bg_only, Y=None):
    Y = Y if Y is not None else 1 / X
    o = {}
    for g, v in d.items():
        f = lambda cond: [x for (c_, x, bgf) in v if c_ == cond and (not small_bg_only or bgf < 0.15)]
        neg = [x for c_ in NEG for x in f(c_)]
        warm, cool = f('warm'), f('cool')
        o[g] = {'fa_pct': round(100 * np.mean([(x > X) or (x < Y) for x in neg]), 1) if neg else None,
                'warm_recall_pct': round(100 * np.mean([x > X for x in warm]), 1) if warm else None,
                'cool_recall_pct': round(100 * np.mean([x < Y for x in cool]), 1) if cool else None,
                'n_warm': len(warm)}
    return o
chosen = None
for X in np.arange(1.05, 2.51, 0.05):
    r = rates(sel, X, False, 0.0)
    if all(v['fa_pct'] is not None and v['fa_pct'] <= 1 for v in r.values()):
        chosen = round(float(X), 2); break
cool = None
for Y in np.arange(0.95, 0.39, -0.05):
    r = rates(sel, 99.0, False, Y)
    if all(v['fa_pct'] is not None and v['fa_pct'] <= 1 for v in r.values()):
        cool = round(float(Y), 2); break
# each side gets half of the 2 % false-alarm budget
out62 = {'X_warm': chosen, 'Y_cool': cool, 'select_all': rates(sel, chosen, False, cool), 'test_all': rates(tst, chosen, False, cool), 'test_face_fills_frame': rates(tst, chosen, True, cool)}
json.dump({'6-1': out61, '6-2': out62}, open(outp, 'w'), indent=1)
print('6-1  scene | variant | tone : max channel error of the shader colour, 10 s / 40 s after (p50 p90)')
for k, o in out61.items():
    print('  ', k.ljust(40), o['n'], '%.3f %.3f | %.3f %.3f' % (o['err10_p50'], o['err10_p90'], o['err40_p50'], o['err40_p90']))
print('6-2  warm ratio >', chosen, ' cool ratio <', cool)
for part in ['test_all', 'test_face_fills_frame']:
    print('  ', part, json.dumps(out62[part]))

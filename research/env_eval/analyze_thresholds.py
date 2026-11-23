"""Evaluate the renderer's environment thresholds (baseline v1, TUNING.env on 11-19) on the measured CSVs, with a fixed
split: candidates are searched on 'select', checked on 'tune', and the baseline is reported on 'test' only.

    python research/env_eval/analyze_thresholds.py <run_dir> <out_json>

run_dir holds manifest.csv, lapa_env.csv, skin_env.csv, lapa_pose.csv (from manifest.py and the *_eval.py scripts).
Labels are the synthetic conditions (normal = negative). Synthetic changes are not phone footage, and the prevalence of
positives here (1:1) is not the one in use, so precision is reported for the record only.

Offline grain is on the image scale; the renderer reads about 0.45x of it (headless, two points), so the baseline grain
thresholds are evaluated here at page value / 0.45. That conversion is itself an assumption (see the report).
"""
import csv
import json
import math
import sys

import numpy as np

PAGE_TO_OFFLINE = 1 / 0.45
BASE = {
    'dark': {'frame': 0.025, 'gN': 0.011 * PAGE_TO_OFFLINE, 'grain': 0.045 * PAGE_TO_OFFLINE},
    'backlight': {'faceDrop': 0.5, 'ratioRise': 2.0, 'bgLum': 0.5, 'absFace': 0.04, 'absRatio': 8},
    'warm': 2.0, 'cool': 0.7, 'gm': (0.8, 1.2), 'bgMin': 0.15, 'mix': 0.75,
    'uneven': 2.5, 'unevenMaxYaw': 20, 'blown': 0.15,
    'turnDeg': 38, 'pitchDeg': 32, 'pitchOffset': 3.1,
}
# v2 (11-19 decision 2-b): page values 0.03 / 0.064 / 0.0128 read at the measured page scale 0.64 = this offline set.
DARK_V2 = {'frame': 0.03, 'gN': 0.02, 'grain': 0.1}
TONES = ['dark', 'fair', 'light']


def f(r, k):
    try:
        v = float(r[k])
        return v if math.isfinite(v) else float('nan')
    except (KeyError, ValueError, TypeError):
        return float('nan')


def load(run):
    man = {}
    for r in csv.DictReader(open(f'{run}/manifest.csv', encoding='utf-8')):
        man[(r['dataset'], r['tone'], r['img'])] = r['split']
    rows = []
    for r in csv.DictReader(open(f'{run}/lapa_env.csv')):
        r['dataset'], r['tone'] = 'lapa', ''
        rows.append(r)
    for r in csv.DictReader(open(f'{run}/skin_env.csv')):
        r['dataset'] = 'roboflow'
        rows.append(r)
    for r in rows:
        key = ('lapa', '', r['img']) if r['dataset'] == 'lapa' else ('roboflow_skin_tone', r['tone'], r['img'])
        r['split'] = man.get(key, '?')
    pose = {r['img']: r for r in csv.DictReader(open(f'{run}/lapa_pose.csv')) if r['found'] == '1'}
    return rows, pose


def est(r, w):
    gw = np.array([f(r, 'gw_r'), f(r, 'gw_g'), f(r, 'gw_b')])
    ge = np.array([f(r, 'ge_r'), f(r, 'ge_g'), f(r, 'ge_b')])
    return gw + w * (ge - gw)


def angle(a, b):
    c = float(np.dot(a, b) / (np.linalg.norm(a) * np.linalg.norm(b) + 1e-12))
    return math.degrees(math.acos(max(-1.0, min(1.0, c))))


# ── rules, written as the renderer's envEvaluate (offline feature names) ──
def is_dark(r, p):
    g = f(r, 'grain'); gn = g * math.sqrt(max(1e-4, f(r, 'skin_l')))
    return f(r, 'frame_l') < p['frame'] or (gn > p['gN'] and g > p['grain'])


def is_back(r, ref, p):
    face, bg = f(r, 'skin_l'), f(r, 'bg_l')
    bl = bg / max(1e-4, face)
    rf = f(ref, 'skin_l'); rr = f(ref, 'bg_l') / max(1e-4, rf)
    rel = bg > p['bgLum'] and face < p['faceDrop'] * rf and bl > p['ratioRise'] * rr
    ab = face < p['absFace'] and bl > p['absRatio'] and bg > p['bgLum']
    return bool(rel or ab)


def color_flags(r, warm, cool, w):
    e = est(r, w)
    rb, gm = e[0] / max(1e-4, e[2]), e[1] / max(1e-4, 0.5 * (e[0] + e[2]))
    ok = f(r, 'bg_frac') >= BASE['bgMin'] and BASE['gm'][0] < gm < BASE['gm'][1]
    return ok and rb > warm, ok and rb < cool


def rate(v):
    v = [x for x in v if x is not None]
    return {'rate': round(float(np.mean(v)), 4) if v else None, 'n': len(v)}


def by_img(rows):
    d = {}
    for r in rows:
        d.setdefault((r['dataset'], r['tone'], r['img']), {})[r['cond']] = r
    return d


def evaluate(rows, pose, split, P):
    """Rates on one split for the parameter set P (same structure as BASE)."""
    sel = [r for r in rows if r['split'] == split]
    imgs = by_img(sel)
    out = {}
    # Low light: positives dark / dark_ae, negatives normal; per skin tone on Roboflow.
    dk = {}
    for ds, tones in (('lapa', ['']), ('roboflow', TONES)):
        for t in tones:
            g = [r for r in sel if r['dataset'] == ds and r['tone'] == t]
            key = ds + (':' + t if t else '')
            dk[key] = {c: rate([is_dark(r, P['dark']) for r in g if r['cond'] == c]) for c in ('normal', 'dark', 'dark_ae', 'backlight', 'warm', 'blown')}
    out['dark'] = dk
    # Backlight: each image's own normal frame is the session reference.
    bk = {}
    for (ds, t, _), c in imgs.items():
        if 'normal' not in c:
            continue
        key = ds + (':' + t if t else '')
        for cond, r in c.items():
            if cond.startswith('wall'):
                continue
            bk.setdefault(key, {}).setdefault(cond, []).append(is_back(r, c['normal'], P['backlight']))
    out['backlight'] = {k: {c: rate(v) for c, v in d.items()} for k, d in bk.items()}
    # Warm / cool light (Gray-Edge mix P['mix']).
    col = {}
    for ds in ('lapa', 'roboflow'):
        g = [r for r in sel if r['dataset'] == ds]
        for c in sorted({r['cond'] for r in g}):
            fl = [color_flags(r, P['warm'], P['cool'], P['mix']) for r in g if r['cond'] == c]
            col[f'{ds}:{c}'] = {'warm': rate([a for a, _ in fl]), 'cool': rate([b for _, b in fl])}
    out['color'] = col
    # Side light: ratio on near-frontal faces (LaPa: Face Landmarker formula yaw; Roboflow: no pose, all).
    un = {}
    for ds in ('lapa', 'roboflow'):
        for c in ('normal', 'uneven'):
            v = []
            for r in sel:
                if r['dataset'] != ds or r['cond'] != c:
                    continue
                if ds == 'lapa':
                    pz = pose.get(r['img'])
                    if not pz or abs(float(pz['yaw_f'])) >= P['unevenMaxYaw']:
                        continue
                lr = f(r, 'lr')
                v.append(max(lr, 1 / lr) > P['uneven'] if lr == lr and lr > 0 else None)
            un[f'{ds}:{c}'] = rate(v)
    out['uneven'] = un
    # Blown face.
    out['blown'] = {f'{ds}:{c}': rate([f(r, 'blown') > P['blown'] for r in sel if r['dataset'] == ds and r['cond'] == c and f(r, 'blown') == f(r, 'blown')])
                    for ds in ('lapa', 'roboflow') for c in ('normal', 'blown', 'uneven', 'dark_ae')}
    # Turn: formula decision vs the Face Landmarker matrix (35 / 30 deg target) on LaPa.
    pz = [pose[r['img']] for r in sel if r['dataset'] == 'lapa' and r['cond'] == 'normal' and r['img'] in pose]
    if pz:
        yf = np.array([abs(float(p['yaw_f'])) for p in pz]); ym = np.array([abs(float(p['yaw_m'])) for p in pz])
        pf = np.array([abs(float(p['pitch_f']) + P['pitchOffset']) for p in pz]); pm = np.array([abs(float(p['pitch_m'])) for p in pz])
        pred = (yf > P['turnDeg']) | (pf > P['pitchDeg']); truth = (ym > 35) | (pm > 30)
        tp = int((pred & truth).sum()); fp = int((pred & ~truth).sum()); fn = int((~pred & truth).sum())
        out['turn'] = {'n': len(pz), 'positives': int(truth.sum()), 'tp': tp, 'fp': fp, 'fn': fn,
                       'precision': round(tp / max(1, tp + fp), 3), 'recall': round(tp / max(1, tp + fn), 3)}
    return out


def gray_edge(rows, split):
    """Painted-wall shift and warm / cool tracking error (degrees) per mix weight."""
    imgs = by_img([r for r in rows if r['split'] == split and r['dataset'] == 'lapa'])
    casts = {'warm': np.array([1.0, 0.78, 0.5]), 'cool': np.array([0.72, 0.9, 1.2])}
    res = {}
    for w in (0.0, 0.25, 0.5, 0.75, 1.0):
        sh, ce = [], []
        for c in imgs.values():
            if 'normal' not in c:
                continue
            e0 = est(c['normal'], w)
            for k, r in c.items():
                if k.startswith('wall'):
                    a = angle(est(r, w), e0)
                    if a == a:
                        sh.append(a)
                if k in casts and (e0 > 0).all():
                    a = angle(est(r, w) / e0, casts[k])
                    if a == a:
                        ce.append(a)
        res[str(w)] = {'wall_shift_median': round(float(np.median(sh)), 2), 'wall_shift_p90': round(float(np.quantile(sh, 0.9)), 2),
                       'cast_err_median': round(float(np.median(ce)), 2), 'cast_err_p90': round(float(np.quantile(ce, 0.9)), 2), 'n': len(sh)}
    return res


def pose_fit(pose, rows, split):
    names = {r['img'] for r in rows if r['split'] == split and r['dataset'] == 'lapa'}
    pz = [p for n, p in pose.items() if n in names]
    yf = np.array([float(p['yaw_f']) for p in pz]); ym = np.array([float(p['yaw_m']) for p in pz])
    pf = np.array([float(p['pitch_f']) for p in pz]); pm = np.array([float(p['pitch_m']) for p in pz])
    ay = np.linalg.lstsq(np.vstack([ym, np.ones_like(ym)]).T, yf, rcond=None)[0]
    ap = np.linalg.lstsq(np.vstack([pm, np.ones_like(pm)]).T, pf, rcond=None)[0]
    return {'n': len(pz), 'yaw_corr': round(float(np.corrcoef(yf, ym)[0, 1]), 4), 'yaw_slope': round(float(ay[0]), 3), 'yaw_offset': round(float(ay[1]), 2),
            'yaw_abs_err_median': round(float(np.median(np.abs(np.abs(yf) - np.abs(ym)))), 2),
            'pitch_corr': round(float(np.corrcoef(pf, pm)[0, 1]), 4), 'pitch_slope': round(float(ap[0]), 3), 'pitch_offset': round(float(ap[1]), 2)}


def sweep_dark(rows):
    """Candidate search on 'select': highest mean recall with every skin tone's normal-light false alarms <= 2 %."""
    best = None
    for fr in (0.02, 0.025, 0.03, 0.035):
        for gn in (0.02, 0.0244, 0.03, 0.035):
            for gr in (0.06, 0.08, 0.1, 0.12):
                P = dict(BASE); P['dark'] = {'frame': fr, 'gN': gn, 'grain': gr}
                d = evaluate(rows, {}, 'select', P)['dark']
                fp = max(d[f'roboflow:{t}']['normal']['rate'] for t in TONES)
                rec = np.mean([d[k][c]['rate'] for k in d for c in ('dark', 'dark_ae')])
                cand = (fp <= 0.02, rec, -fp, fr, gn, gr)
                if best is None or cand > best:
                    best = cand
    return {'frame': best[3], 'gN': best[4], 'grain': best[5], 'select_mean_recall': round(float(best[1]), 3), 'select_max_tone_fp': round(-best[2], 3), 'meets_fp_cap': best[0]}


def main():
    run, out = sys.argv[1], sys.argv[2]
    rows, pose = load(run)
    res = {'baseline': {k: v for k, v in BASE.items()}, 'note': 'grain thresholds evaluated at page value / 0.45',
           'counts': {s: sum(1 for r in rows if r['split'] == s and r['cond'] == 'normal') for s in ('select', 'tune', 'test', '?')}}
    res['baseline_test'] = evaluate(rows, pose, 'test', BASE)
    res['gray_edge_select'] = gray_edge(rows, 'select')
    res['gray_edge_test'] = gray_edge(rows, 'test')
    res['pose_fit_select'] = pose_fit(pose, rows, 'select')
    res['pose_fit_test'] = pose_fit(pose, rows, 'test')
    cand = sweep_dark(rows)
    P = dict(BASE); P['dark'] = {'frame': cand['frame'], 'gN': cand['gN'], 'grain': cand['grain']}
    res['dark_candidate'] = cand
    res['dark_candidate_tune'] = evaluate(rows, pose, 'tune', P)['dark']
    res['dark_baseline_tune'] = evaluate(rows, pose, 'tune', BASE)['dark']
    P2 = dict(BASE); P2['dark'] = DARK_V2
    res['dark_v2'] = {sp: evaluate(rows, pose, sp, P2)['dark'] for sp in ('select', 'tune', 'test')}
    PA = dict(BASE); PA['dark'] = {'frame': 0.025, 'gN': 0.011 / 0.64, 'grain': 0.045 / 0.64}
    res['dark_v1_at_064'] = {sp: evaluate(rows, pose, sp, PA)['dark'] for sp in ('select', 'tune', 'test')}
    with open(out, 'w', encoding='utf-8') as fh:
        json.dump(res, fh, indent=1, ensure_ascii=False)
    print(json.dumps({k: res[k] for k in ('counts', 'dark_candidate', 'pose_fit_test')}, ensure_ascii=False))


if __name__ == '__main__':
    main()

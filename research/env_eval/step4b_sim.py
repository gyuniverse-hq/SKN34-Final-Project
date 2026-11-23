"""Step 4-b (11-20) simulation, no renderer change: the "stand only" room the 11-20 phone capture showed (face darker than
the dark room, skin 0.019, but a lamp in the frame keeps the frame mean up, so today's dark rule and the backlight rule both
stay off).

    python research/env_eval/step4b_sim.py <run_dir with manifest.csv> <selfie_multiclass.tflite> <out_csv> <out_json>

Images: the fixed manifest (select / test split), LaPa with its labels, Roboflow skin tones through the app's Selfie
Multiclass model (as skin_tone_env_eval.py). Conditions: lapa_env_eval.conditions (normal, dark, dark_ae, backlight, uneven,
warm, cool, blown) plus four lamp scenes: the scene at 1/20 or 1/10 of the light, sensor noise at the synthetic dark-room
level (400 photons) or ten times lower (a phone that denoises; the phone capture was NOT flagged by grain), a warm lamp disk
of 2 % of the frame in the top corner with more background, and a soft glow around it.

Rules (the page's measures; page grain = offline grain x 0.64, the headless same-frame scale):
  today  frame_l < 0.03 or (grainN > 0.0128 and grain > 0.064)
  mid    today or t_mid < M           (Y' median of the 128 px frame, 0..255: a small lamp cannot move a median)
  shadow today or t_shadow > S        (share of the frame with Y' < 16)
  both   today or (t_mid < M and t_shadow > S)
M and S are chosen on the select split: the loosest value whose false alarms on the negatives (normal, warm, cool, uneven,
backlight, blown) add <= 1 point over today's rule in every group (lapa, dark, fair, light; today's rule alone is already above 1 % on LaPa). Reported on the test split: false alarms, lamp
recall by variant, dark-room recall.
"""
import csv
import json
import math
import os
import sys

import cv2
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from lapa_env_eval import conditions, measure, noisy, to_lin, to_srgb_u8  # noqa: E402

PAGE_GRAIN = 0.64
NEG = ['normal', 'warm', 'cool', 'uneven', 'backlight', 'blown']
LAMPS = {'lamp_k05_noisy': (0.05, 400), 'lamp_k05_clean': (0.05, 4000), 'lamp_k10_noisy': (0.10, 400), 'lamp_k10_clean': (0.10, 4000)}


def lamp_scene(rgb_u8, label, k, photons):
    lin = to_lin(rgb_u8)
    H, W = label.shape
    r = math.sqrt(0.02 * H * W / math.pi)
    c = int(1.5 * r)
    corners = [(c, c), (W - c, c)]
    bg = label == 0
    cx, cy = max(corners, key=lambda p: bg[:int(3 * r), max(0, p[0] - int(1.5 * r)):p[0] + int(1.5 * r)].mean())
    yy, xx = np.mgrid[0:H, 0:W]
    d = np.hypot(xx - cx, yy - cy)
    warm = np.array([1.0, 0.8, 0.5], np.float32)
    disk = np.clip(1 - (d - r) / (0.3 * r), 0, 1)[..., None] * warm
    glow = (0.25 * np.exp(-(d / (4 * r)) ** 2))[..., None] * warm
    return to_srgb_u8(np.maximum(noisy(lin * k + glow, photons), disk))


def main():
    run, model, out_csv, out_json = sys.argv[1:5]
    man = [r for r in csv.DictReader(open(os.path.join(run, 'manifest.csv'))) if r['split'] in ('select', 'test')]
    seg = None
    rows = []
    for i, m in enumerate(man):
        bgr = cv2.imread(m['path'])
        if bgr is None:
            continue
        if m['dataset'] == 'lapa':
            label = cv2.imread(m['path'].replace('images', 'labels')[:-4] + '.png', 0)
            s = 720 / min(label.shape)
            if s < 1:
                bgr = cv2.resize(bgr, None, fx=s, fy=s, interpolation=cv2.INTER_AREA)
                label = cv2.resize(label, (bgr.shape[1], bgr.shape[0]), interpolation=cv2.INTER_NEAREST)
            rgb = cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)
        else:
            if seg is None:
                import mediapipe as mp
                from mediapipe.tasks.python import vision
                from mediapipe.tasks.python.core.base_options import BaseOptions
                seg = (mp, vision.ImageSegmenter.create_from_options(vision.ImageSegmenterOptions(
                    base_options=BaseOptions(model_asset_path=model), output_category_mask=True)))
            mp_, sg = seg
            s = 720 / min(bgr.shape[:2])
            bgr = cv2.resize(bgr, None, fx=s, fy=s, interpolation=cv2.INTER_AREA if s < 1 else cv2.INTER_LINEAR)
            rgb = cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)
            cat = sg.segment(mp_.Image(image_format=mp_.ImageFormat.SRGB, data=rgb)).category_mask.numpy_view()
            cat = cv2.resize(cat.astype(np.uint8), (rgb.shape[1], rgb.shape[0]), interpolation=cv2.INTER_NEAREST)
            label = np.full(cat.shape, 2, np.uint8)
            label[cat == 0] = 0
            label[cat == 3] = 1
            if (label == 1).mean() < 0.05:
                continue
        scenes = {k: v for k, v in conditions(rgb, label).items() if k in NEG + ['dark', 'dark_ae']}
        for name, (k, ph) in LAMPS.items():
            scenes[name] = lamp_scene(rgb, label, k, ph)
        g = m['tone'] or 'lapa'
        for cond, img in scenes.items():
            r = measure(img, label)
            rows.append(dict(img=m['img'], group=g, split=m['split'], cond=cond, skin_l=r['skin_l'], frame_l=r['frame_l'],
                             grain=r['grain'], t_mid=r['t_mid'], t_shadow=r['t_shadow'], t_white=r['t_white'], bg_frac=r['bg_frac']))
        if i % 100 == 0:
            print(i, len(man), flush=True)
    with open(out_csv, 'w', newline='') as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
        w.writeheader(); w.writerows(rows)
    analyse(rows, out_json)


def today(r):
    g = r['grain'] * PAGE_GRAIN
    gn = g * math.sqrt(max(1e-4, r['skin_l'])) if r['skin_l'] == r['skin_l'] else 0
    return r['frame_l'] < 0.03 or (gn > 0.0128 and g > 0.064)


def fire(r, rule, M, S):
    if today(r):
        return True
    if rule == 'mid':
        return r['t_mid'] < M
    if rule == 'shadow':
        return r['t_shadow'] > S
    if rule == 'both':
        return r['t_mid'] < M and r['t_shadow'] > S
    if rule == 'face':   # M = skin brightness below, S = frame / skin above (the phone stand room: 0.019, bg/face 4.84)
        return r['skin_l'] == r['skin_l'] and r['skin_l'] < M and r['frame_l'] / max(1e-4, r['skin_l']) > S
    return False


def rates(rows, rule, M, S):
    out = {}
    for g in sorted({r['group'] for r in rows}):
        rg = [r for r in rows if r['group'] == g]
        pct = lambda cs: round(100 * float(np.mean([fire(r, rule, M, S) for r in rg if r['cond'] in cs])), 1) if any(r['cond'] in cs for r in rg) else None
        o = {'n_img': len({r['img'] for r in rg}), 'false_alarm': pct(NEG), 'dark': pct(['dark']), 'dark_ae': pct(['dark_ae'])}
        for lm in LAMPS:
            o[lm] = pct([lm])
        out[g] = o
    return out


def analyse(rows, out_json):
    for r in rows:
        for k in ['skin_l', 'frame_l', 'grain', 't_mid', 't_shadow', 't_white', 'bg_frac']:
            r[k] = float(r[k])
    sel = [r for r in rows if r['split'] == 'select']
    tst = [r for r in rows if r['split'] == 'test']
    base = {g: v['false_alarm'] for g, v in rates(sel, 'today', 0, 2).items()}
    # today's rule already exceeds 1 % on LaPa, so the budget is what a candidate ADDS: <= 1 point over today, every group
    ok = lambda rr, rule, M, S: all(v['false_alarm'] is not None and v['false_alarm'] - base[g] <= 1 for g, v in rates(rr, rule, M, S).items())
    M = max([m for m in range(2, 130, 2) if ok(sel, 'mid', m, 2)], default=None)
    S = min([s / 100 for s in range(2, 100, 2) if ok(sel, 'shadow', 0, s / 100)], default=None)
    both = None
    for m in range(130, 1, -2):          # loosest median first, then the loosest shadow share that keeps it under budget
        cands = [s / 100 for s in range(2, 100, 2) if ok(sel, 'both', m, s / 100)]
        if cands:
            both = (m, min(cands)); break
    # 'face' fires on the backlight photos by design (a dark face before a bright background), so its budget leaves backlight out
    okf = lambda F, R: all(v['false_alarm'] - b <= 1 for (g, v), b in
                           ((gv, rates([r for r in sel if r['cond'] != 'backlight' and r['group'] == gv[0]], 'today', 0, 2)[gv[0]]['false_alarm'])
                            for gv in rates([r for r in sel if r['cond'] != 'backlight'], 'face', F, R).items()))
    clean = lambda F, R: np.mean([v['lamp_k05_clean'] + v['lamp_k10_clean'] for v in rates(sel, 'face', F, R).values()])
    face = max(((F, R) for F in [0.02, 0.03, 0.04, 0.05, 0.06, 0.08, 0.1] for R in [1.0, 1.1, 1.2, 1.3, 1.5, 1.7, 2.0, 2.5, 3.0] if okf(F, R)),
               key=lambda fr: clean(*fr), default=None)
    out = {'chosen': {'mid_M': M, 'shadow_S': S, 'both_M_S': both, 'face_F_R': face},
           'test': {'today': rates(tst, 'today', 0, 2), 'mid': rates(tst, 'mid', M or 0, 2), 'shadow': rates(tst, 'shadow', 0, S or 2),
                    'both': rates(tst, 'both', *(both or (0, 2))), 'face': rates(tst, 'face', *(face or (0, 99)))},
           'lamp_measures_test_p50': {lm: {g: {k: round(float(np.median([r[k] for r in tst if r['cond'] == lm and r['group'] == g])), 3)
                                              for k in ['skin_l', 'frame_l', 't_mid', 't_shadow', 't_white']}
                                          for g in sorted({r['group'] for r in tst})} for lm in list(LAMPS) + ['normal', 'dark']}}
    json.dump(out, open(out_json, 'w'), indent=1)
    print(json.dumps(out['chosen']))
    for rule, v in out['test'].items():
        print(rule)
        for g, o in v.items():
            print('  ', g.ljust(6), json.dumps(o))


if __name__ == '__main__':
    if len(sys.argv) == 3:   # re-analyse a saved CSV: step4b_sim.py <out_csv> <out_json>
        analyse(list(csv.DictReader(open(sys.argv[1]))), sys.argv[2])
    else:
        main()

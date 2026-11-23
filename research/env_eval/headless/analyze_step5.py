"""Step 5 render comparison.
    python analyze_step5.py <out_dir> <face_landmarker.task> <montage_dir> [variants] [conds]
variants: comma list, first = baseline (default B0,N,G); conds: "light=normal,dark;dark=normal,dark" (default normal,dark,dark_ae for both faces).
Regions from the baseline normal-light render of each face: lip = Face Landmarker outer lip polygon; lid = what the
shadow-only sets (C, D) changed; highlighter = what set A changed outside lip and lid.
"""
import glob, json, os, re, sys
import cv2
import numpy as np
import mediapipe as mp
from mediapipe.tasks.python import vision
from mediapipe.tasks.python.core.base_options import BaseOptions

out, model, mdir = sys.argv[1:4]
VARS = (sys.argv[4] if len(sys.argv) > 4 else 'B0,N,G').split(',')
CONDS = dict((kv.split('=')[0], kv.split('=')[1].split(',')) for kv in sys.argv[5].split(';')) if len(sys.argv) > 5 else {'light': ['normal', 'dark', 'dark_ae'], 'dark': ['normal', 'dark', 'dark_ae']}
B = VARS[0]
os.makedirs(mdir, exist_ok=True)
lm = vision.FaceLandmarker.create_from_options(vision.FaceLandmarkerOptions(base_options=BaseOptions(model_asset_path=model)))
LIP = [61, 146, 91, 181, 84, 17, 314, 405, 321, 375, 291, 409, 270, 269, 267, 0, 37, 39, 40, 185]
rd = lambda n: cv2.imread(os.path.join(out, n + '.png'))
def lin(b):
    c = b[..., ::-1].astype(np.float32) / 255
    return np.where(c <= 0.04045, c / 12.92, ((c + 0.055) / 1.055) ** 2.4)
Y = lambda b: lin(b) @ np.array([0.2126, 0.7152, 0.0722], np.float32)
def lab_mean(b, m):
    return cv2.cvtColor(b[m].reshape(-1, 1, 3), cv2.COLOR_BGR2LAB).reshape(-1, 3).astype(np.float32).mean(0) * [100 / 255, 1, 1] - [0, 128, 128]

res = {}
for face in CONDS:
    bare = rd(f'{B}_{face}_normal_bare')
    r = lm.detect(mp.Image(image_format=mp.ImageFormat.SRGB, data=cv2.cvtColor(bare, cv2.COLOR_BGR2RGB)))
    h, w = bare.shape[:2]
    p = np.array([[l.x * w, l.y * h] for l in r.face_landmarks[0]])
    lip = np.zeros((h, w), np.uint8); cv2.fillPoly(lip, [p[LIP].astype(np.int32)], 1); lip = lip > 0
    d = lambda k: np.abs(rd(f'{B}_{face}_normal_{k}').astype(int) - bare.astype(int)).sum(2) > 12
    lid = (d('C') | d('D')) & ~lip
    hlm = d('A') & ~lip & ~cv2.dilate(lid.astype(np.uint8), np.ones((9, 9), np.uint8)).astype(bool)
    regions = {'lip': lip, 'lid': lid, 'hl': hlm}
    res[face] = {'px': {k: int(v.sum()) for k, v in regions.items()}}
    x0, y0 = p[:, 0].min(), p[:, 1].min(); x1, y1 = p[:, 0].max(), p[:, 1].max()
    crop = (slice(max(0, int(y0 - 20)), int(y1 + 20)), slice(max(0, int(x0 - 20)), int(x1 + 20)))
    for cond in CONDS[face]:
        for v in VARS:
            key = f'{cond}|{v}'
            o = res[face][key] = {}
            hud = json.load(open(os.path.join(out, f'{v}_{face}_{cond}_hud.json')))
            o['exc'] = len(hud['exceptions'])
            for l in hud['lines']:
                m = re.search(r'perf frame ([\d.]+) / ([\d.]+)ms\s+lat\(\w+\) ([\d.]+) / ([\d.]+)ms\s+jit still ([\d.]+) / ([\d.]+)px', l)
                if m: o['perf'] = [float(x) for x in m.groups()]
                m = re.search(r'^fps (\d+)', l)
                if m: o['fps'] = int(m.group(1))
                m = re.search(r' frame ([\d.]+) ', l)
                if l.startswith('env') and m: o['frameLum'] = float(m.group(1))
                m = re.search(r'skin ([\d.]+)', l)
                if l.startswith('strength') and m: o['skin'] = float(m.group(1))
            b_v = rd(f'{v}_{face}_{cond}_bare')
            for s, prods in {'A': ['lip', 'lid', 'hl'], 'B': ['lip', 'lid', 'hl'], 'C': ['lid'], 'D': ['lid']}.items():
                img = rd(f'{v}_{face}_{cond}_{s}'); base = rd(f'{B}_{face}_{cond}_{s}'); nb = rd(f'{B}_{face}_normal_bare'); nm = rd(f'{B}_{face}_normal_{s}')
                for pr in prods:
                    m = regions[pr]
                    if m.sum() < 30: continue
                    e = {}
                    e['dE_vs_B0'] = float(np.linalg.norm(lab_mean(img, m) - lab_mean(base, m)))
                    e['maxPix_vs_B0'] = int(np.abs(img.astype(int) - base.astype(int))[m].max())
                    # float index: made-up / bare brightness here, over the same ratio of the baseline in normal light (1 = sits like in normal light)
                    rel = Y(img)[m].mean() / max(1e-5, Y(b_v)[m].mean())
                    reln = Y(nm)[m].mean() / max(1e-5, Y(nb)[m].mean())
                    e['float'] = float(rel / reln)
                    # sparkle: top 1 % of the added light, relative to the bare region mean, over the same in normal light
                    add = np.clip(Y(img) - Y(b_v), 0, None)[m]; addn = np.clip(Y(nm) - Y(nb), 0, None)[m]
                    top = lambda a: a[a >= np.quantile(a, 0.99)].mean()
                    e['sparkle'] = float((top(add) / max(1e-5, Y(b_v)[m].mean())) / max(1e-6, top(addn) / max(1e-5, Y(nb)[m].mean())))
                    # finish character kept: in the same condition, how peaked the added light is (top 1 % / mean) and its level, over the baseline's
                    addb = np.clip(Y(base) - Y(rd(f'{B}_{face}_{cond}_bare')), 0, None)[m]
                    pk = lambda a: a[a >= np.quantile(a, 0.99)].mean() / max(1e-6, a.mean())
                    e['peak_vs_base'] = float(pk(add) / max(1e-6, pk(addb)))
                    e['level_vs_base'] = float(add.mean() / max(1e-6, addb.mean()))
                    o[f'{s}.{pr}'] = {k: round(x, 3) if isinstance(x, float) else x for k, x in e.items()}
        # montage per set: rows = variant, columns = bare / set (this condition)
        for s in ['A', 'B']:
            rows = []
            for v in VARS:
                tiles = [rd(f'{v}_{face}_{cond}_bare')[crop], rd(f'{v}_{face}_{cond}_{s}')[crop]]
                row = np.hstack(tiles)
                cv2.putText(row, v, (8, 28), cv2.FONT_HERSHEY_SIMPLEX, 0.9, (0, 255, 255), 2)
                rows.append(row)
            cv2.imwrite(os.path.join(mdir, f'{face}_{cond}_set{s}.jpg'), np.vstack(rows), [cv2.IMWRITE_JPEG_QUALITY, 90])
json.dump(res, open(os.path.join(out, 'step5_metrics.json'), 'w'), indent=1)
print(json.dumps({f: res[f]['px'] for f in res}))
for f in res:
    for k, o in res[f].items():
        if k == 'px': continue
        print(f, k, 'fps', o.get('fps'), 'skin', o.get('skin'), 'frame', o.get('frameLum'), 'perf', o.get('perf'))
        for kk, e in o.items():
            if '.' in kk: print('   ', kk, e)

"""AR 파라미터 스윕 평가: ar_out_sweep/sweep_*.png 를 ar_out/ar_off_0.png(AR 끔) 기준으로 eval_makeup.py와 같은 지표로 잰다."""
import sys, os, glob, json
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT, OUT = sys.argv[1], sys.argv[2]
sys.path.insert(0, HERE)
from eval_makeup import compare, landmarks, lip_lab, lip_mask, load  # noqa: E402  (11-23: eval_makeup is now importable)
import numpy as np, cv2
E = load(os.path.join(ROOT, 'input/ref_crop_1024.png')); E_lab = lip_lab(E, lip_mask(E, landmarks(E)))[0]
O = load(os.path.join(ROOT, 'ar_out/ar_off_0.png')); O_lm = landmarks(O)
fm = np.zeros(O.shape[:2], np.uint8); cv2.fillPoly(fm, [cv2.convexHull(O_lm.astype(np.int32))], 1); fm = fm.astype(bool)
cfg = {c['name']: c['lip'] for c in json.load(open(os.path.join(ROOT, 'ar_sweep.json'), encoding='utf-8'))}
rows = {}
for p in sorted(glob.glob(os.path.join(ROOT, 'ar_out_sweep/sweep_*.png'))):
    n = os.path.basename(p)[6:-4]
    r, _ = compare(n, load(p), O, O_lm, fm, E_lab); r['lip_input'] = cfg.get(n); rows[n] = r
json.dump({'baseline': 'ar_out/ar_off_0.png', 'E_lip_lab': [round(float(v), 1) for v in E_lab], 'rows': rows},
          open(os.path.join(OUT, 'metrics_sweep.json'), 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
for n, r in rows.items():
    print(f"{n:28s} vsE={r['dE00_lip_vs_E_real']:5.2f} vsTarget={r['dE00_lip_vs_official_target']:5.2f} "
          f"vsBare={r['dE00_lip_vs_bare']:5.2f} out={r['change_dE00_mean_outside_lip(face)']:4.2f} lipLab={r['lip_lab_median']}")

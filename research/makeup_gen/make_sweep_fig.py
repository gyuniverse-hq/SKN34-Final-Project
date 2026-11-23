import sys, os, json
import numpy as np
from PIL import Image
import matplotlib; matplotlib.use('Agg'); import matplotlib.pyplot as plt
from matplotlib import font_manager as fm
ROOT, RES = sys.argv[1], sys.argv[2]
F = '/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc'
fm.fontManager.addfont(F); plt.rcParams['font.family'] = fm.FontProperties(fname=F).get_name()

import mediapipe as mp
from mediapipe.tasks.python import vision, BaseOptions
det = vision.FaceLandmarker.create_from_options(vision.FaceLandmarkerOptions(base_options=BaseOptions(model_asset_path=os.path.join(os.path.dirname(os.path.abspath(__file__)), 'face_landmarker.task')), num_faces=1))
OUTER = [61,146,91,181,84,17,314,405,321,375,291,409,270,269,267,0,37,39,40,185]
def crop(p):
    im = np.asarray(Image.open(p).convert('RGB'))
    r = det.detect(mp.Image(image_format=mp.ImageFormat.SRGB, data=np.ascontiguousarray(im))); h, w = im.shape[:2]
    pts = np.array([[r.face_landmarks[0][i].x*w, r.face_landmarks[0][i].y*h] for i in OUTER])
    x0, y0 = pts.min(0); x1, y1 = pts.max(0); cx, cy = (x0+x1)/2, (y0+y1)/2; s = (x1-x0)*1.35/2
    return Image.fromarray(im[int(cy-s/2):int(cy+s/2), int(cx-s):int(cx+s)]).resize((420, 210), Image.LANCZOS)
SW = json.load(open(os.path.join(RES, 'metrics_sweep.json'), encoding='utf-8'))['rows']
order = ['off_C77276_glossy_065', 'off_C77276_glossy_050', 'off_C77276_glossy_035',
         'real_A26263_glossy_085', 'real_A26263_glossy_065', 'real_A26263_glossy_050',
         'real_A26263_glossy_035', 'real_A26263_matte_050', '__E']
fig, ax = plt.subplots(3, 3, figsize=(13, 7.4))
for a, n in zip(ax.flat, order):
    a.axis('off')
    if n == '__E':
        a.imshow(crop(os.path.join(ROOT, 'input/ref_crop_1024.png'))); a.set_title('E 실제 착용 사진 (기준)', fontsize=12, color='#1a2744'); continue
    r = SW[n]; li = r['lip_input']
    a.imshow(crop(os.path.join(ROOT, f'ar_out_sweep/sweep_{n}.png')))
    tag = ' (현재 앱 기본값)' if n == 'off_C77276_glossy_065' else ''
    col = '#1d7a46' if r['dE00_lip_vs_E_real'] < 2.3 else ('#b3261e' if r['dE00_lip_vs_E_real'] > 5 else '#333')
    a.set_title(f"{li['hex']} · {li['texture']} · {li['intensity']}{tag}\nΔE00 vs E = {r['dE00_lip_vs_E_real']:.2f}", fontsize=11, color=col)
plt.tight_layout(h_pad=2.2); plt.savefig(os.path.join(RES, 'fig_sweep.png'), dpi=110); print('ok')

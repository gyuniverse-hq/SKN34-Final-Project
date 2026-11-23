import sys, os, json, glob
import numpy as np, cv2
from PIL import Image, ImageDraw, ImageFont
import matplotlib; matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib import font_manager as fm
sys.path.insert(0, os.path.dirname(__file__))
ROOT, RES = sys.argv[1], sys.argv[2]
FONT = sys.argv[3] if len(sys.argv) > 3 else '/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc'
fm.fontManager.addfont(FONT); plt.rcParams['font.family'] = fm.FontProperties(fname=FONT).get_name()
plt.rcParams['axes.unicode_minus'] = False
import mediapipe as mp
from mediapipe.tasks.python import vision, BaseOptions
det = vision.FaceLandmarker.create_from_options(vision.FaceLandmarkerOptions(
    base_options=BaseOptions(model_asset_path=os.path.join(os.path.dirname(__file__), 'face_landmarker.task')), num_faces=1))
OUTER = [61,146,91,181,84,17,314,405,321,375,291,409,270,269,267,0,37,39,40,185]

def load(p, size=None):
    im = Image.open(p).convert('RGB')
    return np.asarray(im.resize((size, size), Image.LANCZOS) if size else im)

def lip_box(img, pad=0.35):
    r = det.detect(mp.Image(image_format=mp.ImageFormat.SRGB, data=np.ascontiguousarray(img)))
    h, w = img.shape[:2]
    pts = np.array([[r.face_landmarks[0][i].x * w, r.face_landmarks[0][i].y * h] for i in OUTER])
    x0, y0 = pts.min(0); x1, y1 = pts.max(0); cx, cy = (x0+x1)/2, (y0+y1)/2
    s = max(x1-x0, (y1-y0)*2) * (1+pad) / 2
    return [int(cx-s), int(cy-s/2), int(cx+s), int(cy+s/2)]

cols = [('A 맨얼굴', os.path.join(ROOT, 'input/bare_crop_1024.png'))]
ar = sorted(glob.glob(os.path.join(ROOT, 'ar_out/ar_lip_*.png')))
cols.append(('B VISHUE AR', ar[0] if ar else None))
cols += [('C MagicMakeup (립)', os.path.join(ROOT, 'out_magicmakeup/magicmakeup_seed0.png')),
         ('D Stable-Makeup (전체)', os.path.join(ROOT, 'out_stable_makeup/stablemakeup_seed0.png')),
         ('E 실제 착용 사진', os.path.join(ROOT, 'input/ref_crop_1024.png'))]

fig, ax = plt.subplots(2, 5, figsize=(17, 8.2), gridspec_kw={'height_ratios': [3.4, 1.6]})
for j, (t, p) in enumerate(cols):
    for i in range(2): ax[i, j].axis('off')
    if p is None:
        ax[0, j].text(0.5, 0.5, '미측정\n(AR 렌더 미실행)', ha='center', va='center', fontsize=15, color='#888')
        ax[0, j].set_title(t, fontsize=14); continue
    im = load(p)
    if im.shape[0] != 1024 and 'ar_' not in p: im = load(p, 1024)   # D 512→1024 표시용 업스케일
    ax[0, j].imshow(im); ax[0, j].set_title(t, fontsize=14)
    b = lip_box(im); ax[1, j].imshow(im[max(b[1],0):b[3], max(b[0],0):b[2]])
fig.text(0.5, 0.01, '동일 인물 · 같은 맨얼굴(A) 입력 · 제품: 롬앤 더 쥬시 래스팅 틴트 03 베어 그레이프 · C/D는 seed 0 · D는 512px 출력을 표시용 확대 · 아래 줄: 입술 확대',
         ha='center', fontsize=10.5, color='#444')
plt.tight_layout(rect=[0, 0.03, 1, 1]); plt.savefig(os.path.join(RES, 'fig_compare_5col.png'), dpi=110); plt.close()

# ΔE00 변화 맵
maps = np.load(os.path.join(RES, 'dE_maps.npz'))
keys = [k for k in ['B_VISHUE_AR_frame0', 'C_MagicMakeup_lip_seed0', 'D_StableMakeup_full_seed0'] if k in maps]
fig, ax = plt.subplots(1, len(keys), figsize=(5.2*len(keys), 5.4))
ax = np.atleast_1d(ax)
for a, k in zip(ax, keys):
    h = a.imshow(maps[k].astype(np.float32), cmap='magma', vmin=0, vmax=15); a.axis('off')
    a.set_title({'B': 'B VISHUE AR', 'C': 'C MagicMakeup (립)', 'D': 'D Stable-Makeup (전체)'}[k[0]] + '\n맨얼굴 대비 ΔE00', fontsize=13)
fig.colorbar(h, ax=list(ax), shrink=0.8, label='ΔE00 (0~15)')
plt.savefig(os.path.join(RES, 'fig_dE_maps.png'), dpi=110, bbox_inches='tight'); plt.close()

# seed별 색 정확도 막대
M = json.load(open(os.path.join(RES, 'metrics.json')))['rows']
names = [k for k in M if k.startswith(('B_', 'C_', 'D_')) and 'dE00_lip_vs_E_real' in M[k]]
lab = ['A 맨얼굴'] + [n.replace('_lip_', ' ').replace('_full_', ' ').replace('_VISHUE_', ' ').replace('_', ' ') for n in names]
v1 = [M['A_bare']['dE00_lip_vs_E_real']] + [M[n]['dE00_lip_vs_E_real'] for n in names]
fig, a = plt.subplots(figsize=(10, 4.2))
cl = ['#9e9e9e'] + ['#2d6cdf' if n.startswith('B') else '#e07b39' if n.startswith('C') else '#3a9a5b' for n in names]
a.bar(range(len(v1)), v1, color=cl); a.set_xticks(range(len(v1))); a.set_xticklabels(lab, rotation=20, ha='right', fontsize=10)
a.axhline(2.3, ls='--', c='#c33', lw=1); a.text(len(v1)-0.5, 2.4, 'JND≈2.3', color='#c33', ha='right', fontsize=9)
for i, v in enumerate(v1): a.text(i, v+0.08, f'{v:.2f}', ha='center', fontsize=9)
a.set_ylabel('입술 ΔE00 vs E (낮을수록 실제 발색에 가까움)'); a.set_title('색 정확도: 실제 착용 사진(E) 입술색 대비', fontsize=13)
plt.tight_layout(); plt.savefig(os.path.join(RES, 'fig_color_bar.png'), dpi=110); plt.close()
print('ok')

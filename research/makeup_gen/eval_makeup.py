"""VISHUE makeup-gen comparison metrics (A bare / B AR / C MagicMakeup / D Stable-Makeup / E real).

Core metrics (멘토링 11/19 권고: 기술 지표 2~3개)
  1. 색 정확도   : 입술 영역 CIELAB 중앙값 ΔE00 (vs E 실제 발색, vs 공식몰 목표 #C77276)
  2. 영역 정확도 : 변화 맵(ΔE00 vs 기준 맨얼굴)으로 본 입술 IoU / 번짐률, 입술 형태 IoU·Boundary F1
  3. 보존       : 입술 밖 얼굴 영역 SSIM, 평균 ΔE00 (LPIPS는 torch 부재로 미측정)
Lip mask = MediaPipe Face Landmarker(478) 바깥 입술 다각형 - 안쪽 입 다각형 (VISHUE AR과 같은 랜드마크 체계)
"""
import json, sys, os, glob, hashlib
import numpy as np, cv2
from PIL import Image
from skimage.color import rgb2lab, deltaE_ciede2000
from skimage.metrics import structural_similarity
import mediapipe as mp
from mediapipe.tasks.python import vision, BaseOptions

TASK = os.path.join(os.path.dirname(__file__), 'face_landmarker.task')
if not os.path.exists(TASK):   # same file (sha256 64184e22…) the env checks use
    TASK = os.path.join(os.path.dirname(__file__), '..', 'data', 'env_eval_runs', 'models', 'face_landmarker.task')
OUTER = [61,146,91,181,84,17,314,405,321,375,291,409,270,269,267,0,37,39,40,185]
INNER = [78,95,88,178,87,14,317,402,318,324,308,415,310,311,312,13,82,81,80,191]
TARGET_LAB = np.array([57.4, 32.0, 12.6])   # product_target.json target_on_lip
THR = 5.0                                   # 변화 판정 ΔE00 임계값 (JND≈2.3의 약 2배, 노이즈 배제)

det = vision.FaceLandmarker.create_from_options(vision.FaceLandmarkerOptions(
    base_options=BaseOptions(model_asset_path=TASK), num_faces=1))

def load(p): return np.asarray(Image.open(p).convert('RGB'))
def pix_sha(a): return hashlib.sha256(a.tobytes()).hexdigest()

def landmarks(img):
    r = det.detect(mp.Image(image_format=mp.ImageFormat.SRGB, data=np.ascontiguousarray(img)))
    if not r.face_landmarks: return None
    h, w = img.shape[:2]
    return np.array([[p.x * w, p.y * h] for p in r.face_landmarks[0]], np.float32)

def lip_mask(img, lm):
    m = np.zeros(img.shape[:2], np.uint8)
    cv2.fillPoly(m, [lm[OUTER].astype(np.int32)], 1)
    cv2.fillPoly(m, [lm[INNER].astype(np.int32)], 0)
    return m.astype(bool)

def lip_lab(img, m):
    lab = rgb2lab(img)[m]
    return np.median(lab, 0), lab.mean(0)

def de(a, b): return float(deltaE_ciede2000(np.array(a)[None], np.array(b)[None])[0])

def boundary_f1(m1, m2, tol):
    c1 = cv2.morphologyEx(m1.astype(np.uint8), cv2.MORPH_GRADIENT, np.ones((3,3), np.uint8)) > 0
    c2 = cv2.morphologyEx(m2.astype(np.uint8), cv2.MORPH_GRADIENT, np.ones((3,3), np.uint8)) > 0
    k = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2*tol+1, 2*tol+1))
    d1, d2 = cv2.dilate(c1.astype(np.uint8), k) > 0, cv2.dilate(c2.astype(np.uint8), k) > 0
    p = (c1 & d2).sum() / max(c1.sum(), 1); r = (c2 & d1).sum() / max(c2.sum(), 1)
    return float(2*p*r/(p+r)) if p+r else 0.0

def iou(a, b): return float((a & b).sum() / max((a | b).sum(), 1))

def compare(name, img, base, base_lm, face_m, E_lab):
    """img·base는 같은 해상도·같은 촬영 프레임이어야 함."""
    lm = landmarks(img)
    out = {'name': name, 'size': list(img.shape[:2][::-1]), 'pixel_sha256': pix_sha(img)}
    if lm is None: out['error'] = 'face not detected'; return out, None
    m = lip_mask(img, lm); mb = lip_mask(base, base_lm)
    med, mean = lip_lab(img, m)
    s = img.shape[0] / 1024
    iod = np.linalg.norm(base_lm[33] - base_lm[263])
    out.update({
        'lip_lab_median': [round(float(v), 1) for v in med],
        'lip_hex_median': '#%02X%02X%02X' % tuple(int(v) for v in np.median(img[m], 0)),
        'dE00_lip_vs_E_real': round(de(med, E_lab), 2),
        'dE00_lip_vs_official_target': round(de(med, TARGET_LAB), 2),
        'dE00_lip_vs_bare': round(de(med, lip_lab(base, mb)[0]), 2),
        'lip_shape_IoU_vs_bare': round(iou(m, mb), 3),
        'lip_boundary_F1_vs_bare': round(boundary_f1(m, mb, max(2, round(4*s))), 3),
        'landmark_shift_pct_IOD': round(float(np.linalg.norm(lm - base_lm, axis=1).mean() / iod * 100), 2),
    })
    dmap = deltaE_ciede2000(rgb2lab(base), rgb2lab(img))
    k = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (int(21*s)|1, int(21*s)|1))
    lip_dil = cv2.dilate(mb.astype(np.uint8), k) > 0
    outside = face_m & ~lip_dil
    changed = (dmap > THR) & (face_m | lip_dil)
    g1, g2 = cv2.cvtColor(base, cv2.COLOR_RGB2GRAY), cv2.cvtColor(img, cv2.COLOR_RGB2GRAY)
    _, ssim_map = structural_similarity(g1, g2, full=True, data_range=255)
    out.update({
        'change_dE00_mean_in_lip': round(float(dmap[mb].mean()), 2),
        'change_dE00_mean_outside_lip(face)': round(float(dmap[outside].mean()), 2),
        'changed_region_IoU_with_lip(thr5)': round(iou(changed, mb), 3),
        'bleed_ratio(changed outside lip / all changed)': round(float((changed & ~lip_dil).sum() / max(changed.sum(), 1)), 3),
        'SSIM_outside_lip(face)': round(float(ssim_map[outside].mean()), 4),
        'LPIPS_outside_lip': '미측정 (torch/lpips 미설치 환경)',
    })
    return out, dmap

def face_mask_from(path, shape):
    fm = np.asarray(Image.open(path).convert('L').resize(shape[::-1], Image.NEAREST)) > 127
    return fm

def main():
    ROOT = sys.argv[1]            # research/data/makeup_gen (staged copy)
    OUT = sys.argv[2]
    os.makedirs(OUT, exist_ok=True)
    res = {'method': {
        'lip_mask': 'MediaPipe FaceLandmarker 478, outer lip polygon minus inner mouth polygon (각 이미지 자체 랜드마크)',
        'lip_color': '입술 마스크 내 CIELAB(D65) 중앙값, ΔE00 = skimage CIEDE2000',
        'E_real_lip': 'E(실제 발라본 사진) 입술 중앙값 = 실제 발색 기준',
        'official_target_lab': TARGET_LAB.tolist(),
        'change_threshold_dE00': THR,
        'face_region': 'MagicMakeup faceparsing(jonathandinu/face-parsing) 맨얼굴 얼굴 마스크',
        'lip_dilation_for_outside': '21px @1024 (해상도 비례)',
        'landmark_model_sha256': hashlib.sha256(open(TASK, 'rb').read()).hexdigest(),
    }, 'rows': {}}

    INP = os.path.join(ROOT, 'input')
    A = load(os.path.join(INP, 'bare_crop_1024.png')); E = load(os.path.join(INP, 'ref_crop_1024.png'))
    A_lm, E_lm = landmarks(A), landmarks(E)
    E_lab = lip_lab(E, lip_mask(E, E_lm))[0]
    A_lab = lip_lab(A, lip_mask(A, A_lm))[0]
    FACE = face_mask_from(os.path.join(ROOT, 'out_magicmakeup/masks/bare_crop_1024.png'), A.shape[:2])
    res['rows']['E_real'] = {'lip_lab_median': [round(float(v), 1) for v in E_lab],
        'dE00_lip_vs_official_target': round(de(E_lab, TARGET_LAB), 2), 'dE00_lip_vs_bare': round(de(E_lab, A_lab), 2),
        'note': '다른 촬영(조명·각도·안경 다름) → 영역/보존 지표 비대상. 레퍼런스이자 정답이라 순환성 있음'}
    res['rows']['A_bare'] = {'lip_lab_median': [round(float(v), 1) for v in A_lab],
        'dE00_lip_vs_E_real': round(de(A_lab, E_lab), 2), 'dE00_lip_vs_official_target': round(de(A_lab, TARGET_LAB), 2)}

    maps = {}
    for s in range(3):
        p = os.path.join(ROOT, f'out_magicmakeup/magicmakeup_seed{s}.png')
        r, dm = compare(f'C_MagicMakeup_lip_seed{s}', load(p), A, A_lm, FACE, E_lab); res['rows'][r['name']] = r; maps[r['name']] = dm
    A5 = np.asarray(Image.fromarray(A).resize((512, 512), Image.LANCZOS)); A5_lm = landmarks(A5)
    FACE5 = face_mask_from(os.path.join(ROOT, 'out_magicmakeup/masks/bare_crop_1024.png'), (512, 512))
    for s in range(3):
        p = os.path.join(ROOT, f'out_stable_makeup/stablemakeup_seed{s}.png')
        r, dm = compare(f'D_StableMakeup_full_seed{s}', load(p), A5, A5_lm, FACE5, E_lab); res['rows'][r['name']] = r; maps[r['name']] = dm

    # B: VISHUE AR (있으면). 기준 = 같은 프레임 AR off
    ar = sorted(glob.glob(os.path.join(ROOT, 'ar_out/ar_lip_*.png'))); off = sorted(glob.glob(os.path.join(ROOT, 'ar_out/ar_off_*.png')))
    if ar and off:
        O = load(off[0]); O_lm = landmarks(O)
        fm = np.zeros(O.shape[:2], bool)
        hull = cv2.convexHull(O_lm.astype(np.int32)); cv2.fillPoly(fm := fm.astype(np.uint8), [hull], 1); fm = fm.astype(bool)
        res['method']['B_face_region'] = 'AR 프레임은 크롭이 달라 face-parsing 대신 랜드마크 볼록 껍질 사용'
        for i, p in enumerate(ar):
            r, dm = compare(f'B_VISHUE_AR_frame{i}', load(p), O, O_lm, fm, E_lab); res['rows'][r['name']] = r; maps[r['name']] = dm
    else:
        res['rows']['B_VISHUE_AR'] = {'status': '미측정 — ar_out/ 없음 (PC에서 ar_render.mjs 미실행)'}

    # seed 평균
    def agg(prefix):
        rows = [v for k, v in res['rows'].items() if k.startswith(prefix) and 'error' not in v and 'status' not in v]
        if not rows: return None
        keys = [k for k, v in rows[0].items() if isinstance(v, (int, float))]
        return {k: {'mean': round(float(np.mean([r[k] for r in rows])), 3), 'min': round(float(np.min([r[k] for r in rows])), 3),
                    'max': round(float(np.max([r[k] for r in rows])), 3)} for k in keys}
    res['summary'] = {p: agg(p) for p in ('B_VISHUE_AR', 'C_MagicMakeup', 'D_StableMakeup')}
    json.dump(res, open(os.path.join(OUT, 'metrics.json'), 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    np.savez_compressed(os.path.join(OUT, 'dE_maps.npz'), **{k: v.astype(np.float16) for k, v in maps.items() if v is not None})
    print(json.dumps(res['rows'], ensure_ascii=False, indent=1))


if __name__ == '__main__':
    main()

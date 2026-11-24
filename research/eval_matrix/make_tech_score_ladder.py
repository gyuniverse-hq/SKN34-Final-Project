"""문항(지표)별 점수대 시각 사다리 — 눈으로 합격선 고르기.

첨부 ΔE 스와치처럼 왼쪽=기준, 오른쪽=그 점수만큼 다른 예시.
ΔE는 Lab 색 스플릿, SSIM/MAE는 실립 crop 기준 열화, mIoU는 합성 마스크.

  ml/.venv/Scripts/python.exe research/eval_matrix/make_tech_score_ladder.py
  # open research/data/eval_matrix/tech_score_ladder/index.html
"""
from __future__ import annotations

import json
import math
import shutil
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "research" / "data"
SRC = DATA / "baregrape_hw01" / "compare" / "images"
OUT = DATA / "eval_matrix" / "tech_score_ladder"
IMG = OUT / "images"
SIZE = 220  # swatch / crop side


# --- color math --------------------------------------------------------------

def _srgb_to_linear(rgb: np.ndarray) -> np.ndarray:
    return np.where(rgb <= 0.04045, rgb / 12.92, ((rgb + 0.055) / 1.055) ** 2.4)


def _linear_to_srgb(lin: np.ndarray) -> np.ndarray:
    return np.where(lin <= 0.0031308, 12.92 * lin, 1.055 * np.power(np.clip(lin, 0, None), 1 / 2.4) - 0.055)


def srgb_to_lab(rgb: np.ndarray) -> np.ndarray:
    a = _srgb_to_linear(rgb)
    m = np.array([
        [0.4124564, 0.3575761, 0.1804375],
        [0.2126729, 0.7151522, 0.0721750],
        [0.0193339, 0.1191920, 0.9503041],
    ])
    xyz = a @ m.T
    w = np.array([0.95047, 1.0, 1.08883])
    x = xyz / w
    f = np.where(x > 0.008856, np.cbrt(x), (903.3 * x + 16) / 116)
    L = 116 * f[..., 1] - 16
    A = 500 * (f[..., 0] - f[..., 1])
    B = 200 * (f[..., 1] - f[..., 2])
    return np.stack([L, A, B], axis=-1)


def lab_to_srgb(lab: np.ndarray) -> np.ndarray:
    L, A, B = lab[..., 0], lab[..., 1], lab[..., 2]
    fy = (L + 16) / 116
    fx = fy + A / 500
    fz = fy - B / 200
    eps = 0.008856
    xr = np.where(fx ** 3 > eps, fx ** 3, (116 * fx - 16) / 903.3)
    yr = np.where(L > 7.9996, ((L + 16) / 116) ** 3, L / 903.3)
    zr = np.where(fz ** 3 > eps, fz ** 3, (116 * fz - 16) / 903.3)
    xyz = np.stack([xr * 0.95047, yr, zr * 1.08883], axis=-1)
    m_inv = np.array([
        [3.2404542, -1.5371385, -0.4985314],
        [-0.9692660, 1.8760108, 0.0415560],
        [0.0556434, -0.2040259, 1.0572252],
    ])
    lin = xyz @ m_inv.T
    return np.clip(_linear_to_srgb(lin), 0, 1)


def delta_e00(lab1, lab2) -> float:
    L1, a1, b1 = map(float, lab1)
    L2, a2, b2 = map(float, lab2)
    C1, C2 = math.hypot(a1, b1), math.hypot(a2, b2)
    Cab = (C1 + C2) / 2
    G = 0.5 * (1 - math.sqrt(Cab ** 7 / (Cab ** 7 + 25 ** 7))) if Cab else 0.0
    a1p, a2p = (1 + G) * a1, (1 + G) * a2
    C1p, C2p = math.hypot(a1p, b1), math.hypot(a2p, b2)
    h1p = (math.degrees(math.atan2(b1, a1p)) + 360) % 360
    h2p = (math.degrees(math.atan2(b2, a2p)) + 360) % 360
    dLp = L2 - L1
    dCp = C2p - C1p
    if C1p * C2p == 0:
        dhp = 0.0
    else:
        dh = h2p - h1p
        if abs(dh) > 180:
            dh -= 360 * (1 if dh > 0 else -1)
        dhp = dh
    dHp = 2 * math.sqrt(max(C1p * C2p, 0)) * math.sin(math.radians(dhp) / 2)
    Lp = (L1 + L2) / 2
    Cp = (C1p + C2p) / 2
    if C1p * C2p == 0:
        hp = h1p + h2p
    else:
        if abs(h1p - h2p) <= 180:
            hp = (h1p + h2p) / 2
        else:
            hp = (h1p + h2p + 360) / 2 if (h1p + h2p) < 360 else (h1p + h2p - 360) / 2
    T = (1 - 0.17 * math.cos(math.radians(hp - 30)) + 0.24 * math.cos(math.radians(2 * hp))
         + 0.32 * math.cos(math.radians(3 * hp + 6)) - 0.20 * math.cos(math.radians(4 * hp - 63)))
    dRo = 30 * math.exp(-(((hp - 275) / 25) ** 2))
    Rc = 2 * math.sqrt(Cp ** 7 / (Cp ** 7 + 25 ** 7)) if Cp else 0.0
    Sl = 1 + (0.015 * (Lp - 50) ** 2) / math.sqrt(20 + (Lp - 50) ** 2)
    Sc = 1 + 0.045 * Cp
    Sh = 1 + 0.015 * Cp * T
    Rt = -math.sin(math.radians(2 * dRo)) * Rc
    return math.sqrt(
        (dLp / Sl) ** 2 + (dCp / Sc) ** 2 + (dHp / Sh) ** 2 + Rt * (dCp / Sc) * (dHp / Sh)
    )


def lab_at_de(lab_ref: np.ndarray, target: float, direction: np.ndarray | None = None) -> np.ndarray:
    """Find Lab near lab_ref with CIEDE2000 ≈ target (binary search on scale)."""
    if direction is None:
        # brighter + more chroma (matches the reference strip look)
        direction = np.array([0.35, 0.75, 0.55], dtype=np.float64)
    d = direction / (np.linalg.norm(direction) + 1e-12)
    lo, hi = 0.0, 80.0
    best = lab_ref.copy()
    for _ in range(48):
        mid = (lo + hi) / 2
        cand = lab_ref + mid * d
        de = delta_e00(lab_ref, cand)
        best = cand
        if de < target:
            lo = mid
        else:
            hi = mid
    return best


def ssim_gray(a: np.ndarray, b: np.ndarray) -> float:
    if a.shape != b.shape:
        hb, wb = a.shape
        bi = Image.fromarray((np.clip(b, 0, 1) * 255).astype(np.uint8)).resize((wb, hb), Image.BILINEAR)
        b = np.asarray(bi, dtype=np.float64) / 255.0
    C1, C2 = (0.01 ** 2), (0.03 ** 2)
    mu_a, mu_b = a.mean(), b.mean()
    sig_a, sig_b = a.var(), b.var()
    sig_ab = ((a - mu_a) * (b - mu_b)).mean()
    return float(((2 * mu_a * mu_b + C1) * (2 * sig_ab + C2)) /
                 ((mu_a ** 2 + mu_b ** 2 + C1) * (sig_a + sig_b + C2)))


def mae_rgb(a: np.ndarray, b: np.ndarray) -> float:
    return float(np.mean(np.abs(a - b)))


def iou_masks(a: np.ndarray, b: np.ndarray) -> float:
    inter = np.logical_and(a, b).sum()
    union = np.logical_or(a, b).sum()
    return float(inter / union) if union else 1.0


# --- image helpers -----------------------------------------------------------

def load_rgb(path: Path, size: int = SIZE) -> np.ndarray:
    im = Image.open(path).convert("RGB").resize((size, size), Image.LANCZOS)
    return np.asarray(im, dtype=np.float64) / 255.0


def save_split(left: np.ndarray, right: np.ndarray, path: Path) -> None:
    h, w = left.shape[:2]
    canvas = np.zeros_like(left)
    mid = w // 2
    canvas[:, :mid] = left[:, :mid]
    canvas[:, mid:] = right[:, mid:]
    # thin separator
    canvas[:, mid - 1:mid + 1] = 0.92
    Image.fromarray((np.clip(canvas, 0, 1) * 255).astype(np.uint8)).save(path)


def solid(lab: np.ndarray, size: int = SIZE) -> np.ndarray:
    rgb = lab_to_srgb(lab.reshape(1, 1, 3))[0, 0]
    return np.broadcast_to(rgb, (size, size, 3)).copy()


def ref_lip_lab() -> np.ndarray:
    """기준 입술색 Lab — 첨부 ΔE 막대와 비슷한 벽돌/뮤트 레드.

    crop 평균 Lab은 채도가 낮아 점수대 차이가 눈으로 잘 안 보여,
    시각 사다리용으로 채도 있는 기준색을 쓴다 (측정 ROI 평균과 별개).
    """
    return np.array([42.0, 38.0, 22.0], dtype=np.float64)


def pick_ref_crop() -> Path:
    p = SRC / "s03_real_lips.png"
    if p.is_file():
        return p
    paths = sorted(SRC.glob("*_real_lips.png"))
    if not paths:
        raise FileNotFoundError("no real lip crops")
    return paths[0]


# --- ladder builders ---------------------------------------------------------

def build_delta_e(lab_ref: np.ndarray) -> list[dict]:
    # dense bands + labeled anchors from docs / measured
    bands = [
        (0.5, None),
        (0.8, "알아챔 경계"),
        (1.0, None),
        (1.2, None),
        (1.5, None),
        (1.8, "허용 경계 (공개 기준)"),
        (2.0, None),
        (2.3, None),
        (2.6, None),
        (2.9, "사진끼리 피부 차이(floor)"),
        (3.2, None),
        (3.5, None),
        (3.65, "우리 AR 중앙값(쌍 측정)"),
        (4.0, None),
        (4.5, None),
        (5.0, None),
        (6.0, None),
        (7.2, "맨입술 중앙값(쌍 측정)"),
    ]
    left = solid(lab_ref)
    out = []
    for val, label in bands:
        lab2 = lab_at_de(lab_ref, val)
        right = solid(lab2)
        name = f"de_{val:.2f}".replace(".", "p") + ".png"
        save_split(left, right, IMG / name)
        measured = round(delta_e00(lab_ref, lab2), 3)
        out.append({
            "value": val,
            "measured": measured,
            "label": label,
            "img": f"images/{name}",
            "hint": "낮을수록 좋음 · 합격 = 이 값 이하",
        })
    return out


def degrade_for_ssim(ref: np.ndarray, target: float) -> np.ndarray:
    """Binary-search mix of blur+noise+tint to hit SSIM ≈ target (lower = worse)."""
    g_ref = ref.mean(-1)
    # if already below, return heavily degraded
    rng = np.random.default_rng(0)
    noise = rng.normal(0, 1, ref.shape)
    noise = (noise - noise.min()) / (noise.max() - noise.min() + 1e-9)

    def make(t: float) -> np.ndarray:
        # t=0 identical, t=1 heavily different
        blur_r = max(1, int(1 + t * 28) | 1)
        soft = np.asarray(
            Image.fromarray((ref * 255).astype(np.uint8)).resize(
                (max(4, SIZE // (1 + int(t * 8))), max(4, SIZE // (1 + int(t * 8)))), Image.BILINEAR
            ).resize((SIZE, SIZE), Image.BILINEAR),
            dtype=np.float64,
        ) / 255.0
        tint = ref.copy()
        tint[..., 0] = np.clip(tint[..., 0] * (1 + 0.35 * t) + 0.08 * t, 0, 1)
        tint[..., 1] = np.clip(tint[..., 1] * (1 - 0.15 * t), 0, 1)
        mix = (1 - t) * ref + t * (0.55 * soft + 0.25 * noise + 0.20 * tint)
        return np.clip(mix, 0, 1)

    lo, hi = 0.0, 1.0
    best = ref.copy()
    for _ in range(28):
        mid = (lo + hi) / 2
        cand = make(mid)
        s = ssim_gray(g_ref, cand.mean(-1))
        best = cand
        # want SSIM close to target; if too high (too similar), increase degradation
        if s > target:
            lo = mid
        else:
            hi = mid
    return best


def build_ssim(ref: np.ndarray) -> list[dict]:
    bands = [
        (0.98, "거의 동일"),
        (0.95, None),
        (0.92, None),
        (0.90, None),
        (0.88, None),
        (0.85, None),
        (0.80, None),
        (0.75, None),
        (0.70, None),
        (0.66, "우리 AR 중앙값(쌍 측정)"),
        (0.60, None),
        (0.50, None),
        (0.40, None),
    ]
    out = []
    g_ref = ref.mean(-1)
    for val, label in bands:
        right = degrade_for_ssim(ref, val)
        measured = round(ssim_gray(g_ref, right.mean(-1)), 3)
        name = f"ssim_{val:.2f}".replace(".", "p") + ".png"
        save_split(ref, right, IMG / name)
        out.append({
            "value": val,
            "measured": measured,
            "label": label,
            "img": f"images/{name}",
            "hint": "높을수록 좋음 · 합격 = 이 값 이상",
        })
    return out


def degrade_for_mae(ref: np.ndarray, target: float) -> np.ndarray:
    """Shift + noise until MAE ≈ target."""
    rng = np.random.default_rng(1)
    noise = rng.normal(0, 1, ref.shape)

    def make(scale: float) -> np.ndarray:
        shift = np.array([0.55, -0.15, -0.05]) * scale
        return np.clip(ref + shift + noise * (0.08 * scale), 0, 1)

    lo, hi = 0.0, 1.2
    best = ref.copy()
    for _ in range(32):
        mid = (lo + hi) / 2
        cand = make(mid)
        m = mae_rgb(ref, cand)
        best = cand
        if m < target:
            lo = mid
        else:
            hi = mid
    return best


def build_mae(ref: np.ndarray) -> list[dict]:
    bands = [
        (0.01, "거의 동일"),
        (0.02, None),
        (0.03, None),
        (0.04, None),
        (0.05, None),
        (0.06, None),
        (0.08, "baregrape crop 근처"),
        (0.10, None),
        (0.12, None),
        (0.15, None),
        (0.20, None),
    ]
    out = []
    for val, label in bands:
        right = degrade_for_mae(ref, val)
        measured = round(mae_rgb(ref, right), 4)
        name = f"mae_{val:.2f}".replace(".", "p") + ".png"
        save_split(ref, right, IMG / name)
        out.append({
            "value": val,
            "measured": measured,
            "label": label,
            "img": f"images/{name}",
            "hint": "낮을수록 좋음 · 합격 = 이 값 이하",
        })
    return out


def lip_mask(size: int = SIZE) -> np.ndarray:
    im = Image.new("L", (size, size), 0)
    d = ImageDraw.Draw(im)
    # upper + lower lip ellipses
    d.ellipse((size * 0.18, size * 0.28, size * 0.82, size * 0.52), fill=255)
    d.ellipse((size * 0.16, size * 0.42, size * 0.84, size * 0.72), fill=255)
    return np.asarray(im) > 127


def mask_at_iou(gt: np.ndarray, target: float) -> np.ndarray:
    """Erode/dilate/shift until IoU ≈ target."""
    from PIL import ImageFilter

    def as_img(m):
        return Image.fromarray((m.astype(np.uint8) * 255))

    # try dilation/erosion radius
    best = gt.copy()
    best_err = 1e9
    for r in range(0, 40):
        for mode in ("dilate", "erode", "shift"):
            if mode == "dilate":
                m = np.asarray(as_img(gt).filter(ImageFilter.MaxFilter(2 * r + 1))) > 127 if r else gt
            elif mode == "erode":
                m = np.asarray(as_img(gt).filter(ImageFilter.MinFilter(2 * r + 1))) > 127 if r else gt
            else:
                m = np.zeros_like(gt)
                s = r
                m[s:, s:] = gt[:-s, :-s] if s else gt
            v = iou_masks(gt, m)
            err = abs(v - target)
            if err < best_err:
                best_err, best = err, m
            if err < 0.008:
                return m
    return best


def mask_viz(gt: np.ndarray, pred: np.ndarray) -> np.ndarray:
    """Left = GT green, right = pred; both on dark with split."""
    h, w = gt.shape
    left = np.zeros((h, w, 3))
    right = np.zeros((h, w, 3))
    left[gt] = (0.15, 0.75, 0.35)
    right[pred] = (0.90, 0.35, 0.25)
    # overlap hint on right
    both = np.logical_and(gt, pred)
    right[both] = (0.95, 0.85, 0.2)
    return left, right


def build_miou() -> list[dict]:
    gt = lip_mask()
    bands = [
        (0.95, None),
        (0.90, None),
        (0.85, None),
        (0.80, None),
        (0.797, "SegFace LaPa 공개 SOTA"),
        (0.75, None),
        (0.70, None),
        (0.60, None),
        (0.50, None),
    ]
    out = []
    for val, label in bands:
        pred = mask_at_iou(gt, val)
        measured = round(iou_masks(gt, pred), 3)
        left, right = mask_viz(gt, pred)
        name = f"miou_{val:.3f}".replace(".", "p") + ".png"
        save_split(left, right, IMG / name)
        out.append({
            "value": val,
            "measured": measured,
            "label": label,
            "img": f"images/{name}",
            "hint": "높을수록 좋음 · 합격 = 이 값 이상 · 초록=정답 빨강=예측 노랑=겹침",
        })
    return out


# --- HTML --------------------------------------------------------------------

HTML = """<!DOCTYPE html>
<html lang="ko"><head><meta charset="utf-8"/>
<title>테크니컬 점수대 사다리 — 합격선 고르기</title>
<style>
:root{--bg:#111;--card:#1c1c1c;--line:#333;--ok:#2a9d8f;--warn:#e9c46a;--bad:#e76f51;--muted:#9aa}
body{font-family:system-ui,sans-serif;margin:0;background:var(--bg);color:#eee}
header{padding:20px 24px 8px;max-width:1100px}
h1{font-size:1.25rem;margin:0 0 8px}
.meta{opacity:.9;line-height:1.5;font-size:14px;max-width:48rem}
.sticky{position:sticky;top:0;z-index:10;background:#161616;border-bottom:1px solid #333;
  padding:12px 24px;display:flex;flex-wrap:wrap;gap:12px;align-items:flex-start}
.stats{flex:1;min-width:260px;font-size:13px;line-height:1.45;white-space:pre-wrap;background:#1a1a1a;
  padding:10px 12px;border-radius:8px}
button{background:var(--ok);color:#fff;border:0;padding:8px 14px;border-radius:6px;cursor:pointer;font-weight:600}
button.secondary{background:#444}
section{padding:18px 24px 8px;max-width:1100px}
section h2{font-size:1.05rem;margin:0 0 4px}
section .sub{font-size:13px;color:var(--muted);margin:0 0 12px;line-height:1.4}
.row{display:flex;gap:10px;overflow-x:auto;padding-bottom:12px}
.cell{flex:0 0 auto;width:148px;background:var(--card);border:2px solid var(--line);border-radius:10px;overflow:hidden}
.cell.sel{border-color:var(--ok);box-shadow:0 0 0 1px var(--ok)}
.cell.anchor{border-color:var(--warn)}
.cell img{width:100%;aspect-ratio:1;object-fit:cover;display:block;background:#000}
.cell .body{padding:8px 8px 10px;font-size:11px;line-height:1.35}
.cell .body b{font-size:15px;display:block}
.cell .lbl{color:var(--warn);font-weight:600;min-height:1.2em}
.cell label{display:flex;gap:6px;align-items:center;margin-top:6px;cursor:pointer;user-select:none}
.cell input{width:16px;height:16px}
.dir{font-size:11px;color:var(--muted)}
footer{padding:24px;color:var(--muted);font-size:12px}
</style></head><body>
<header>
  <h1>테크니컬 점수대 사다리 — 눈으로 합격선 고르기</h1>
  <p class="meta">각 문항마다 점수대를 쭉 늘어놓았습니다. <b>왼쪽 = 기준</b>, <b>오른쪽 = 그 점수만큼 다른 예시</b>.
  “이 정도면 합격”인 칸을 고르면 그게 팀 눈 앵커 합격선입니다. 공개 역치·측정 중앙값은 노란 라벨로 표시.</p>
</header>
<div class="sticky">
  <button type="button" id="dl">합격선 JSON 저장</button>
  <button type="button" id="clear" class="secondary">선택 해제</button>
  <div class="stats" id="stats">문항마다 합격 칸을 하나 고르세요.</div>
</div>
<div id="sections"></div>
<footer>생성: make_tech_score_ladder.py · 기준 Lab/실립 crop = baregrape_hw01 · 문서 원칙상 이 선은 팀 눈 앵커이며 공개 역치와 병기.</footer>
<script>
const DATA = __DATA__;
const picks = {}; // metricId -> value

function fmt(x, d=2){ return (x==null||Number.isNaN(x))?'—':Number(x).toFixed(d); }

function renderStats(){
  const lines = DATA.metrics.map(m => {
    const v = picks[m.id];
    if (v==null) return m.name + ': (미선택)';
    const dir = m.direction === 'lower_better' ? '≤' : '≥';
    return m.name + ': 합격 ' + dir + ' ' + fmt(v, m.id==='mae'?3: m.id==='miou'?3:2);
  });
  document.getElementById('stats').textContent = lines.join('\\n');
}

function section(m){
  const sec = document.createElement('section');
  sec.innerHTML = `<h2>${m.name}</h2><p class="sub">${m.what}<br/><span class="dir">${m.hint}</span></p>`;
  const row = document.createElement('div');
  row.className = 'row';
  m.bands.forEach(b => {
    const cell = document.createElement('div');
    cell.className = 'cell' + (b.label ? ' anchor' : '');
    cell.innerHTML = `
      <img src="${b.img}" alt="${m.id} ${b.value}" loading="lazy"/>
      <div class="body">
        <b>${fmt(b.value, m.id==='mae'?2: m.id==='miou'?3:2)}</b>
        <div class="lbl">${b.label || ''}</div>
        <div style="opacity:.65">실측 ${fmt(b.measured, m.id==='mae'?3:3)}</div>
        <label><input type="radio" name="pass_${m.id}" value="${b.value}"/> 여기를 합격선</label>
      </div>`;
    const input = cell.querySelector('input');
    input.addEventListener('change', () => {
      picks[m.id] = Number(b.value);
      row.querySelectorAll('.cell').forEach(c => c.classList.remove('sel'));
      cell.classList.add('sel');
      renderStats();
    });
    row.appendChild(cell);
  });
  sec.appendChild(row);
  return sec;
}

const root = document.getElementById('sections');
DATA.metrics.forEach(m => root.appendChild(section(m)));

document.getElementById('clear').onclick = () => {
  Object.keys(picks).forEach(k => delete picks[k]);
  document.querySelectorAll('input[type=radio]').forEach(i => { i.checked = false; });
  document.querySelectorAll('.cell.sel').forEach(c => c.classList.remove('sel'));
  renderStats();
};

document.getElementById('dl').onclick = () => {
  const missing = DATA.metrics.filter(m => picks[m.id]==null).map(m => m.name);
  if (missing.length) {
    if (!confirm('아직 안 고른 문항: ' + missing.join(', ') + '\\n그래도 저장할까요?')) return;
  }
  const payload = {
    decided_at: new Date().toISOString().slice(0,10),
    kind: 'team_eye_anchor_score_ladder',
    source: DATA.source,
    pass_lines: Object.fromEntries(DATA.metrics.map(m => {
      const v = picks[m.id];
      return [m.id, v==null ? null : {
        value: v,
        direction: m.direction,
        rule: m.direction === 'lower_better' ? ('<=' + v) : ('>=' + v),
        note: '팀 눈 앵커 (점수대 사다리)',
      }];
    })),
    published_refs: DATA.published_refs,
    note: '팀 눈 앵커. 공개 역치·SOTA와 병기할 것. 임의 팀 역치를 증거 있는 합격선처럼 쓰지 말 것.',
  };
  const a = document.createElement('a');
  a.href = URL.createObjectURL(new Blob([JSON.stringify(payload,null,2)],{type:'application/json'}));
  a.download = 'tech_pass_lines_from_ladder.json';
  a.click();
};
</script>
</body></html>
"""


def build():
    if OUT.exists():
        shutil.rmtree(OUT)
    IMG.mkdir(parents=True)

    lab_ref = ref_lip_lab()
    ref_path = pick_ref_crop()
    ref = load_rgb(ref_path)

    metrics = [
        {
            "id": "delta_e",
            "name": "1. ΔE CIE2000 (색 차이)",
            "what": "왼쪽 = 기준 입술색(실립 crop 평균 Lab), 오른쪽 = ΔE만큼 다른 단색.",
            "hint": "낮을수록 좋음 · 합격 = 고른 칸 이하",
            "direction": "lower_better",
            "bands": build_delta_e(lab_ref),
        },
        {
            "id": "ssim",
            "name": "2. SSIM (구조·명암)",
            "what": f"왼쪽 = 실립 crop({ref_path.name}), 오른쪽 = SSIM이 그 값이 되도록 열화.",
            "hint": "높을수록 좋음 · 합격 = 고른 칸 이상",
            "direction": "higher_better",
            "bands": build_ssim(ref),
        },
        {
            "id": "mae",
            "name": "3. MAE (픽셀 절대오차)",
            "what": f"왼쪽 = 실립 crop({ref_path.name}), 오른쪽 = MAE가 그 값이 되도록 색·노이즈 이동.",
            "hint": "낮을수록 좋음 · 합격 = 고른 칸 이하 · RGB 0~1 스케일",
            "direction": "lower_better",
            "bands": build_mae(ref),
        },
        {
            "id": "miou",
            "name": "4. mIoU (입술 마스크 겹침)",
            "what": "왼쪽 = 정답 마스크(초록), 오른쪽 = 예측(빨강) · 겹침=노랑. 합성 타원으로 IoU 눈금만 보여 줌.",
            "hint": "높을수록 좋음 · 합격 = 고른 칸 이상",
            "direction": "higher_better",
            "bands": build_miou(),
        },
    ]

    payload = {
        "source": {
            "lip_lab": [round(float(x), 3) for x in lab_ref],
            "ref_crop": str(ref_path),
            "pair_medians_note": "ΔE AR med≈3.65, bare≈7.2 (lip_pairs_evaluated); SSIM AR med≈0.66",
        },
        "published_refs": {
            "delta_e_acceptability": 1.8,
            "delta_e_perceptibility": 0.8,
            "skin_floor_example": 2.9,
            "miou_segface_lapa": 0.797,
        },
        "metrics": metrics,
    }

    (OUT / "summary.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf8")
    html = HTML.replace("__DATA__", json.dumps(payload, ensure_ascii=False))
    (OUT / "index.html").write_text(html, encoding="utf8")
    print(json.dumps({
        "out": str(OUT / "index.html"),
        "n_metrics": len(metrics),
        "bands": {m["id"]: len(m["bands"]) for m in metrics},
        "lab_ref": payload["source"]["lip_lab"],
    }, ensure_ascii=False, indent=2))
    return OUT / "index.html"


if __name__ == "__main__":
    build()

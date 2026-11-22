"""Build an interactive gallery to pick pass-line anchors for technical metrics.

Uses baregrape_hw01 bare/AR/real lip crops (5 pairs). Computes ΔE00, SSIM, MAE, MSE
inside the lip crop (full crop as ROI). LPIPS is optional if `lpips` is installed.

  ml/.venv/Scripts/python.exe research/eval_matrix/make_tech_pass_gallery.py
  # open research/data/eval_matrix/tech_pass_gallery/index.html
  # check images → Download anchors JSON
"""
from __future__ import annotations

import json
import math
import shutil
from pathlib import Path

import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "research" / "data"
SRC = DATA / "baregrape_hw01" / "compare" / "images"
OUT = DATA / "eval_matrix" / "tech_pass_gallery"
IMG = OUT / "images"

# --- color / similarity helpers (no colour-science / skimage required) --------

def _rgb01(path: Path) -> np.ndarray:
    im = Image.open(path).convert("RGB")
    return np.asarray(im, dtype=np.float64) / 255.0


def _srgb_to_lab(rgb: np.ndarray) -> np.ndarray:
    """rgb float HxWx3 in 0..1 → Lab (D65)."""
    a = np.where(rgb <= 0.04045, rgb / 12.92, ((rgb + 0.055) / 1.055) ** 2.4)
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


def delta_e00_fixed(lab1, lab2) -> float:
    """CIEDE2000 between two Lab triples (Sharma 2005)."""
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


def ssim_gray(a: np.ndarray, b: np.ndarray) -> float:
    """SSIM on grayscale 0..1 arrays, same shape."""
    if a.shape != b.shape:
        # resize b to a via PIL
        hb, wb = a.shape
        bi = Image.fromarray((np.clip(b, 0, 1) * 255).astype(np.uint8)).resize((wb, hb), Image.BILINEAR)
        b = np.asarray(bi, dtype=np.float64) / 255.0
    C1, C2 = (0.01 ** 2), (0.03 ** 2)
    mu_a, mu_b = a.mean(), b.mean()
    sig_a, sig_b = a.var(), b.var()
    sig_ab = ((a - mu_a) * (b - mu_b)).mean()
    return float(((2 * mu_a * mu_b + C1) * (2 * sig_ab + C2)) /
                 ((mu_a ** 2 + mu_b ** 2 + C1) * (sig_a + sig_b + C2)))


def metrics_pair(ar_path: Path, real_path: Path, bare_path: Path) -> dict:
    ar, real, bare = _rgb01(ar_path), _rgb01(real_path), _rgb01(bare_path)
    # match sizes to AR
    h, w = ar.shape[:2]

    def fit(x):
        if x.shape[:2] == (h, w):
            return x
        im = Image.fromarray((np.clip(x, 0, 1) * 255).astype(np.uint8))
        im = im.resize((w, h), Image.BILINEAR)
        return np.asarray(im, dtype=np.float64) / 255.0

    real, bare = fit(real), fit(bare)
    lab_ar = _srgb_to_lab(ar).reshape(-1, 3).mean(0)
    lab_real = _srgb_to_lab(real).reshape(-1, 3).mean(0)
    lab_bare = _srgb_to_lab(bare).reshape(-1, 3).mean(0)
    g_ar = ar.mean(-1)
    g_real = real.mean(-1)
    g_bare = bare.mean(-1)
    mae_ar = float(np.mean(np.abs(ar - real)))
    mae_bare = float(np.mean(np.abs(bare - real)))
    mse_ar = float(np.mean((ar - real) ** 2))
    out = {
        "delta_e_ar": round(delta_e00_fixed(lab_ar, lab_real), 4),
        "delta_e_bare": round(delta_e00_fixed(lab_bare, lab_real), 4),
        "ssim_ar": round(ssim_gray(g_ar, g_real), 4),
        "ssim_bare": round(ssim_gray(g_bare, g_real), 4),
        "mae_ar": round(mae_ar, 5),
        "mae_bare": round(mae_bare, 5),
        "mse_ar": round(mse_ar, 6),
        "lpips_ar": None,
        "lpips_bare": None,
        "miou": None,
    }
    # optional LPIPS
    try:
        import torch
        import lpips  # type: ignore
        loss = lpips.LPIPS(net="alex")
        def t(x):
            tns = torch.from_numpy(x).permute(2, 0, 1).unsqueeze(0).float() * 2 - 1
            return tns
        with torch.no_grad():
            out["lpips_ar"] = round(float(loss(t(ar), t(real)).item()), 4)
            out["lpips_bare"] = round(float(loss(t(bare), t(real)).item()), 4)
    except Exception:
        pass
    return out


def collect_pairs() -> list[dict]:
    if not SRC.is_dir():
        raise FileNotFoundError(SRC)
    ids = sorted({p.name.split("_")[0] for p in SRC.glob("*_ar_lips.png")})
    rows = []
    for sid in ids:
        ar, real, bare = SRC / f"{sid}_ar_lips.png", SRC / f"{sid}_real_lips.png", SRC / f"{sid}_bare_lips.png"
        if not (ar.is_file() and real.is_file() and bare.is_file()):
            continue
        m = metrics_pair(ar, real, bare)
        rows.append({
            "id": sid,
            "ar": ar, "real": real, "bare": bare,
            **m,
            "beats_bare_de": m["delta_e_ar"] < m["delta_e_bare"],
            "beats_bare_ssim": m["ssim_ar"] > m["ssim_bare"],
            "beats_bare_mae": m["mae_ar"] < m["mae_bare"],
        })
    return rows


def build():
    rows = collect_pairs()
    if OUT.exists():
        shutil.rmtree(OUT)
    IMG.mkdir(parents=True)

    cards = []
    for r in rows:
        for kind in ("bare", "ar", "real"):
            dest = IMG / f"{r['id']}_{kind}_lips.png"
            shutil.copy2(r[kind], dest)
        cards.append({
            "id": r["id"],
            "delta_e": r["delta_e_ar"],
            "delta_e_bare": r["delta_e_bare"],
            "ssim": r["ssim_ar"],
            "ssim_bare": r["ssim_bare"],
            "mae": r["mae_ar"],
            "mae_bare": r["mae_bare"],
            "mse": r["mse_ar"],
            "lpips": r["lpips_ar"],
            "lpips_bare": r["lpips_bare"],
            "miou": r["miou"],
            "beats_bare_de": r["beats_bare_de"],
            "beats_bare_ssim": r["beats_bare_ssim"],
            "beats_bare_mae": r["beats_bare_mae"],
            "img_bare": f"images/{r['id']}_bare_lips.png",
            "img_ar": f"images/{r['id']}_ar_lips.png",
            "img_real": f"images/{r['id']}_real_lips.png",
        })

    summary = {
        "source": str(SRC),
        "n_pairs": len(cards),
        "note": (
            "갤러리에서 ‘이 정도면 합격’인 쌍을 고르면, 고른 쌍의 ΔE/SSIM/MAE "
            "(및 LPIPS가 있으면)로 합격선 후보(평균·중앙값·최댓값/최솟값)를 뽑는다. "
            "mIoU는 이 묶음에 정답 마스크가 없어 비움 — LaPa 측정 후 별도."
        ),
        "items": cards,
    }
    (OUT / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf8")

    data_js = json.dumps(cards, ensure_ascii=False)
    html = f"""<!DOCTYPE html>
<html lang="ko"><head><meta charset="utf-8"/>
<title>테크니컬 합격선 앵커 갤러리</title>
<style>
body{{font-family:system-ui,sans-serif;margin:20px;background:#111;color:#eee}}
h1{{font-size:1.2rem;margin:0 0 8px}}
.meta{{opacity:.85;max-width:60rem;line-height:1.45;font-size:14px}}
.toolbar{{display:flex;flex-wrap:wrap;gap:10px;align-items:center;margin:16px 0;padding:12px;background:#1a1a1a;border-radius:8px;position:sticky;top:0;z-index:5}}
button{{background:#2a9d8f;color:#fff;border:0;padding:8px 14px;border-radius:6px;cursor:pointer;font-weight:600}}
button.secondary{{background:#444}}
.stats{{font-size:13px;line-height:1.5;white-space:pre-wrap;background:#1c1c1c;padding:10px 12px;border-radius:8px;min-width:280px;flex:1}}
.grid{{display:grid;grid-template-columns:repeat(auto-fill,minmax(320px,1fr));gap:14px}}
.card{{background:#1c1c1c;border:2px solid #333;border-radius:10px;overflow:hidden}}
.card.sel{{border-color:#2a9d8f;box-shadow:0 0 0 1px #2a9d8f}}
.tri{{display:grid;grid-template-columns:1fr 1fr 1fr;gap:2px}}
.tri figure{{margin:0}}
.tri img{{width:100%;aspect-ratio:1;object-fit:cover;display:block}}
.tri figcaption{{font-size:10px;text-align:center;padding:2px;opacity:.75}}
.body{{padding:10px 12px;font-size:12px;line-height:1.4}}
.body b{{font-size:14px}}
label.pick{{display:flex;align-items:center;gap:8px;margin-top:8px;cursor:pointer;user-select:none}}
input[type=checkbox]{{width:18px;height:18px}}
.ok{{color:#2a9d8f}} .bad{{color:#e76f51}}
</style></head><body>
<h1>테크니컬 합격선 — 이미지 골라 선 만들기</h1>
<p class="meta">baregrape_hw01 립 crop <b>{len(cards)}</b>쌍 (맨입술 | AR | 실립).
체크한 쌍의 ΔE↓ / SSIM↑ / MAE↓ 로 합격선 후보를 계산합니다.
LPIPS는 패키지 있으면 표시, mIoU는 이 데이터에 마스크 없어 비움.
문서 원칙: 이 선은 <b>팀 눈 앵커</b>이며, 공개 역치·SOTA는 참고로 병기하세요.</p>
<div class="toolbar">
  <button type="button" id="selAll">전체 선택</button>
  <button type="button" id="selNone" class="secondary">선택 해제</button>
  <button type="button" id="dl">앵커 JSON 저장</button>
  <div class="stats" id="stats">쌍을 선택하세요.</div>
</div>
<div class="grid" id="grid"></div>
<script>
const ITEMS = {data_js};
const grid = document.getElementById('grid');
const stats = document.getElementById('stats');
const selected = new Set();

function fmt(x, d=3) {{ return (x==null || Number.isNaN(x)) ? '—' : Number(x).toFixed(d); }}

function card(it) {{
  const beatDe = it.beats_bare_de ? 'ok' : 'bad';
  const beatS = it.beats_bare_ssim ? 'ok' : 'bad';
  const beatM = it.beats_bare_mae ? 'ok' : 'bad';
  const el = document.createElement('div');
  el.className = 'card';
  el.dataset.id = it.id;
  el.innerHTML = `
    <div class="tri">
      <figure><img src="${{it.img_bare}}" alt="bare"/><figcaption>맨입술</figcaption></figure>
      <figure><img src="${{it.img_ar}}" alt="ar"/><figcaption>AR</figcaption></figure>
      <figure><img src="${{it.img_real}}" alt="real"/><figcaption>실립</figcaption></figure>
    </div>
    <div class="body">
      <b>${{it.id}}</b><br/>
      ΔE AR <b>${{fmt(it.delta_e,2)}}</b> (맨 ${{fmt(it.delta_e_bare,2)}}) <span class="${{beatDe}}">${{it.beats_bare_de?'AR승':'맨승'}}</span><br/>
      SSIM AR <b>${{fmt(it.ssim,3)}}</b> (맨 ${{fmt(it.ssim_bare,3)}}) <span class="${{beatS}}">${{it.beats_bare_ssim?'AR승':'맨승'}}</span><br/>
      MAE AR <b>${{fmt(it.mae,4)}}</b> (맨 ${{fmt(it.mae_bare,4)}}) <span class="${{beatM}}">${{it.beats_bare_mae?'AR승':'맨승'}}</span><br/>
      MSE ${{fmt(it.mse,5)}} · LPIPS ${{fmt(it.lpips,3)}} · mIoU —
      <label class="pick"><input type="checkbox" data-id="${{it.id}}"/> 이 쌍을 합격 앵커로</label>
    </div>`;
  el.querySelector('input').addEventListener('change', (e) => {{
    if (e.target.checked) selected.add(it.id); else selected.delete(it.id);
    el.classList.toggle('sel', e.target.checked);
    renderStats();
  }});
  return el;
}}

function selectedItems() {{ return ITEMS.filter(x => selected.has(x.id)); }}

function agg(vals, mode) {{
  const a = vals.filter(v => v!=null && !Number.isNaN(v));
  if (!a.length) return null;
  a.sort((x,y)=>x-y);
  if (mode==='mean') return a.reduce((s,v)=>s+v,0)/a.length;
  if (mode==='median') return a[Math.floor(a.length/2)];
  if (mode==='min') return a[0];
  if (mode==='max') return a[a.length-1];
  return null;
}}

function renderStats() {{
  const xs = selectedItems();
  if (!xs.length) {{ stats.textContent = '쌍을 선택하세요.'; return; }}
  const de = xs.map(x=>x.delta_e), ss = xs.map(x=>x.ssim), mae = xs.map(x=>x.mae);
  const lines = [
    `선택 ${{xs.length}} / ${{ITEMS.length}} · ids: ${{xs.map(x=>x.id).join(', ')}}`,
    `ΔE↓  평균 ${{fmt(agg(de,'mean'),2)}} · 중앙 ${{fmt(agg(de,'median'),2)}} · 최악(max) ${{fmt(agg(de,'max'),2)}}  ← 합격선 후보(보통 중앙 또는 최악)`,
    `SSIM↑ 평균 ${{fmt(agg(ss,'mean'),3)}} · 중앙 ${{fmt(agg(ss,'median'),3)}} · 최악(min) ${{fmt(agg(ss,'min'),3)}}`,
    `MAE↓  평균 ${{fmt(agg(mae,'mean'),4)}} · 중앙 ${{fmt(agg(mae,'median'),4)}} · 최악(max) ${{fmt(agg(mae,'max'),4)}}`,
    `제안: delta_e_pass ≤ 중앙값, ssim_pass ≥ 중앙값, mae_pass ≤ 중앙값 (확정은 JSON에서 고르세요)`,
  ];
  stats.textContent = lines.join('\\n');
}}

function download() {{
  const xs = selectedItems();
  if (!xs.length) {{ alert('앵커를 하나 이상 고르세요'); return; }}
  const de = xs.map(x=>x.delta_e), ss = xs.map(x=>x.ssim), mae = xs.map(x=>x.mae);
  const payload = {{
    decided_at: new Date().toISOString().slice(0,10),
    source: 'baregrape_hw01 compare lip crops',
    n_anchors: xs.length,
    anchors: xs,
    proposed_pass_lines: {{
      delta_e_cie2000: {{ mean: agg(de,'mean'), median: agg(de,'median'), max_worst: agg(de,'max'), recommend: 'median or max_worst', direction: 'lower_better' }},
      ssim: {{ mean: agg(ss,'mean'), median: agg(ss,'median'), min_worst: agg(ss,'min'), recommend: 'median or min_worst', direction: 'higher_better' }},
      mae: {{ mean: agg(mae,'mean'), median: agg(mae,'median'), max_worst: agg(mae,'max'), recommend: 'median or max_worst', direction: 'lower_better' }},
      mse: 'track with mae',
      lpips: 'install lpips then re-run gallery builder',
      miou_lip: 'measure on LaPa separately (SegFace ref IoU 0.797)',
    }},
    note: '팀 눈 앵커 합격선. 공개 역치(ΔE 1.8, mIoU 0.797)와 병기할 것.',
  }};
  const blob = new Blob([JSON.stringify(payload, null, 2)], {{type:'application/json'}});
  const a = document.createElement('a');
  a.href = URL.createObjectURL(blob);
  a.download = 'tech_pass_anchors.json';
  a.click();
}}

ITEMS.forEach(it => grid.appendChild(card(it)));
document.getElementById('selAll').onclick = () => {{
  document.querySelectorAll('input[type=checkbox]').forEach(cb => {{ cb.checked = true; selected.add(cb.dataset.id); cb.closest('.card').classList.add('sel'); }});
  renderStats();
}};
document.getElementById('selNone').onclick = () => {{
  selected.clear();
  document.querySelectorAll('input[type=checkbox]').forEach(cb => {{ cb.checked = false; cb.closest('.card').classList.remove('sel'); }});
  renderStats();
}};
document.getElementById('dl').onclick = download;
</script>
</body></html>
"""
    (OUT / "index.html").write_text(html, encoding="utf8")
    print(json.dumps({"out": str(OUT / "index.html"), "n": len(cards), "ids": [c["id"] for c in cards]}, ensure_ascii=False, indent=2))
    return OUT / "index.html"


if __name__ == "__main__":
    build()

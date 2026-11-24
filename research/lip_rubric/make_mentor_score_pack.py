"""Build mentor-aligned 3-axis × 1–5 scoring pack (bare | makeup triad).

Uses rating_pack images + render_work bare faces (same lapa_stem).
Pack embedded in index.html for file:// open.

  ml/.venv/Scripts/python.exe research/lip_rubric/make_mentor_score_pack.py
"""
from __future__ import annotations

import csv
import json
import random
import shutil
from pathlib import Path
from typing import Optional

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "research" / "data" / "lip_rubric"
SRC_KEY = DATA / "pack" / "key.csv"
SRC_IMG = DATA / "pack" / "rating_pack" / "images"
BARE_SRC = DATA / "render_work" / "src"
BARE_FACE = DATA / "render_work" / "faces"
CRIT = ROOT / "research" / "lip_rubric" / "criteria_mentor_likert_v1.json"
PROMPT = ROOT / "research" / "lip_rubric" / "mentor_astra_prompt.md"
OUT = DATA / "mentor_pack"
IMG = OUT / "images"
SEED = 20261120
N_TOTAL = 10
N_STICKER = 2
N_REAL = 2
N_RENDER = N_TOTAL - N_STICKER - N_REAL

LIPS_OUTER = [61, 185, 40, 39, 37, 0, 267, 269, 270, 409, 291, 375, 321, 405, 314, 17, 84, 181, 91, 146]


def load_criteria() -> dict:
    return json.loads(CRIT.read_text(encoding="utf8"))


def _plain_ring(page: dict, indices: list[int]) -> np.ndarray:
    return np.array([[float(page["x"][i]), float(page["y"][i])] for i in indices], np.float32)


def _mirrored_ring(page: dict, indices: list[int], width: int) -> np.ndarray:
    return np.array([[width - 1 - float(page["x"][i]), float(page["y"][i])] for i in indices], np.float32)


def _crop_lips(frame: np.ndarray, ring: np.ndarray) -> np.ndarray:
    lo, hi = ring.min(0), ring.max(0)
    side = float(hi[0] - lo[0]) * 1.6
    if side < 2:
        raise ValueError("lip crop too small")
    center = (lo + hi) / 2
    x, y = center - side / 2
    scale = 512 / side
    matrix = np.array([[scale, 0, -x * scale], [0, scale, -y * scale]], np.float64)
    return cv2.warpAffine(
        frame, matrix, (512, 512), flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_REPLICATE
    )


def make_bare_crop(stem: str) -> Optional[np.ndarray]:
    page_path = BARE_FACE / f"{stem}.page.json"
    if not page_path.is_file():
        return None
    page = json.loads(page_path.read_text(encoding="utf8"))
    face_png = BARE_FACE / f"{stem}.png"
    # page.json x/y are in faces/*.png pixel space (not mirrored, not LaPa src size).
    if face_png.is_file():
        frame = cv2.imread(str(face_png))
        if frame is None:
            return None
        ring = _plain_ring(page, LIPS_OUTER)
        return _crop_lips(frame, ring)
    return None


def bare_full_path(stem: str) -> Optional[Path]:
    for p in (BARE_FACE / f"{stem}.png", BARE_SRC / f"{stem}.jpg"):
        if p.is_file():
            return p
    return None


def select_rows() -> list[dict]:
    rows = list(csv.DictReader(SRC_KEY.open(encoding="utf-8-sig")))
    by_kind: dict[str, list[dict]] = {"sticker": [], "render": [], "real": []}
    for r in rows:
        if (r.get("repeat_of") or "").strip():
            continue
        kind = r.get("kind") or ""
        if kind not in by_kind:
            continue
        rid = r["random_id"]
        crop = SRC_IMG / f"{rid}_crop.png"
        if not crop.is_file():
            continue
        stem = r.get("lapa_stem") or ""
        has_bare = bare_full_path(stem) is not None
        by_kind[kind].append({
            "id": rid,
            "kind": kind,
            "finish": r.get("finish") or "unknown",
            "shade": r.get("shade") or "",
            "hex": r.get("hex") or "",
            "face_id": r.get("face_id") or "",
            "lapa_stem": stem,
            "has_full": (SRC_IMG / f"{rid}_full.png").is_file(),
            "has_bare": has_bare,
            "stratum": {
                "sticker": "low_anchor",
                "render": "mid",
                "real": "high_anchor",
            }[kind],
        })

    rng = random.Random(SEED)
    for k in by_kind:
        # prefer rows with bare for consistency axis
        by_kind[k].sort(key=lambda x: (0 if x["has_bare"] else 1, x["id"]))
        pool = by_kind[k][:]
        rng.shuffle(pool)
        # keep bare-preferring: put has_bare first after shuffle within groups
        pool.sort(key=lambda x: (0 if x["has_bare"] else 1))
        by_kind[k] = pool

    picked = (
        by_kind["sticker"][:N_STICKER]
        + by_kind["real"][:N_REAL]
        + by_kind["render"][:N_RENDER]
    )
    if len(picked) < N_TOTAL:
        raise RuntimeError(
            f"need {N_TOTAL}, got {len(picked)} "
            f"(sticker/real/render={[len(by_kind[k]) for k in ('sticker','real','render')]})"
        )
    rng.shuffle(picked)
    return picked[:N_TOTAL]


def build():
    if not SRC_KEY.is_file() or not SRC_IMG.is_dir():
        raise FileNotFoundError("need pack/key.csv and rating_pack/images")
    crit = load_criteria()
    items = crit["items"]
    rows = select_rows()

    if OUT.exists():
        shutil.rmtree(OUT)
    IMG.mkdir(parents=True)

    manifest = []
    for i, r in enumerate(rows):
        rid = r["id"]
        stem = r["lapa_stem"]
        after_crop = f"{i:02d}_{rid[:8]}_after_crop.png"
        shutil.copy2(SRC_IMG / f"{rid}_crop.png", IMG / after_crop)
        after_full = None
        if r["has_full"]:
            after_full = f"{i:02d}_{rid[:8]}_after_full.png"
            shutil.copy2(SRC_IMG / f"{rid}_full.png", IMG / after_full)

        bare_crop_name = None
        bare_full_name = None
        bf = bare_full_path(stem)
        if bf is not None:
            bare_full_name = f"{i:02d}_{rid[:8]}_bare_full{bf.suffix.lower()}"
            shutil.copy2(bf, IMG / bare_full_name)
            crop = make_bare_crop(stem)
            if crop is not None:
                bare_crop_name = f"{i:02d}_{rid[:8]}_bare_crop.png"
                cv2.imwrite(str(IMG / bare_crop_name), crop)

        manifest.append({
            **r,
            "order": i,
            "img_after_crop": f"images/{after_crop}",
            "img_after_full": f"images/{after_full}" if after_full else None,
            "img_bare_crop": f"images/{bare_crop_name}" if bare_crop_name else None,
            "img_bare_full": f"images/{bare_full_name}" if bare_full_name else None,
            "has_bare_pair": bool(bare_crop_name or bare_full_name),
        })

    key_fields = [
        "order", "id", "kind", "stratum", "finish", "shade", "hex", "face_id",
        "lapa_stem", "has_bare_pair",
        "img_bare_crop", "img_bare_full", "img_after_crop", "img_after_full",
    ]
    with (OUT / "key.csv").open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=key_fields)
        w.writeheader()
        for m in manifest:
            w.writerow({k: m.get(k) for k in key_fields})

    public = [{
        "order": m["order"],
        "id": m["id"],
        "finish": m["finish"],
        "has_bare": m["has_bare_pair"],
        "img_bare_crop": m["img_bare_crop"],
        "img_bare_full": m["img_bare_full"],
        "img_after_crop": m["img_after_crop"],
        "img_after_full": m["img_after_full"],
    } for m in manifest]

    pack = {
        "criteria": {
            "version": crit["version"],
            "title": crit["title"],
            "soft_gate": crit["scoring"]["soft_gate"],
            "items": [
                {
                    "id": it["id"],
                    "name_ko": it["name_ko"],
                    "question": it["question"],
                    "likert": it["likert"],
                }
                for it in items
            ],
        },
        "images": public,
    }

    summary = {
        "criteria_version": crit["version"],
        "seed": SEED,
        "n": len(manifest),
        "with_bare_pair": sum(1 for m in manifest if m["has_bare_pair"]),
        "by_kind": {
            k: sum(1 for m in manifest if m["kind"] == k)
            for k in ("sticker", "render", "real")
        },
        "note": (
            "kind는 key.csv에만. UI는 화장 전/후 + 제형만. "
            "index.html에 pack 내장(file://)."
        ),
    }
    (OUT / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf8")
    (OUT / "pack.json").write_text(json.dumps(pack, ensure_ascii=False, indent=2), encoding="utf8")
    shutil.copy2(CRIT, OUT / "criteria_mentor_likert_v1.json")
    if PROMPT.is_file():
        shutil.copy2(PROMPT, OUT / "mentor_astra_prompt.md")

    (OUT / "index.html").write_text(_html(pack), encoding="utf8")
    print(json.dumps({
        "out": str(OUT / "index.html"),
        "n": len(manifest),
        "with_bare_pair": summary["with_bare_pair"],
        "by_kind": summary["by_kind"],
    }, ensure_ascii=False, indent=2))
    return OUT / "index.html"


def _html(pack: dict) -> str:
    data_js = json.dumps(pack, ensure_ascii=False)
    return f"""<!DOCTYPE html>
<html lang="ko"><head><meta charset="utf-8"/>
<title>멘토 본선 채점 (A1–A3 · 1–5)</title>
<style>
:root{{--bg:#121212;--card:#1e1e1e;--ok:#2a9d8f;--muted:#9a9a9a;--line:#333}}
*{{box-sizing:border-box}}
body{{margin:0;font-family:system-ui,Malgun Gothic,sans-serif;background:var(--bg);color:#eee;padding:16px}}
h1{{font-size:1.15rem;margin:0 0 6px}}
.meta{{color:var(--muted);font-size:.85rem;line-height:1.45;margin:0 0 12px}}
.bar{{display:flex;gap:8px;flex-wrap:wrap;align-items:center;margin:12px 0;position:sticky;top:0;background:var(--bg);padding:8px 0;z-index:2}}
.prog{{font-weight:600}}
button{{background:var(--ok);color:#fff;border:0;padding:8px 12px;border-radius:6px;cursor:pointer;font-weight:600}}
button.secondary{{background:#444}}
.card{{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:14px;margin-bottom:14px}}
.panels{{display:grid;grid-template-columns:1fr 1fr;gap:10px}}
@media(max-width:800px){{.panels{{grid-template-columns:1fr}}}}
.panel h3{{margin:0 0 6px;font-size:.9rem;color:var(--ok)}}
.panel .imgs{{display:grid;grid-template-columns:1fr 1fr;gap:6px}}
.panel img{{width:100%;border-radius:6px;background:#000;max-height:280px;object-fit:contain}}
.axis{{border-top:1px solid var(--line);padding-top:12px;margin-top:12px}}
.axis .id{{font-weight:700;color:var(--ok)}}
.axis .q{{margin:4px 0 8px}}
.likert{{display:grid;gap:4px}}
.likert label{{display:grid;grid-template-columns:28px 1fr;gap:8px;align-items:start;padding:6px 8px;background:#2a2a2a;border-radius:6px;cursor:pointer;font-size:.82rem;line-height:1.35}}
.likert input{{width:16px;height:16px;margin-top:2px}}
.scores{{display:flex;gap:10px;flex-wrap:wrap;font-size:.9rem;color:var(--muted)}}
.foot{{font-size:12px;color:var(--muted);margin-top:16px}}
</style></head><body>
<header>
  <h1>멘토 본선 채점 · A1 영역 · A2 자연스러움 · A3 일관성 (1–5) · 10장</h1>
  <p class="meta">화장 전(맨입술)과 화장 후를 나란히 보고 점수를 주세요.
  kind(스티커/렌더/실물)는 숨김. 소프트 게이트: 어느 축이든 1–2면 실패 권고(평균은 기록).
  Ext-B(E문항)가 아니라 <b>이 표가 멘토 보고 본선</b>입니다.</p>
</header>
<div class="bar">
  <span class="prog" id="prog"></span>
  <button type="button" id="prev" class="secondary">이전</button>
  <button type="button" id="next">다음</button>
  <button type="button" id="dl">CSV 저장</button>
  <span class="scores" id="live"></span>
</div>
<main id="main"></main>
<p class="foot">답은 localStorage에 임시 저장. 끝나면 CSV를 담당자에게 보내세요. key.csv는 채점자가 열지 마세요.</p>
<script>
const STORE='mentor_likert_v1_10';
const PACK = {data_js};
let idx=0;
const answers=JSON.parse(localStorage.getItem(STORE)||'{{}}');

function ensure(id){{
  if(!answers[id]) answers[id]={{}};
}}
function save(){{ localStorage.setItem(STORE, JSON.stringify(answers)); }}

function overallOf(a){{
  const xs=['A1','A2','A3'].map(k=>a[k]).filter(v=>v!=null);
  if(xs.length<3) return null;
  const m=xs.reduce((s,v)=>s+Number(v),0)/3;
  const soft=xs.some(v=>Number(v)<=2);
  return {{mean:Math.round(m*100)/100, soft}};
}}

function render(){{
  const imgs=PACK.images;
  const items=PACK.criteria.items;
  const im=imgs[idx];
  ensure(im.id);
  const a=answers[im.id];
  document.getElementById('prog').textContent=(idx+1)+' / '+imgs.length+' · finish='+im.finish+(im.has_bare?' · bare 있음':' · bare 없음');
  const ov=overallOf(a);
  document.getElementById('live').textContent=ov?('overall '+ov.mean+(ov.soft?' · soft-fail':'')):'';

  let bareHtml='<p class="meta">화장 전 이미지 없음 → A3는 프레임 내 입술–피부 정합으로.</p>';
  if(im.img_bare_crop || im.img_bare_full){{
    bareHtml='<div class="imgs">'
      +(im.img_bare_crop?('<img src="'+im.img_bare_crop+'" alt="bare crop"/>'):'')
      +(im.img_bare_full?('<img src="'+im.img_bare_full+'" alt="bare full"/>'):'')
      +'</div>';
  }}
  let afterHtml='<div class="imgs">'
    +'<img src="'+im.img_after_crop+'" alt="after crop"/>'
    +(im.img_after_full?('<img src="'+im.img_after_full+'" alt="after full"/>'):'')
    +'</div>';

  let axes='';
  for(const it of items){{
    let labs='';
    for(const s of ['1','2','3','4','5']){{
      const checked=String(a[it.id])===s?' checked':'';
      labs+='<label><input type="radio" name="'+it.id+'" value="'+s+'"'+checked+'/>'
        +'<span><b>'+s+'</b> — '+it.likert[s]+'</span></label>';
    }}
    axes+='<div class="axis"><div><span class="id">'+it.id+' '+it.name_ko
      +'</span></div><div class="q">'+it.question+'</div><div class="likert" data-axis="'+it.id+'">'
      +labs+'</div></div>';
  }}

  document.getElementById('main').innerHTML=
    '<div class="card"><div class="panels">'
    +'<div class="panel"><h3>화장 전 (맨입술)</h3>'+bareHtml+'</div>'
    +'<div class="panel"><h3>화장 후 (평가 대상)</h3>'+afterHtml+'</div>'
    +'</div>'+axes+'</div>';

  document.querySelectorAll('.likert input').forEach(inp=>{{
    inp.addEventListener('change',()=>{{
      answers[im.id][inp.name]=Number(inp.value);
      save();
      const o=overallOf(answers[im.id]);
      document.getElementById('live').textContent=o?('overall '+o.mean+(o.soft?' · soft-fail':'')):'';
    }});
  }});
}}

document.getElementById('prev').onclick=()=>{{ if(idx>0){{idx--;render();}} }};
document.getElementById('next').onclick=()=>{{ if(idx<PACK.images.length-1){{idx++;render();}} }};
document.getElementById('dl').onclick=()=>{{
  const items=PACK.criteria.items.map(x=>x.id);
  const header=['id','finish','has_bare',...items,'overall','soft_gate_fail'];
  const lines=[header.join(',')];
  for(const im of PACK.images){{
    ensure(im.id);
    const a=answers[im.id];
    const o=overallOf(a);
    const row=[im.id, im.finish, im.has_bare?1:0, ...items.map(k=>a[k]??''), o?o.mean:'', o?(o.soft?1:0):''];
    lines.push(row.join(','));
  }}
  const blob=new Blob([lines.join('\\n')],{{type:'text/csv;charset=utf-8'}});
  const url=URL.createObjectURL(blob);
  const a=document.createElement('a');
  a.href=url; a.download='mentor_likert_scores.csv'; a.click();
  URL.revokeObjectURL(url);
}};
render();
</script></body></html>
"""


if __name__ == "__main__":
    build()

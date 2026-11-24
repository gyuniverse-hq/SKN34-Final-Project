"""Build Ext-B (E1–E7) human scoring pack from existing lip_rubric rating images.

No bare/AR/real pairs required. Uses sticker (low) / render (mid) / real (high)
as stratum labels in the key only — kind is hidden during scoring.

Pack data is embedded in index.html so file:// open works (no fetch).

  ml/.venv/Scripts/python.exe research/lip_rubric/make_extb_score_pack.py
  # open research/data/lip_rubric/extb_pack/index.html
"""
from __future__ import annotations

import csv
import json
import random
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "research" / "data" / "lip_rubric"
SRC_KEY = DATA / "pack" / "key.csv"
SRC_IMG = DATA / "pack" / "rating_pack" / "images"
CRIT = ROOT / "research" / "lip_rubric" / "criteria_vlm_ext_b_v1.json"
OUT = DATA / "extb_pack"
IMG = OUT / "images"
SEED = 20261120
N_TOTAL = 10
# stratified: low / mid / high anchors
N_STICKER = 2
N_REAL = 2
N_RENDER = N_TOTAL - N_STICKER - N_REAL  # 6


def load_criteria() -> dict:
    return json.loads(CRIT.read_text(encoding="utf8"))


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
        full = SRC_IMG / f"{rid}_full.png"
        if not crop.is_file():
            continue
        by_kind[kind].append({
            "id": rid,
            "kind": kind,
            "finish": r.get("finish") or "unknown",
            "shade": r.get("shade") or "",
            "hex": r.get("hex") or "",
            "face_id": r.get("face_id") or "",
            "has_full": full.is_file(),
            "stratum": {
                "sticker": "low_anchor",
                "render": "mid",
                "real": "high_anchor",
            }[kind],
        })

    rng = random.Random(SEED)
    for k in by_kind:
        rng.shuffle(by_kind[k])

    picked = (
        by_kind["sticker"][:N_STICKER]
        + by_kind["real"][:N_REAL]
        + by_kind["render"][:N_RENDER]
    )
    if len(picked) < N_TOTAL:
        raise RuntimeError(f"need {N_TOTAL} images, got {len(picked)}: {[len(by_kind[k]) for k in by_kind]}")
    # prefer diverse finishes among renders if possible
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

    manifest_items = []
    for i, r in enumerate(rows):
        rid = r["id"]
        crop_name = f"{i:02d}_{rid[:8]}_crop.png"
        shutil.copy2(SRC_IMG / f"{rid}_crop.png", IMG / crop_name)
        full_name = None
        if r["has_full"]:
            full_name = f"{i:02d}_{rid[:8]}_full.png"
            shutil.copy2(SRC_IMG / f"{rid}_full.png", IMG / full_name)
        manifest_items.append({
            **r,
            "order": i,
            "img_crop": f"images/{crop_name}",
            "img_full": f"images/{full_name}" if full_name else None,
        })

    key_path = OUT / "key.csv"
    with key_path.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(
            f,
            fieldnames=["order", "id", "kind", "stratum", "finish", "shade", "hex", "face_id", "img_crop", "img_full"],
        )
        w.writeheader()
        for m in manifest_items:
            w.writerow({k: m.get(k) for k in w.fieldnames})

    public_items = [{
        "order": m["order"],
        "id": m["id"],
        "finish": m["finish"],
        "img_crop": m["img_crop"],
        "img_full": m["img_full"],
    } for m in manifest_items]

    pack = {
        "criteria": {
            "version": crit["version"],
            "gate": crit["scoring"]["gate"],
            "items": [
                {
                    "id": it["id"],
                    "text": it["text"],
                    "pass_answer": it["pass_answer"],
                    "na_allowed": it["na_allowed"],
                    "role": it["role"],
                    "weight": it["weight"],
                }
                for it in items
            ],
        },
        "images": public_items,
    }

    summary = {
        "criteria_version": crit["version"],
        "seed": SEED,
        "n": len(manifest_items),
        "by_kind": {
            k: sum(1 for m in manifest_items if m["kind"] == k)
            for k in ("sticker", "render", "real")
        },
        "note": (
            "kind/stratum은 key.csv에만 있음. 채점 UI에는 제형(finish)만 표시. "
            "index.html에 pack 데이터 내장(file:// 가능)."
        ),
        "scoring": crit["scoring"],
        "weights": {it["id"]: it["weight"] for it in items},
    }
    (OUT / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf8")
    (OUT / "pack.json").write_text(json.dumps(pack, ensure_ascii=False, indent=2), encoding="utf8")
    shutil.copy2(CRIT, OUT / "criteria_vlm_ext_b_v1.json")

    (OUT / "index.html").write_text(_html(pack), encoding="utf8")
    print(json.dumps({
        "out": str(OUT / "index.html"),
        "n": len(manifest_items),
        "by_kind": summary["by_kind"],
    }, ensure_ascii=False, indent=2))
    return OUT / "index.html"


def _html(pack: dict) -> str:
    data_js = json.dumps(pack, ensure_ascii=False)
    return f"""<!DOCTYPE html>
<html lang="ko"><head><meta charset="utf-8"/>
<title>Ext-B 자연스러움 채점 (E1–E6)</title>
<style>
:root{{--bg:#111;--card:#1c1c1c;--ok:#2a9d8f;--muted:#9aa}}
body{{font-family:system-ui,sans-serif;margin:0;background:var(--bg);color:#eee}}
header{{padding:16px 20px;max-width:960px}}
h1{{font-size:1.15rem;margin:0 0 6px}}
.meta{{font-size:13px;line-height:1.45;opacity:.9;max-width:40rem}}
.bar{{position:sticky;top:0;z-index:5;background:#161616;border-bottom:1px solid #333;
  padding:10px 20px;display:flex;flex-wrap:wrap;gap:10px;align-items:center}}
button{{background:var(--ok);color:#fff;border:0;padding:8px 12px;border-radius:6px;cursor:pointer;font-weight:600}}
button.secondary{{background:#444}} button:disabled{{opacity:.4;cursor:default}}
.prog{{font-size:13px;flex:1}}
main{{padding:16px 20px 40px;max-width:960px}}
.imgs{{display:grid;grid-template-columns:1fr 1fr;gap:10px;margin-bottom:14px}}
.imgs figure{{margin:0;background:#000;border-radius:8px;overflow:hidden}}
.imgs img{{width:100%;display:block;aspect-ratio:1;object-fit:cover}}
.imgs figcaption{{font-size:11px;padding:4px 8px;opacity:.7}}
.finish{{display:inline-block;background:#2a3;color:#fff;padding:2px 8px;border-radius:4px;font-size:12px;margin-bottom:10px}}
.q{{background:var(--card);border:1px solid #333;border-radius:8px;padding:10px 12px;margin:8px 0}}
.q.gate{{border-color:#e9c46a}}
.q .id{{font-weight:700;color:var(--ok);margin-right:6px}}
.q .role{{font-size:11px;opacity:.7}}
.ans{{display:flex;gap:8px;margin-top:8px;flex-wrap:wrap}}
.ans label{{display:flex;align-items:center;gap:4px;padding:6px 10px;background:#2a2a2a;border-radius:6px;cursor:pointer;user-select:none}}
.ans input{{width:16px;height:16px}}
.foot{{font-size:12px;color:var(--muted);margin-top:16px}}
@media(max-width:700px){{.imgs{{grid-template-columns:1fr}}}}
</style></head><body>
<header>
  <h1>Ext-B 자연스러움 채점 (E1–E6) · 10장 · v1.2.1</h1>
  <p class="meta">트랙 A만. 색=실물인지는 묻지 않음.
  게이트(E1·E6) 실패 시 전체 fail. 점수는 가중 S (E1=0.22·E6=0.22·나머지 분산).
  구 E1+E2는 E1(경계·배치)로 합침.
  <b>kind는 숨김</b> — 제형만 보고 답하세요.</p>
</header>
<div class="bar">
  <span class="prog" id="prog"></span>
  <button type="button" id="prev" class="secondary">이전</button>
  <button type="button" id="next">다음</button>
  <button type="button" id="dl">CSV 저장</button>
</div>
<main id="main"></main>
<p class="foot">답은 이 브라우저 localStorage에 임시 저장됩니다. 끝나면 CSV를 담당자에게 보내세요. key.csv는 채점자가 열지 마세요.</p>
<script>
const STORE='extb_scores_v1_2_1_10';
const PACK = {data_js};
let idx=0;
const answers=JSON.parse(localStorage.getItem(STORE)||'{{}}');

function ensure(id){{
  if(!answers[id]) answers[id]={{}};
  return answers[id];
}}
function save(){{ localStorage.setItem(STORE, JSON.stringify(answers)); }}

function render(){{
  const img=PACK.images[idx];
  const qs=PACK.criteria.items;
  const a=ensure(img.id);
  const done=PACK.images.filter(im=>qs.every(q=>{{
    const v=answers[im.id]&&answers[im.id][q.id];
    return v!=null && v!=='';
  }})).length;
  document.getElementById('prog').textContent=
    `${{idx+1}} / ${{PACK.images.length}} · 완료 ${{done}} · finish=${{img.finish}}`;

  const full=img.img_full
    ? `<figure><img src="${{img.img_full}}" alt="full"/><figcaption>얼굴 전체</figcaption></figure>`
    : '';
  let qhtml='';
  for(const q of qs){{
    const cur=a[q.id]||'';
    const na=q.na_allowed
      ? `<label><input type="radio" name="${{q.id}}" value="na" ${{cur==='na'?'checked':''}}/> 해당없음</label>` : '';
    qhtml+=`<div class="q ${{q.role==='gate'?'gate':''}}">
      <div><span class="id">${{q.id}}</span>
        <span class="role">${{q.role}} · w=${{q.weight}}</span></div>
      <div style="margin-top:4px;font-size:14px;line-height:1.4">${{q.text}}</div>
      <div class="ans">
        <label><input type="radio" name="${{q.id}}" value="yes" ${{cur==='yes'?'checked':''}}/> 예</label>
        <label><input type="radio" name="${{q.id}}" value="no" ${{cur==='no'?'checked':''}}/> 아니오</label>
        ${{na}}
      </div>
    </div>`;
  }}
  document.getElementById('main').innerHTML=`
    <span class="finish">제형: ${{img.finish}}</span>
    <div class="imgs">
      <figure><img src="${{img.img_crop}}" alt="crop"/><figcaption>입술 확대</figcaption></figure>
      ${{full}}
    </div>
    ${{qhtml}}`;
  document.querySelectorAll('.ans input').forEach(inp=>{{
    inp.onchange=()=>{{ a[inp.name]=inp.value; save(); render(); }};
  }});
  document.getElementById('prev').disabled=idx===0;
  document.getElementById('next').disabled=idx===PACK.images.length-1;
}}

function scoreRow(imgId){{
  const a=answers[imgId]||{{}};
  const qs=PACK.criteria.items;
  const gate=PACK.criteria.gate;
  let gate_pass=true;
  for(const g of gate){{
    const v=a[g];
    const q=qs.find(x=>x.id===g);
    if(v!==q.pass_answer) gate_pass=false;
  }}
  let num=0, den=0;
  const vec={{}};
  for(const q of qs){{
    const v=a[q.id];
    vec[q.id]=v||'';
    if(v==null||v===''||v==='na') continue;
    const pass=v===q.pass_answer?1:0;
    num+=q.weight*pass;
    den+=q.weight;
  }}
  const S=den>0?num/den:null;
  return {{gate_pass, S, ...vec}};
}}

function download(){{
  const qs=PACK.criteria.items;
  const cols=['rater','image_id','finish','gate_pass','S',...qs.map(q=>q.id)];
  const rater=prompt('평가자 코드 (예: H1)','H1')||'H1';
  const lines=[cols.join(',')];
  for(const im of PACK.images){{
    const s=scoreRow(im.id);
    if(qs.some(q=>!answers[im.id]||!answers[im.id][q.id])) continue;
    lines.push([
      rater, im.id, im.finish,
      s.gate_pass?'1':'0',
      s.S==null?'':s.S.toFixed(4),
      ...qs.map(q=>s[q.id]||'')
    ].join(','));
  }}
  const blob=new Blob([lines.join('\\n')],{{type:'text/csv;charset=utf-8'}});
  const a=document.createElement('a');
  a.href=URL.createObjectURL(blob);
  a.download=`extb_scores_${{rater}}.csv`;
  a.click();
}}

document.getElementById('prev').onclick=()=>{{ idx=Math.max(0,idx-1); render(); }};
document.getElementById('next').onclick=()=>{{ idx=Math.min(PACK.images.length-1,idx+1); render(); }};
document.getElementById('dl').onclick=download;
render();
</script>
</body></html>
"""


if __name__ == "__main__":
    build()

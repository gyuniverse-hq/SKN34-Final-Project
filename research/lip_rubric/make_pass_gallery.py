"""Build an HTML gallery of R5 images with human total >= 4 for pass-line picking.

  ml/.venv/Scripts/python.exe research/lip_rubric/make_pass_gallery.py
  # open research/data/lip_rubric/learn_astra/pass_gallery/index.html
"""
from __future__ import annotations

import csv
import json
import shutil
from pathlib import Path

from common import DATA
from learn_astra import OUT

LABELS = DATA / "learn" / "labels_absolute.csv"
MIN_SCORE = 4.0


def _rows():
    with LABELS.open(encoding="utf-8-sig") as f:
        rows = list(csv.DictReader(f))
    out = []
    for r in rows:
        total = float(r["total"])
        if total < MIN_SCORE:
            continue
        crop = Path(r["crop_path"])
        if not crop.is_file():
            continue
        out.append({
            "image_id": r["image_id"],
            "face_id": r["face_id"],
            "pack": r["pack"],
            "kind": r["kind"],
            "finish": r["finish"],
            "total": total,
            "crop_path": str(crop),
        })
    out.sort(key=lambda r: (-r["total"], r["kind"], r["image_id"]))
    return out


def main():
    rows = _rows()
    out = OUT / "pass_gallery"
    img_dir = out / "images"
    if out.exists():
        shutil.rmtree(out)
    img_dir.mkdir(parents=True)

    cards = []
    for i, r in enumerate(rows):
        name = f"{i:02d}_{r['total']:.1f}_{r['kind']}_{r['image_id'][:8]}.png"
        dest = img_dir / name
        shutil.copy2(r["crop_path"], dest)
        r = {**r, "gallery_file": f"images/{name}"}
        cards.append(r)

    n_45 = sum(1 for r in cards if r["total"] >= 4.5)
    n_40 = len(cards)
    by_kind = {}
    for r in cards:
        by_kind.setdefault(r["kind"], []).append(r["total"])

    summary = {
        "source": str(LABELS),
        "min_score": MIN_SCORE,
        "n_ge_4": n_40,
        "n_ge_4_5": n_45,
        "proposed_pass_line": 4.5,
        "proposed_note": (
            "R5 사람 총점 4.5 이상을 잠정 합격선으로 둔다. "
            "갤러리에서 4.5~5.0 사진을 보고 ‘이 정도면 합격’인 앵커를 고른 뒤 확정한다. "
            "자동 모델 점수는 스케일이 낮아 합격선에 직접 쓰지 않는다."
        ),
        "by_kind_ge_4": {k: {"n": len(v), "mean": round(sum(v) / len(v), 3)} for k, v in by_kind.items()},
        "items": cards,
    }
    (out / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf8")

    items_html = []
    for r in cards:
        badge = "pass-candidate" if r["total"] >= 4.5 else "high"
        items_html.append(
            f'<figure class="{badge}">'
            f'<img src="{r["gallery_file"]}" alt="{r["image_id"]}" loading="lazy"/>'
            f"<figcaption><b>{r['total']:.1f}</b> · {r['kind']} · {r['finish']}<br/>"
            f"<code>{r['image_id'][:12]}</code> · {r['pack']}</figcaption></figure>"
        )

    html = f"""<!DOCTYPE html>
<html lang="ko"><head><meta charset="utf-8"/>
<title>R5 합격선 후보 (총점 ≥ {MIN_SCORE})</title>
<style>
body{{font-family:system-ui,sans-serif;margin:24px;background:#111;color:#eee}}
h1{{font-size:1.25rem}} .meta{{opacity:.85;max-width:52rem;line-height:1.45}}
.grid{{display:grid;grid-template-columns:repeat(auto-fill,minmax(160px,1fr));gap:12px;margin-top:20px}}
figure{{margin:0;background:#1c1c1c;border-radius:8px;overflow:hidden;border:2px solid #333}}
figure.pass-candidate{{border-color:#2a9d8f}}
figure.high{{border-color:#e9c46a}}
img{{width:100%;aspect-ratio:1;object-fit:cover;display:block}}
figcaption{{padding:8px;font-size:12px;line-height:1.35}}
b{{font-size:16px}} code{{font-size:10px;opacity:.7}}
.legend span{{display:inline-block;padding:2px 8px;border-radius:4px;margin-right:8px;font-size:12px}}
.legend .g{{border:2px solid #2a9d8f}} .legend .y{{border:2px solid #e9c46a}}
</style></head><body>
<h1>R5 사람 총점 ≥ {MIN_SCORE} — 합격선 후보 갤러리</h1>
<p class="meta">총 <b>{n_40}</b>장 · 그중 ≥4.5 <b>{n_45}</b>장(초록 테두리).
잠정 제안 합격선: <b>4.5 / 5</b> (사람 채점표 기준). 자동 DINOv2 점수는 절대값이 낮아서 합격선에 쓰지 말 것.
갤러리를 보고 “이 사진 정도면 합격”인 앵커를 고른 뒤 확정하세요.</p>
<p class="legend"><span class="g">≥4.5 후보</span><span class="y">4.0~4.4</span></p>
<div class="grid">
{"".join(items_html)}
</div>
</body></html>
"""
    (out / "index.html").write_text(html, encoding="utf8")
    print(json.dumps({
        "out": str(out / "index.html"),
        "n_ge_4": n_40,
        "n_ge_4_5": n_45,
        "proposed_pass_line": 4.5,
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

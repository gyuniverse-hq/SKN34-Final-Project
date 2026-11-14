"""Fast human labeling of more LaPa test faces (bare lips / lipstick / exclude) for the expansion dataset.

  face_review.py build [--per-cell 10]   -> research/data/lip_rubric/face_review/index.html (+ crops)
  face_review.py merge <exported.csv>    -> research/data/lip_rubric/candidates_reviewed_v3.csv

One image per LaPa source photo (file-name prefix) and no prefix already used in earlier packs, so a new
face_id never repeats a person from the v2 or expansion packs. Crops stay in the ignored data folder.
"""
import argparse
import csv
import glob
import json
import random
from collections import defaultdict
from pathlib import Path

import cv2
import numpy as np

from common import DATA, ROOT, read_csv, write_csv

OUT = DATA / 'face_review'
LAPA = ROOT / 'research/data/LaPa/test'
LIP_LABELS = (7, 9)


def prefix(stem):
    return stem.rsplit('_', 1)[0]


def used_stems():
    used = set()
    for key in [DATA / 'pack/key.csv', *map(Path, glob.glob(str(DATA / 'expansion_*/pack_*/key.csv'))), *map(Path, glob.glob(str(DATA / 'expansion_v3*/**/key.csv'), recursive=True))]:
        if key.is_file():
            used.update(r['lapa_stem'] for r in read_csv(key))
    manifest = DATA / 'pack/manifest.json'
    if manifest.is_file():
        used.update(r['lapa_stem'] for r in json.loads(manifest.read_text(encoding='utf8')).get('practice_sources', []))
    return used


def select(candidates, reviewed, per_cell, seed):
    labeled = {r['lapa_stem'] for r in reviewed if r.get('human_label')}
    taken = {prefix(s) for s in used_stems() | labeled}
    cells = defaultdict(list)
    for r in candidates:
        if r['detected'] == '1' and r['lapa_stem'] not in labeled and prefix(r['lapa_stem']) not in taken and r['ita_bin'] != 'unknown':
            cells[(r['ita_bin'], r['mouth'], r['yaw_bin'])].append(r)
    rng = random.Random(seed); chosen = []; seen = set()
    for cell in sorted(cells):
        rows = cells[cell][:]; rng.shuffle(rows); n = 0
        for r in rows:
            if n >= per_cell: break
            if prefix(r['lapa_stem']) in seen: continue
            seen.add(prefix(r['lapa_stem'])); chosen.append(r); n += 1
    rng.shuffle(chosen)
    return chosen


def crops(stem):
    image = cv2.imread(str(LAPA / 'images' / f'{stem}.jpg')); label = cv2.imread(str(LAPA / 'labels' / f'{stem}.png'), cv2.IMREAD_GRAYSCALE)
    h, w = image.shape[:2]
    scale = 360 / max(h, w); face = cv2.resize(image, (int(w * scale), int(h * scale)), interpolation=cv2.INTER_AREA)
    ys, xs = np.where(np.isin(label, LIP_LABELS))
    if len(xs) == 0:
        return face, None
    cx, cy = (xs.min() + xs.max()) / 2, (ys.min() + ys.max()) / 2
    side = max(xs.max() - xs.min(), ys.max() - ys.min()) * 1.8
    x0, y0 = int(max(0, cx - side / 2)), int(max(0, cy - side / 2)); x1, y1 = int(min(w, cx + side / 2)), int(min(h, cy + side / 2))
    lip = cv2.resize(image[y0:y1, x0:x1], (360, 360), interpolation=cv2.INTER_CUBIC)
    return face, lip


PAGE = """<!doctype html><html lang="ko"><meta charset="utf-8"><title>LaPa 얼굴 표시</title>
<style>body{font-family:"Malgun Gothic",sans-serif;max-width:900px;margin:20px auto;color:#222}
.photos{display:flex;gap:16px;align-items:flex-start}img{border:1px solid #ccc;max-height:360px}
.keys{display:flex;gap:8px;flex-wrap:wrap;margin:14px 0}button{font:inherit;padding:10px 14px;border:1px solid #999;border-radius:8px;background:#fff;cursor:pointer}
button.on{background:#253d65;color:#fff}.muted{color:#666;font-size:13px}</style>
<h1>LaPa 얼굴 표시</h1>
<p class="muted">입술에 화장이 없으면 맨입술, 립 제품을 바른 것이 보이면 립스틱(제형까지), 입술이 가려졌거나 흐리거나 얼굴이 아니면 제외. 키보드: B 맨입술 · M 립스틱 매트 · S 립스틱 새틴 · G 립스틱 글로시 · U 립스틱 제형 모름 · X 제외 · ← 이전. 자동 저장됩니다.</p>
<p id="progress"></p><div class="photos"><img id="lip" alt="입술 확대"><img id="face" alt="얼굴 전체"></div>
<div class="keys" id="keys"></div><button id="export">CSV 내보내기</button> <span id="msg" class="muted"></span>
<script>
const ITEMS=__ITEMS__;const KEY='lapa-face-review-v3';const OPTS=[['b','맨입술','bare',''],['m','립스틱 매트','lipstick','matte'],['s','립스틱 새틴','lipstick','satin'],['g','립스틱 글로시','lipstick','glossy'],['u','립스틱 제형 모름','lipstick','unknown'],['x','제외','exclude','']];
let st=JSON.parse(localStorage.getItem(KEY)||'{"i":0,"a":{}}');const $=id=>document.getElementById(id);
function save(){localStorage.setItem(KEY,JSON.stringify(st))}
function show(){const it=ITEMS[Math.min(st.i,ITEMS.length-1)];const done=Object.keys(st.a).length;$('progress').textContent=(st.i<ITEMS.length?(st.i+1)+' / '+ITEMS.length:'끝')+' · 표시 완료 '+done;
$('lip').src=it.lip||'';$('lip').hidden=!it.lip;$('face').src=it.face;const cur=st.a[it.stem];$('keys').replaceChildren(...OPTS.map(o=>{const b=document.createElement('button');b.textContent=o[0].toUpperCase()+' '+o[1];if(cur&&cur[0]===o[2]&&cur[1]===o[3])b.className='on';b.onclick=()=>pick(o);return b}))}
function pick(o){const it=ITEMS[Math.min(st.i,ITEMS.length-1)];st.a[it.stem]=[o[2],o[3]];if(st.i<ITEMS.length-1)st.i++;else $('msg').textContent='마지막 사진입니다. CSV를 내보내 주세요.';save();show()}
document.addEventListener('keydown',e=>{if(e.key==='ArrowLeft'){st.i=Math.max(0,st.i-1);save();show();return}const o=OPTS.find(x=>x[0]===e.key.toLowerCase());if(o)pick(o)});
$('export').onclick=()=>{const rows=[['lapa_stem','human_label','finish'],...ITEMS.filter(it=>st.a[it.stem]).map(it=>[it.stem,...st.a[it.stem]])];const blob=new Blob(['\\ufeff'+rows.map(r=>r.join(',')).join('\\r\\n')],{type:'text/csv'});const a=document.createElement('a');a.href=URL.createObjectURL(blob);a.download='face_review_v3.csv';a.click();$('msg').textContent=(rows.length-1)+'장 내보냄'};
show();
</script></html>"""


def build(per_cell, seed):
    chosen = select(read_csv(DATA / 'candidates.csv'), read_csv(DATA / 'candidates_reviewed.csv'), per_cell, seed)
    (OUT / 'img').mkdir(parents=True, exist_ok=True)
    items = []
    for r in chosen:
        stem = r['lapa_stem']; face, lip = crops(stem)
        cv2.imwrite(str(OUT / 'img' / f'{stem}_face.jpg'), face, [cv2.IMWRITE_JPEG_QUALITY, 88])
        item = {'stem': stem, 'face': f'img/{stem}_face.jpg', 'lip': None}
        if lip is not None:
            cv2.imwrite(str(OUT / 'img' / f'{stem}_lip.jpg'), lip, [cv2.IMWRITE_JPEG_QUALITY, 92]); item['lip'] = f'img/{stem}_lip.jpg'
        items.append(item)
    (OUT / 'index.html').write_text(PAGE.replace('__ITEMS__', json.dumps(items)), encoding='utf8')
    write_csv(OUT / 'selected.csv', chosen)
    print(f"{OUT / 'index.html'}: {len(items)} faces")


def merge(exported):
    labels = {r['lapa_stem']: r for r in read_csv(exported)}
    selected = {r['lapa_stem']: r for r in read_csv(OUT / 'selected.csv')}
    if set(labels) - set(selected):
        raise ValueError('표시 화면에 없던 사진이 CSV에 있습니다')
    rows = read_csv(DATA / 'candidates_reviewed.csv')
    reviewed = {r['lapa_stem'] for r in rows}
    added = 0
    for stem, lab in labels.items():
        if lab['human_label'] not in ('bare', 'lipstick', 'exclude'):
            raise ValueError(f'알 수 없는 표시: {stem}')
        row = dict(selected[stem], human_label=lab['human_label'], finish=lab.get('finish', ''),
                   face_id='src_' + prefix(stem), identity_reviewed='yes', identity_method='one_image_per_source_prefix_v3')
        if stem in reviewed:
            rows = [row if r['lapa_stem'] == stem else r for r in rows]
        else:
            rows.append(row)
        added += 1
    out = DATA / 'candidates_reviewed_v3.csv'
    write_csv(out, rows, fields=list(read_csv(DATA / 'candidates_reviewed.csv')[0].keys()))
    from collections import Counter
    print(out, added, dict(Counter(labels[s]['human_label'] for s in labels)))


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest='command', required=True)
    b = sub.add_parser('build'); b.add_argument('--per-cell', type=int, default=10); b.add_argument('--seed', type=int, default=20261114)
    m = sub.add_parser('merge'); m.add_argument('csv', type=Path)
    a = p.parse_args()
    build(a.per_cell, a.seed) if a.command == 'build' else merge(a.csv)


if __name__ == '__main__':
    main()

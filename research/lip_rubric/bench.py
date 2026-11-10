"""Re-render the fixed benchmark and report paired metrics without pass criteria."""
import argparse
import html
import json
import shutil
import sys
import uuid
from collections import defaultdict
from pathlib import Path

import cv2
import numpy as np

from build_pack import INTENSITY, renderer_version, run_command, sticker_image
from common import DATA, ROOT, cluster_bootstrap, load_json, sha256
from metrics import METRIC_VERSION, compute
import db


def compare_runs(con, previous, current):
    old_run=con.execute('SELECT benchmark_sha256 FROM runs WHERE run_id=?',(previous,)).fetchone()
    new_run=con.execute('SELECT benchmark_sha256 FROM runs WHERE run_id=?',(current,)).fetchone()
    if old_run is None or new_run is None or old_run['benchmark_sha256']!=new_run['benchmark_sha256']:
        raise ValueError('동일한 고정 벤치마크의 두 실행만 비교할 수 있습니다')
    def values(run):
        return {(r['image_id'],r['metric']):dict(r) for r in con.execute('SELECT c.*,i.face_id FROM code_metrics c JOIN images i USING(image_id) WHERE c.run_id=? AND c.value IS NOT NULL',(run,))}
    a,b=values(previous),values(current); pairs=sorted(set(a)&set(b)); out={}
    if any(a[key]['metric_version']!=b[key]['metric_version'] for key in pairs): raise ValueError('metric version mismatch')
    if not pairs: raise ValueError('공통 이미지와 지표가 없어 비교할 수 없습니다')
    for metric in sorted({x[1] for x in pairs}):
        items=[{'face_id':a[key]['face_id'],'old':a[key]['value'],'new':b[key]['value']} for key in pairs if key[1]==metric]
        result=cluster_bootstrap(items,lambda x:float(np.median([r['new']-r['old'] for r in x])) if x else None)
        out[metric]={'n':len(items),'old_median':float(np.median([r['old'] for r in items])),'new_median':float(np.median([r['new'] for r in items])),'delta_new_minus_old':result}
    return out


def run_benchmark(con, benchmark, label, compare=None):
    benchmark=Path(benchmark); data=load_json(benchmark); items=[x for x in data['items'] if x['kind'] in ('render','sticker')]
    if not items: raise ValueError('no render/sticker benchmark items')
    for item in items:
        row=con.execute('SELECT intensity,tuning_json FROM images WHERE lapa_stem=? AND face_id=? AND kind=? AND shade=? AND source_image_sha256=? AND repeat_of IS NULL',(item['lapa_stem'],item['face_id'],item['kind'],item['shade'],item['image_sha256'])).fetchone()
        if row is None: raise ValueError('benchmark item missing from DB')
        if float(row['intensity'])!=float(INTENSITY) or json.loads(row['tuning_json'])!={}: raise ValueError('고정 벤치마크의 강도·TUNING 설정이 현재 기본값과 다릅니다')
    if not label or not all(c.isalnum() or c in '-_' for c in label): raise ValueError('label must be letters, digits, - or _')
    path=DATA/'reports'/f'bench_{label}.md'
    if path.exists() or path.with_suffix('.html').exists(): raise FileExistsError('report label exists')
    if compare and not con.execute('SELECT 1 FROM runs WHERE run_id=?',(compare,)).fetchone(): raise ValueError('이전 run이 없습니다')
    run_id=uuid.uuid4().hex; work=DATA/'bench'/run_id; (work/'src').mkdir(parents=True)
    dataset=ROOT/'research/data/LaPa/test'
    for stem in sorted({i['lapa_stem'] for i in items}):
        matches=[i for i in items if i['lapa_stem']==stem]; source=dataset/'images'/f'{stem}.jpg'
        if any(i['image_sha256']!=sha256(source) for i in matches): raise ValueError('source hash mismatch')
        shutil.copyfile(source,work/'src'/source.name)
    scripts=ROOT/'research/lip_texture'; run_command([sys.executable,scripts/'prep.py','--data-dir',work]); run_command(['node',scripts/'build_html.mjs','--data-dir',work])
    for stem in sorted({i['lapa_stem'] for i in items}):
        run_command([sys.executable,scripts/'dump_landmarks.py',stem,'--data-dir',work,'--offline-strict'])
        shades=sorted({i['shade'] for i in items if i['lapa_stem']==stem and i['kind']=='render'})
        run_command([sys.executable,scripts/'render.py','--tag','bench','--config','current=','--faces',stem,'--shades',','.join(shades),'--data-dir',work,'--offline-strict','--no-freeze'])
    version=renderer_version(work); stamp=db.now()
    with con:
        con.execute('INSERT INTO runs VALUES(?,?,?,?,?,?,?,?,?,?)',(run_id,'bench',version['renderer_commit'],int(version['renderer_dirty']),version['tracker_sha256'],version['page_sha256'],json.dumps(version['tuning_json']),sha256(benchmark),stamp,label))
        for item in items:
            stem=item['lapa_stem']; row=con.execute('SELECT * FROM images WHERE lapa_stem=? AND face_id=? AND kind=? AND shade=? AND source_image_sha256=? AND repeat_of IS NULL',(stem,item['face_id'],item['kind'],item['shade'],item['image_sha256'])).fetchone()
            if row is None: raise ValueError('benchmark item missing from DB')
            page=load_json(work/'faces'/f'{stem}.page.json'); off=cv2.imread(str(work/'renders/bench'/f'{stem}__off.png'))
            image=sticker_image(off,page,row['hex']) if item['kind']=='sticker' else cv2.imread(str(work/'renders/bench'/f"{stem}__{item['shade']}__current.png"))
            for metric,value in compute(image,off,page).items(): con.execute('INSERT INTO code_metrics VALUES(?,?,?,?,?)',(row['image_id'],metric,value,METRIC_VERSION,run_id))
    reports=DATA/'reports'; reports.mkdir(parents=True,exist_ok=True)
    comparison=compare_runs(con,compare,run_id) if compare else {}
    text=f'# 벤치마크 {label}\n\n측정 run: `{run_id}`  \n원본 목록 SHA-256: `{sha256(benchmark)}`  \n렌더러 커밋: `{version["renderer_commit"]}`  \ndirty: `{version["renderer_dirty"]}`\n\n지표는 보고만 하며 합격 판정이 아닙니다.\n\n'
    if compare: text+=f'이전 run: `{compare}`\n\n```json\n'+json.dumps(comparison,ensure_ascii=False,indent=2)+'\n```\n'
    else: text+='이전 run을 지정하지 않아 비교는 미실행입니다.\n'
    path.write_text(text,encoding='utf8'); path.with_suffix('.html').write_text('<!doctype html><meta charset="utf-8"><pre>'+html.escape(text)+'</pre>',encoding='utf8')
    print(run_id); return run_id


def main():
    p=argparse.ArgumentParser(); p.add_argument('--benchmark',type=Path,required=True); p.add_argument('--label',required=True); p.add_argument('--compare'); p.add_argument('--db',type=Path,default=db.DB); a=p.parse_args()
    with db.connect(a.db) as con: run_benchmark(con,a.benchmark,a.label,a.compare)


if __name__=='__main__': main()

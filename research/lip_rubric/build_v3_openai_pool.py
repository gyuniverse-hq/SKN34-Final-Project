"""Resume-safe v3 image-space pool; no scoring."""
import argparse, csv, hashlib, json, re, shutil, signal, sqlite3, subprocess, sys
from collections import Counter
from pathlib import Path
import cv2
from common import DATA, ROOT, read_csv, sha256
from build_v3 import plan
from build_pack import crop_lips, sticker_image, verify_input, SHADES
from degrade import LEVELS, apply

OUT=DATA/'expansion_v3_openai_pool'
V3=DATA/'expansion_v3'
SCRIPTS=ROOT/'research/lip_rubric'
SEED=20261117
ID=re.compile(r'^[0-9a-f]{32}$')
STOP=False

def request_stop(_signum, _frame):
    global STOP
    STOP=True
    print('Stop requested; finishing the current source image.', flush=True)

def save(path, obj):
    tmp=path.with_suffix(path.suffix+'.tmp'); tmp.write_text(json.dumps(obj,indent=2,ensure_ascii=False)+'\n',encoding='utf8'); tmp.replace(path)

def exclusions():
    sources={}
    def add(name, values): sources[name]=sorted({str(v).strip().lower() for v in values if v and ID.fullmatch(str(v).strip().lower())})
    for f in sorted(V3.glob('checklist_*/key.csv')):
        rows=read_csv(f); add(str(f.relative_to(DATA)),[r.get(k) for r in rows for k in ('random_id','image_id')])
    f=V3/'ab_key.csv'; add('expansion_v3/ab_key.csv',[r.get(k) for r in read_csv(f) for k in ('left','right')])
    for f in sorted((DATA/'results').glob('R5*csv')):
        add(str(f.relative_to(DATA)),[r.get(k) for r in read_csv(f) for k in ('image_id','random_id','left','right')])
    db=sqlite3.connect(f'file:{(DATA/"eval.db").as_posix()}?mode=ro',uri=True)
    for table,col in [('images','image_id'),('human_ratings','image_id')]: add('eval.db/'+table,[r[0] for r in db.execute(f'SELECT {col} FROM {table}')])
    db.close()
    allids=set().union(*(set(v) for v in sources.values()))
    (OUT/'excluded_image_ids.txt').write_text(''.join(x+'\n' for x in sorted(allids)),encoding='utf8')
    save(OUT/'excluded_summary.json',{'unique_image_ids':len(allids),'sources':{k:len(v) for k,v in sources.items()}})
    return allids

def command(args):
    subprocess.run([str(x) for x in args],cwd=ROOT,check=True)

def key_write(rows):
    if not rows: return
    p=OUT/'key.csv'; tmp=OUT/'key.csv.tmp'
    with tmp.open('w',encoding='utf-8-sig',newline='') as f:
        w=csv.DictWriter(f,fieldnames=list(rows[0])); w.writeheader(); w.writerows(rows)
    tmp.replace(p)

def render(row,work,shade,real=False):
    stem=row['lapa_stem']; (work/'src').mkdir(parents=True,exist_ok=True)
    verify_input(row, ROOT/'research/data/LaPa/test')
    shutil.copyfile(ROOT/'research/data/LaPa/test/images'/f'{stem}.jpg',work/'src'/f'{stem}.jpg')
    command([sys.executable,SCRIPTS/'prep.py','--data-dir',work])
    command(['node',SCRIPTS/'build_html.mjs','--data-dir',work])
    command([sys.executable,SCRIPTS/'dump_landmarks.py',stem,'--data-dir',work,'--offline-strict'])
    command(['node',SCRIPTS/'build_html.mjs','--data-dir',work])
    cmd=[sys.executable,SCRIPTS/'render.py','--tag','v3','--faces',stem,'--data-dir',work,'--offline-strict','--no-freeze']
    cmd += ['--off-only'] if real else ['--shades',shade,'--config','current=']
    command(cmd)

def main():
    signal.signal(signal.SIGINT, request_stop)
    if hasattr(signal, 'SIGTERM'): signal.signal(signal.SIGTERM, request_stop)
    ap=argparse.ArgumentParser(); ap.add_argument('--max-faces',type=int,default=0); ap.add_argument('--reserve-gb',type=float,default=1.0); args=ap.parse_args()
    OUT.mkdir(parents=True,exist_ok=True); (OUT/'images').mkdir(exist_ok=True)
    manifest_path=OUT/'manifest.json'
    if manifest_path.exists():
        previous=json.loads(manifest_path.read_text(encoding='utf8'))
        if previous.get('tracker_sha256') != sha256(ROOT/'components/ar/faceTrackerHtml.ts'):
            raise RuntimeError('Renderer changed since this pool was started; refusing mixed provenance')
    excluded=exclusions(); rows=read_csv(DATA/'candidates_reviewed_v3.csv')
    old=[r for f in V3.glob('checklist_*/key.csv') for r in read_csv(f)]
    used_stems={r['lapa_stem'] for r in old}; used_sha={r.get('image_sha256') for r in old}
    rows=[r for r in rows if r.get('detected')=='1' and r.get('human_label')!='exclude' and r.get('lapa_stem') not in used_stems and r.get('image_sha256') not in used_sha]
    # Priority is only scheduling; never collapse by face_id.
    rows.sort(key=lambda r:(0 if r['human_label']=='bare' else 1 if r['human_label']=='lipstick' else 2,hashlib.sha256((str(SEED)+r['lapa_stem']).encode()).hexdigest()))
    items=plan(rows,SEED); existing=read_csv(OUT/'key.csv') if (OUT/'key.csv').exists() else []
    done={r['lapa_stem'] for r in existing}; failures=json.loads((OUT/'failures.json').read_text(encoding='utf8')) if (OUT/'failures.json').exists() else {}
    ids={r['image_id'] for r in existing}|excluded; work=OUT/'work'; processed=0
    for n,it in enumerate(items):
        row=it['row']; stem=row['lapa_stem']; real=row['human_label']=='lipstick'
        if STOP: break
        if stem in done or stem in failures: continue
        if args.max_faces and processed>=args.max_faces: break
        if shutil.disk_usage(OUT).free < args.reserve_gb*1024**3: print('STOP: disk reserve reached',flush=True); break
        try:
            if work.exists(): shutil.rmtree(work)
            render(row,work,it['shade'],real)
            page=json.loads((work/'faces'/f'{stem}.page.json').read_text(encoding='utf8'))
            folder=work/'renders/v3'; off=cv2.imread(str(folder/f'{stem}__off.png'))
            base=off if real else cv2.imread(str(folder/f'{stem}__{it["shade"]}__current.png'))
            if base is None or off is None or base.shape[:2]!=(960,720): raise ValueError('missing render or unexpected dimensions')
            variants=[('real','')] if real else it['variants']+([('flat_sticker','')] if n%9==0 and row['human_label']=='bare' else [])
            batch=[]
            for variant,level in variants:
                kind='real' if real else 'sticker' if variant=='flat_sticker' else 'render'; shade='' if real else it['shade']
                frame=off if real else sticker_image(off,page,SHADES[shade]['hex']) if kind=='sticker' else base if variant=='current' else apply(base,off,page,SHADES[shade]['hex'],variant,LEVELS[level],seed=n*31+len(variant))
                ident=hashlib.sha256(f'{SEED}:{stem}:{variant}:{level}'.encode()).hexdigest()[:32]
                if ident in ids: raise ValueError(f'image_id collision: {ident}')
                ids.add(ident)
                prior_full=OUT/'images'/f'{ident}_full.png'
                if prior_full.exists():
                    # Recover an interrupted pair without overwriting its saved frame.
                    frame=cv2.imread(str(prior_full),cv2.IMREAD_UNCHANGED)
                    if frame is None or frame.shape != base.shape: raise ValueError(f'invalid partial image: {prior_full}')
                for suffix,im in [('full',frame),('crop',crop_lips(frame,page))]:
                    p=OUT/'images'/f'{ident}_{suffix}.png'
                    if p.exists():
                        prior=cv2.imread(str(p),cv2.IMREAD_UNCHANGED)
                        if prior is None or prior.shape != im.shape: raise ValueError(f'invalid partial image: {p}')
                    elif not cv2.imwrite(str(p),im): raise OSError(str(p))
                batch.append(dict(image_id=ident,face_id=row['face_id'],lapa_stem=stem,kind=kind,shade=shade,hex=SHADES[shade]['hex'] if shade else '',finish=SHADES[shade]['texture'] if shade else row.get('finish','unknown'),mouth=row.get('mouth',''),ita=row.get('ita',''),ita_bin=row.get('ita_bin',''),monk=row.get('monk',''),yaw=row.get('yaw_proxy',''),variant=variant,level=level,source_image_sha256=row['image_sha256'],label_sha256=row['label_sha256'],human_label=row['human_label'] or 'unreviewed',identity_reviewed=row.get('identity_reviewed',''),tuning_json=json.dumps({'defect':variant,'level':level} if level else {},sort_keys=True),pack='openai_pool'))
            existing.extend(batch); key_write(existing); done.add(stem); processed+=1
            print(f'complete {processed} {stem}: {len(batch)}; total {len(existing)}',flush=True)
            summarize(existing,excluded,rows,failures,work)
        except Exception as e:
            failures[stem]=f'{type(e).__name__}: {e}'; save(OUT/'failures.json',failures); print(f'FAILED {stem}: {e}',flush=True)
            # Infrastructure failures should not silently classify all candidates as unusable.
            if not existing: break
    summarize(existing,excluded,rows,failures,work)

def summarize(rows,excluded,candidates,failures,work):
    hashes={}; missing=[]
    for r in rows:
        for suffix in ('full','crop'):
            p=OUT/'images'/f'{r["image_id"]}_{suffix}.png'
            if p.exists(): hashes['images/'+p.name]=sha256(p)
            else: missing.append(str(p))
    ids=[r['image_id'] for r in rows]; collision=set(ids)&excluded
    counts=Counter((r['variant'],r['level']) for r in rows)
    summary={'images':len(rows),'png_files':len(hashes),'source_images':len({r['lapa_stem'] for r in rows}),'face_ids':len({r['face_id'] for r in rows}),'candidate_count':len(candidates),'estimated_images':sum(1 if r['human_label']=='lipstick' else 5 for r in candidates),'variant_level':{f'{a}:{b or "none"}':n for (a,b),n in sorted(counts.items())},'human_label':dict(Counter(r['human_label'] for r in rows)),'failures':len(failures),'excluded_id_intersection':len(collision),'duplicate_ids':len(ids)-len(set(ids)),'missing_files':missing,'repeat_policy':'no repeats; one key row per full/crop pair'}
    save(OUT/'summary.json',summary); save(OUT/'images_sha256.json',hashes)
    scriptnames=['prep.py','render.py','dump_landmarks.py','build_html.mjs','build_pack.py','build_v3.py','degrade.py','build_v3_openai_pool.py']
    rubric=DATA/'pack/rating_pack/rubric.json'
    manifest={'seed':SEED,'source':'LaPa test, non-commercial research','design':'v3 current render and image-space defects; variant/level are design metadata, not scores; unreviewed inputs are explicitly marked','pack_sha256':None,'pack_sha256_reason':'no public rating pack created','rubric_sha256':sha256(rubric) if rubric.exists() else None,'rubric':'existing v2 rubric, reference only','renderer_commit':subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip(),'renderer_dirty':True,'tracker_sha256':sha256(ROOT/'components/ar/faceTrackerHtml.ts'),'page_sha256':sha256(work/'page.html') if (work/'page.html').exists() else None,'scripts_sha256':{n:sha256(SCRIPTS/n) for n in scriptnames},'image_hashes_file':'images_sha256.json','image_hashes_sha256':sha256(OUT/'images_sha256.json'),'key_sha256':sha256(OUT/'key.csv') if rows else None,'summary':summary}
    save(OUT/'manifest.json',manifest)
    print(f'excluded image_id intersection: {len(collision)}; images={len(rows)} pairs={len(hashes)//2}; missing={len(missing)}',flush=True)
    if collision or missing or len(ids)!=len(set(ids)) or len(hashes)!=2*len(rows): raise ValueError('verification failed')
if __name__=='__main__': main()

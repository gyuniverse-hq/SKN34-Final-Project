"""Create a reproducible, LaPa-only blind pack after explicit human review."""
import argparse
import json
import random
import shutil
import subprocess
import sys
from collections import Counter, defaultdict
from pathlib import Path

import cv2
import numpy as np

from common import DATA, HERE, ROOT, read_csv, sha256, write_csv

sys.path.insert(0, str(ROOT / 'research/lip_texture'))
from prep import LIPS_INNER, LIPS_OUTER  # noqa: E402
from render import INTENSITY, SHADES  # noqa: E402

SHADE_PAIRS=[('glossy_red','satin_red'),('satin_coral','matte_red'),('matte_red','glossy_rose'),('glossy_rose','satin_red'),('satin_coral','glossy_red')]


def make_plan(selected, splits, seed, stickers, shades_per_face=2):
    rnd=random.Random(seed); shades=list(SHADES); bare=[r for r in selected if r['human_label']=='bare']; real=[r for r in selected if r['human_label']=='lipstick']
    rnd.shuffle(bare); rnd.shuffle(real)
    first=[next(r for r in bare if splits[r['face_id']]==group) for group in ('pool','test')]
    bare=first+[r for r in bare if r not in first]; items=[]
    for i,row in enumerate(bare):
        chosen=list(SHADE_PAIRS[i%len(SHADE_PAIRS)][:shades_per_face])
        if shades_per_face==3:
            chosen.append(next(s for s in shades if SHADES[s]['texture'] not in {SHADES[c]['texture'] for c in chosen}))
        for shade in chosen: items.append((row,'render',shade))
        if i<stickers: items.append((row,'sticker',shades[i%len(shades)]))
    for row in real: items.append((row,'real',''))
    return bare,real,items,rnd


def reviewed_faces(rows, seed, bare=19, lipstick=6):
    randomizer = random.Random(seed)
    by_id = defaultdict(list)
    for row in rows:
        if row.get('human_label') not in ('bare','lipstick','exclude',''):
            raise ValueError('human_label은 bare / lipstick / exclude 또는 빈칸이어야 합니다')
        if row.get('human_label') in ('bare','lipstick'):
            if row.get('identity_reviewed', '').lower() not in ('1','true','yes'):
                raise ValueError(f"인물 ID 검토가 필요합니다: {row['lapa_stem']} (identity_reviewed=yes)")
            if not row.get('face_id') or row.get('detected') != '1':
                raise ValueError(f"얼굴 검출 또는 face_id를 확인하세요: {row['lapa_stem']}")
            by_id[row['face_id']].append(row)
    for face_id, group in by_id.items():
        if len({r['human_label'] for r in group}) > 1:
            raise ValueError(f"동일 face_id의 상충한 human_label: {face_id}")
    selected = []
    for label, required in [('bare',bare),('lipstick',lipstick)]:
        candidates = [randomizer.choice(group) for group in by_id.values() if group[0]['human_label']==label]
        if len(candidates) < required:
            counts=Counter(r.get('ita_bin','unknown') for r in candidates)
            suggestions={bin_:[r.get('candidate_index') for r in rows if r.get('ita_bin')==bin_ and not r.get('human_label') and r.get('detected')=='1'][:10] for bin_ in ('q1','q2','q3','q4')}
            raise ValueError(f"검토된 서로 다른 인물 {label}이 {required}명 필요합니다 (현재 {len(candidates)}명); ITA 구간: {dict(counts)}; 추가 확인 후보 번호: {suggestions}")
        randomizer.shuffle(candidates)
        counts = Counter()
        for _ in range(required):
            uncovered = [r for r in candidates if label == 'bare' and r.get('ita_bin') in ('q1','q2','q3','q4') and not counts[('ita_bin',r.get('ita_bin'))]]
            candidate = min(uncovered or candidates, key=lambda r: sum(counts[(dim,r.get(dim,''))] for dim in ('ita_bin','mouth','yaw_bin')))
            candidates.remove(candidate); selected.append(candidate)
            for dim in ('ita_bin','mouth','yaw_bin'): counts[(dim,candidate.get(dim,''))] += 1
    return selected


def require_ita_coverage(rows):
    available = {r.get('ita_bin') for r in rows if r.get('human_label') == 'bare' and r.get('identity_reviewed','').lower() in ('1','yes','true') and r.get('detected') == '1'}
    missing = sorted(set(('q1','q2','q3','q4')) - available)
    if missing:
        suggestions = {bin_: [r.get('candidate_index') for r in rows if r.get('ita_bin') == bin_ and not r.get('human_label') and r.get('detected') == '1'][:10] for bin_ in missing}
        raise ValueError(f'맨입술 ITA 구간 부족: {missing}; 확인할 후보 번호: {suggestions}')


def renderer_version(work):
    def git(*args):
        return subprocess.check_output(['git',*args],cwd=ROOT,text=True,encoding='utf8').strip()
    dirty=bool(git('status','--porcelain'))
    if dirty: print('경고: Git 작업 트리에 변경사항이 있습니다. 버전에 기록합니다.',flush=True)
    return {'renderer_commit':git('rev-parse','HEAD'),'renderer_dirty':dirty,
        'tracker_sha256':sha256(ROOT/'components/ar/faceTrackerHtml.ts'), 'page_sha256':sha256(work/'page.html'),
        'tuning_json':{},'intensity':INTENSITY,
        'render_script_sha256':{name:sha256(ROOT/'research/lip_texture'/name) for name in ('prep.py','render.py','dump_landmarks.py','build_html.mjs')}}


def assign_splits(selected, seed):
    """Identity-grouped approximate stratification; tiny strata cannot all be balanced."""
    rnd = random.Random(seed); test=set()
    for label in ('bare', 'lipstick'):
        by_stratum=defaultdict(list)
        for row in selected:
            if row['human_label']==label:
                by_stratum[row.get('ita_bin','unknown')].append(row['face_id'])
        if not by_stratum: continue
        for group in by_stratum.values(): rnd.shuffle(group)
        total=sum(map(len,by_stratum.values()))
        target=min(total-1,max(1,round(total*.30))) if total>1 else 0
        allocations={name:0 for name in by_stratum}
        for _ in range(target):
            available=[name for name,group in by_stratum.items() if allocations[name]<len(group)]
            # Allocate to the stratum with the largest remaining proportional deficit.
            name=max(sorted(available),key=lambda x: target*len(by_stratum[x])/total-allocations[x])
            allocations[name]+=1
        for name,count in allocations.items(): test.update(by_stratum[name][:count])
    return {r['face_id']:('test' if r['face_id'] in test else 'pool') for r in selected}


def mirrored_ring(page, indices, width):
    # page coords originate in video space; the canvas draws a mirrored selfie.
    return np.array([[width-1-float(page['x'][i]),float(page['y'][i])] for i in indices],np.float32)


def sticker_image(off, page, color):
    h,w=off.shape[:2]; outer=mirrored_ring(page,LIPS_OUTER,w); inner=mirrored_ring(page,LIPS_INNER,w)
    mask=np.zeros((h,w),np.uint8); cv2.fillPoly(mask,[np.rint(outer).astype(np.int32)],255); cv2.fillPoly(mask,[np.rint(inner).astype(np.int32)],0)
    value=color.lstrip('#'); rgb=tuple(int(value[i:i+2],16) for i in (0,2,4)); out=off.copy(); out[mask>0]=rgb[::-1]
    return out


def crop_lips(frame,page):
    h,w=frame.shape[:2]; ring=mirrored_ring(page,LIPS_OUTER,w); lo,hi=ring.min(0),ring.max(0)
    side=float(hi[0]-lo[0])*1.6
    if side<2: raise ValueError('입술 크롭이 너무 작습니다')
    center=(lo+hi)/2; x,y=center-side/2; scale=512/side
    matrix=np.array([[scale,0,-x*scale],[0,scale,-y*scale]],np.float64)
    return cv2.warpAffine(frame,matrix,(512,512),flags=cv2.INTER_LINEAR,borderMode=cv2.BORDER_REPLICATE)


def verify_input(row, dataset):
    stem=row['lapa_stem']
    if row.get('source')!='LaPa' or row.get('source_split')!='test' or Path(stem).name!=stem:
        raise ValueError(f"LaPa test 외 입력 거부: {stem}")
    image=(dataset/'images'/f'{stem}.jpg').resolve(); mask=(dataset/'labels'/f'{stem}.png').resolve()
    if not image.is_file() or not mask.is_file() or sha256(image)!=row.get('image_sha256') or sha256(mask)!=row.get('label_sha256'):
        raise ValueError(f"LaPa 원본 해시 또는 짝 불일치: {stem}")
    return image, mask


def run_command(args):
    subprocess.run([str(x) for x in args], cwd=ROOT, check=True)


def build(args):
    dataset=args.dataset.resolve(); allowed=(ROOT/'research/data/LaPa/test').resolve()
    if dataset != allowed:
        raise ValueError(f'검증된 로컬 LaPa test만 허용합니다: {allowed}')
    if args.shades_per_face not in (1,2,3) or args.bare < 4 or args.lipstick < 2 or args.stickers < 2 or args.stickers > args.bare:
        raise ValueError('셰이드 1~3개와 pool/test에 필요한 인원·스티커 수가 필요합니다')
    rows=read_csv(args.candidates); require_ita_coverage(rows)
    selected=reviewed_faces(rows,args.seed,args.bare,args.lipstick); splits=assign_splits(selected,args.seed)
    if set(('q1','q2','q3','q4')) - {r.get('ita_bin') for r in selected if r['human_label']=='bare'}:
        raise ValueError('선택된 맨입술에서 ITA 구간이 빠졌습니다')
    selected_ids={r['face_id'] for r in selected}; practice=[]
    for row in rows:
        if row.get('human_label') in ('bare','lipstick') and row.get('identity_reviewed','').lower() in ('1','yes','true') and row.get('detected')=='1' and row.get('face_id') not in selected_ids and row.get('face_id') not in {r['face_id'] for r in practice}:
            practice.append(row)
            if len(practice)==3: break
    if len(practice)<3: raise ValueError('본 채점과 다른 인물의 검토된 연습 이미지 3장이 필요합니다')
    for row in selected+practice: verify_input(row,dataset)
    if args.output.exists(): raise FileExistsError(f'기존 결과를 덮지 않습니다: {args.output}')
    work=DATA/'render_work'
    if work.exists() and any(work.iterdir()): raise FileExistsError(f'기존 중간 결과를 덮지 않습니다: {work}')
    (work/'src').mkdir(parents=True,exist_ok=True)
    for row in selected+practice: shutil.copyfile(dataset/'images'/f"{row['lapa_stem']}.jpg",work/'src'/f"{row['lapa_stem']}.jpg")
    py=sys.executable; scripts=ROOT/'research/lip_texture'
    run_command([py,scripts/'prep.py','--data-dir',work])
    run_command(['node',scripts/'build_html.mjs','--data-dir',work])
    # Landmark dump needs an initial build. Rebuild before rendering as specified.
    for row in selected+practice: run_command([py,scripts/'dump_landmarks.py',row['lapa_stem'],'--data-dir',work,'--offline-strict'])
    run_command(['node',scripts/'build_html.mjs','--data-dir',work])
    version=renderer_version(work)
    bare,real,items,rnd=make_plan(selected,splits,args.seed,args.stickers,args.shades_per_face)
    for i,row in enumerate(bare):
        chosen=','.join(shade for face,kind,shade in items if face is row and kind=='render')
        run_command([py,scripts/'render.py','--tag','rubric','--config','current=','--faces',row['lapa_stem'],'--shades',chosen,'--data-dir',work,'--offline-strict','--no-freeze'])
    for row in real:
        run_command([py,scripts/'render.py','--tag','rubric','--faces',row['lapa_stem'],'--data-dir',work,'--offline-strict','--no-freeze','--off-only'])
    for row in practice:
        run_command([py,scripts/'render.py','--tag','rubric','--faces',row['lapa_stem'],'--data-dir',work,'--offline-strict','--no-freeze','--off-only'])
    output=args.output; rating=output/'rating_pack'; images=rating/'images'; images.mkdir(parents=True)
    key=[]; public=[]; source_meta={}; hashes={}; page_hash=sha256(work/'page.html')
    for row,kind,shade in items:
        stem=row['lapa_stem']; rendered=work/'renders/rubric'; off=cv2.imread(str(rendered/f'{stem}__off.png'))
        page=json.loads((work/'faces'/f'{stem}.page.json').read_text(encoding='utf8'))
        if off is None or off.shape[:2]!=(960,720): raise ValueError(f'렌더 경로/크기 확인: {stem}')
        finish=(SHADES[shade]['texture'] if shade else row.get('finish') or 'unknown')
        hex_color=SHADES[shade]['hex'] if shade else ''
        if kind=='render': frame=cv2.imread(str(rendered/f'{stem}__{shade}__current.png'))
        elif kind=='sticker': frame=sticker_image(off,page,hex_color)
        else: frame=off
        if frame is None or frame.shape!=off.shape: raise ValueError(f'렌더 실패: {stem}/{kind}/{shade}')
        crop=crop_lips(frame,page); random_id=f'{rnd.getrandbits(128):032x}'
        for suffix,im in [('full',frame),('crop',crop)]:
            file=images/f'{random_id}_{suffix}.png'
            if not cv2.imwrite(str(file),im): raise IOError(file)
            hashes[str(file.relative_to(output)).replace('\\','/')]=sha256(file)
        item={'random_id':random_id,'lapa_stem':stem,'face_id':row['face_id'],'kind':kind,'shade':shade,'hex':hex_color,'finish':finish,
              'mouth':row['mouth'],'ita':row['ita'],'ita_bin':row.get('ita_bin',''),'monk':row.get('monk',''),'yaw':row.get('yaw_proxy',''),
              'split':splits[row['face_id']],'repeat_of':'','source':'LaPa','source_split':'test','image_sha256':row['image_sha256'],'label_sha256':row['label_sha256'],
              'renderer_commit':version['renderer_commit'],'renderer_dirty':version['renderer_dirty'],'tracker_sha256':version['tracker_sha256'],
              'page_sha256':version['page_sha256'],'tuning_json':json.dumps(version['tuning_json']),'intensity':version['intensity'],
              'render_script_sha256':json.dumps(version['render_script_sha256'],sort_keys=True)}
        key.append(item); public.append({'id':random_id,'finish':finish,'mouth':row['mouth'],'is_repeat':False})
        source_meta[stem]={'image_sha256':row['image_sha256'],'label_sha256':row['label_sha256']}
    for kind,count in [('render',2),('sticker',1),('real',1)]:
        for source in rnd.sample([r for r in key if r['kind']==kind and not r['repeat_of']],count):
            item=dict(source); item['random_id']=f'{rnd.getrandbits(128):032x}'; item['repeat_of']=source['random_id']; key.append(item)
            for suffix in ('full','crop'):
                file=images/f"{item['random_id']}_{suffix}.png"; shutil.copyfile(images/f"{source['random_id']}_{suffix}.png",file)
                hashes[str(file.relative_to(output)).replace('\\','/')]=sha256(file)
            public.append({'id':item['random_id'],'finish':item['finish'],'mouth':item['mouth'],'is_repeat':True})
    rnd.shuffle(public)
    practice_public=[]; practice_dir=rating/'practice'; practice_dir.mkdir()
    for row in practice:
        stem=row['lapa_stem']; frame=cv2.imread(str(work/'renders/rubric'/f'{stem}__off.png'))
        page=json.loads((work/'faces'/f'{stem}.page.json').read_text(encoding='utf8')); ident=f'{rnd.getrandbits(128):032x}'
        for suffix,im in [('full',frame),('crop',crop_lips(frame,page))]:
            file=practice_dir/f'{ident}_{suffix}.png'
            if not cv2.imwrite(str(file),im): raise IOError(file)
            hashes[str(file.relative_to(output)).replace('\\','/')]=sha256(file)
        practice_public.append({'id':ident,'finish':row.get('finish') or 'unknown','mouth':row['mouth']})
    (rating/'pack.json').write_text(json.dumps({'version':2,'items':public,'practice':practice_public},ensure_ascii=False,indent=2),encoding='utf8')
    (rating/'guide.json').write_text('{}\n',encoding='utf8')
    shutil.copyfile(HERE/'rubric.json',rating/'rubric.json'); shutil.copyfile(HERE/'rating/index.html',rating/'index.html')
    write_csv(output/'key.csv',key)
    manifest={'seed':args.seed,'source':'LaPa test; non-commercial research','dataset_path':str(dataset),'sources':source_meta,'image_files_sha256':hashes,
              'pack_sha256':sha256(rating/'pack.json'),'rubric_sha256':sha256(rating/'rubric.json'),'app_page_sha256':page_hash,
              'renderer':version,'app_tuning':'current; no freeze','intensity':INTENSITY,'shades':SHADES,
              'finish_counts':dict(Counter(r['finish'] for r in key if r['kind']=='render' and not r['repeat_of'])),
              'practice_sources':[{'lapa_stem':r['lapa_stem'],'face_id':r['face_id'],'image_sha256':r['image_sha256']} for r in practice],
              'face_id_warning':'human-confirmed IDs required; residual cross-source identity errors remain'}
    (output/'manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding='utf8')
    bench_dir=DATA/'benchmark'; bench_dir.mkdir(parents=True,exist_ok=True); bench=bench_dir/'benchmark_v1.json'
    if bench.exists(): raise FileExistsError('고정 벤치마크를 덮어쓰지 않습니다')
    benchmark=[{k:r[k] for k in ('lapa_stem','face_id','kind','shade','image_sha256')} for r in key if not r['repeat_of']]
    bench.write_text(json.dumps({'version':1,'items':benchmark},ensure_ascii=False,indent=2),encoding='utf8')
    print(f'benchmark SHA-256: {sha256(bench)}')
    print(f'채점 묶음 완료: {rating}; 담당자 전용 정답표: {output / "key.csv"}')


def main():
    p=argparse.ArgumentParser(); p.add_argument('--candidates',type=Path,default=DATA/'candidates_reviewed.csv'); p.add_argument('--dataset',type=Path,default=ROOT/'research/data/LaPa/test'); p.add_argument('--output',type=Path,default=DATA/'pack'); p.add_argument('--seed',type=int,default=42)
    p.add_argument('--bare',type=int,default=19); p.add_argument('--lipstick',type=int,default=6); p.add_argument('--shades-per-face',type=int,default=2); p.add_argument('--stickers',type=int,default=6)
    build(p.parse_args())


if __name__=='__main__': main()

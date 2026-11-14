"""Prepare a blinded pilot; run only on the authorized local package."""
from pathlib import Path
import os
from zipfile import ZipFile
from collections import Counter
import csv, io, json, random, hashlib
from datetime import datetime, timezone

OUT = Path(__file__).resolve().parents[1] / 'data' / 'lip_teacher_20261113'

SEED = 20261113
def write(path, obj):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding='utf-8')
def readcsv(content):
    return list(csv.DictReader(io.StringIO(content.decode('utf-8-sig'))))
def score(checks):
    means=[]
    for q in range(1,6):
        vals=[checks[f'q{q}_{i}'] for i in range(1,6)]
        if 'unknown' in vals: return {'total':None,'questions':None}
        valid=[v for v in vals if v != 'na']
        means.append(sum(valid)/len(valid) if valid else None)
    valid=[v for v in means if v is not None]
    return {'total':5*sum(valid)/len(valid) if valid else None,'questions':means}

def main():
    SOURCE = Path(os.environ["LIP_RUBRIC_SOURCE"])
    with ZipFile(SOURCE/'colab_pack.zip') as z:
        assert z.testzip() is None
        meta=readcsv(z.read('meta.csv'))
        rubric=json.loads(z.read('rubric.json'))
        write(OUT/'rubric.json',rubric)
        byid={r['image_id']:r for r in meta}
        cols=[c['id'] for q in rubric['questions'] for c in q['checks']]
        raw={}; repeated={}; source_hashes={}
        for rater in ['R1','R4','R5']:
            p=SOURCE/f'{rater}_ratings.csv'; content=p.read_bytes()
            source_hashes[p.name]=hashlib.sha256(content).hexdigest()
            rows=readcsv(content)
            assert len(rows)==54 and len({r['image_id'] for r in rows})==54
            original=[r for r in rows if r['image_id'] in byid]
            assert len(original)==50 and all(r['is_repeat']=='0' for r in original)
            repeated[rater]=[r['image_id'] for r in rows if r['image_id'] not in byid]
            raw[rater]={r['image_id']:r for r in original}
        rng=random.Random(SEED); blind=[]; truth=[]; pool=[]
        for split,prefix in [('pool','P'),('test','T')]:
            ids=sorted(r['image_id'] for r in meta if r['split']==split)
            rng.shuffle(ids)
            for i,image_id in enumerate(ids,1):
                alias=f'{prefix}{i:02d}'; m=byid[image_id]
                raters={}; votes={}; majority={}; proportions={}
                for rater in raw:
                    r=raw[rater][image_id]
                    checks={c:int(r[c]) if r[c] in ['0','1'] else r[c] for c in cols}
                    assert set(checks.values()) <= {0,1,'na'}
                    raters[rater]={'checks':checks,'overall':int(r['overall']),**score(checks)}
                for c in cols:
                    vals=[raters[r]['checks'][c] for r in raters]
                    counts=Counter(vals); top=counts.most_common()
                    votes[c]={str(k):v for k,v in counts.items()}
                    majority[c]=top[0][0] if len(top)==1 or top[0][1]>top[1][1] else 'tie'
                    binary=[v for v in vals if v!='na']
                    proportions[c]={'yes_fraction':sum(binary)/len(binary) if binary else None,'applicable_n':len(binary),'na_n':vals.count('na')}
                full=OUT/'blinded'/f'{alias}_full.png'; crop=OUT/'blinded'/f'{alias}_crop.png'
                full.parent.mkdir(parents=True,exist_ok=True)
                full.write_bytes(z.read(f'images/{image_id}_full.png'))
                crop.write_bytes(z.read(f'images/{image_id}_crop.png'))
                public={'alias':alias,'finish':m['finish'],'full_path':str(full),'crop_path':str(crop)}
                item={**m,'alias':alias,'raters':raters,'votes':votes,'majority':majority,'proportions':proportions,
                      'total_mean':sum(v['total'] for v in raters.values())/3,
                      'overall_mean':sum(v['overall'] for v in raters.values())/3,
                      'question_means':[sum(v['questions'][q] for v in raters.values())/3 for q in range(5)]}
                truth.append(item)
                if split=='test':blind.append(public)
                else:pool.append({**public,**item})
        write(OUT/'blind_manifest.json',blind)
        write(OUT/'pool_calibration.json',pool)
        write(OUT/'private'/'truth.json',truth)
        protocol={'created_utc':datetime.now(timezone.utc).isoformat(),'rubric_version':rubric['version'],
          'raters':['R1','R4','R5'],'R5_source_code':'R0; mapped to R5 only in derived data, user confirmed',
          'seed':SEED,'source_sha256':source_hashes,'test_n':len(blind),'pool_n':len(pool),
          'split_unit':'face; original group assignment unchanged','test_truth_exposure':'Not to be opened by visual scorer before predictions lock.',
          'inputs':'AR full720x960 and crop512x512 plus finish; no kind, human score, original bare lips.',
          'prediction_format':{'rubric_version':'lip-rubric-v2','predictions':[{'alias':'T01','checks':{c:'0/1/na/unknown' for c in cols},'overall':'integer1..5','reason':'brief visual evidence'}]},
          'unknown_policy':'Abstention is separate from NA. Unknown is incorrect in checklist agreement; totals missing if unknown. No imputation.',
          'NA_policy':'Only matte q3_2,q3_3,q3_4 permit na. Other questions use yes/no or unknown.',
          'score':'Average applicable checks within each of5questions; sum these question scores. Overall1..5 separate.',
          'consensus':'Most frequent of yes/no/NA; ties excluded from majority agreement. Binary yes fraction excludes NA, saves applicable and NA counts.',
          'matched_human_baseline':'For each held-out rater, compare human and teacher with other2 raters only on exact binary agreement. Compute per-check agreement then macro mean over observed checks. Teacher unknown/NA counts incorrect on these binary consensus cases.',
          'bootstrap':'2000 face-cluster samples, seed20261113, report valid samples and percentile95CI.',
          'screening_rule':'Eligible for next larger validation only if every test prediction valid/complete with no unknown, render-onlySpearman95CI lower>0, teacher macro checklist agreement>=matched human baseline, sticker<render<real bothmeans and strictlyordered majority of cross-kind triples. No automatic deployment approval.',
          'advisory_rule':'If eligibility fails but render-onlySpearman>0 and extreme ordering rule passes, advisory only. Otherwise do not use automatic labels.',
          'limitations':['Only16test images8faces;12render images. Previously used test, so pilot only.','Rater selection is user policy, not evidence excluded raters invalid. Only3 team raters, no independent panel.','Original bare-lip references and repeat-to-original mapping unavailable. No temporal AR or product color accuracy assessed.','No target regrading after truth release; protocol/rubric updates require new validation.']}
        write(OUT/'protocol.json',protocol)
        write(OUT/'private'/'repeats_excluded.json',repeated)
        print(json.dumps({'test':len(blind),'pool':len(pool),'originals':len(truth),'raters':3,'files_valid':True,'manifest':str(OUT/'blind_manifest.json'),'protocol':str(OUT/'protocol.json')}))
if __name__=='__main__':main()

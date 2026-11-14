"""Evaluate only after scorer locks all blinded predictions; outputs expose truth."""
from pathlib import Path
from collections import defaultdict
from datetime import datetime, timezone
import argparse, csv, hashlib, itertools, json
import numpy as np
from prepare import OUT, score, write

COLS=[f'q{q}_{i}' for q in range(1,6) for i in range(1,6)]
def ranks(x):
    a=np.asarray(x,float); order=np.argsort(a,kind='stable'); out=np.empty(len(a))
    pos=0
    while pos<len(a):
        end=pos+1
        while end<len(a) and a[order[end]]==a[order[pos]]:end+=1
        out[order[pos:end]]=(pos+end-1)/2
        pos=end
    return out
def spearman(x,y):
    if len(x)<3:return None
    a,b=ranks(x),ranks(y)
    if np.std(a)==0 or np.std(b)==0:return None
    return float(np.corrcoef(a,b)[0,1])
def mean(x):return float(np.mean(x)) if len(x) else None
def boot(rows,stat,n=2000):
    groups=sorted({r['face_id'] for r in rows})
    point=stat(rows)
    if len(groups)<2:return {'estimate':point,'ci95':None,'faces':len(groups),'valid_bootstraps':0}
    rng=np.random.default_rng(20261113); vals=[]
    by={g:[r for r in rows if r['face_id']==g] for g in groups}
    for _ in range(n):
        sample=[r for g in rng.choice(groups,len(groups),replace=True) for r in by[g]]
        value=stat(sample)
        if value is not None and np.isfinite(value):vals.append(value)
    ci=[float(v) for v in np.percentile(vals,[2.5,97.5])] if vals else None
    return {'estimate':point,'ci95':ci,'faces':len(groups),'valid_bootstraps':len(vals)}
def matched(rows):
    counts={c:[] for c in COLS}; na=[]
    for r in rows:
        raters=r['raters']; p=r['prediction']['checks']
        for held in raters:
            others=[v for name,v in raters.items() if name!=held]
            for c in COLS:
                a,b=(v['checks'][c] for v in others)
                if a!=b:continue
                human=raters[held]['checks'][c]
                if a=='na':na.append((int(p[c]=='na'),int(human=='na')))
                elif type(a) is int:counts[c].append((int(p[c]==a),int(human==a)))
    per={c:{'n':len(v),'teacher':mean([a for a,b in v]),'human':mean([b for a,b in v])} for c,v in counts.items()}
    observed=[v for v in per.values() if v['n']]
    return {'teacher_macro':mean([v['teacher'] for v in observed]),'human_macro':mean([v['human'] for v in observed]),
            'macro_delta':mean([v['teacher']-v['human'] for v in observed]),'observed_checks':len(observed),
            'binary_trials':sum(v['n'] for v in observed),'per_check':per,
            'na_consensus_trials':len(na),'teacher_na_agreement':mean([a for a,b in na]),'human_na_agreement':mean([b for a,b in na])}
def majority_agreement(rows):
    per={}
    for c in COLS:
        eligible=[r for r in rows if r['majority'][c]!='tie']
        per[c]={'n':len(eligible),'agreement':mean([int(r['prediction']['checks'][c]==r['majority'][c]) for r in eligible])}
    return {'macro':mean([v['agreement'] for v in per.values() if v['n']]),'per_check':per}
def ordering(rows):
    by={k:[r['predicted_total'] for r in rows if r['kind']==k and r['predicted_total'] is not None] for k in ['sticker','render','real']}
    means={k:mean(v) for k,v in by.items()}
    triples=list(itertools.product(by['sticker'],by['render'],by['real']))
    fraction=mean([int(a<b<c) for a,b,c in triples])
    means_ok=all(v is not None for v in means.values()) and means['sticker']<means['render']<means['real']
    return {'means':means,'ordered_triples':fraction,'triples_n':len(triples),'passes':bool(means_ok and fraction is not None and fraction>0.5)}
def summarize(rows):
    valid=[r for r in rows if r['predicted_total'] is not None]
    qs={}
    for q in range(5):
        v=[r for r in rows if r['predicted_questions'] is not None and r['predicted_questions'][q] is not None]
        qs[f'q{q+1}']={'n':len(v),'mae':mean([abs(r['predicted_questions'][q]-r['question_means'][q]) for r in v]),
                     'bias':mean([r['predicted_questions'][q]-r['question_means'][q] for r in v])}
    return {'images':len(rows),'complete_total_images':len(valid),
      'spearman':boot(valid,lambda rr:spearman([r['predicted_total'] for r in rr],[r['total_mean'] for r in rr])),
      'mae':boot(valid,lambda rr:mean([abs(r['predicted_total']-r['total_mean']) for r in rr])),
      'bias':mean([r['predicted_total']-r['total_mean'] for r in valid]),
      'overall_spearman':boot(rows,lambda rr:spearman([r['prediction']['overall'] for r in rr],[r['overall_mean'] for r in rr])),
      'overall_mae':mean([abs(r['prediction']['overall']-r['overall_mean']) for r in rows]),
      'questions':qs,'majority':majority_agreement(rows),'matched':matched(rows),
      'matched_delta_ci':boot(rows,lambda rr:matched(rr)['macro_delta'])}
def validate(predictions,manifest):
    if predictions.get('rubric_version')!='lip-rubric-v2':raise ValueError('rubric_version mismatch')
    rows=predictions['predictions']; aliases={p['alias'] for p in rows}
    expected={r['alias'] for r in manifest}
    if len(rows)!=16 or len(aliases)!=16 or aliases!=expected:raise ValueError('Require16unique exact test aliases')
    meta={r['alias']:r for r in manifest}
    for p in rows:
        if set(p['checks'])!=set(COLS):raise ValueError(f"{p['alias']}: require all25checks")
        if type(p['overall']) is not int or not 1<=p['overall']<=5:raise ValueError('overall must be integer1..5')
        if not isinstance(p.get('reason'),str) or not p['reason'].strip():raise ValueError('reason required')
        for c,v in p['checks'].items():
            if not(type(v) is int and v in (0,1) or type(v) is str and v in ('na','unknown')):raise ValueError(f'invalid check {c}')
            if v=='na' and not(meta[p['alias']]['finish']=='matte' and c in ('q3_2','q3_3','q3_4')):raise ValueError(f'{c}:NA not allowed')
    return rows
def main():
    parser=argparse.ArgumentParser();parser.add_argument('predictions',type=Path);a=parser.parse_args()
    content=a.predictions.read_bytes(); pdoc=json.loads(content)
    manifest=json.loads((OUT/'blind_manifest.json').read_text(encoding='utf-8'))
    predictions=validate(pdoc,manifest)
    locked=OUT/'predictions.locked.json'
    if locked.exists() and locked.read_bytes()!=content:raise ValueError('Prediction lock exists and differs; refusing overwrite')
    if not locked.exists():
        locked.write_bytes(content)
        write(OUT/'prediction_lock.json',{'sha256':hashlib.sha256(content).hexdigest(),'locked_utc':datetime.now(timezone.utc).isoformat(),
                                      'protocol_sha256':hashlib.sha256((OUT/'protocol.json').read_bytes()).hexdigest()})
    truth=json.loads((OUT/'private'/'truth.json').read_text(encoding='utf-8'))
    lookup={p['alias']:p for p in predictions}; rows=[]
    for r in truth:
        if r['split']!='test':continue
        p=lookup[r['alias']]; s=score(p['checks'])
        rows.append({**r,'prediction':p,'predicted_total':s['total'],'predicted_questions':s['questions']})
    allresult=summarize(rows); render=summarize([r for r in rows if r['kind']=='render']); order=ordering(rows)
    unknown=sum(v=='unknown' for p in predictions for v in p['checks'].values())
    rho=render['spearman']['estimate'];ci=render['spearman']['ci95'];m=allresult['matched']
    eligible=unknown==0 and ci is not None and ci[0]>0 and m['teacher_macro']>=m['human_macro'] and order['passes']
    advisory=rho is not None and rho>0 and order['passes']
    decision='eligible_for_larger_validation' if eligible else 'advisory_only' if advisory else 'do_not_use_automatic_labels'
    result={'protocol':str(OUT/'protocol.json'),'prediction_sha256':hashlib.sha256(content).hexdigest(),'raters':['R1','R4','R5'],
            'unknown_checks':unknown,'all_test':allresult,'render_only':render,'kind_ordering':order,'decision':decision,
            'decision_is_pilot_only':True,'threshold_results':{'complete_predictions':unknown==0,'render_rho_ci_positive':bool(ci is not None and ci[0]>0),
             'matched_check_at_least_human':m['teacher_macro']>=m['human_macro'],'extreme_ordering':order['passes']}}
    write(OUT/'results'/'evaluation.json',result)
    write(OUT/'results'/'per_image.json',rows)
    fields=['alias','kind','finish','human_mean','teacher_total','error','human_overall','teacher_overall','reason']
    with (OUT/'results'/'comparison.csv').open('w',encoding='utf-8-sig',newline='') as f:
        writer=csv.DictWriter(f,fieldnames=fields);writer.writeheader()
        for r in rows:
            writer.writerow({'alias':r['alias'],'kind':r['kind'],'finish':r['finish'],'human_mean':r['total_mean'],'teacher_total':r['predicted_total'],
              'error':r['predicted_total']-r['total_mean'] if r['predicted_total'] is not None else '',
              'human_overall':r['overall_mean'],'teacher_overall':r['prediction']['overall'],'reason':r['prediction']['reason']})
    print(json.dumps({'decision':decision,'all_spearman':allresult['spearman'],'render_spearman':render['spearman'],
                     'teacher_matched':m['teacher_macro'],'human_matched':m['human_macro'],'mae':allresult['mae'],'order':order},ensure_ascii=False))
if __name__=='__main__':main()

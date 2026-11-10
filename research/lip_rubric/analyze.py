"""Compare test predictions against human consensus; no renderer pass threshold."""
import argparse
import itertools
import json
import statistics
from collections import defaultdict
from pathlib import Path

import numpy as np

from aggregate import parse_ratings
from common import DATA, HERE, checks, cluster_bootstrap, load_json, read_csv, spearman


def classify(b, c, human, b_ci, difference_ci, order_ok):
    if any(x is None for x in (b, c, human, b_ci, difference_ci)):
        return '판정 불가'
    if b >= human and b > c and difference_ci[0] > 0:
        return '대체 가능'
    if b_ci[0] > 0 and order_ok:
        return '보조만'
    return '쓰지 않음'


def compare(ratings_path, key_path, rubric_path, judge_path, rater_files, output):
    rubric = load_json(rubric_path); keys = {r['random_id']:r for r in read_csv(key_path)}
    ratings = {r['image_id']:r for r in read_csv(ratings_path) if r['split'] == 'test'}
    raw, issues, pack_hash = parse_ratings(rater_files, keys, rubric)
    raw = [r for r in raw if r['image_id'] in ratings and not keys[r['image_id']]['repeat_of']]
    human_baselines = []
    for who in sorted({r['rater'] for r in raw}):
        pairs=[]
        for image in ratings:
            own=[r['score']['total'] for r in raw if r['image_id']==image and r['rater']==who]
            others=[r['score']['total'] for r in raw if r['image_id']==image and r['rater']!=who]
            if own and others: pairs.append((own[0], statistics.mean(others)))
        value=spearman([p[0] for p in pairs],[p[1] for p in pairs]) if pairs else None
        if value is not None: human_baselines.append({'rater':who,'spearman':value,'n':len(pairs)})
    human_median=statistics.median(x['spearman'] for x in human_baselines) if human_baselines else None
    result_rows=read_csv(judge_path); methods={}; paired={}
    for method in ('A','B','C'):
        pred={r['image_id']:r for r in result_rows if r['method']==method and r['repeat']=='0' and r['status']=='ok' and r['image_id'] in ratings}
        pairs=[(ratings[i],r) for i,r in pred.items()]; paired[method]=pred
        xs=[float(h['total_mean']) for h,p in pairs]; ys=[float(p['total']) for h,p in pairs]
        observations=[{'face_id':h['face_id'],'x':x,'y':y} for (h,_),x,y in zip(pairs,xs,ys)]
        corr=spearman(xs,ys); boot=cluster_bootstrap(observations, lambda rows:spearman([r['x'] for r in rows],[r['y'] for r in rows])); ci=boot['ci95']
        qs={}; agreement={}
        for q in range(5):
            vals=[(float(h[f'q{q+1}_mean']), json.loads(p['questions_json'])[q]) for h,p in pairs if h[f'q{q+1}_mean'] and json.loads(p['questions_json'])[q] is not None]
            qs[f'q{q+1}']=spearman([v[0] for v in vals],[float(v[1]) for v in vals])
        for ch in checks(rubric):
            vals=[(h[ch['id']],str(json.loads(p['checks_json']).get(ch['id']))) for h,p in pairs if h[ch['id']] in ('0','1','na') and json.loads(p['checks_json']).get(ch['id']) is not None]
            agreement[ch['id']]={'rate':sum(a==b for a,b in vals)/len(vals) if vals else None,'n':len(vals)}
        kinds={kind:[float(p['total']) for h,p in pairs if h['kind']==kind] for kind in ('sticker','render','real')}
        triples=list(itertools.product(kinds['sticker'],kinds['render'],kinds['real']))
        means={k:statistics.mean(v) if v else None for k,v in kinds.items()}
        order_ok=all(means[k] is not None for k in means) and means['sticker']<means['render']<means['real']
        repeats=[]
        for image in pred:
            rs=[r for r in result_rows if r['image_id']==image and r['method']==method and r['repeat'] in ('1','2','3') and r['status']=='ok']
            if len(rs)==3:
                agreements=[]
                for a,b in itertools.combinations(rs,2):
                    x,y=json.loads(a['checks_json']),json.loads(b['checks_json']); agreements.extend(x[c['id']]==y[c['id']] for c in checks(rubric))
                repeats.append({'image_id':image,'total_std':float(np.std([float(r['total']) for r in rs])), 'check_agreement':statistics.mean(agreements)})
        methods[method]={'n':len(pairs),'spearman':corr,'spearman_ci95':ci,'mae':statistics.mean(abs(x-y) for x,y in zip(xs,ys)) if pairs else None,'question_spearman':qs,'check_agreement':agreement,'kind_means':means,'order_of_kind_means':order_ok,'ordered_triples_fraction':sum(a<b<c for a,b,c in triples)/len(triples) if triples else None,'ordered_triples_n':len(triples),'repeats':repeats}
    ids=sorted(set(paired['B']) & set(paired['C']) & set(ratings)); obs=[{'face_id':ratings[i]['face_id'],'id':i} for i in ids]
    def difference(rows):
        h=[float(ratings[r['id']]['total_mean']) for r in rows]; b=[float(paired['B'][r['id']]['total']) for r in rows]; c=[float(paired['C'][r['id']]['total']) for r in rows]
        x,y=spearman(h,b),spearman(h,c)
        return x-y if x is not None and y is not None else None
    diff_ci=cluster_bootstrap(obs,difference)['ci95']
    b,c=methods['B']['spearman'],methods['C']['spearman']
    report={'input_paths':{'ratings':str(ratings_path),'key':str(key_path),'judges':str(judge_path),'rater_csvs':[str(p) for p in rater_files]},'pack_hash':pack_hash,'methods':methods,'human_baseline':{'per_rater':human_baselines,'median':human_median,'range':[min(x['spearman'] for x in human_baselines),max(x['spearman'] for x in human_baselines)] if human_baselines else None},'b_minus_c_ci95':diff_ci,'decision':classify(b,c,human_median,methods['B']['spearman_ci95'],diff_ci,methods['B']['order_of_kind_means']),'neighbor_at_least_b':c>=b if c is not None and b is not None else None,'limitations':'test 표본이 작으면 신뢰구간이 넓고, 얼굴 ID 오인 및 단일 LaPa 데이터셋에 따른 편향이 남을 수 있습니다.','issues':issues}
    output=Path(output); output.parent.mkdir(parents=True,exist_ok=True); output.write_text(json.dumps(report,ensure_ascii=False,indent=2,allow_nan=False),encoding='utf8')
    print(f"{output}: {report['decision']}")
    return report


def main():
    p=argparse.ArgumentParser(); p.add_argument('--ratings',type=Path,default=DATA/'results/ratings.csv'); p.add_argument('--key',type=Path,default=DATA/'pack/key.csv'); p.add_argument('--rubric',type=Path,default=HERE/'rubric.json'); p.add_argument('--judge',type=Path,default=DATA/'results/judge_results.csv'); p.add_argument('--raters',nargs='+',type=Path,required=True); p.add_argument('--output',type=Path,default=DATA/'results/judge_summary.json'); a=p.parse_args(); compare(a.ratings,a.key,a.rubric,a.judge,a.raters,a.output)


if __name__=='__main__': main()

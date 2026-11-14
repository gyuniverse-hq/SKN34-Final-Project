"""Post-lock descriptive audit; does not change predictions or preregistration."""
from pathlib import Path
import os
from zipfile import ZipFile
from collections import Counter
import csv, io, json, statistics, hashlib, itertools
from datetime import datetime, timezone

BASE = Path(__file__).resolve().parents[1] / 'data' / 'lip_teacher_20261113'

RATERS=['R1','R4','R5']; COLS=[f'q{q}_{i}' for q in range(1,6) for i in range(1,6)]
def read(p):return json.loads(p.read_text(encoding='utf-8'))
def value(x):return int(x) if str(x) in ['0','1'] else x
def qscore(checks,q):
    answers=[value(checks[f'q{q}_{i}']) for i in range(1,6)]
    applicable=[a for a in answers if a!='na']
    return sum(applicable)/len(applicable)
def exact_score(checks):return sum(qscore(checks,q) for q in range(1,6))
def mean(vals):return statistics.mean(vals) if vals else None
def rankcorr(a,b):
    def rank(values):
        levels={v:mean([i+1 for i,x in enumerate(sorted(values)) if x==v]) for v in set(values)}
        return [levels[v] for v in values]
    return statistics.correlation(rank(a),rank(b))

def main():
    SOURCE = Path(os.environ["LIP_RUBRIC_SOURCE"])
    prediction=read(BASE/'predictions.locked.json');truth=read(BASE/'private/truth.json');result=read(BASE/'results/evaluation.json')
    lookup={r['alias']:r for r in prediction['predictions']}
    rows=[r for r in truth if r['split']=='test']
    source={}
    for rater in RATERS:
        with (SOURCE/f'{rater}_ratings.csv').open(encoding='utf-8-sig',newline='') as f:
            source[rater]={r['image_id']:r for r in csv.DictReader(f)}
    errors=[];item_summary=[]
    for r in truth:
        for who in RATERS:
            raw=source[who][r['image_id']];stored=r['raters'][who]
            if any(value(raw[c])!=stored['checks'][c] for c in COLS):errors.append([r['alias'],who,'source check mismatch'])
            if abs(exact_score(raw)-stored['total'])>1e-12:errors.append([r['alias'],who,'source total mismatch'])
        expected=mean([exact_score(source[w][r['image_id']]) for w in RATERS])
        if abs(expected-r['total_mean'])>1e-12:errors.append([r['alias'],'human mean mismatch'])
        if r['split']=='test':item_summary.append({'alias':r['alias'],'human':expected,'teacher':exact_score(lookup[r['alias']]['checks']),
                                                'human_questions':[mean([qscore(source[w][r['image_id']],q) for w in RATERS]) for q in range(1,6)]})
    summaries={};na_disagreements=[]
    for name,subset in [('all_test',rows),('render_only',[r for r in rows if r['kind']=='render'])]:
        majority={c:[] for c in COLS}; matched={c:[] for c in COLS}; na=[]
        for r in subset:
            pred=lookup[r['alias']]['checks']; votes={c:[value(source[w][r['image_id']][c]) for w in RATERS] for c in COLS}
            for c in COLS:
                counts=Counter(votes[c]);mode=counts.most_common()
                if len(mode)==1 or mode[0][1]>mode[1][1]:majority[c].append(pred[c]==mode[0][0])
                if name=='all_test' and 'na' in votes[c] and any(pred[c]!=a for a in votes[c]):
                    na_disagreements.append({'alias':r['alias'],'check':c,'teacher':pred[c],'human_votes':dict(zip(RATERS,votes[c]))})
                for held in range(3):
                    other=[a for j,a in enumerate(votes[c]) if j!=held]
                    if other[0]!=other[1]:continue
                    reference=other[0]; own=votes[c][held]
                    if reference=='na':na.append((pred[c]=='na',own=='na'))
                    else:matched[c].append((pred[c]==reference,own==reference,reference==1))
        perquestion={}
        for q in range(1,6):
            columns=[f'q{q}_{i}' for i in range(1,6)]
            counts=[a for c in columns for a in matched[c]]
            perquestion[f'q{q}']={'teacher_macro':mean([mean([a for a,b,z in matched[c]]) for c in columns if matched[c]]),
              'human_macro':mean([mean([b for a,b,z in matched[c]]) for c in columns if matched[c]]),
              'binary_trials':len(counts),'teacher_correct':sum(a for a,b,z in counts),'human_correct':sum(b for a,b,z in counts),
              'teacher_micro':mean([a for a,b,z in counts]),'human_micro':mean([b for a,b,z in counts]),
              'majority_macro':mean([mean(majority[c]) for c in columns if majority[c]]),
              'majority_support':sum(len(majority[c]) for c in columns)}
        summary={'checklist_majority_macro':mean([mean(v) for v in majority.values() if v]),
         'matched_teacher_macro':mean([mean([a for a,b,z in v]) for v in matched.values() if v]),
         'matched_human_macro':mean([mean([b for a,b,z in v]) for v in matched.values() if v]),
         'all_yes_matched_macro_descriptive_only':mean([mean([z for a,b,z in v]) for v in matched.values() if v]),
         'matched_binary_support':sum(len(v) for v in matched.values()),'na_consensus_support':len(na),
         'na_teacher_correct':sum(a for a,b in na),'na_human_correct':sum(b for a,b in na),'per_question':perquestion}
        expected=result[name]
        teacher_totals=[exact_score(lookup[r['alias']]['checks']) for r in subset]
        human_totals=[mean([exact_score(source[w][r['image_id']]) for w in RATERS]) for r in subset]
        independently_computed={'mae':mean([abs(a-b) for a,b in zip(teacher_totals,human_totals)]),
                               'spearman':rankcorr(teacher_totals,human_totals)}
        for key,v in independently_computed.items():
            if abs(v-expected[key]['estimate'])>1e-12:errors.append([name,key,'independent score metric mismatch'])
        summary['independent_total_metrics']=independently_computed
        for key,target in [('checklist_majority_macro',expected['majority']['macro']),('matched_teacher_macro',expected['matched']['teacher_macro']),('matched_human_macro',expected['matched']['human_macro'])]:
            if abs(summary[key]-target)>1e-12:errors.append([name,key,'metric mismatch'])
        summaries[name]=summary
    calibration=read(BASE/'calibration/pool_labels.json');calibration_differences=[]
    for r in calibration:
        checks=[{c:r['votes'][c][i] for c in COLS} for i in range(3)]
        correctq=[mean([qscore(c,q) for c in checks]) for q in range(1,6)]
        correcttotal=mean([exact_score(c) for c in checks])
        if any(abs(a-b)>1e-12 for a,b in zip(correctq,r['qmeans'])) or abs(correcttotal-r['total'])>1e-12:
            calibration_differences.append({'alias':r['alias'],'displayed_total':r['total'],'correct_total':correcttotal,
              'displayed_qmeans':r['qmeans'],'correct_qmeans':correctq})
    lock=read(BASE/'prediction_lock.json')
    pairs=[]
    for a,b in itertools.combinations(rows,2):
        if a['kind']!=b['kind'] or a['kind']!='render' or a['face_id']!=b['face_id']:continue
        hd=b['total_mean']-a['total_mean'];td=exact_score(lookup[b['alias']]['checks'])-exact_score(lookup[a['alias']]['checks'])
        sign=lambda x:0 if abs(x)<1e-9 else 1 if x>0 else -1
        pairs.append({'left':a['alias'],'right':b['alias'],'human_difference_right_minus_left':hd,'teacher_difference_right_minus_left':td,
                      'human_abs_gap':abs(hd),'same_order':sign(hd)==sign(td),'teacher_tie_only':sign(td)==0 and sign(hd)!=0,
                      'left_finish':a['finish'],'right_finish':b['finish']})
    notes={'audited_utc':datetime.now(timezone.utc).isoformat(),'post_preregistration_descriptive_audit':True,
      'source_originals_audited':50,'raters':RATERS,'mismatches':errors,'numerical_evaluation_passed':not errors,
      'prediction_hash_intact':hashlib.sha256((BASE/'predictions.locked.json').read_bytes()).hexdigest()==lock['sha256'],
      'protocol_hash_intact':hashlib.sha256((BASE/'protocol.json').read_bytes()).hexdigest()==lock['protocol_sha256'],
      'summaries':summaries,'na_disagreement_cases':na_disagreements,'per_image_recomputed':item_summary,
      'calibration_display_differences':calibration_differences,
      'same_face_render_pairs_descriptive':{'n':len(pairs),'same_order':sum(p['same_order'] for p in pairs),'pairs':pairs,
       'warning':'Post-hoc descriptive; derived from individual score means, not direct human pairwise preference. Different shades/finishes, not controlled renderer versions. Tiny sample and small human gaps; no historical0.943 comparison.'},
      'audit_explanation':['Human total is mean of3rater totals, each sums5within-rater NA-excluded question averages. No pooled denominator substituted in test scoring.',
      'Matched binary baseline uses same other2-agree cases for both teacher and held-out human; denominator excludes other2 disagreement/NA but held-out NA is incorrect on binary consensus.',
      'Unanimous binary checks contribute3held-out trials;2:1binary splits contribute1trial. Support counts are correlated trials, not independent labels; bootstrap unit remains face.',
      'Original gate is non-tautological: independent visual predictions and human labels; matched comparison is held-out rather than scored against self-inclusive consensus. Render-only rank CI fails and gate correctly returns advisory_only.',
      'Checklist-majority macro is separate from matched teacher-human comparison. Do not compare82.75% majority agreement to84.10% matched human baseline.',
      'Post-hoc per-question and always-yes comparisons are descriptive only and do not change the preregistered gate.',
      'Some calibration figures used pooled applicable-check averages for Q3. Record any display differences; do not alter existing predictions, and correct displays in future independent replication.']}
    (BASE/'audit_notes.json').write_text(json.dumps(notes,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({'numerical_evaluation_passed':not errors,'calibration_difference_count':len(calibration_differences),'na_disagreement_count':len(na_disagreements),'summaries':summaries},ensure_ascii=False))
if __name__=='__main__':main()

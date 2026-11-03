#!/usr/bin/env python3
"""VISHUE 1-A normalized MOCK contract evaluator (stdlib only).

NOT a direct VISHUE API client, not a Gold grader. The caller MUST first map
raw local-worktree API responses into normalized_predictions.jsonl. Mock
side-effect observations must be gathered independently from the application
state or test doubles; assistant claims do not count as observations.
"""
import argparse,csv,json,math,re,sys
from pathlib import Path

OUTCOMES={'PROPOSAL','NO_COMMAND','ERROR','CLARIFICATION','UNSUPPORTED'}
SUCCESS_CLAIM=re.compile(r'(적용했|바꿨|변경했|설정했)(?:어요|습니다|다)|적용\s*완료|변경\s*완료',re.I)

def read_jsonl(path):
    result=[]
    for n,line in enumerate(Path(path).read_text(encoding='utf8').splitlines(),1):
        if not line.strip():continue
        try:result.append(json.loads(line))
        except json.JSONDecodeError as e:raise ValueError(f'{path}:{n}: invalid JSON: {e}') from e
    return result

def one(c,p):
    issues=[]
    cid=c['id']
    if not isinstance(p,dict):return 'FAIL',['prediction_not_object']
    for key in ('id','outcome','commands','claims_applied','response_schema_valid','side_effects','test_mode'):
        if key not in p:issues.append('missing:'+key)
    if issues:return 'FAIL',issues
    if p['id']!=cid:issues.append('id_mismatch')
    if p['test_mode']!='MOCK':issues.append('not_mock_mode')
    if p['outcome'] not in OUTCOMES:issues.append('unknown_outcome')
    if not isinstance(p['commands'],list):issues.append('commands_not_array')
    if not isinstance(p['claims_applied'],bool):issues.append('claims_applied_not_boolean')
    if p['response_schema_valid'] is not True:issues.append('response_schema_invalid_or_unverified')
    if not isinstance(p['side_effects'],dict):issues.append('side_effects_not_object')
    if issues:return 'FAIL',issues
    exp=c['expected']
    if p['claims_applied'] is True:issues.append('claims_applied_without_ack')
    answer=p.get('answer','')
    if isinstance(answer,str) and SUCCESS_CLAIM.search(answer):issues.append('answer_claims_applied')
    if exp.get('kind')=='PROPOSAL':
        if p['outcome']!='PROPOSAL':issues.append('proposal_missing')
        if len(p['commands'])!=1:issues.append('command_count_not_one')
        else:
            given=p['commands'][0];gold=exp['commands'][0]
            if not isinstance(given,dict):issues.append('command_not_object')
            else:
                for key in ('targetZone','action','expectedStateVersion'):
                    if given.get(key)!=gold[key]:issues.append('command_'+key+'_mismatch')
                value=given.get('value')
                if isinstance(value,bool) or not isinstance(value,(int,float)) or not math.isfinite(value) or not math.isclose(value,gold['value'],abs_tol=1e-9,rel_tol=0):
                    issues.append('command_value_mismatch')
    elif exp.get('kind')=='NO_COMMAND':
        if len(p['commands'])!=0:issues.append('unwanted_command')
        if p['outcome']=='PROPOSAL':issues.append('unexpected_proposal')
    else:issues.append('unsupported_expected_kind')
    if cid.startswith('E-AR-07') and p.get('injection_tested') is not True:
        # Since the case tests a malformed model output, no injection means the case was not exercised.
        return 'NOT_EXECUTED',['fake_model_injection_missing']+issues
    # An assertion about no side effects requires an independent observation.
    obs=p['side_effects']
    if obs.get('observed') is not True:
        if issues:return 'FAIL',issues
        return 'CONTRACT_ONLY_OBSERVATION_MISSING',['side_effects_not_independently_observed']
    if obs.get('ar_state_changed') is not False:issues.append('ar_state_changed_or_unknown')
    if not isinstance(obs.get('source'),str) or not obs.get('source'):
        issues.append('side_effect_provenance_missing')
    return ('FAIL' if issues else 'MOCK_CONTRACT_OK_GOLD_PENDING'),issues

def main(argv=None):
    ap=argparse.ArgumentParser()
    ap.add_argument('--cases',required=True)
    ap.add_argument('--predictions',required=True)
    ap.add_argument('--out',required=True)
    args=ap.parse_args(argv)
    cases=read_jsonl(args.cases); predictions=read_jsonl(args.predictions)
    case_ids=[x['id'] for x in cases];pred_ids=[x.get('id') for x in predictions]
    if len(set(case_ids))!=len(case_ids):raise ValueError('duplicate case ids')
    if len(set(pred_ids))!=len(pred_ids):raise ValueError('duplicate prediction ids')
    by_id={x['id']:x for x in predictions}
    results=[]
    for c in cases:
        if c['id'] not in by_id:status,reasons='NOT_EXECUTED',['missing_prediction']
        else:status,reasons=one(c,by_id[c['id']])
        results.append({'id':c['id'],'status':status,'reasons':';'.join(reasons),'gold_approved':False,'real_llm_run':False,'real_ar_run':False})
    for extra in set(pred_ids)-set(case_ids):
        results.append({'id':extra,'status':'FAIL','reasons':'unexpected_prediction_id','gold_approved':False,'real_llm_run':False,'real_ar_run':False})
    Path(args.out).parent.mkdir(parents=True,exist_ok=True)
    with open(args.out,'w',encoding='utf-8-sig',newline='') as f:
        writer=csv.DictWriter(f,fieldnames=results[0].keys());writer.writeheader();writer.writerows(results)
    stats={s:sum(x['status']==s for x in results) for s in sorted(set(x['status'] for x in results))}
    summary={'total_cases':len(cases),'results':stats,'overall':'ONLY_MOCK_CONTRACT_EVALUATION',
             'human_gold_approved':0,'real_llm_runs':0,'real_ar_runs':0,
             'warning':'MOCK_CONTRACT_OK_GOLD_PENDING is NOT a real LLM quality pass.'}
    Path(args.out).with_suffix('.summary.json').write_text(json.dumps(summary,indent=2,ensure_ascii=False)+'\n',encoding='utf8')
    print(json.dumps(summary,ensure_ascii=False,indent=2))
    return 1 if any(x['status'] in ('FAIL','NOT_EXECUTED','CONTRACT_ONLY_OBSERVATION_MISSING') for x in results) else 0

if __name__=='__main__':sys.exit(main())

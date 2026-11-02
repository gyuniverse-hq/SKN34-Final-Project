#!/usr/bin/env python3
"""Check handoff integrity without fetching or executing any VISHUE service."""
import collections,hashlib,json
from pathlib import Path
D=Path(__file__).resolve().parent
read=lambda p:[json.loads(x) for x in (D/p).read_text(encoding='utf8').splitlines() if x.strip()]
original=read('resolved_inputs_359_원본v13.jsonl')
patched=read('resolved_inputs_359_fixture_patch.jsonl')
cum=read('누적검수_359_원본보존.jsonl')
changes=json.loads((D/'fixture_patch_audit.json').read_text(encoding='utf8'))
world=json.loads((D/'fixtures_world_v1.3.json').read_text(encoding='utf8'))
inputs=read('1A_mock_contract_cases_11.jsonl')
assert len(original)==len(patched)==len(cum)==359
assert [x['case_id'] for x in original]==[x['case_id'] for x in patched]==[x['case_id'] for x in cum]
assert len({x['case_id'] for x in cum})==359
assert collections.Counter(x['review_status'] for x in cum)=={'APPROVAL_CANDIDATE':25,'NEEDS_POLICY':10,'NOT_REVIEWED':324}
assert all(not x['approved_gold_assertions'] for x in cum)
changed=[]
for a,b in zip(original,patched):
  if a==b:continue
  assert {k:v for k,v in a.items() if k!='test_input'}=={k:v for k,v in b.items() if k!='test_input'}
  assert {k:v for k,v in a['test_input'].items() if k!='context'}=={k:v for k,v in b['test_input'].items() if k!='context'}
  changed.append(b['case_id'])
assert len(changed)==8 and set(changed)=={x['case_id'] for x in changes}
product_shades={x['id']:set(x['shades']) for x in world['products']}
invalid=[]
for x in patched:
  c=x['test_input']['context'];p=c.get('selectedProductId');s=c.get('selectedShadeId')
  if p and s and s not in product_shades.get(p,set()):invalid.append(x['case_id'])
assert set(invalid)=={'E-I-05-E','E-XC08'}
assert world['arStates']['A_UNDO_READY']['stateVersion']==4
assert world['arStates']['A_UNDO_READY']['layers']['lip']['intensity']==0.5
assert world['meta']['productionGoldApproved'] is False
assert len(inputs)==11 and len({x['id'] for x in inputs})==11
summary={'validated':True,'original_cases':len(original),'unchanged_review_records':len(cum),
 'context_patched':len(changed),'context_patch_ids':changed,
 'expected_negative_fk':invalid,'unexpected_fk_errors':0,'1a_mock_candidates':len(inputs),
 'review_states':dict(collections.Counter(x['review_status'] for x in cum)),
 'gold_approved':0,'real_llm_test_count':0,'real_ar_test_count':0,
 'source_cumulative_sha256':hashlib.sha256((D/'누적검수_359_원본보존.jsonl').read_bytes()).hexdigest()}
(D/'self_validation.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2)+'\n',encoding='utf8')
print(json.dumps(summary,ensure_ascii=False,indent=2))

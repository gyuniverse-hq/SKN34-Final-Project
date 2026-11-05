#!/usr/bin/env python3
"""Optional import of the *actual* 842 utterance strings from a source workbook/CSV/JSONL.
Outputs candidate lexical links; never marks semantic equivalence as human-approved.
For XLSX, requires artifact_tool, matching the spreadsheet handling contract.
"""
import argparse,csv,json,re,unicodedata,math,collections
from pathlib import Path
HERE=Path(__file__).resolve().parent

def jl(p):return [json.loads(l) for l in Path(p).read_text(encoding='utf8').splitlines() if l.strip()]
def dumpjl(p,rows):Path(p).write_text(''.join(json.dumps(r,ensure_ascii=False)+'\n' for r in rows),encoding='utf8')
def clean(x):return re.sub(r'\s+',' ',unicodedata.normalize('NFKC',str(x or '')).strip()).lower()
def sim(a,b):
    a=clean(a);b=clean(b)
    if not a or not b:return 0.0
    if a==b:return 1.0
    A=set(a[i:i+2] for i in range(max(0,len(a)-1)));B=set(b[i:i+2] for i in range(max(0,len(b)-1)))
    return 2*len(A&B)/max(1,len(A)+len(B))
def first(r,keys):
    for k in keys:
        if r.get(k) not in (None,''):return r[k]
    return None

def source_rows(path):
    path=Path(path);typ=path.suffix.lower()
    if typ=='.jsonl':
        data=jl(path)
    elif typ=='.csv':
        with path.open(encoding='utf-8-sig',newline='') as fp:data=list(csv.DictReader(fp))
    elif typ=='.xlsx':
        from artifact_tool import Blob,SpreadsheetFile
        wb=SpreadsheetFile.import_xlsx(Blob.load(str(path)))
        sh=wb.worksheets.get_item('04_발화842')
        cells=sh.get_range('A1:N870').values
        hidx=next((i for i,row in enumerate(cells[:10]) if any('발화 ID' in str(v) for v in row if v is not None)),None)
        if hidx is None:raise ValueError('Cannot find the U842 header row')
        head=[str(x or '') for x in cells[hidx]]
        data=[dict(zip(head,row)) for row in cells[hidx+1:] if any(v not in (None,'') for v in row)]
    else:raise ValueError('Use .xlsx, .csv or .jsonl source')
    out=[]
    for r in data:
        uid=first(r,['기존 발화 ID','ID','utterance_id','발화 ID'])
        tx=first(r,['합성 사용자 발화','사용자발화','사용자 발화','original_text','utterance','text'])
        if uid is None and tx is None:continue
        if not uid or not tx:raise ValueError(f'Missing source utterance ID/text: {r}')
        out.append({'utterance_id':str(uid).strip(),'original_text':str(tx),'source_category':first(r,['대분류','category']),
                  'source_intent':first(r,['세부 의도','세부의도','intent'])})
    exp=[f'U{i:04d}' for i in range(1,843)]
    actual=[r['utterance_id'] for r in out]
    if actual!=exp:raise ValueError(f'Source must contain U0001..U0842 in order, got {len(out)} rows / {len(set(actual))} unique')
    return out

def run(source, cases, uindex):
    rows=source_rows(source)
    byid={x['utterance_id']:x for x in uindex}
    candidates=collections.defaultdict(list)
    for c in cases:candidates[c['intent_id']].append(c)
    all_exact=collections.defaultdict(list)
    for c in cases:all_exact[clean(c['utterance'])].append(c['id'])
    result=[];stats=collections.Counter()
    for r in rows:
        uid=r['utterance_id'];prev=byid[uid];it=prev['intent_id'];text=r['original_text'];li=candidates[it]
        scored=sorted(((sim(text,c['utterance']),c['id'],c['utterance']) for c in li),reverse=True)
        hit=all_exact.get(clean(text),[])
        if hit:rel='EXACT_TEXT_MATCH_NOT_HUMAN_SEMANTIC_APPROVAL'
        elif scored and scored[0][0]>=0.68:rel='HIGH_LEXICAL_SIMILARITY_REVIEW_REQUIRED'
        elif scored and scored[0][0]>=0.40:rel='PARTIAL_LEXICAL_SIMILARITY_REVIEW_REQUIRED'
        else:rel='SAME_INTENT_ONLY_REVIEW_REQUIRED'
        result.append({'utterance_id':uid,'original_text':text,'intent_id':it,'category':prev['category'],
            'intent_name':prev['intent_name'],'candidate_cases':[{'case_id':cid,'score':round(score,4),'case_utterance':utt} for score,cid,utt in scored[:3]],
            'exact_case_ids':hit,'link_relation':rel,'semantic_human_review':'NOT_REVIEWED','reviewer':None,'decision':None,
            'review_note':None,'source_verified':'ACTUAL_SOURCE_TEXT_IMPORTED','source_path_label':Path(source).name})
        stats[rel]+=1
    return result,dict(stats)

def main():
    ap=argparse.ArgumentParser();ap.add_argument('--source',required=True,help='Actual original U842 xlsx/csv/jsonl (not the v1.2 index)')
    ap.add_argument('--cases',default=str(HERE/'cases_v1.3.jsonl'))
    ap.add_argument('--index',default=str(HERE/'source_U842_link_review_v1.3.jsonl'))
    ap.add_argument('--out',default=str(HERE/'source_U842_fulltext_review_v1.3.jsonl'))
    args=ap.parse_args()
    res,stats=run(args.source,jl(args.cases),jl(args.index));dumpjl(args.out,res)
    report={'source_file':Path(args.source).name,'total':len(res),'human_semantic_reviews_completed':0,'candidate_relation_counts':stats,
            'important':'Lexical matches are suggestions only and do not prove semantic coverage of a feature or test.'}
    Path(str(args.out)+'.report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf8')
    print(json.dumps(report,ensure_ascii=False))
if __name__=='__main__':main()

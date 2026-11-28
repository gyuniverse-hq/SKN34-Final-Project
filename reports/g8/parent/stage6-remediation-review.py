"""Seal observed Q/A and source identities; preserve intermediate failures."""
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
OUT = ROOT / 'reports/g8/parent'
P = 'stage6-remediation-'

def read(name):
    return json.loads((OUT / (P + name)).read_text(encoding='utf-8'))

def write(name, value):
    (OUT / (P + name)).write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')

def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()

rows = [json.loads(x) for x in (OUT / (P + 'app-turns.jsonl')).read_text(encoding='utf-8').splitlines()]
assert len(rows) == 19
assert all(read('pg-review.json')['checks'].values())
assert rows[15]['parent']['tasks'][0]['goal'] == 'skin'
assert len(rows[15]['parent']['tasks']) == 1
assert len(rows[16]['modelCalls']) == 2
assert all(c['body']['maxPriceKRW'] == 18000 for c in rows[16]['catalogCalls'])
assert rows[17]['catalogCalls'][0]['body']['query'] == '립펜슬'
assert rows[17]['catalogCalls'][0]['body']['maxPriceKRW'] == 15000
assert rows[18]['errorCode'] == 'request_interrupted'
assert rows[17]['startedAt'] < rows[18]['at']
assert len(rows[8]['modelCalls']) == len(rows[8]['catalogCalls']) == 0
assert rows[7]['parent']['pendingQuestions']

baseline = read('baseline.json')
scope = read('scope.json')
allowed = set(scope['code'] + scope['management'])
outside = [x['path'] for x in baseline['source'] if x['path'] not in allowed and digest(ROOT/x['path']) != x['sha256']]
assert not outside, outside
final_runtime = json.loads((OUT / rows[15]['sourceSnapshot']).read_text(encoding='utf-8'))
assert all(digest(ROOT/x['path']) == x['sha256'] for x in final_runtime)
code = [{'path': name, 'sha256': digest(ROOT/name), 'text': (ROOT/name).read_text(encoding='utf-8')} for name in scope['code']]
write('uncommitted-source.json', code)
source_paths = sorted(set(x['path'] for x in baseline['source']) | set(scope['code']))
source_paths = [x for x in source_paths if x not in scope['management']]
sources = [{'path': name, 'sha256': digest(ROOT/name)} for name in source_paths]
write('final-sources.json', sources)
write('scope-check.json', {'baselineCoveredFiles': len(baseline['source']), 'outsideApprovedChanges': outside, 'approvedCodeFiles': len(code), 'missingInitialByteBaseline': ['backend/chatbot/tests/test_supervisor.py', 'backend/chatbot/tests/test_style_recipe.py'], 'provenance': 'baseline-extra.json preserves prior app runtime hashes; missing initial test bytes are not claimed as captured'})

dialogue = []
for i, r in sorted(enumerate(rows), key=lambda pair: pair[1]['startedAt']):
    dialogue.append(f"ROW {i}\nSTART {r['startedAt']}\nSOURCE {r['sourceSnapshot']}\nMODEL configured=live actualGenerationHttp={len(r.get('modelCalls', []))} replay=0 mock=0\nCATALOG actualReads={len(r.get('catalogCalls', []))}\nUSER: {r['utterance']}\n" + ('ASSISTANT: '+r['answer'] if 'answer' in r else 'NO FINAL ANSWER: '+r.get('errorCode', 'unknown')))
(OUT / (P + 'dialogue.txt')).write_text('\n\n'.join(dialogue)+'\n', encoding='utf-8')
review = {
    'at': datetime.now(timezone.utc).isoformat(),
    'policy': 'Main agent actual Aside web review replaces human semantic review by explicit user decision; not independent human or mobile-device certification.',
    'overall': 'F1-F4 scoped remediation verified; full gate NOT_CLOSED because actual recent-conversation restoration still hangs.',
    'stage': '⑤ existing defects repaired; ⑥ targeted integration in progress; ⑤ final closure withheld for bundle 5 actual restore',
    'cases': [
        {'id':'F1/N01', 'rows':[14,15,16], 'result':'PASS ownership and answer+condition workflow; knowledge coverage PARTIAL', 'reason':'One typed skin task owns original explanation and suitable products. Actual clarification answer plus budget accepted; G5 explanation and four exact options, budget-only update returns two options without G5. No claim of individualized diagnosis or product efficacy.'},
        {'id':'F1/F2/N02', 'rows':[4,5,6,7], 'result':'PASS scoped defects; original full owned-lip workflow PARTIAL', 'reason':'Seven general guidance steps contain no None. Missing palette answer and budget accepted; Bbia exact sale option under 20k returned, Romand ownership question preserved. General guide is not verified video technique; full owned-lip substitution not established in this run.'},
        {'id':'F3/B01', 'rows':[8], 'result':'PASS protected reply and execution boundary', 'reason':'Relevant AR/memory instructions, no model or Catalog calls, no AR execution or memory write. Actual same-requestId browser replay NOT_RUN.'},
        {'id':'F3/single-read-entry', 'rows':[17], 'result':'PASS', 'reason':'Typed initial product task, actual Catalog query lip-pencil and maxPriceKRW15000. Partial candidate coverage is preserved, not full catalog completion.'},
        {'id':'F4/cancel-replacement', 'rows':[17,18], 'result':'PASS actual model-overlap replacement and final-save guard', 'reason':'Cancel POST200 while G5 running, new lip search starts before old request ends and succeeds without503. Old request ends409/request_interrupted. Actual PG stores only replacement pair and current summary. Durable checkpoint locking separately reproduced/fixed using real PG and controlled mock specialist.'},
        {'id':'E01', 'rows':[9,10,11], 'result':'PASS tested partial-success/selective-retry semantics', 'reason':'Validation-only Style UpstreamError, actual product comparison preserved; after disabling fault, style-only Catalog reads and honest no-match. Not a natural upstream HTTP503 or positive look recommendation.'},
        {'id':'app-recent-restore', 'rows':[], 'result':'FAIL', 'reason':'After full web navigation, selecting new replacement room and current-run N02 room leaves recent-list loading. Repeated direct REPL snapshots show loading; no corresponding detail GET observed at the Chat server. Exact pre-request wait location not instrumented/proven. PG saved data is correct. Do not claim restored cards/detail PASS. Frontend product files not modified in this 17-file scope.'}
    ],
    'intermediateFailures': [{'rows':[2], 'reason':'Budget update unnecessarily reran G5 before task-scoped delta fix'}, {'rows':[12,13], 'reason':'Situation answer split into independent product search and skin knowledge-only plan; fixed before rows14-16'}],
    'sourcePolicy':'Each raw turn retains immutable runtime manifest; earlier-source successes are not relabelled final-source executions. Rows14-18 use final runtime. Current final source capsule includes all 15 approved code/test files; optional import deletion separately approved.',
    'notRun':['full original N02 owned-lip application and all alternatives in final live environment', 'full ingredient-positive adoption/retention/removal integration in this run', 'same-requestId replay with actual browser auth', 'restored-card detail due restore failure', 'Android/iOS touch, face/camera/AR, voice, other languages', 'global dataset/provider snapshot pinning', 'SLO/load acceptance', 'PR/commit/push/deploy'],
    'next':'Finish the existing bundle5 recent-restore defect with a separately reviewed exact frontend scope, then remaining original 14-capability/12-scenario integration matrix; no new product feature scope.'
}
write('review.json', review)
write('ui.json', {
    'browser':'Aside direct REPL; actual existing Supabase login/G7 settings',
    'viewport':{'width':390,'height':844,'scope':'web, not physical device'},
    'freshN02SaleDetail':{'result':'PASS','row':7,'url':'http://localhost:19836/product/oy-a000000162667?optionId=A000000162667-012&requireShade=1','optionName':'[단품] 07 웜 베이지','referencePriceKRW':17000,'asOf':'2026-10-28T10:06:07','optionCheckoutRestricted':True},
    'stopReplacement':{'cancelHttp':200,'oldLateHttp':409,'replacementHttp':200,'replacementQuery':'립펜슬','maxPriceKRW':15000,'oldInternalHttpMayContinue':True},
    'recentRestore':{'result':'FAIL','observed':'상담을 불러오는 중이에요.','attempts':['latest replacement room','current-run N02 room after full navigation'],'serverDetailRequestObserved':False,'rawCaptureCaveat':'One-shot attachment snapshots can show pre-loading state. Persistent REPL repeatedly showed loading. UI cause not proven; no successful restore inferred from an enabled-list snapshot.'},
    'screenshots':'NOT_SAVED; actual DOM/server/PG evidence only','writes':{'AR':False,'cart':False,'checkout':False,'memoryConfirmation':False}
})
print('Built 19 verbatim turns, source capsule and scoped review; app restore remains FAIL')

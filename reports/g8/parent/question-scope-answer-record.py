"""Freeze tested WIP and execution evidence without treating planned commands as results."""
import hashlib
from collections import Counter
import json
from pathlib import Path
import subprocess
import xml.etree.ElementTree as ET
from datetime import datetime, timezone

ROOT=Path(__file__).resolve().parents[3]
OUT=ROOT/'reports/g8/parent'
previous=json.loads((OUT/'stage5-closeout-record.json').read_text(encoding='utf-8'))
paths={e['path'] for e in previous['sourceSha256']}
paths.update(['backend/chatbot/app/services/knowledge_service.py',
    'backend/chatbot/tests/test_knowledge_service.py','lib/api.ts',
    '__tests__/chatSessionApi.test.ts','docs/ai-design/G8-WORKLOG.md',
    'docs/ai-design/G8-IMPLEMENTATION-SPEC.md'])
def digest(p):return hashlib.sha256(p.read_bytes()).hexdigest()
sources=[{'path':p,'sha256':digest(ROOT/p)} for p in sorted(paths)]
diff=subprocess.check_output(['git','diff','--binary','HEAD'],cwd=ROOT)
(OUT/'question-scope-answer-source.diff').write_bytes(diff)
new=[]
for path in sorted(paths):
    tracked=subprocess.run(['git','ls-files','--error-unmatch',path],cwd=ROOT,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL).returncode==0
    if not tracked:new.append({'path':path,'content':(ROOT/path).read_text(encoding='utf-8')})
(OUT/'question-scope-answer-new-sources.json').write_text(json.dumps(new,ensure_ascii=False,indent=2),encoding='utf-8')
def xml(name):
    p=OUT/name
    if not p.exists():return {'result':'NOT_RUN','evidence':name}
    suites=list(ET.parse(p).iter('testsuite'))
    fields={k:sum(float(s.get(k,0)) for s in suites) for k in ['tests','failures','errors','skipped','time']}
    return {'result':'PASS' if not(fields['failures'] or fields['errors']) else 'FAIL',
            'evidence':name,**fields,'timestamps':[s.get('timestamp') for s in suites]}
turnfile=OUT/'question-scope-answer-app-turns.jsonl'
turns=[json.loads(x) for x in turnfile.read_text(encoding='utf-8').splitlines()] if turnfile.exists() else []
events=[json.loads(x) for x in (OUT/'question-scope-answer-model-events.jsonl').read_text(encoding='utf-8').splitlines()]
g5=[json.loads(x) for x in (OUT/'question-scope-answer-g5-models.jsonl').read_text(encoding='utf-8').splitlines()]
rounds=[]
for p in sorted(OUT.glob('question-scope-answer-model*.json')):
    r=json.loads(p.read_text(encoding='utf-8'))
    if 'records' not in r:continue
    rounds.append({'path':p.name,'attempts':len(r['records']),
                   'reportedPass':sum(c['passed'] for c in r['records']),
                   'actualHttpStarts':r['actualHttpStarts'],'promptSha256':r['promptSha256'],
                   'schemaSha256':r['schemaSha256']})
artifacts=[{'path':p.relative_to(ROOT).as_posix(),'sha256':digest(p)}
    for p in sorted(OUT.glob('question-scope-answer-*')) if p.is_file()
    and p.name not in {'question-scope-answer-record.json','question-scope-answer-security.log'}]
record={'case':'G8-QUESTION-SCOPE-ANSWER-CONSISTENCY','at':datetime.now(timezone.utc).isoformat(),
    'stage':'⑤ / bundles 3,5,6; G8 overall not complete',
    'head':subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip(),
    'branch':'feat/compound-consultation','developLocalRef':previous['developLocalRef'],
    'remoteFreshnessChecked':False,'uncommitted':True,
    'sourceSha256':sources,'sourceDiff':'reports/g8/parent/question-scope-answer-source.diff',
    'untrackedSources':'reports/g8/parent/question-scope-answer-new-sources.json',
    'modelConfiguredMode':'live','replayTurns':0,'mockAppTurns':0,
    'modelRounds':rounds,'actualSyntheticModelHttpStarts':sum(r['actualHttpStarts'] for r in rounds),
    'uncertainHarnessCallCount':{'path':'question-scope-answer-model-pipeline.log',
        'status':'NOT_CAPTURED','reason':'fixture zone validation aborted after parent invocation before per-case/event persistence; no confirmed HTTP count inferred'},
    'actualAppModelHttpStarts':sum(e['event']=='start' for e in events),
    'actualG5ApiHttpStarts':sum(e['event']=='start' for e in g5),
    'actualAppRequestModels':dict(Counter(e.get('model') for e in events if e['event']=='start')),
    'actualG5ApiRequestModels':dict(Counter(e.get('model') for e in g5 if e['event']=='start')),
    'modelVersionLimit':'HTTP request model aliases recorded; provider-resolved immutable snapshot IDs were not captured',
    'data':{'catalog':'existing local API19834; serving code was not separately repinned this turn',
        'observedV4Version':'local-20261104-conservative-v1-20261123T111457291156Z',
        'actualPg':'vishue_g8_browser','pgRegression':'vishue_chat_test',
        'g5SourceVersions':'original evidence metadata retained in task payloads and PG evidence'},
    'appTurns':[{'turn':i+1,'utterance':r['utterance'],'sourceSnapshot':r.get('sourceSnapshot'),
        'modelMode':'live','actualModelHttpStarts':len(r.get('modelCalls',[])),
        'actualCatalogRequests':len(r.get('catalogCalls',[])),
        'errorCode':r.get('errorCode'),'summary':r.get('consultation'),
        'pendingQuestions':len((r.get('parent') or {}).get('pendingQuestions',[]))}
        for i,r in enumerate(turns)],
    'validation':{'backendMock':xml('question-scope-answer-backend-verified.xml'),
        'actualPgMockModel':xml('question-scope-answer-pg-final.xml')},
    'appContractTests':{'passed':44,'suites':2,'evidence':'question-scope-answer-app-final-clean.log',
                        'modelMode':'mock'},
    'actualPgInvariantEvidence':'question-scope-answer-pg-invariants.json',
    'remainingStage5Defects':['numeric result show over-clarification',
        'explicit lip-pencil kind re-clarified before Catalog; no lookup executed'],
    'notRun':['full G8 evaluation','mobile touch QA','actual cancellation replay in this scope',
              'new screenshot artifact','human review'],
    'security':{'status':'PENDING','scanner':'8.30.1','ignore':'empty'},
    'failuresPreserved':True,'commitPushPr':False,'artifactSha256':artifacts}
(OUT/'question-scope-answer-record.json').write_text(json.dumps(record,ensure_ascii=False,indent=2),encoding='utf-8')
print('Recorded',len(sources),'source hashes;',len(artifacts),'artifacts;',len(turns),'app turns')

"""Finalize only this approved evidence set; never prints credentials or rewrites history."""
import hashlib,importlib.util,json,subprocess,sys,xml.etree.ElementTree as ET
from datetime import datetime,timezone
from pathlib import Path
ROOT=Path(__file__).resolve().parents[3];OUT=ROOT/'reports/g8/parent';PREFIX='stage5-three-item-'

def digest(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def manifest(paths):return [{'path':p.relative_to(ROOT).as_posix(),'sha256':digest(p)} for p in paths]

baseline=json.loads((OUT/(PREFIX+'baseline.json')).read_text(encoding='utf-8'))
changed=[e['path'] for e in baseline['source'] if digest(ROOT/e['path'])!=e['sha256']]
allowed={'backend/chatbot/'+p for p in [
'app/schemas/consultation_parent.py','app/schemas/consultation_task.py',
'app/services/consultation_intent_service.py','app/services/consultation_parent_graph.py',
'app/services/product_search_contract.py','app/services/beauty_consultation_service.py',
'app/services/knowledge_service.py','app/services/compound_consultation_service.py',
'tests/test_g8_consultation_intent.py','tests/test_g8_consultation_parent.py',
'tests/test_product_search_contract.py','tests/test_g8_compound_consultation.py',
'tests/test_knowledge_service.py','tests/test_g7_conversation_api_pg.py']}
assert set(changed)<=allowed, 'Source outside approved scope changed'
assert subprocess.check_output(['git','rev-parse','HEAD'],text=True).strip()==baseline['head'], 'HEAD changed during validation'
release=json.loads((OUT/(PREFIX+'release-sources.json')).read_text(encoding='utf-8'))
assert all(digest(ROOT/e['path'])==e['sha256'] for e in release)
app=json.loads((OUT/(PREFIX+'app-pg.json')).read_text(encoding='utf-8'))
assert app['result']=='PASS'
rows=[json.loads(x) for x in (OUT/(PREFIX+'app-turns.jsonl')).read_text(encoding='utf-8').splitlines()]
final_rows=[r for r in rows if json.loads((OUT/r['sourceSnapshot']).read_text(encoding='utf-8'))==release]
assert final_rows
live=json.loads((OUT/(PREFIX+'live.json')).read_text(encoding='utf-8'))
assert live['pass'] and len(live['cases'])==9
suite=ET.parse(OUT/(PREFIX+'backend.xml')).getroot()
assert sum(int(s.get('failures',0))+int(s.get('errors',0)) for s in suite.iter('testsuite'))==0
original=json.loads((OUT/'question-scope-answer-record.json').read_text(encoding='utf-8'))
paths=[ROOT/e['path'] for e in original['sourceSha256']]
paths=sorted(set(paths)|{ROOT/p for p in changed})
(OUT/(PREFIX+'source.diff')).write_bytes(subprocess.check_output(['git','diff','--binary','HEAD','--','backend/chatbot','app','hooks','lib','store','types','__tests__']))
(OUT/(PREFIX+'uncommitted-source.json')).write_text(json.dumps([{'path':p.relative_to(ROOT).as_posix(),'sha256':digest(p),'text':p.read_text(encoding='utf-8')} for p in paths],ensure_ascii=False),encoding='utf-8')
spec=importlib.util.spec_from_file_location('runtime',OUT/(PREFIX+'runtime.py'))
runtime=importlib.util.module_from_spec(spec);spec.loader.exec_module(runtime)
env=runtime.environment()
secrets=[v for k,v in env.items() if any(t in k for t in ['PASSWORD','API_KEY','INTERNAL_TOKEN']) and isinstance(v,str) and len(v)>=8]
from sqlalchemy.engine import make_url
import psycopg
for key in ['DATABASE_URL','CHAT_DATABASE_URL']:
 password=make_url(env[key]).password
 if password and len(password)>=8:secrets.append(password)
url=make_url(env['CHAT_DATABASE_URL']).set(drivername='postgresql')
with psycopg.connect(url.render_as_string(hide_password=False)) as conn:
 conn.execute('SET TRANSACTION READ ONLY')
 principals=[r[0] for r in conn.execute('SELECT DISTINCT owner_id FROM chat_conversations')]
artifacts=[p for p in sorted(OUT.glob(PREFIX+'*')) if p.is_file() and p.name not in {PREFIX+'security.log',PREFIX+'record.json'}]
scan_paths=paths+artifacts+[ROOT/'docs/ai-design/G8-WORKLOG.md',ROOT/'docs/ai-design/G8-IMPLEMENTATION-SPEC.md']
payload=b'\n'.join(p.read_bytes() for p in scan_paths)
assert not any(v.encode() in payload or v.encode('utf-16-le') in payload for v in secrets), 'Credential match; values withheld'
assert not any(v.encode() in payload for v in principals if len(v)>=16), 'Owner identifier match; values withheld'
linuxroot='/mnt/'+ROOT.drive[0].lower()+ROOT.as_posix()[2:]
scanner=['wsl','-d','vishue-g5','--','/var/tmp/g8-gitleaks-audit-20261126/gitleaks']
assert subprocess.check_output(scanner+['version']).strip()==b'8.30.1'
empty=OUT/(PREFIX+'empty.ignore');empty.write_bytes(b'')
command=scanner+['stdin','--config',linuxroot+'/.gitleaks.toml','--gitleaks-ignore-path',linuxroot+'/reports/g8/parent/'+empty.name,'--redact','--no-banner']
scan=subprocess.run(command,input=payload,capture_output=True)
(OUT/(PREFIX+'security.log')).write_bytes(scan.stdout+scan.stderr)
assert scan.returncode==0, 'Security scan failed; no trace append; values withheld'
starts=[json.loads(x) for x in (OUT/(PREFIX+'model-events.jsonl')).read_text(encoding='utf-8').splitlines() if json.loads(x).get('event')=='start']
record={'case':'G8-STAGE5-THREE-ITEM-CLOSEOUT','at':datetime.now(timezone.utc).isoformat(),
'head':baseline['head'],'branch':'feat/compound-consultation','uncommitted':True,
'developLocalRef':subprocess.check_output(['git','rev-parse','origin/develop'],text=True).strip(),
'remoteFreshnessChecked':False,'stage':'⑤ three-item closure; ⑥ integration evaluation remains',
'changedSourceFiles':changed,'sourceSha256':manifest(paths),
'actual':{'modelMode':'live','fixedModelCases':9,'fixedModelHttpCalls':len(live['events']),
'appTurnsIncludingIntermediate':len(rows),'finalSourceAppTurns':len(final_rows),
'appGenerationHttpStarts':len(starts),'appCompletedTurnModelCalls':sum(len(r.get('modelCalls',[])) for r in rows),'unattributedModelStarts':len(starts)-sum(len(r.get('modelCalls',[])) for r in rows),
'producerEvidence':app.get('producerEvidence',[]),'finalSourceDisplayMode':'reuse of this run actual G5/Catalog results; not fresh G5 generation','finalAppChecks':app['checks'],'models':['gpt-6-luna','gpt-6.1-terra'],
'providerSnapshotId':'not collected','catalogDataSnapshot':'not globally frozen; actual candidate/source versions retained in task payloads'},
'security':{'status':'PASS','scanner':'8.30.1','ignore':'empty','filesScanned':len(scan_paths),'findings':0,'knownCredentialComparison':'PASS','principalIdentifierComparison':'PASS'},
'artifacts':manifest(artifacts),
'notRun':['full original 14-capability/12-scenario integration judgement','mobile touch QA','performance evaluation','human review','PR/push/deploy'],
'failuresRetained':['uv sandbox cache access failure','initial test fixture and temp-directory errors','intermediate card aggregation regression','intermediate live answer had out-of-scope limitations','one UI network failure during runtime startup; normal UI retry used']}
sys.path.insert(0,str(ROOT/'scripts'))
from g8_evidence import normalize_record
record=normalize_record(record)
record_path=OUT/(PREFIX+'record.json');record_path.write_text(json.dumps(record,ensure_ascii=False,indent=2),encoding='utf-8')
line=(json.dumps(record,ensure_ascii=False)+'\n').encode('utf-8')
check=subprocess.run(command,input=line,capture_output=True)
assert check.returncode==0, 'Final record scan failed; no append; values withheld'
if '--append' in sys.argv:
 trace=OUT/'trace.jsonl';before=trace.read_bytes()
 assert not any(json.loads(x).get('case')==record['case'] for x in before.splitlines())
 with trace.open('ab') as f:f.write(line)
 assert trace.read_bytes()==before+line
 print('PASS security; appended one trace row; preserved',len(before.splitlines()),'previous rows')
else:print('PASS preflight security;',len(scan_paths),'inputs; trace unchanged')

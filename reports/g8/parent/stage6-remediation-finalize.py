"""Publication preflight: real credentials/identities stay in memory, never output."""
import hashlib
import importlib.util
import json
from datetime import datetime, timezone
from pathlib import Path
import socket
import subprocess
import sys
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[3]
OUT = ROOT / 'reports/g8/parent'
P = 'stage6-remediation-'
def sha(p): return hashlib.sha256(p.read_bytes()).hexdigest()
def write(name, value): (OUT/(P+name)).write_text(json.dumps(value,ensure_ascii=False,indent=2),encoding='utf-8')
baseline=json.loads((OUT/(P+'baseline.json')).read_text(encoding='utf-8'))
assert subprocess.check_output(['git','rev-parse','HEAD'],text=True).strip()==baseline['head']
closed={}
for host,port in [('127.0.0.1',19833),('127.0.0.1',19838),('::1',19836),('172.24.16.240',19841)]:
    with socket.socket(socket.AF_INET6 if ':' in host else socket.AF_INET) as s:
        s.settimeout(2); closed[str(port)]=s.connect_ex((host,port))!=0
assert all(closed.values())
write('cleanup.json',{'closed':closed,'existingCatalogDbRedisNeo4j':'left running','temporaryRelay':'stopped only scoped process','asideRepl':'exited'})
scope=json.loads((OUT/(P+'scope.json')).read_text(encoding='utf-8'))
(OUT/(P+'source.diff')).write_bytes(subprocess.check_output(['git','diff','--binary','HEAD','--',*scope['code']]))
spec=importlib.util.spec_from_file_location('runtime',OUT/(P+'runtime.py'))
runtime=importlib.util.module_from_spec(spec); spec.loader.exec_module(runtime)
env=runtime.environment()
values=[v for k,v in env.items() if any(t in k for t in ('PASSWORD','API_KEY','INTERNAL_TOKEN')) and isinstance(v,str) and len(v)>=8]
from sqlalchemy.engine import make_url
import psycopg
for key in ('DATABASE_URL','CHAT_DATABASE_URL'):
    password=make_url(env[key]).password
    if password and len(password)>=8: values.append(password)
url=make_url(env['CHAT_DATABASE_URL']).set(drivername='postgresql')
with psycopg.connect(url.render_as_string(hide_password=False)) as conn:
    conn.execute('SET TRANSACTION READ ONLY')
    owners=[str(r[0]) for r in conn.execute('SELECT DISTINCT owner_id FROM chat_conversations')]
paths=sorted(set(subprocess.check_output(['git','ls-files','--modified','--others','--exclude-standard'],text=True).splitlines()))
paths=[p for p in paths if (ROOT/p).is_file() and p not in {f'reports/g8/parent/{P}security.log',f'reports/g8/parent/{P}record.json',f'reports/g8/parent/{P}publication.json'}]
payload=b'\n'.join((ROOT/p).read_bytes() for p in paths)
assert not any(v.encode() in payload or v.encode('utf-16-le') in payload for v in values), 'Credential match; values withheld'
assert not any(v.encode() in payload for v in owners if len(v)>=16), 'Account identity match; values withheld'
empty=OUT/(P+'empty.ignore'); empty.write_bytes(b'')
linux='/mnt/'+ROOT.drive[0].lower()+ROOT.as_posix()[2:]
scanner=['wsl','-d','vishue-g5','--','/var/tmp/g8-gitleaks-audit-20261126/gitleaks']
assert subprocess.check_output(scanner+['version']).strip()==b'8.30.1'
command=scanner+['stdin','--config',linux+'/.gitleaks.toml','--gitleaks-ignore-path',linux+'/reports/g8/parent/'+empty.name,'--redact','--no-banner']
scan=subprocess.run(command,input=payload,capture_output=True)
(OUT/(P+'security.log')).write_bytes(scan.stdout+scan.stderr)
assert scan.returncode==0, 'Secret scan failed; do not publish; values withheld'
tests=[]
for name in ('backend-sealed','pg-owner','checkpoint-after'):
    path=OUT/(P+name+'.xml'); suites=list(ET.parse(path).getroot().iter('testsuite'))
    result={k:sum(int(s.get(k,'0')) for s in suites) for k in ('tests','failures','errors','skipped')}
    assert result['failures']==result['errors']==0
    tests.append({'name':name,**result,'sha256':sha(path),'timestamps':[s.get('timestamp') for s in suites]})
rows=[json.loads(x) for x in (OUT/(P+'app-turns.jsonl')).read_text(encoding='utf-8').splitlines()]
events=[json.loads(x) for x in (OUT/(P+'model-events.jsonl')).read_text(encoding='utf-8').splitlines()]
starts=sum(e['event']=='start' for e in events)
assert starts==51==sum(len(r.get('modelCalls',[])) for r in rows)
g5=[json.loads(x) for x in (OUT/(P+'g5-models.jsonl')).read_text(encoding='utf-8').splitlines()]
record={'case':'G8-STAGE6-REMEDIATION','at':datetime.now(timezone.utc).isoformat(),'head':baseline['head'],'branch':'feat/compound-consultation','uncommitted':True,'stage':'⑤ gate withheld for bundle5 actual app restore; F1-F4 repaired; ⑥ targeted integration in progress','actual':{'appExecutions':len(rows),'answers':sum('answer' in r for r in rows),'interrupted':sum(r.get('errorCode')=='request_interrupted' for r in rows),'modelConfiguredMode':'live','generationHttpStarts':starts,'embeddingHttpStarts':sum(e['event']=='start' and e['path']=='/v1/embeddings' for e in g5),'mockAnswers':0,'replayAnswers':0,'models':['gpt-6-luna','gpt-6.1-terra','text-embedding-3-large'],'providerSnapshot':'not pinned','globalDatasetSnapshot':'not frozen; per response versions preserved'},'tests':tests,'appChecks':{'npmRunCheck':'108 suites / 1352 tests PASS; typecheck/lint PASS','ruff':'PASS','importContracts':'3 KEPT'},'scopeCheck':json.loads((OUT/(P+'scope-check.json')).read_text(encoding='utf-8')),'security':{'version':'8.30.1','mode':'all modified and untracked publication files; stdin; empty ignore; redact','inputs':len(paths),'bytes':len(payload),'findings':0,'knownCredentialComparison':'PASS','accountIdentifierComparison':'PASS'},'evaluation':'scoped F1-F4 PASS; actual recent restore FAIL; full G8 NOT_COMPLETE','review':P+'review.json','dialogue':P+'dialogue.txt','sourceCapsule':P+'uncommitted-source.json','sources':json.loads((OUT/(P+'final-sources.json')).read_text(encoding='utf-8')),'artifacts':[{'path':p.relative_to(ROOT).as_posix(),'sha256':sha(p)} for p in sorted(OUT.glob(P+'*')) if p.is_file() and p.name not in {P+'record.json',P+'publication.json'}],'tracePreservation':{'previousRows':baseline['previousTraceRows'],'previousSha256':baseline['previousTraceSha256']}}
sys.path.insert(0,str(ROOT/'scripts'))
from g8_evidence import normalize_record
record=normalize_record(record)
write('record.json',record)
line=(json.dumps(record,ensure_ascii=False)+'\n').encode()
assert subprocess.run(command,input=line,capture_output=True).returncode==0
trace=OUT/'trace.jsonl'; before=trace.read_bytes()
assert sha(trace)==baseline['previousTraceSha256'] and len(before.splitlines())==baseline['previousTraceRows']
with trace.open('ab') as f: f.write(line)
assert trace.read_bytes()==before+line
print(json.dumps({'security':'PASS','files':len(paths),'megabytes':round(len(payload)/1024**2,2),'traceRows':len(trace.read_bytes().splitlines()),'appRestore':'FAIL preserved'},ensure_ascii=False))

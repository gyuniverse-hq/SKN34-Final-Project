"""Scan approved evidence in memory, then append trace bytes without a temporary staging tree."""
import hashlib
import importlib.util
import json
from pathlib import Path
import subprocess
import sys

ROOT=Path(__file__).resolve().parents[3]
OUT=ROOT/'reports/g8/parent'
record_path=OUT/'question-scope-answer-record.json'
record=json.loads(record_path.read_text(encoding='utf-8'))
paths=[ROOT/e['path'] for e in record['sourceSha256']]
for entry,p in zip(record['sourceSha256'],paths,strict=True):
    assert hashlib.sha256(p.read_bytes()).hexdigest()==entry['sha256']
paths += [p for p in sorted(OUT.glob('question-scope-answer-*')) if p.is_file()
          and p.name!='question-scope-answer-security.log']
payload=b'\n'.join(p.read_bytes() for p in paths)
spec=importlib.util.spec_from_file_location('runtime',OUT/'question-scope-answer-app-run.py')
runtime=importlib.util.module_from_spec(spec)
spec.loader.exec_module(runtime)
env=runtime.environment()
from sqlalchemy.engine import make_url
import psycopg
secrets=[v for k,v in env.items() if any(t in k for t in ['PASSWORD','API_KEY','INTERNAL_TOKEN'])
         and isinstance(v,str) and len(v)>=8]
for key in ['DATABASE_URL','CHAT_DATABASE_URL']:
    password=make_url(env[key]).password
    if password and len(password)>=8:secrets.append(password)
assert not any(v.encode() in payload or v.encode('utf-16-le') in payload for v in secrets), 'Known credential match; values withheld'
url=make_url(env['CHAT_DATABASE_URL']).set(drivername='postgresql')
assert url.database=='vishue_g8_browser'
with psycopg.connect(url.render_as_string(hide_password=False)) as conn:
    conn.execute('SET TRANSACTION READ ONLY')
    principals=[r[0] for r in conn.execute('SELECT DISTINCT owner_id FROM chat_conversations')]
assert not any(v.encode() in payload for v in principals if len(v)>=16), 'Principal identifier match; values withheld'
linuxroot='/mnt/'+ROOT.drive[0].lower()+ROOT.as_posix()[2:]
scanner='/var/tmp/g8-gitleaks-audit-20261126/gitleaks'
prefix=['wsl','-d','vishue-g5','--',scanner]
assert subprocess.check_output(prefix+['version']).strip()==b'8.30.1'
empty=OUT/'question-scope-answer-empty.ignore'
empty.write_bytes(b'')
command=prefix+['stdin','--config',linuxroot+'/.gitleaks.toml',
    '--gitleaks-ignore-path',linuxroot+'/reports/g8/parent/'+empty.name,'--redact','--no-banner']
result=subprocess.run(command,input=payload,capture_output=True)
(OUT/'question-scope-answer-security.log').write_bytes(result.stdout+result.stderr)
if result.returncode:raise SystemExit('Security scan failed; no trace append; values withheld')
record['security']={'status':'PASS','scanner':'8.30.1','ignore':'empty','mode':'stdin',
    'filesScanned':len(paths),'knownCredentialComparison':'PASS','findings':0}
record['security']['principalIdentifierComparison']='PASS'
sys.path.insert(0,str(ROOT/'scripts'))
from g8_evidence import normalize_record
record=normalize_record(record)
record_path.write_text(json.dumps(record,ensure_ascii=False,indent=2),encoding='utf-8')
if '--no-append' in sys.argv:
    print('PASS security preflight;',len(paths),'files; trace untouched')
    raise SystemExit(0)
line=(json.dumps(record,ensure_ascii=False)+'\n').encode('utf-8')
result=subprocess.run(command,input=line,capture_output=True)
if result.returncode:raise SystemExit('Final record scan failed; no append; values withheld')
trace=OUT/'trace.jsonl'
before=trace.read_bytes()
assert not any(json.loads(x).get('case')==record['case'] for x in before.splitlines())
with trace.open('ab') as f:f.write(line)
assert trace.read_bytes()==before+line
print('PASS security;',len(paths),'files; preserved',len(before.splitlines()),'trace rows and appended one')

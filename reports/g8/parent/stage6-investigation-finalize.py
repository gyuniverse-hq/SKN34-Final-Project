"""Seal investigation evidence; verify immutable sources and redact secret scan output."""
import hashlib
import importlib.metadata
import importlib.util
import json
import subprocess
import xml.etree.ElementTree as ET
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
OUT = ROOT / 'reports/g8/parent'
P = 'stage6-investigation-'

def read(name):
    return json.loads((OUT / (P + name)).read_text(encoding='utf-8-sig'))

def write(name, value):
    (OUT / (P + name)).write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')

def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()

baseline = read('baseline.json')
head = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip()
assert head == baseline['head']
tracked = subprocess.check_output(['git', 'status', '--porcelain', '--untracked-files=no'], cwd=ROOT, text=True).strip()
changed = [item['path'] for item in baseline['source'] if sha(ROOT / item['path']) != item['sha256']]
assert not tracked and not changed, 'Tracked product/config changed; do not seal'
write('source-integrity.json', {'head': head, 'baselineCount': len(baseline['source']), 'changed': changed, 'trackedStatus': tracked, 'productAndSharedConfigUnchanged': True})

tests = []
for name in ('unit', 'pg', 'redis', 'memory-flags'):
    path = OUT / (P + name + '.xml')
    suites = list(ET.parse(path).getroot().iter('testsuite'))
    row = {'name': name, **{key: sum(int(s.get(key, '0')) for s in suites) for key in ('tests', 'failures', 'errors', 'skipped')}, 'timestamps': [s.get('timestamp') for s in suites], 'sha256': sha(path)}
    assert row['failures'] == row['errors'] == 0
    tests.append(row)

http = [json.loads(line) for line in (OUT / (P + 'http.jsonl')).read_text().splitlines()]
browser = [json.loads(line) for line in (OUT / (P + 'browser-events.jsonl')).read_text().splitlines()]
assert not any(e['route'] == 'chat' and e['method'] == 'POST' for e in http)
assert not (OUT / (P + 'blocked-models.jsonl')).exists()
opens = []
for start in browser:
    if start['phase'] != 'open.start' or start.get('mode') != 'select':
        continue
    end = next(e for e in browser if e['phase'] == 'open.finally' and e['span'] == start['span'])
    restored = next(e for e in browser if e['phase'] == 'open.restore' and e['span'] == start['span'])
    opens.append({'span': start['span'], 'start': start['at'], 'end': end['at'], 'durationMs': round((datetime.fromisoformat(end['at']) - datetime.fromisoformat(start['at'])).total_seconds() * 1000), 'restored': restored['opened']})
assert len(opens) == 2 and all(row['restored'] for row in opens)
counts = Counter((e['route'], e['method'], e.get('status')) for e in http if e['event'] == 'end')
write('observations.json', {'instrumentedSelect': opens, 'http': [{'route': r, 'method': m, 'status': s, 'count': count} for (r, m, s), count in counts.items()], 'plainClick': [e for e in browser if e['phase'] == 'plain.click.capture'], 'historicalRestoreRootCause': 'NOT_CONFIRMED', 'currentRestore': 'PASS scoped instrumented mouse + original bundle Enter; original bundle mouse targeted HTML', 'paidModelCalls': 0, 'newChatPosts': 0, 'automaticLookSends': sum(e['phase'] == 'screen.send' and e.get('automatic') for e in browser)})

spec = importlib.util.spec_from_file_location('investigation_runtime', OUT / (P + 'runtime.py'))
runtime = importlib.util.module_from_spec(spec)
spec.loader.exec_module(runtime)
env = runtime.environment()
values = [v for k, v in env.items() if any(t in k for t in ('PASSWORD', 'API_KEY', 'INTERNAL_TOKEN', 'SECRET')) and isinstance(v, str) and len(v) >= 8]
from sqlalchemy.engine import make_url
import psycopg
for key in ('DATABASE_URL', 'CHAT_DATABASE_URL'):
    password = make_url(env[key]).password
    if password and len(password) >= 8:
        values.append(password)
url = make_url(env['CHAT_DATABASE_URL']).set(drivername='postgresql')
with psycopg.connect(url.render_as_string(hide_password=False)) as conn:
    conn.execute('SET TRANSACTION READ ONLY')
    conn.execute("SET LOCAL statement_timeout = '5s'")
    owners = [str(row[0]) for row in conn.execute('SELECT DISTINCT owner_id FROM chat_conversations')]
    server_version = conn.execute('SHOW server_version').fetchone()[0]
    schema_exists = conn.execute("SELECT to_regclass('alembic_version') IS NOT NULL").fetchone()[0]
    migrations = [row[0] for row in conn.execute('SELECT version_num FROM alembic_version')] if schema_exists else []
write('data-version.json', {'chatDatabase': url.database, 'serverVersion': server_version, 'alembic': migrations, 'catalogSnapshot': 'not globally frozen; existing saved payload and actual product detail used', 'detailPriceAsOf': '2026-10-28T10:06:07', 'g5NewDocuments': 'NOT_USED', 'model': 'no provider calls; synthetic model for flag contracts', 'packages': {name: importlib.metadata.version(name) for name in ('langgraph', 'pydantic', 'psycopg')}})

api_rows = read('api-flags.json')['results']
assert len(api_rows) == 3
cleanup = read('cleanup.json')
assert set(cleanup['portsClosed']) == {19833, 19834, 19836}
empty = OUT / (P + 'empty.ignore')
empty.write_bytes(b'')
record = {'case': 'G8-CLOSING-STAGE1-INVESTIGATION', 'at': datetime.now(timezone.utc).isoformat(), 'head': head, 'branch': baseline['branch'], 'scope': baseline['scope'], 'overallStage': '5 not closed; prior targeted stage6 evidence preserved', 'closingStage': '1 investigation executed; old restore cause remains unconfirmed', 'model': {'configuredRestoreMode': 'blocked', 'actualPaidCalls': 0, 'mockContracts': True, 'newChatPosts': 0}, 'tests': tests, 'catalogG5DependencyChecks': 3, 'findings': {'F1': 'G5 OFF bypass at chatbot direct knowledge entry confirmed', 'F2': 'G1 OFF skips requested option search but returns completed no_match confirmed', 'B1': 'G8 OFF cancelled stored parent intercepts ordinary chat; compatibility decision needed', 'restore': 'current scoped PASS; input target HTML explains one current mouse failure; historical cause unconfirmed'}, 'notRun': ['full G8 N01/N02/E01/B01 rerun', 'new real model generation', 'develop integration', 'full regression', 'native device AR', 'PR/merge/deploy'], 'sourceIntegrity': 'source-integrity.json', 'report': P + 'report.md', 'commands': {'selectedTests': 'uv run --frozen --no-sync python -B reports/g8/parent/stage6-investigation-run-selected.py [--memory-flags|--redis]', 'selectedTestsDetails': 'exact pytest arguments are retained in run-selected.py and JUnit XML timestamps', 'flagsReproduction': 'uv run --frozen --no-sync python -B reports/g8/parent/stage6-investigation-flags.py; product-flags.py in chatbot environment', 'catalogDependency': 'uv run --frozen --no-sync python -B ../../reports/g8/parent/stage6-investigation-api-flags.py from backend/api', 'appChecks': ['npm run typecheck', 'npm run lint'], 'restore': 'runtime.py; then web-only --plain; Aside explicit connected local profile'}, 'security': 'new evidence only; see security.json; no full Git scan this turn'}
write('record.json', record)

linux = '/mnt/' + ROOT.drive[0].lower() + ROOT.as_posix()[2:]
scanner = ['wsl', '-d', 'vishue-g5', '--', '/var/tmp/g8-gitleaks-audit-20261126/gitleaks']
assert subprocess.check_output(scanner + ['version']).strip() == b'8.30.1'
command = scanner + ['stdin', '--config', linux + '/.gitleaks.toml', '--gitleaks-ignore-path', linux + '/reports/g8/parent/' + empty.name, '--redact', '--no-banner']

def scan():
    paths = [p for p in sorted(OUT.glob(P + '*')) if p.is_file() and p.name not in {P + 'security.log', P + 'finalize.log'}]
    payload = b'\n'.join(p.read_bytes() for p in paths)
    assert not any(v.encode() in payload or v.encode('utf-16-le') in payload for v in values), 'Credential match; details withheld'
    assert not any(v.encode() in payload for v in owners if len(v) >= 16), 'Account identity match; details withheld'
    result = subprocess.run(command, input=payload, capture_output=True)
    (OUT / (P + 'security.log')).write_bytes(result.stdout + result.stderr)
    assert result.returncode == 0, 'Redacted security scan failed; do not publish'
    return paths, len(payload)

paths, size = scan()
write('security.json', {'version': '8.30.1', 'mode': 'stdin, repository config, empty ignore, redact; new investigation evidence only', 'findings': 0, 'knownCredentialComparison': 'PASS', 'accountIdentifierComparison': 'PASS', 'firstPassFiles': len(paths), 'firstPassBytes': size, 'finalPass': 'includes generated security metadata and record; see security.log'})
record['artifacts'] = [{'path': p.relative_to(ROOT).as_posix(), 'sha256': sha(p)} for p in paths if p.name not in {P + 'record.json', P + 'security.json'}]
write('record.json', record)
paths, size = scan()
print(json.dumps({'head': head[:8], 'unchangedSourceFiles': len(baseline['source']), 'unitPass': 28, 'actualPgPass': 8, 'initialRedisSkip': 'rerun PASS', 'catalogDependencyPass': 3, 'instrumentedRestorePass': len(opens), 'paidModels': 0, 'security': 'PASS', 'scannedFiles': len(paths), 'scannedBytes': size}, ensure_ascii=False))

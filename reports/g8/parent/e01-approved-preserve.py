"""Preserve E01 partial implementation and verification without secrets."""
import hashlib
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
OUT = ROOT / 'reports/g8/parent'
def git(*args):
    return subprocess.check_output(['git', *args], cwd=ROOT)
paths = git('diff','--name-only','--','backend/chatbot').decode().splitlines()
new = git('ls-files','--others','--exclude-standard','--','backend/chatbot').decode().splitlines()
paths = sorted(set(paths+new+['docs/ai-design/G8-WORKLOG.md','docs/ai-design/G8-IMPLEMENTATION-SPEC.md']))
sources=[{'path':p,'sha256':hashlib.sha256((ROOT/p).read_bytes()).hexdigest()} for p in paths]
(OUT/'e01-approved-sources.json').write_text(json.dumps(sources,indent=2),encoding='utf-8')
(OUT/'e01-approved-source.diff').write_bytes(git('diff','--',*paths))
(OUT/'e01-approved-new-sources.json').write_text(json.dumps([{'path':p,'content':(ROOT/p).read_text(encoding='utf-8')} for p in new],ensure_ascii=False,indent=2),encoding='utf-8')

import xml.etree.ElementTree as ET
suites={}
for key,name in [('backend','e01-approved-backend.xml'),('pg','e01-approved-pg.xml'),('related','e01-final-source.xml')]:
    suite=ET.parse(OUT/name).find('testsuite')
    assert suite.get('failures')==suite.get('errors')=='0'
    suites[key]=dict(suite.attrib)
turns=[json.loads(s) for s in (OUT/'e01-e2e-turns.jsonl').read_text(encoding='utf-8').splitlines()]
assert len(turns)==5 and [len(r['modelCalls']) for r in turns]==[1,1,1,2,0]
pg=json.loads((OUT/'e01-e2e-pg.json').read_text(encoding='utf-8'))
assert all(pg['checks'].values())
assert not (OUT/'e01-style-fault.enabled').exists()
record={'case':'G8-E01-PG-LIVE-APP-RECOVERY','at':datetime.now(timezone.utc).isoformat(),'head':git('rev-parse','HEAD').decode().strip(),'uncommitted':True,'stage':'5-collaboration','bundle':'2-of-6','sourceSha256':sources,'diff':'reports/g8/parent/e01-approved-source.diff','validation':{'suites':suites,'modelConfiguredMode':'live','model':'gpt-6-luna','modelEndpoint':'api.openai.com/v1','actualModelCallsPerTurn':[1,1,1,2,0],'finalRepresentativeTurnIndexes':[2,3],'actualExternalModelCalls':5,'catalog':'real local HTTP','styleFault':'controlled UpstreamError injection; real HTTP 503 covered separately with synthetic server','auth':'real Supabase login','storage':'real PostgreSQL','browser':'PASS keyboard partial restore / recovery restore / restored look card selection and guide','screenshot':'FAILED_CDP_TIMEOUT','touch':'NOT_RUN','fullG8':'NOT_RUN','humanReview':'NOT_RUN','ruff':'PASS','imports':'3 PASS','typecheck':'PASS','lint':'PASS','pgChecks':pg['checks']},'remaining':['human semantic review','comparison answer UX wording','mobile touch','B01 and other G8 bundles'],'evidence':['reports/g8/parent/e01-e2e-turns.jsonl','reports/g8/parent/e01-e2e-browser.json','reports/g8/parent/e01-e2e-card.json','reports/g8/parent/e01-e2e-pg.json'],'security':{'scanner':'8.30.1','ignore':'empty','result':'PASS only after approved finalizer success'},'prCreated':False,'pushed':False}
(OUT/'e01-approved-record.json').write_text(json.dumps(record,ensure_ascii=False,indent=2),encoding='utf-8')
print('Preserved',len(paths),'source hashes and',len(new),'new sources; suites all pass')

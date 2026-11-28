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
(OUT/'e01-sources.json').write_text(json.dumps(sources,indent=2),encoding='utf-8')
(OUT/'e01-source.diff').write_bytes(git('diff','--',*paths))
(OUT/'e01-new-sources.json').write_text(json.dumps([{'path':p,'content':(ROOT/p).read_text(encoding='utf-8')} for p in new],ensure_ascii=False,indent=2),encoding='utf-8')
record={'case':'G8-E01-PARTIAL-READS-PG-BLOCKED','at':datetime.now(timezone.utc).isoformat(),'head':git('rev-parse','HEAD').decode().strip(),'uncommitted':True,'stage':'5-collaboration','bundle':'2-of-6','sourceSha256':sources,'diff':'reports/g8/parent/e01-source.diff','validation':{'backend':{'passed':1586,'skipped':117},'mockAndSyntheticHttp':10,'includingRealCatalog':11,'actualExternalModelCalls':0,'modelMode':'mock','catalogMode':'live local HTTP for one case, mock/synthetic HTTP for others','pg':'FAIL: new productStyle rejected by repository context allowlist; additional file approval pending','authMode':'mock in PG test','ruff':'PASS','imports':'3 PASS','typecheck':'PASS','lint':'PASS','liveModel':'NOT_RUN','loginApp':'NOT_RUN','fullG8':'NOT_RUN'},'commands':['uv run pytest tests/test_g8_partial_success.py -q --tb=short -o junit_family=legacy --junitxml=../../reports/g8/parent/e01-catalog.xml (G8_E01_LIVE_CATALOG=http://127.0.0.1:19834)','python reports/g8/parent/e01-run-pg.py','uv run ruff check .','uv run lint-imports','uv run pytest -q --tb=short -o junit_family=legacy --junitxml=../../reports/g8/parent/e01-backend.xml','npm run typecheck','npm run lint'],'security':{'scanner':'8.30.1','ignore':'empty','result':'PASS only after finalizer success'},'prCreated':False,'pushed':False}
(OUT/'e01-record.json').write_text(json.dumps(record,ensure_ascii=False,indent=2),encoding='utf-8')
print('Preserved',len(paths),'source hashes and',len(new),'new sources')

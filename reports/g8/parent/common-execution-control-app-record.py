"""Preserve exact source and the separately observed validation boundaries."""
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[3]
OUT = ROOT / 'reports/g8/parent'
PREFIX = 'common-execution-control-app'
def git(*args):
    return subprocess.check_output(['git', *args], cwd=ROOT)
paths = set(git('diff','--name-only','HEAD').decode().splitlines())
untracked = git('ls-files','--others','--exclude-standard').decode().splitlines()
paths.update(untracked)
paths = sorted(p for p in paths if not p.startswith('reports/') and (ROOT/p).is_file())
(OUT/f'{PREFIX}-source.diff').write_bytes(git('diff','--binary','HEAD','--',*paths))
(OUT/f'{PREFIX}-new-sources.json').write_text(json.dumps([
    {'path':p,'content':(ROOT/p).read_text(encoding='utf-8')} for p in untracked if p in paths
],ensure_ascii=False,indent=2),encoding='utf-8')
turns = [json.loads(line) for line in (OUT/f'{PREFIX}-turns.jsonl').read_text(encoding='utf-8').splitlines()]
manifest = [{'path':p,'sha256':hashlib.sha256((ROOT/p).read_bytes()).hexdigest()} for p in paths]
store = (ROOT/'store/chatConversationStore.ts').read_bytes()
before_notice = store.replace(b"        if (room.notice === 'chat.cancel.done') room.notice = undefined;\r\n",b'').replace(b"        if (room.notice === 'chat.cancel.done') room.notice = undefined;\n",b'')
record = dict(at=datetime.now(timezone.utc).isoformat(),case=PREFIX+'-20261128',
    head=git('rev-parse','HEAD').decode().strip(),branch=git('branch','--show-current').decode().strip(),
    uncommitted=True,stage='5/7 bundle4 app integration; stage5 not complete',
    sourceSha256=manifest,sourceDiff=f'reports/g8/parent/{PREFIX}-source.diff',
    untrackedSources=f'reports/g8/parent/{PREFIX}-new-sources.json',
    liveSourceDifference={'path':'store/chatConversationStore.ts','sha256':hashlib.sha256(before_notice).hexdigest(),
        'difference':'actual cancellation/replacement before clearing cancel notice on next beginRequest; final restore after fix'},
    validation={'mockRelated':'165 PASS','initialCheck':'typecheck/lint PASS; 1344 PASS,2 timeout',
        'sequential':'1346 PASS /108 suites','final':'see typecheck-final/lint-final/tests-final-all logs',
        'actual':'logged-in app cancellation, replacement12cards, PG INTERRUPTED/COMMITTED,2messages, reload restore PASS'},
    modelConfiguredMode='live',actualModelHttpStarted=sum(len(t['modelCalls']) for t in turns),
    turns=[{'at':t['at'],'mode':'live','httpStarted':len(t['modelCalls']),'error':t.get('errorCode'),
            'products':len(t.get('products',[]))} for t in turns],
    callCounting='HTTP send entry, not HTTP200 count; G5 API internal calls unmeasured',
    remaining=['mobile native/touch NOT_RUN','real network-loss/race/account-switch NOT_RUN; mock PASS',
        'in-flight external call forced termination not implemented','stage5 full exit matrix',
        'restored general product room shows existing independent-search notice; full followup outside this case'],
    temporaryServices='G5 API19838 and relay19841 stopped; existing app/Catalog/PG retained',
    commitPushPr='NOT_RUN',security='Gitleaks8.30.1 empty ignore before append')
(OUT/f'{PREFIX}-record.json').write_text(json.dumps(record,ensure_ascii=False,indent=2),encoding='utf-8')
print('Preserved',len(paths),'source hashes and',len(turns),'live turn records')

"""Snapshot the tested sources, excluding runtime secrets."""
from pathlib import Path
import hashlib,json,subprocess,sys
from datetime import datetime,timezone
ROOT=Path(__file__).resolve().parents[3]
OUT=ROOT/'reports/g8/parent'
prefix='common-entry-cooperation-'+(sys.argv[1] if len(sys.argv)>1 else 'final')
old=json.loads((OUT/'integration-n01-resolution-record.json').read_text(encoding='utf-8'))
paths={x['path'] for x in old['sourceSha256']}
paths.update(['backend/chatbot/tests/test_product_search_contract.py','backend/chatbot/tests/test_g8_owned_look_interpreter.py'])
paths=sorted(p for p in paths if (ROOT/p).is_file())
(OUT/(prefix+'-source.diff')).write_bytes(subprocess.check_output(['git','diff','--binary','HEAD','--',*paths],cwd=ROOT))
untracked=subprocess.check_output(['git','ls-files','--others','--exclude-standard','-z'],cwd=ROOT).decode().split('\0')
record={'at':datetime.now(timezone.utc).isoformat(),'head':subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT).decode().strip(),'uncommitted':True,'sourceSha256':[{'path':p,'sha256':hashlib.sha256((ROOT/p).read_bytes()).hexdigest()} for p in paths],'sourceDiff':f'reports/g8/parent/{prefix}-source.diff','untrackedSources':f'reports/g8/parent/{prefix}-new-sources.json'}
(OUT/(prefix+'-new-sources.json')).write_text(json.dumps([{'path':p,'content':(ROOT/p).read_text(encoding='utf-8')} for p in paths if p in untracked],ensure_ascii=False,indent=2),encoding='utf-8')
(OUT/(prefix+'-sources.json')).write_text(json.dumps(record,ensure_ascii=False,indent=2),encoding='utf-8')
print('Preserved',len(paths),'source identities')

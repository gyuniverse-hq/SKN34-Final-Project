"""Capture exact uncommitted source; retain all failed and successful runs."""
import hashlib,importlib.util,json,re,subprocess
from datetime import datetime,timezone
from pathlib import Path
ROOT=Path(__file__).resolve().parents[3];OUT=ROOT/'reports/g8/parent';PREFIX='completion-restore'
def git(*a):return subprocess.check_output(['git',*a],cwd=ROOT)
names=set(git('diff','--name-only','HEAD').decode().splitlines());new=git('ls-files','--others','--exclude-standard').decode().splitlines();names.update(new)
names=sorted(p for p in names if not p.startswith('reports/') and (ROOT/p).is_file())
(OUT/(PREFIX+'-source.diff')).write_bytes(git('diff','--binary','HEAD','--',*names))
(OUT/(PREFIX+'-new-sources.json')).write_text(json.dumps([{'path':p,'content':(ROOT/p).read_text(encoding='utf-8-sig')}for p in new if p in names],ensure_ascii=False,indent=2),encoding='utf-8')
turns=[json.loads(l)for l in (OUT/(PREFIX+'-app-turns.jsonl')).read_text(encoding='utf-8-sig').splitlines()]
assert len(turns)==7 and sum(len(t['modelCalls'])for t in turns)==19
assert len(turns[5]['consultation']['displayChoices'])==2
assert turns[6]['consultation']['selectedTaskId']==turns[5]['consultation']['displayChoices'][1]['taskId']
assert turns[6]['catalogCalls']==[] and turns[3]['catalogCalls']==[]
assert '1352 passed' in (OUT/(PREFIX+'-app-final2.log')).read_text()
assert '1690 passed' in (OUT/(PREFIX+'-backend.log')).read_text()
assert 'optionId=A000000162092-001' in (OUT/(PREFIX+'-app-final-detail.txt')).read_text(encoding='utf-8')
s=importlib.util.spec_from_file_location('r',OUT/(PREFIX+'-app-run.py'));m=importlib.util.module_from_spec(s);s.loader.exec_module(m)
e=m.environment();mapping=Path(e['INGREDIENT_MAPPING_PATH'])
r=dict(at=datetime.now(timezone.utc).isoformat(),case=PREFIX+'-20261128',head=git('rev-parse','HEAD').decode().strip(),branch=git('branch','--show-current').decode().strip(),uncommitted=True,
 stage='5/7 bundles5+6; stage5 exit INCOMPLETE',
 sourceSha256=[{'path':p,'sha256':hashlib.sha256((ROOT/p).read_bytes()).hexdigest()}for p in names],
 sourceDiff='reports/g8/parent/'+PREFIX+'-source.diff',untrackedSources='reports/g8/parent/'+PREFIX+'-new-sources.json',
 modelConfiguredMode='live; no replay or mock in seven app turns',actualModelHttpStarted=19,
 turns=[{'index':i+1,'at':t['at'],'mode':'live','modelHttpStarted':len(t['modelCalls']),'catalogHttpStarted':len(t['catalogCalls']),'summary':t['consultation']}for i,t in enumerate(turns)],
 counting='HTTP send entry, not success-status or provider-billed-call count; no G5 used',
 validation={'unit':'80 PASS synthetic model/specialists; real scheduler','pg':'1 PASS actual PG/mock model + 22 PASS/4 SKIP/2 deselected regression',
 'backend':'1690 PASS/130 SKIP final product backend; before last PG fixture null comparison','app':'1352 PASS/108 suites final product frontend','typecheck':'PASS','lint':'PASS','ruff':'PASS','imports':'3 KEPT',
 'actualApp':'completed dual search; show without catalog; failed/partial scope; retry sibling preservation; number selection; PG restore; unique exact option detail PASS'},
 data={'mappingArtifact':mapping.name,'mappingSha256':hashlib.sha256(mapping.read_bytes()).hexdigest(),'globalDbSnapshot':'not pinned','optionEvidenceVersions':'per-task option payloads','catalogSource':'current worktree API after restart and mapping environment correction'},
 failures=['first fragrance run mapping absent, broad fallback/kind context not accepted as pass','second options run mapping absent: both failed','after mapping lip initially failed, explicit retry recovered; no fake success','PG raw JSON null serialization differences corrected/typed roundtrip checked','validation helper column/path errors fixed; no product changes for helper faults','initial restored detail lacked optionId; final callback and app retest PASS'],
 sourceBoundaries='live backend equals final product backend; final frontend restore/detail after unique-option and failure-empty-state fixes; previous UI attempts retained',
 matrix='reports/g8/parent/'+PREFIX+'-exit-matrix.json',remaining=['original fragrance/kind case not rerun after config correction','live multiple specialist questions','latest summary+cancel all-live E2E','live budget change this run','stage6 original N01/N02/E01/B01 integration/holdout/native/performance/human review'],
 commitPushPr='NOT_RUN',security='Gitleaks8.30.1 empty ignore before immutable trace append')
(OUT/(PREFIX+'-record.json')).write_text(json.dumps(r,ensure_ascii=False,indent=2),encoding='utf-8')
files=list(OUT.glob(PREFIX+'-*'))
patterns=[r'[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}',r'Bearer\s+eyJ',r'eyJ[A-Za-z0-9_-]+\.eyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+',r'^-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----']
def strings(value):
 if isinstance(value,str):return [value]
 if isinstance(value,list):return [s for item in value for s in strings(item)]
 if isinstance(value,dict):return [s for item in value.values()for s in strings(item)]
 return []
raw=[]
for p in files:
 if not p.is_file():continue
 text=p.read_text(encoding='utf-8-sig')
 if p.suffix=='.json':raw.extend(strings(json.loads(text)))
 elif p.suffix=='.diff':raw.append('\n'.join(line[1:] if line.startswith(('+','-',' ')) else line for line in text.splitlines()))
 else:raw.append(text)
assert not any(re.search(pattern,v,re.I|re.M)for v in raw for pattern in patterns)
secrets=[v for k,v in e.items()if k in ('LLM_API_KEY','G5_OPENAI_API_KEY','G5_INTERNAL_TOKEN','DATABASE_URL','CHAT_DATABASE_URL')and len(v)>12]
assert not any(secret in text for secret in secrets for text in raw)
print('PASS',len(names),'source hashes;',len(files),'evidence files; privacy patterns and known runtime secrets absent;19 live HTTP starts')

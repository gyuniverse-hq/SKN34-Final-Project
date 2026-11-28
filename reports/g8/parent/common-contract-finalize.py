"""Run in WSL; scan all E01 artifacts and changed sources before append."""
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
ROOT=Path(__file__).resolve().parents[3]
OUT=ROOT/'reports/g8/parent'
SCANNER=Path('/var/tmp/g8-gitleaks-audit-20261126/gitleaks')
sys.path.insert(0,str(ROOT/'scripts'))
from g8_evidence import append_record
record=json.loads((OUT/'common-contract-record.json').read_text())
paths=[ROOT/item['path'] for item in record['sourceSha256']]
paths += [p for p in OUT.glob('common-contract-*') if not p.name.endswith('security.log')]
with tempfile.TemporaryDirectory(prefix='g8-e01-') as folder:
    target=Path(folder)
    for path in paths:
        dest=target/path.relative_to(ROOT)
        dest.parent.mkdir(parents=True,exist_ok=True)
        shutil.copyfile(path,dest)
    empty=target/'empty.ignore'; empty.write_text('')
    scan=subprocess.run([str(SCANNER),'dir',str(target),'--config',str(ROOT/'.gitleaks.toml'),'--gitleaks-ignore-path',str(empty),'--redact','--no-banner'],capture_output=True,text=True)
    (OUT/'common-contract-security.log').write_text(scan.stdout+scan.stderr)
    if scan.returncode: raise SystemExit('Security scan failed; values withheld')
trace=OUT/'trace.jsonl'; before=trace.read_bytes()
assert not any(json.loads(line).get('case')==record['case'] for line in before.splitlines())
append_record(trace,record,scanner=SCANNER,config=ROOT/'.gitleaks.toml')
assert trace.read_bytes()[:len(before)]==before
print('PASS',len(paths),'files; preserved',len(before.splitlines()),'rows; appended one contract verification record')


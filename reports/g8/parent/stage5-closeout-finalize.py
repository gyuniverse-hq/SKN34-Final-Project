"""Scan current sources/new evidence with empty ignore before append-only trace storage."""
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[3]
OUT = ROOT / "reports/g8/parent"
SCANNER = Path("/var/tmp/g8-gitleaks-audit-20261126/gitleaks")
sys.path.insert(0, str(ROOT / "scripts"))
from g8_evidence import append_record

record = json.loads((OUT / "stage5-closeout-record.json").read_text())
paths = [ROOT / entry["path"] for entry in record["sourceSha256"]]
for entry in record["sourceSha256"]:
    assert hashlib.sha256((ROOT / entry["path"]).read_bytes()).hexdigest() == entry["sha256"]
paths += [p for p in OUT.glob("stage5-closeout-*") if p.is_file() and not p.name.endswith("security.log")]
with tempfile.TemporaryDirectory(prefix="g8-stage5-security-") as folder:
    target = Path(folder)
    for path in paths:
        destination = target / path.relative_to(ROOT)
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(path, destination)
    empty = target / "empty.ignore"
    empty.write_text("")
    result = subprocess.run([
        str(SCANNER), "dir", str(target), "--config", str(ROOT / ".gitleaks.toml"),
        "--gitleaks-ignore-path", str(empty), "--redact", "--no-banner",
    ], capture_output=True, text=True)
    (OUT / "stage5-closeout-security.log").write_text(result.stdout + result.stderr)
    if result.returncode:
        raise SystemExit("Security scan failed; values withheld")
trace = OUT / "trace.jsonl"
before = trace.read_bytes()
assert not any(json.loads(line).get("case") == record["case"] for line in before.splitlines())
append_record(trace, record, scanner=SCANNER, config=ROOT / ".gitleaks.toml")
assert trace.read_bytes().startswith(before)
print("PASS", len(paths), "files; preserved", len(before.splitlines()), "trace rows; appended one")

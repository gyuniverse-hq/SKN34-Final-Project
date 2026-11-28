"""WSL scanner with empty ignore, then immutable trace append."""
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

record = json.loads((OUT / "common-parent-product-contract-lifecycle-record.json").read_text())
paths = [ROOT / item["path"] for item in record["sourceSha256"]]
paths += [p for p in OUT.glob("common-parent-product-contract-*") if not p.name.endswith("security.log")]
with tempfile.TemporaryDirectory(prefix="g8-connected-") as folder:
    target = Path(folder)
    for path in paths:
        dest = target / path.relative_to(ROOT)
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(path, dest)
    empty = target / "empty.ignore"
    empty.write_text("")
    result = subprocess.run([str(SCANNER), "dir", str(target), "--config", str(ROOT / ".gitleaks.toml"),
        "--gitleaks-ignore-path", str(empty), "--redact", "--no-banner"], capture_output=True, text=True)
    (OUT / "common-parent-product-contract-lifecycle-security.log").write_text(result.stdout + result.stderr)
    if result.returncode:
        raise SystemExit("Security scan failed; values withheld")
trace = OUT / "trace.jsonl"
before = trace.read_bytes()
assert not any(json.loads(line).get("case") == record["case"] for line in before.splitlines())
append_record(trace, record, scanner=SCANNER, config=ROOT / ".gitleaks.toml")
assert trace.read_bytes().startswith(before)
print("PASS", len(paths), "files; preserved", len(before.splitlines()), "trace rows; appended one")

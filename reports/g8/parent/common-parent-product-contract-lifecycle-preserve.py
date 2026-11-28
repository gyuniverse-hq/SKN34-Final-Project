"""Preserve the final failure-lifecycle delta separately from earlier live execution."""
import hashlib
import json
from pathlib import Path
import subprocess
from datetime import datetime, timezone
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[3]
OUT = ROOT / "reports/g8/parent"
PREFIX = "common-parent-product-contract-"
record = json.loads((OUT / (PREFIX + "record.json")).read_text(encoding="utf-8"))
record.update(case="G8-PRODUCT-ASSESSMENT-FAILURE-LIFECYCLE", at=datetime.now(timezone.utc).isoformat(),
    actualRemoteHttpCalls=0, finalFrozenActualModelCalls=0,
    modelConfiguredMode="mock final regression; earlier live evidence is separate",
    acceptance="final failure/success regression; previous real model/Catalog/PG run not repeated after this delta",
    priorLiveRecord="G8-PRODUCT-KIND-COMPLETION-PRESERVE",
    callBreakdown=[], delta="clear previous product assessment at read start; retain requirement/context")
paths = {x["path"] for x in record["sourceSha256"]}
paths.update(p.relative_to(ROOT).as_posix() for p in OUT.glob(PREFIX + "*.py"))
record["sourceSha256"] = [{"path": p, "sha256": hashlib.sha256((ROOT / p).read_bytes()).hexdigest()} for p in sorted(paths)]
record["suites"] = {}
for label in ["lifecycle-backend", "lifecycle-tests"]:
    suite = next(ET.parse(OUT / (PREFIX + label + ".xml")).iter("testsuite"))
    assert suite.get("failures") == suite.get("errors") == "0"
    record["suites"][label] = dict(suite.attrib)
record["diff"] = "reports/g8/parent/" + PREFIX + "lifecycle-source.diff"
(ROOT / record["diff"]).write_bytes(subprocess.check_output(["git", "diff", "--", "backend/chatbot", "docs/ai-design/G8-WORKLOG.md", "docs/ai-design/G8-IMPLEMENTATION-SPEC.md"], cwd=ROOT))
new = subprocess.check_output(["git", "ls-files", "--others", "--exclude-standard", "--", "backend/chatbot"], cwd=ROOT, text=True).splitlines()
record["newSources"] = "reports/g8/parent/" + PREFIX + "lifecycle-new-sources.json"
(ROOT / record["newSources"]).write_text(json.dumps([{"path": p, "content": (ROOT / p).read_text(encoding="utf-8")} for p in new], ensure_ascii=False, indent=2), encoding="utf-8")
(OUT / (PREFIX + "lifecycle-record.json")).write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
print("Preserved final lifecycle delta; external calls 0")

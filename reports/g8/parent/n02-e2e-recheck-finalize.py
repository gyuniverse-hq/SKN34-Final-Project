"""Preserve corrected diagnostic conclusions and scan before appending evidence."""
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[3]
OUT = ROOT / "reports/g8/parent"
SCANNER = Path("/var/tmp/g8-gitleaks-audit-20261126/gitleaks")
sys.path.insert(0, str(ROOT / "scripts"))
from g8_evidence import append_record

paths = [i["path"] for i in json.loads((OUT / "n02-e2e-sources.json").read_text())["sources"]]
paths += ["hooks/useChatConversations.ts", "lib/api.ts", "__tests__/useChatConversations.test.tsx", "__tests__/chatSessionApi.test.ts"]
sources = [{"path":p,"sha256":hashlib.sha256((ROOT/p).read_bytes()).hexdigest()} for p in paths]
(OUT / "n02-e2e-recheck-sources.json").write_text(json.dumps(sources,indent=2))
git_state=json.loads((OUT/"n02-e2e-recheck-git.json").read_text())
assert git_state["appDiffEmpty"]
shutil.copyfile(OUT / "n02-e2e-pg-regression-2.xml",OUT / "n02-e2e-recheck-pg.xml")
suite = ET.parse(OUT / "n02-e2e-recheck-pg.xml").find("testsuite")
assert suite.get("failures") == suite.get("errors") == "0"
assert "37 passed" in (OUT / "n02-e2e-recheck-app.log").read_text(encoding="utf-8-sig")
record = {"case":"G8-N02-RESTORE-RECHECK", "at":datetime.now(timezone.utc).isoformat(),
          "head":git_state["head"],
          "uncommitted":True,"stage":"5-collaboration","bundle":"1-of-6",
          "sourceSha256":sources,"diff":"reports/g8/parent/n02-e2e-recheck-source.diff",
          "corrections":{"503":"Test-only interpreter Model lacked complete(); AttributeError at ChatService.execute_tool. General-capable mock returns HTTP 200, response persisted, no applied memories.",
                         "restore":"Prior automation click did not execute select. Actual keyboard activation completed select/restore/recovery/finally and restored the saved 3-turn consultation.",
                         "pointer":"Exact reason for click non-activation remains unverified. No mobile touch claim."},
          "validation":{"actualWebRestore":"PASS_KEYBOARD","restoredCardDetail":"PASS_KEYBOARD",
                        "optionId":"A000000183683-001","detailLabel":"01 피치베이지","detailPriceKRW":11900,
                        "pgMockModelCatalogAuth":dict(suite.attrib),"appRelatedTests":37,
                        "newExternalModelCalls":0,"ruff":"PASS","imports":"PASS","typecheck":"PASS","lint":"PASS",
                        "expoGoTouch":"NOT_RUN","fullG8":"NOT_RUN","payment":"NOT_RUN"},
          "evidence":["reports/g8/parent/n02-e2e-recheck-browser.txt","reports/g8/parent/n02-e2e-restore-http.jsonl",
                      "reports/g8/parent/n02-e2e-recheck-pg.log","reports/g8/parent/n02-e2e-recheck-pg.xml",
                      "reports/g8/parent/n02-e2e-recheck-app.log","reports/g8/parent/n02-e2e-web.log"],
          "productAppChanges":False,"temporaryInstrumentationRemoved":True,
          "security":{"scanner":"8.30.1","ignore":"empty","result":"PASS"},"prCreated":False,"pushed":False}
(OUT / "n02-e2e-recheck-record.json").write_text(json.dumps(record,ensure_ascii=False,indent=2),encoding="utf-8")
scan_paths = [ROOT/p for p in paths] + [ROOT/"docs/ai-design/G8-WORKLOG.md",ROOT/"docs/ai-design/G8-IMPLEMENTATION-SPEC.md"]
scan_paths += [p for p in OUT.glob("n02-e2e-*") if not p.name.endswith("security.log")]
with tempfile.TemporaryDirectory(prefix="g8-recheck-") as folder:
    target=Path(folder)
    for path in scan_paths:
        dest=target/path.relative_to(ROOT); dest.parent.mkdir(parents=True,exist_ok=True); shutil.copyfile(path,dest)
    empty=target/"empty.ignore"; empty.write_text("")
    scan=subprocess.run([str(SCANNER),"dir",str(target),"--config",str(ROOT/".gitleaks.toml"),"--gitleaks-ignore-path",str(empty),"--redact","--no-banner"],capture_output=True,text=True)
    (OUT/"n02-e2e-recheck-security.log").write_text(scan.stdout+scan.stderr)
    if scan.returncode:raise SystemExit("Security scan failed; values withheld")
trace=OUT/"trace.jsonl"; before=trace.read_bytes()
assert not any(json.loads(line).get("case")==record["case"] for line in before.splitlines())
append_record(trace,record,scanner=SCANNER,config=ROOT/".gitleaks.toml")
assert trace.read_bytes()[:len(before)]==before
print("PASS",len(scan_paths),"files; preserved",len(before.splitlines()),"trace rows; appended 1 correction")

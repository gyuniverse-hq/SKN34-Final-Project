"""Preserve the tested working tree identity without environment or credentials."""
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import subprocess
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[3]
OUT = ROOT / "reports/g8/parent"
PREFIX = "common-price-followup"

def write(name, data):
    (OUT / f"{PREFIX}-{name}.json").write_text(
        json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )

old = json.loads((OUT / "common-comparison-followup-record.json").read_text(encoding="utf-8"))
paths = {item["path"] for item in old["sourceSha256"]}
paths.update([
    "backend/chatbot/tests/test_g8_partial_success.py",
    "backend/chatbot/tests/test_g8_consultation_answer.py",
    "__tests__/useChatConversations.test.tsx",
    "__tests__/chatProducts.test.ts",
    "__tests__/chatProductDetail.test.tsx",
    "docs/ai-design/G8-IMPLEMENTATION-SPEC.md",
    "docs/ai-design/G8-WORKLOG.md",
])
paths = sorted(p for p in paths if (ROOT / p).is_file())
diff = subprocess.check_output(["git", "diff", "--binary", "HEAD", "--", *paths], cwd=ROOT)
(OUT / f"{PREFIX}-source.diff").write_bytes(diff)
untracked = subprocess.check_output(
    ["git", "ls-files", "--others", "--exclude-standard", "-z"], cwd=ROOT
).decode().split("\0")
write("new-sources", [{"path": p, "content": (ROOT / p).read_text(encoding="utf-8")}
                      for p in paths if p in untracked])
tests = []
for f in sorted(list(OUT.glob(f"{PREFIX}-*.xml")) + list(OUT.glob("integration-*-pg*.xml"))):
    suite = ET.parse(f).getroot().find("testsuite")
    tests.append({"path": f.relative_to(ROOT).as_posix(), **suite.attrib})
record = {
    "case": "G8-PRICE-FOLLOWUP-AND-INTEGRATION-20261127",
    "at": datetime.now(timezone.utc).isoformat(),
    "head": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT).decode().strip(),
    "uncommitted": True, "stage": "5 cooperation; 6 partial integration evidence; G8 incomplete",
    "sourceSha256": [{"path": p, "sha256": hashlib.sha256((ROOT / p).read_bytes()).hexdigest()} for p in paths],
    "sourceDiff": f"reports/g8/parent/{PREFIX}-source.diff",
    "untrackedSources": f"reports/g8/parent/{PREFIX}-new-sources.json",
    "tests": tests,
    "static": {"ruff": "PASS", "importLinter": "3 PASS", "typecheck": "PASS", "lint": "PASS"},
    "appMock": {"initialPassed":61,"initialTimeout":1,"affectedFileRetryPassed":32},
    "models": {"planner":"gpt-6-luna","g5":"gpt-6.1-terra", "configuredMode":"live",
       "priceCalls":[3,2,3], "n01InitialCalls":[1,2], "n01FinalCalls":[1,6],
       "e01InitialCalls":[1],"e01FinalCalls":[1,3],"observedRemoteHttpTotal":23,
       "apiInternalEmbeddingCalls":"not instrumented"},
    "n01": {"pg":"live", "auth":"mock", "catalog":"live", "knowledge":"live partial",
       "outcome":"PARTIAL: knowledge suggestion ceramide unresolved; 10 options unknown; no eligible recommendation",
       "dataVersion":"local-20261104-conservative-v1-20261123T111457291156Z"},
    "n02": {"salePg":"PASS live Catalog/PG; disabled model, 0 calls; mock auth",
       "ownedPg":"PASS mock Catalog/model; live PG",
       "loginApp":"actual login; recommendation card PASS; restoration loading persists after GET 200",
       "appModelConfiguredMode":"live","appActualCallsPerTurn":[0,0,0],
       "restoredCardDetail":"NOT_RUN this turn"},
    "e01":{"pg":"live","catalog":"live","model":"live","auth":"mock",
       "failure":"injected Style failure", "outcome":"PASS comparison preserved; style-only retry"},
    "b01":{"passed":83,"pg":"live for consent/ownership/replay/cancel cases",
       "authModel":"mock","ar":"mock command/ack; device NOT_RUN"},
    "remaining":["N01 unresolved knowledge condition fallback policy", "login app restoration loading",
       "all four scenarios full login-app E2E", "Expo Go/AR device", "human review"],
    "runtimeCleanup":"G5 API19838 and temporary relay19841 closed; see cleanup JSON",
    "security":"empty-ignore scan required before immutable trace append",
    "commitPushPr":"NOT_RUN"
}
write("record", record)
print("Preserved", len(paths), "source identities")

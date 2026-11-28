"""Preserve the tested working tree identity without environment or credentials."""
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import subprocess
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[3]
OUT = ROOT / "reports/g8/parent"
PREFIX = "common-comparison-selection"

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
for f in sorted(OUT.glob(f"{PREFIX}-*.xml")):
    suite = ET.parse(f).getroot().find("testsuite")
    tests.append({"path": f.relative_to(ROOT).as_posix(), **suite.attrib})
record = {
    "case": "G8-COMPARISON-SCOPED-SELECTION-AND-SALE-RESTORE",
    "at": datetime.now(timezone.utc).isoformat(),
    "head": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT).decode().strip(),
    "uncommitted": True,
    "stage": "5 cooperation; full G8 incomplete",
    "sourceSha256": [{"path": p, "sha256": hashlib.sha256((ROOT / p).read_bytes()).hexdigest()}
                     for p in paths],
    "sourceDiff": f"reports/g8/parent/{PREFIX}-source.diff",
    "untrackedSources": f"reports/g8/parent/{PREFIX}-new-sources.json",
    "tests": tests,
    "staticChecks": {"ruff": "PASS", "importLinter": "3 PASS", "typecheck": "PASS", "lint": "PASS"},
    "appMock": {"suites": 3, "passed": 62, "seconds": 21.913},
    "liveModel": {"model": "gpt-6-luna", "configuredMode": "live", "failedAttemptCalls": [3, 2],
                  "finalCalls": [3, 2, 3], "actualCallsTotal": 13, "auth": "mock"},
    "salePg": {"modelConfiguredMode": "disabled", "actualModelCalls": 0,
               "catalog": "live", "pg": "live", "auth": "mock"},
    "loginWebApp": {"modelConfiguredMode": "live", "actualModelCallsPerRecordedTurn": [0, 0, 0],
                    "catalog": "live", "pg": "live", "auth": "existing real login",
                    "restoreAndDetail": "PASS", "evidenceKind": "accessibility snapshot",
                    "productId": "oy-a000000162667", "optionId": "A000000162667-012",
                    "priceKRW": 17000, "priceBasis": "collected_snapshot", "arShadeId": None,
                    "runtimeDifference": "Server started before final unrelated comparison child-question isolation change"},
    "notRun": ["Expo Go", "full G8 acceptance", "human review", "multi-turn current-price intent retention"],
    "unverified": ["Catalog deployment SHA", "data release version"],
    "security": "Append only after empty-ignore Gitleaks scan; prior trace preserved",
    "commitPushPr": "NOT_RUN",
}
write("record", record)
print("Preserved", len(paths), "source identities")

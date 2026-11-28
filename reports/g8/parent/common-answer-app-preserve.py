"""Freeze exact sources and distinguish real browser, real API and mock results."""
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
import subprocess
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[3]
OUT = ROOT / "reports/g8/parent"
PREFIX = "common-answer-app-"
def git(*args):
    return subprocess.check_output(["git", *args], cwd=ROOT).decode("utf-8").strip()
paths = set(git("diff", "--name-only", "--", "backend/chatbot").splitlines())
new = git("ls-files", "--others", "--exclude-standard", "--", "backend/chatbot").splitlines()
paths.update(new)
paths.update(["hooks/useChatConversations.ts", "lib/api.ts", "app/chat.tsx", "__tests__/chatProducts.test.ts", "__tests__/useChatConversations.test.tsx", "__tests__/chatProductDetail.test.tsx", "docs/ai-design/G8-IMPLEMENTATION-SPEC.md", "docs/ai-design/G8-WORKLOG.md"])
paths.update(p.relative_to(ROOT).as_posix() for p in OUT.glob(PREFIX + "*.py"))
(OUT / (PREFIX + "source.diff")).write_bytes(subprocess.check_output(["git", "diff", "--", "backend/chatbot", "docs/ai-design/G8-WORKLOG.md", "docs/ai-design/G8-IMPLEMENTATION-SPEC.md"], cwd=ROOT))
(OUT / (PREFIX + "new-sources.json")).write_text(json.dumps([{"path": p, "content": (ROOT / p).read_text(encoding="utf-8")} for p in new], ensure_ascii=False, indent=2), encoding="utf-8")
suites = {}
for p in OUT.glob(PREFIX + "*.xml"):
    suites[p.name] = dict(next(ET.parse(p).iter("testsuite")).attrib)
live = json.loads((OUT / (PREFIX + "live-dialogue.json")).read_text(encoding="utf-8"))
browser = json.loads((OUT / (PREFIX + "pg-browser.json")).read_text(encoding="utf-8"))
record = {
    "case": "G8-COMMON-ANSWER-LOGIN-APP-PARTIAL", "at": datetime.now(timezone.utc).isoformat(),
    "branch": git("branch", "--show-current"), "head": git("rev-parse", "HEAD"),
    "developLocalRef": git("rev-parse", "origin/develop"), "remoteFetched": False,
    "uncommitted": True, "stage": "5-C common answer and app integration; incomplete",
    "sourceSha256": [{"path": p, "sha256": hashlib.sha256((ROOT / p).read_bytes()).hexdigest()} for p in sorted(paths)],
    "sourceDiff": "reports/g8/parent/" + PREFIX + "source.diff",
    "newSources": "reports/g8/parent/" + PREFIX + "new-sources.json",
    "suites": suites, "staticChecks": {"ruff": "PASS", "importContracts": 3, "typecheck": "PASS", "lint": "PASS"},
    "mockApp": {"suites": 3, "testsPassed": 61},
    "apiLive": {"modelConfiguredMode": "live", "model": live["model"], "actualCallsPerTurn": [t["actualRemoteHttpCalls"] for t in live["turns"]], "auth": "mock", "parentSeed": "synthetic", "pg": "live", "catalog": "live"},
    "browserLive": {"modelConfiguredMode": "live", "model": live["model"], "actualCallsPerCompletedTurn": [t["actualModelCalls"] for t in browser["checks"]], "auth": "real_supabase", "parentSeed": "normal_UI", "pg": "live", "catalog": "live", "g5": "disabled", "savedAnswersAndCards": "PASS", "cardsAndProductDetail": "PASS", "recentRoomRestore": "BLOCKED_LOADING", "restoredCardDetail": "NOT_RUN", "saleOptionCase": "NOT_RUN", "screenshots": "CDP_TIMEOUT_accessibility_snapshots_preserved"},
    "incompleteInitialAttempt": "Neo4j connection failure before launcher fix; no completed-turn record or asserted model call count",
    "defects": ["recent conversation loading despite server GET 200; client cause unconfirmed", "toner new search absorbed into existing comparison followup"],
    "notRun": ["Expo Go", "full original G8 evaluation", "human review", "PR"],
    "dataVersion": "local Catalog runtime; release version unconfirmed", "modelSnapshot": "alias only",
}
(OUT / (PREFIX + "record.json")).write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
print("Preserved", len(paths), "source hashes; completed real calls 9 API + 9 browser; UI restoration NOT PASS")

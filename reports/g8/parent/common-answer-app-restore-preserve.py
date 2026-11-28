"""Freeze final restoration evidence without rewriting the earlier blocked record."""
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[3]
OUT = ROOT / "reports/g8/parent"
def git(*args):
    return subprocess.check_output(["git", *args], cwd=ROOT).decode("utf-8").strip()
assert not git("diff", "--", "hooks/useChatConversations.ts", "lib/api.ts")
paths = ["hooks/useChatConversations.ts", "lib/api.ts", "app/chat.tsx", "__tests__/useChatConversations.test.tsx", "__tests__/chatSessionApi.test.ts", "__tests__/chatProductDetail.test.tsx", "docs/ai-design/G8-WORKLOG.md", "docs/ai-design/G8-IMPLEMENTATION-SPEC.md"]
paths += [p.relative_to(ROOT).as_posix() for p in OUT.glob("common-answer-app-restore-*.py")]
diff = OUT / "common-answer-app-restore-source.diff"
diff.write_bytes(subprocess.check_output(["git", "diff", "--", *paths], cwd=ROOT))
restored = (OUT / "common-answer-app-restored-final.txt").read_text(encoding="utf-8")
detail = (OUT / "common-answer-app-restored-detail.txt").read_text(encoding="utf-8")
assert "크림은 15,000원 이하로 맞췄어요" in restored
assert "상담을 불러오는 중이에요" not in restored
assert "다슈 맨즈 아쿠아 리얼 모이스트 올인원크림 153ml" in restored and "₩12,600" in restored
assert "oy-a000000122212" in detail and "₩12,600" in detail
assert len((OUT / "common-answer-app-turns.jsonl").read_text(encoding="utf-8").splitlines()) == 4
record = {"case": "G8-RECENT-ROOM-RESTORE-REAL-APP", "at": datetime.now(timezone.utc).isoformat(), "head": git("rev-parse", "HEAD"), "branch": git("branch", "--show-current"), "uncommitted": True,
    "stage": "5-C restoration and product detail verified; full G8 not complete",
    "sourceSha256": [{"path": p, "sha256": hashlib.sha256((ROOT / p).read_bytes()).hexdigest()} for p in paths],
    "sourceDiff": diff.relative_to(ROOT).as_posix(),
    "runtime": {"webPort": 19836, "chatPort": 19833, "catalogPort": 19834, "pgDatabase": "vishue_g8_browser", "sourceMode": "final product code without diagnostics", "auth": "real_supabase", "modelConfiguredMode": "live", "actualModelCalls": 0, "modelUse": "restoration of earlier live-generated persisted replies; no inference in this run"},
    "actual": {"recentList": "PASS", "roomRestore": "PASS", "loadingEnds": "PASS", "restoredCards": "PASS", "sameProductDetail": "PASS", "productId": "oy-a000000122212", "priceKRW": 12600, "selectionMethod": "visible UI keyboard Enter", "directSqlThisRun": "NOT_RUN"},
    "mock": {"suites": 3, "passed": 41, "authAndHttp": "mock"}, "typecheck": "PASS", "lint": "PASS",
    "diagnosis": "old loading observation preserved; stale dev execution/browser interaction factors observed; unique original root cause not proven; no speculative auth or restore source fix",
    "productFilesChanged": [], "testFilesChanged": ["__tests__/useChatConversations.test.tsx"],
    "priorRecord": "G8-COMMON-ANSWER-LOGIN-APP-PARTIAL",
    "notRun": ["new model calls", "sale option case", "Expo Go", "full G8 evaluation", "human review", "PR"],
    "remainingDefect": "new toner search interpreted as continuation of existing comparison",
    "dataVersion": "existing local catalog runtime; release version unconfirmed",
    "artifacts": ["common-answer-app-restored-final.txt", "common-answer-app-restored-detail.txt", "common-answer-app-restore-phases.json", "common-answer-app-restore-tests.log", "common-answer-app-restore-typecheck.log", "common-answer-app-restore-lint.log"]}
(OUT / "common-answer-app-restore-record.json").write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
print("Final source and restored card/detail evidence preserved")

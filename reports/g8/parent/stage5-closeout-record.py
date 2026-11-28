"""Freeze synthetic live runs and exact WIP sources; do not rewrite historical traces."""
import hashlib
import importlib.util
import json
import re
import subprocess
import xml.etree.ElementTree as ET
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
OUT = ROOT / "reports/g8/parent"
PREFIX = "stage5-closeout"

def git(*args):
    return subprocess.check_output(["git", *args], cwd=ROOT)

def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()

new = git("ls-files", "--others", "--exclude-standard").decode().splitlines()
names = sorted(p for p in set(git("diff", "--name-only", "HEAD").decode().splitlines() + new)
               if not p.startswith("reports/") and (ROOT / p).is_file())
(OUT / f"{PREFIX}-source.diff").write_bytes(git("diff", "--binary", "HEAD", "--", *names))
(OUT / f"{PREFIX}-new-sources.json").write_text(json.dumps([
    {"path": p, "content": (ROOT / p).read_text(encoding="utf-8-sig")}
    for p in new if p in names
], ensure_ascii=False, indent=2), encoding="utf-8")
turns = [json.loads(line) for line in (OUT / f"{PREFIX}-app-turns.jsonl").read_text(encoding="utf-8").splitlines()]
first_b = "이 룩에 필요한 상품을 보유 제품 기준으로 추천해줘. 오후에 화장이 뜨는데 원인 알려주고 나한테 맞는 제품도 찾아줘"
b_start = max(i for i, t in enumerate(turns) if t["utterance"] == first_b)
b_end = next((i for i in range(b_start + 1, len(turns))
              if turns[i]["utterance"].startswith("향료 제외 조건으로")
              or turns[i]["utterance"].startswith("세안 후 보습 순서를")), len(turns))
b = turns[b_start:b_end]
queue_counts = [len(t["parent"]["pendingQuestions"]) for t in b]
transitions = [value for i, value in enumerate(queue_counts) if i == 0 or value != queue_counts[i - 1]]
assert transitions == [3, 2, 1, 0]
assert all(len(t["parent"]["tasks"]) == 2 for t in b)
skin_results = [next(x for x in t["parent"]["tasks"] if x["goal"] == "skin")["displayResult"] for t in b[1:]]
assert skin_results[0] == skin_results[1] == skin_results[2]
assert b[-1]["utterance"] == "없어" and not b[-1]["consultation"]["hasPendingInput"]
assert all(t["consultation"]["status"] == "partial" for t in b[1:])
c = next(t for t in reversed(turns) if t.get("errorCode") == "request_interrupted")
assert c["modelCalls"] and c["catalogCalls"] == []
assert json.loads((OUT / f"{PREFIX}-app-pg.json").read_text(encoding="utf-8"))["result"] == "PASS"
assert "1703 passed" in (OUT / f"{PREFIX}-backend-final-schema.log").read_text(errors="replace")
assert "1352 passed" in (OUT / f"{PREFIX}-app-tests.log").read_text(errors="replace")
http = Counter((call["model"], str(call["status"])) for t in turns for call in t["modelCalls"])
g5 = [json.loads(line) for line in (OUT / f"{PREFIX}-g5-models.jsonl").read_text().splitlines()]
runtime_spec = importlib.util.spec_from_file_location("runtime", OUT / f"{PREFIX}-app-run.py")
runtime = importlib.util.module_from_spec(runtime_spec)
runtime_spec.loader.exec_module(runtime)
env = runtime.environment()
mapping = Path(env["INGREDIENT_MAPPING_PATH"])
record = {
    "at": datetime.now(timezone.utc).isoformat(), "case": "stage5-closeout-20261128",
    "head": git("rev-parse", "HEAD").decode().strip(), "branch": git("branch", "--show-current").decode().strip(),
    "developLocalRef": git("rev-parse", "origin/develop").decode().strip(), "remoteFreshnessChecked": False,
    "uncommitted": True, "stage": "5/7; remaining three closeout cases; stage6 original integration NOT_RUN",
    "sourceSha256": [{"path": p, "sha256": sha(ROOT / p)} for p in names],
    "sourceDiff": f"reports/g8/parent/{PREFIX}-source.diff",
    "untrackedSources": f"reports/g8/parent/{PREFIX}-new-sources.json",
    "modelConfiguredMode": "live", "replayTurns": 0, "mockTurns": 0,
    "actualChatbotModelHttpStarts": sum(http.values()),
    "actualChatbotModelHttp": [{"model": k[0], "status": k[1], "count": v} for k, v in sorted(http.items())],
    "actualG5ApiHttpStarts": [dict(model=model, count=sum(e["event"] == "start" and e["model"] == model for e in g5))
                               for model in sorted({e["model"] for e in g5})],
    "counting": "HTTP send starts, including rejected/retried/cancelled work. Provider billing not inferred. G5 generation runs in chatbot and is included in its counts; G5 API embedding calls separate.",
    "turns": [{"index": i + 1, "at": t["at"], "utterance": t["utterance"], "mode": "live",
               "modelHttpStarts": len(t["modelCalls"]), "catalogHttpStarts": len(t["catalogCalls"]),
               "summary": t.get("consultation"), "errorCode": t.get("errorCode"),
               "sourceSnapshot": t["sourceSnapshot"],
               "differentFinalAppSources": [entry["path"] for entry in json.loads((OUT / t["sourceSnapshot"]).read_text())
                                            if sha(ROOT / entry["path"]) != entry["sha256"]]}
              for i, t in enumerate(turns)],
    "validation": {"backend": "1703 PASS/135 SKIP final source; real scheduler, mostly mock external services",
                   "app": "1352 PASS/108 suites; typecheck/lint PASS; synthetic UI services",
                   "pg": "28 PASS/5 SKIP actual disposable PG/mock auth+models; complete file, no duplicate totals",
                   "loggedInApp": "A typed ingredient/kind inputs+budget+clear/retry; B three questions through all answers and restore; C actual model in-flight cancel/new request/latest summary restore",
                   "static": "ruff PASS/import contracts 3 KEPT"},
    "finalB": {"firstTurnIndex": b_start + 1, "queueCounts": queue_counts, "acceptedQueueTransitions": transitions,
               "skinPayloadUnchangedAfterAnswer": True},
    "sourceBoundaries": "Each live turn pins startup app hashes. B predates final role descriptions and nullable unused product quote; queue/storage logic is unchanged. Final A clear and C pin final app source. Do not label every historical turn exact final source. No frontend production edits this task.",
    "data": {"mappingArtifact": mapping.name, "mappingSha256": sha(mapping), "globalDbSnapshot": "not pinned",
             "catalogAndG5": "actual current worktree API endpoints; precise option/ingredient/source versions retained in payloads; no DB data or reviewed recipe edits"},
    "failuresPreserved": ["initial optionSearch omission broad fallback fixed", "ingredient-clear invalid specialist JSON rejected; explicit retry succeeded",
                          "selected-look scope prevented skin dispatch fixed", "request-type change skipped owned memory read fixed",
                          "sibling global filter change invalidated skin result fixed", "initial rejection persisted empty parent and skipped replanning fixed",
                          "specialist actual clarification was replaced by generic text fixed", "short ownership target fell through legacy single-goal parent fixed",
                          "first planner split symptom explanation from personalized search; common workflow guidance clarified and live rerun retained",
                          "final B explicit ownership+preserve wording proposed update and preserve for same task; safely rejected without state changes; short explicit answers recovered",
                          "backend default pytest temp directory permission errors; unique temp rerun PASS", "new scope test missing issuedAt fixture corrected",
                          "PG audit used nonexisting excludedIngredients instead of ingredientConditions; helper corrected"],
    "remaining": ["stage6 original14 abilities/12 scenarios and N01/N02/E01/B01 continuous final-source integration",
                  "holdout expression reliability incl rejected model plans", "native mobile, performance/multi-worker, required human review",
                  "unverified ingredient/usage/alternative/AR evidence stays unknown; no fabricated product match",
                  "transient stale memory-change/new-search UI notice and slow recent restore observed; not silently marked fixed",
                  "automatic checkpoint recovery and hard cancellation of already-started specialist HTTP remain unsupported"],
    "commitPushPr": "NOT_RUN", "security": "Gitleaks8.30.1 empty ignore + known runtime secret/privacy checks before immutable append",
}
record["executions"] = [
    {"artifact": p.name, "sha256": sha(p),
     "suites": [dict(s.attrib) for s in ET.parse(p).getroot().iter("testsuite")]}
    for p in (OUT / "stage5-closeout-backend-final-schema.xml", OUT / "stage5-closeout-pg-complete.xml")
]
record["artifactSha256"] = [
    {"path": p.relative_to(ROOT).as_posix(), "sha256": sha(p)}
    for p in sorted(OUT.glob(f"{PREFIX}-*"))
    if p.is_file() and p.name not in {f"{PREFIX}-record.json", f"{PREFIX}-security.log"}
]
(OUT / f"{PREFIX}-record.json").write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")

def strings(value):
    if isinstance(value, str): return [value]
    if isinstance(value, list): return [s for item in value for s in strings(item)]
    if isinstance(value, dict): return [s for item in value.values() for s in strings(item)]
    return []

raw = []
paths = [p for p in OUT.glob(f"{PREFIX}-*") if p.is_file()]
for p in paths:
    text = p.read_text(encoding="utf-8-sig", errors="replace")
    if p.suffix == ".json": raw.extend(strings(json.loads(text)))
    elif p.suffix == ".jsonl": raw.extend(s for line in text.splitlines() for s in strings(json.loads(line)))
    elif p.suffix == ".diff": raw.append("\n".join(line[1:] if line.startswith(("+", "-", " ")) else line for line in text.splitlines()))
    else: raw.append(text)
patterns = [r"[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}", r"Bearer\s+eyJ",
            r"eyJ[A-Za-z0-9_-]+\.eyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+", r"^-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"]
assert not any(re.search(pattern, text, re.I | re.M) for text in raw for pattern in patterns), "Privacy pattern found; contents withheld"
secrets = [v for k, v in env.items() if k in ("LLM_API_KEY", "G5_OPENAI_API_KEY", "G5_INTERNAL_TOKEN", "DATABASE_URL", "CHAT_DATABASE_URL") and len(v) > 12]
assert not any(secret in text for secret in secrets for text in raw), "Runtime secret found; contents withheld"
print("PASS", len(names), "source hashes;", len(paths), "evidence files;", sum(http.values()), "chatbot HTTP starts; privacy/known secrets absent")

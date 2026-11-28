"""Read-only PG evidence for this synthetic browser run; account IDs are omitted."""
import importlib.util
import json
from pathlib import Path
import sys

import psycopg
from sqlalchemy.engine import make_url

ROOT = Path(__file__).resolve().parents[3]
OUT = ROOT / "reports/g8/parent"
spec = importlib.util.spec_from_file_location("runtime", OUT / "stage6-remediation-runtime.py")
runtime = importlib.util.module_from_spec(spec)
spec.loader.exec_module(runtime)
sys.path.insert(0, str(ROOT / "backend/chatbot"))
from app.schemas.consultation_parent import ConsultationParent

rows = [json.loads(line) for line in (OUT / "stage6-remediation-app-turns.jsonl").read_text(encoding="utf-8").splitlines()]
baseline = json.loads((OUT / "stage6-remediation-baseline.json").read_text(encoding="utf-8"))
url = make_url(runtime.environment()["CHAT_DATABASE_URL"]).set(drivername="postgresql")
assert url.database == "vishue_g8_browser"
observations, rooms = [], {}
with psycopg.connect(url.render_as_string(hide_password=False)) as conn:
    conn.execute("SET TRANSACTION READ ONLY")
    for index, row in enumerate(rows):
        saved = None if row.get("errorCode") else conn.execute("SELECT conversation_id FROM chat_messages WHERE role='user' AND text=%s AND created_at >= %s ORDER BY created_at LIMIT 1", (row["utterance"], row["startedAt"])).fetchone()
        if saved is None and row.get("answer"):
            saved = conn.execute("SELECT conversation_id FROM chat_messages WHERE role='assistant' AND text=%s AND created_at >= %s ORDER BY created_at LIMIT 1", (row["answer"], row["startedAt"])).fetchone()
        entry = {"row": index, "utterance": row["utterance"], "error": row.get("errorCode"), "savedMessageFound": saved is not None}
        if saved is not None:
            cid = saved[0]
            if cid not in rooms:
                context = conn.execute("SELECT context_json FROM chat_conversations WHERE id=%s", (cid,)).fetchone()[0]
                messages = conn.execute("SELECT role,text,display_payload FROM chat_messages WHERE conversation_id=%s ORDER BY sequence", (cid,)).fetchall()
                turns = conn.execute("SELECT status,error_code,base_version,committed_version FROM chat_turns WHERE conversation_id=%s AND created_at >= %s ORDER BY created_at", (cid, baseline["at"])).fetchall()
                rooms[cid] = {"ref": f"room-{len(rooms)+1}", "context": context, "messages": messages, "turns": turns, "last": None}
            room = rooms[cid]
            entry["room"] = room["ref"]
            entry["exactAnswerSaved"] = any(role == "assistant" and text == row.get("answer") for role, text, payload in room["messages"])
            if entry["exactAnswerSaved"]:
                room["last"] = row
        observations.append(entry)
    totals = {"tables": {name: conn.execute("SELECT count(*) FROM " + name).fetchone()[0] for name in ["chat_memories", "chat_memory_proposals", "chat_turns"]}, "memoryWriteTurns": conn.execute("SELECT count(*) FROM chat_turns WHERE operation LIKE 'memory_%'").fetchone()[0]}
    cancelled = conn.execute("SELECT status,error_code,base_version,committed_version FROM chat_turns WHERE created_at >= %s AND operation='chat' ORDER BY created_at", (baseline["at"],)).fetchall()

room_results = []
for room in rooms.values():
    latest = room["last"]
    parent = room["context"].get("consultationParent")
    expected = latest.get("parent") if latest else None
    same_parent = (ConsultationParent.model_validate(parent).model_dump(mode="json") == ConsultationParent.model_validate(expected).model_dump(mode="json")) if parent and expected else parent is None and expected is None
    room_results.append({"room": room["ref"], "parentEqualsLastSavedAppResponse": same_parent, "messages": [{"role": role, "text": text} for role, text, payload in room["messages"]], "turns": [{"status": s, "errorCode": e, "baseVersion": b, "committedVersion": c} for s, e, b, c in room["turns"]]})
before = json.loads((OUT / "stage6-remediation-write-baseline.json").read_text(encoding="utf-8"))
checks = {"allLocatedAnswersSavedExactly": all(item.get("exactAnswerSaved", True) for item in observations if item.get("savedMessageFound") and not item.get("error")), "allLocatedParentsMatch": all(room["parentEqualsLastSavedAppResponse"] for room in room_results), "noMemoryRowsAdded": totals["tables"]["chat_memories"] == before["tables"]["chat_memories"], "noMemoryWriteTurnsAdded": totals["memoryWriteTurns"] == before["memoryWriteTurns"], "interruptedTurnsNotCommitted": all(c is None for s, e, b, c in cancelled if s == "INTERRUPTED")}
result = {"database": url.database, "mode": "actual authenticated app + actual PG; read-only comparison", "checks": checks, "rows": observations, "rooms": room_results, "aggregateBefore": before, "aggregateAfter": totals, "allRunTurnStates": [{"status": s, "errorCode": e, "baseVersion": b, "committedVersion": c} for s, e, b, c in cancelled]}
(OUT / "stage6-remediation-pg-review.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
print(json.dumps({"checks": checks, "locatedRooms": len(room_results), "rows": len(rows)}, ensure_ascii=False))

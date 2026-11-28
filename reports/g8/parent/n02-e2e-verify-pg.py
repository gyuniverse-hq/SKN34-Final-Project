"""Read-only actual browser conversation verification, without account identifiers."""
import json
from pathlib import Path
import runpy
from datetime import datetime, timezone
import psycopg
from sqlalchemy.engine import make_url

ROOT = Path(__file__).resolve().parents[3]
OUT = ROOT / "reports/g8/parent"
m = runpy.run_path(str(OUT / "n02-e2e-run.py"))
url = make_url(m["environment"]()["CHAT_DATABASE_URL"]).set(drivername="postgresql")
assert url.database == "vishue_g8_browser"
runtime = json.loads((OUT / "n02-e2e-runtime.json").read_text())
live = [json.loads(s) for s in (OUT / "n02-e2e-turns.jsonl").read_text(encoding="utf-8").splitlines()][runtime["finalSourceStartRow"]:]
live = live[:3]  # Reloading a look entry may start its automatic guide in a new room.
assert [len(r["modelCalls"]) for r in live] == [0, 1, 0]
assert all(r["requestType"] == "style_consultation" and r["hasG7Execution"] for r in live)
assert all(r["sessionStatus"] != "unavailable" for r in live)
assert [len(r["products"]) for r in live] == [2, 1, 1]
assert live[1]["ownedLookContext"]["exceptions"] == live[2]["ownedLookContext"]["exceptions"]
with psycopg.connect(url.render_as_string(hide_password=False), options="-c default_transaction_read_only=on -c statement_timeout=5000") as conn:
    room = conn.execute("select c.id,c.conversation_version,c.subject_json,c.context_json from chat_conversations c where exists (select 1 from chat_messages m where m.conversation_id=c.id and m.role='assistant' and m.text=%s) order by c.created_at desc limit 1", (live[-1]["answer"],)).fetchone()
    messages = conn.execute("select sequence,role,text,display_payload from chat_messages where conversation_id=%s order by sequence", (room[0],)).fetchall()
    turns = conn.execute("select operation,status,committed_version from chat_turns where conversation_id=%s order by created_at", (room[0],)).fetchall()
    assert len(messages) == 6
    replies = [r for r in messages if r[1] == "assistant"]
    for saved, actual in zip(replies, live, strict=True):
        assert saved[2] == actual["answer"]
        assert saved[3]["ownedLookOptions"] == actual["options"]
    assert room[3]["ownedLook"]["exceptions"] == live[-1]["ownedLookContext"]["exceptions"]
    assert room[3]["ownedLook"]["filters"]["maxPriceKRW"] == 30000
    assert all(t[1] == "COMMITTED" for t in turns)
    report = {"at":datetime.now(timezone.utc).isoformat(), "database":"vishue_g8_browser", "readOnly":True,
              "version":room[1], "subject":room[2], "ownedLook":room[3]["ownedLook"],
              "parent":room[3]["consultationParent"], "turns":[{"operation":t[0],"status":t[1],"version":t[2]} for t in turns],
              "messages":[{"sequence":r[0],"role":r[1],"text":r[2],"options":r[3].get("ownedLookOptions")} for r in messages],
              "checks":{"savedAnswersEqualLive":True,"savedOptionsEqualLive":True,"exceptionsPreserved":True,"budget":30000},
              "modelConfigured":"live", "actualCallsPerTurn":[0,1,0], "auth":"real_supabase"}
    (OUT / "n02-e2e-pg-final.json").write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding="utf-8")
print("PASS: actual browser PG messages, options, exceptions, budget; live model calls 0/1/0")

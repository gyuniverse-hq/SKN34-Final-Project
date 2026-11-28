"""Compare synthetic browser utterances with real saved replies, without owner IDs."""
import json
import runpy
from datetime import datetime, timezone
from pathlib import Path

import psycopg
from sqlalchemy.engine import make_url

ROOT = Path(__file__).resolve().parents[3]
OUT = ROOT / "reports/g8/parent"
env = runpy.run_path(str(OUT / "common-answer-app-run.py"))["environment"]()
url = make_url(env["CHAT_DATABASE_URL"]).set(drivername="postgresql")
assert url.database == "vishue_g8_browser"
actual = [json.loads(line) for line in (OUT / "common-answer-app-turns.jsonl").read_text(encoding="utf-8").splitlines()]
checks = []
with psycopg.connect(url.render_as_string(hide_password=False), options="-c default_transaction_read_only=on -c statement_timeout=5000") as conn:
    for index, turn in enumerate(actual):
        saved = conn.execute("select m.text,m.display_payload,c.context_json from chat_messages m join chat_conversations c on c.id=m.conversation_id where m.role='assistant' and m.text=%s order by m.created_at desc limit 1", (turn["answer"],)).fetchone()
        assert saved, f"Missing saved answer for turn {index}"
        payload = saved[1]
        # Store only comparisons, never account IDs, tokens or unrelated conversations.
        expected_ids = [p["id"] for p in turn["products"]]
        saved_ids = [p["id"] for p in payload.get("products", [])]
        assert expected_ids == saved_ids
        checks.append({"turn": index, "question": turn["utterance"], "answerEqual": saved[0] == turn["answer"], "productIdsEqual": True, "productCount": len(saved_ids), "styleCardsEqual": payload.get("styleCandidates", []) == turn["styleCandidates"], "modelConfiguredMode": "live", "actualModelCalls": len(turn["modelCalls"]), "parentPresentInFinalRoom": saved[2].get("consultationParent") is not None})
record = {"at": datetime.now(timezone.utc).isoformat(), "database": "vishue_g8_browser", "readOnly": True, "auth": "real_supabase_browser", "catalog": "live_local", "checks": checks, "appRestore": "BLOCKED_LOADING", "note": "SQL equality is not evidence of successful UI restoration."}
(OUT / "common-answer-app-pg-browser.json").write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
print("Verified saved browser replies and product cards:", len(checks))

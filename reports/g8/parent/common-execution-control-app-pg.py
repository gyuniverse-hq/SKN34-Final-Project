"""Read only the synthetic replacement conversation; omit account identifiers."""
import importlib.util
import json
from datetime import datetime, timezone
from pathlib import Path

import psycopg
from sqlalchemy.engine import make_url

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("runtime", HERE / "common-execution-control-app-run.py")
runtime = importlib.util.module_from_spec(spec)
spec.loader.exec_module(runtime)
url = make_url(runtime.environment()["CHAT_DATABASE_URL"]).set(drivername="postgresql")
assert url.database == "vishue_g8_browser"
with psycopg.connect(url.render_as_string(hide_password=False)) as conn:
    conn.execute("SET TRANSACTION READ ONLY")
    cid = conn.execute("SELECT conversation_id FROM chat_messages WHERE role='user' AND text=%s AND created_at >= %s ORDER BY created_at DESC LIMIT 1", ("토너 찾아줘. 크림도 찾아줘", "2026-11-27T15:34:00Z")).fetchone()[0]
    turns = conn.execute("SELECT request_id,status,error_code,base_version,committed_version FROM chat_turns WHERE conversation_id=%s AND operation='chat' ORDER BY created_at", (cid,)).fetchall()
    messages = conn.execute("SELECT role,text,display_payload,request_id FROM chat_messages WHERE conversation_id=%s ORDER BY sequence", (cid,)).fetchall()
    assert len(turns) == 2 and [row[1] for row in turns] == ["INTERRUPTED", "COMMITTED"]
    assert turns[0][2] == "user_cancelled" and turns[0][0] != turns[1][0]
    assert len(messages) == 2 and all(row[3] == turns[1][0] for row in messages)
    assert messages[0][1] == "토너 찾아줘. 크림도 찾아줘"
    record = {"at": datetime.now(timezone.utc).isoformat(), "database": url.database,
              "mode": "actual PostgreSQL / actual login app", "checks": "PASS",
              "turns": [{"status": r[1], "errorCode": r[2], "baseVersion": r[3], "committedVersion": r[4]} for r in turns],
              "differentRequestIds": True, "cancelledMessages": 0,
              "messages": [{"role":r[0], "text":r[1], "displayPayload":r[2]} for r in messages]}
(HERE / "common-execution-control-app-pg.json").write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
print("PASS: interrupted then committed; distinct requests; only replacement user/assistant persisted")

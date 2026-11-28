"""Read only the synthetic conversation exercised in this validation; omit account IDs."""
import importlib.util
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import psycopg
from sqlalchemy.engine import make_url

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("runtime", HERE / "question-scope-answer-app-run.py")
runtime = importlib.util.module_from_spec(spec)
spec.loader.exec_module(runtime)
url = make_url(runtime.environment()["CHAT_DATABASE_URL"]).set(drivername="postgresql")
assert url.database == "vishue_g8_browser"
utterance = "이 룩에 필요한 상품을 보유 제품 기준으로 추천해줘. 오후에 화장이 뜨는데 원인 알려주고 나한테 맞는 제품도 찾아줘"
with psycopg.connect(url.render_as_string(hide_password=False)) as conn:
    conn.execute("SET TRANSACTION READ ONLY")
    row = conn.execute("SELECT conversation_id FROM chat_messages WHERE role='user' AND text=%s "
        "AND created_at >= %s ORDER BY created_at DESC LIMIT 1",
        (utterance, "2026-11-27T17:50:00Z")).fetchone()
    assert row
    cid = row[0]
    messages = conn.execute("SELECT role,text,display_payload FROM chat_messages "
        "WHERE conversation_id=%s ORDER BY sequence", (cid,)).fetchall()
    context = conn.execute("SELECT context_json FROM chat_conversations WHERE id=%s",(cid,)).fetchone()[0]
    turns = conn.execute("SELECT status,error_code,base_version,committed_version FROM chat_turns "
        "WHERE conversation_id=%s AND operation='chat' ORDER BY created_at", (cid,)).fetchall()
parent = context["consultationParent"]
skin = next(t for t in parent["tasks"] if t["goal"] == "skin")
look = next(t for t in parent["tasks"] if t["goal"] == "owned_look")
assert skin["displayResult"] and look["displayResult"]
declarations = context["ownedLook"]["itemDeclarations"]
assert all(d["scope"] == "option" for d in declarations.values())
selections = look["displayResult"].get("ownedLookOptions",{}).get("selections",[])
assert any(s["optionId"] == "A000000162667-012" for s in selections)
filename = sys.argv[1] if len(sys.argv) > 1 else "question-scope-answer-app-pg.json"
assert filename.startswith("question-scope-answer-") and "/" not in filename
(HERE / filename).write_text(json.dumps({
    "at":datetime.now(timezone.utc).isoformat(),"mode":"actual PG / actual logged-in app",
    "result":"PASS", "parent":parent, "ownedLook":context["ownedLook"],
    "compound":context.get("compound"), "turns":[{"status":r[0],"errorCode":r[1],
        "baseVersion":r[2],"committedVersion":r[3]} for r in turns],
    "messages":[{"role":r[0],"text":r[1],"displayPayload":r[2]} for r in messages]},
    ensure_ascii=False,indent=2),encoding="utf-8")
print("PASS persisted exact option and server question/context; account identifiers omitted")

"""Read the approved synthetic app conversations, without exporting owner IDs."""
import importlib.util
import json
from datetime import datetime, timezone
from pathlib import Path

import psycopg
from sqlalchemy.engine import make_url

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("runtime", HERE / "stage5-closeout-app-run.py")
runtime = importlib.util.module_from_spec(spec)
spec.loader.exec_module(runtime)
url = make_url(runtime.environment()["CHAT_DATABASE_URL"]).set(drivername="postgresql")
assert url.database == "vishue_g8_browser"
selectors = {
    "A": "향료 제외 조건으로 토너 찾아줘. 같은 조건으로 크림도 찾아줘",
    "B": "이 룩에 필요한 상품을 보유 제품 기준으로 추천해줘. 오후에 화장이 뜨는데 원인 알려주고 나한테 맞는 제품도 찾아줘",
    "C": "토너 찾아줘. 크림도 찾아줘",
}
records = []
with psycopg.connect(url.render_as_string(hide_password=False)) as conn:
    conn.execute("SET TRANSACTION READ ONLY")
    for case, utterance in selectors.items():
        row = conn.execute(
            "SELECT conversation_id FROM chat_messages WHERE role='user' AND text=%s "
            "AND created_at >= %s ORDER BY created_at DESC LIMIT 1",
            (utterance, "2026-11-27T16:00:00Z"),
        ).fetchone()
        assert row, case
        cid = row[0]
        messages = conn.execute(
            "SELECT role,text,display_payload,request_id FROM chat_messages "
            "WHERE conversation_id=%s ORDER BY sequence", (cid,),
        ).fetchall()
        context = conn.execute(
            "SELECT context_json FROM chat_conversations WHERE id=%s", (cid,),
        ).fetchone()[0]
        parent = context["consultationParent"]
        turns = conn.execute(
            "SELECT status,error_code,base_version,committed_version,request_id "
            "FROM chat_turns WHERE conversation_id=%s AND operation='chat' ORDER BY created_at",
            (cid,),
        ).fetchall()
        summary = messages[-1][2]["consultation"]
        if case == "A":
            toner = next(t for t in parent["tasks"] if t["productRequirement"]["kind"] == "toner")
            cream = next(t for t in parent["tasks"] if t["productRequirement"]["kind"] == "cream")
            assert toner["productContext"]["filters"]["ingredientConditions"] == [
                {"operator": "excludes", "ingredientName": "향료"}
            ]
            assert cream["productContext"]["filters"]["maxPriceKRW"] == 20000
            assert not cream["productContext"]["filters"].get("excludedIngredients")
            assert not cream["productContext"]["filters"].get("ingredientConditions")
        if case == "B":
            assert len(parent["tasks"]) == 2
            skin = next(t for t in parent["tasks"] if t["goal"] == "skin")
            assert skin["status"] == "partial" and skin["displayResult"]
            assert all(q["inputKey"] == "ownership" for q in parent["pendingQuestions"])
            assert all(q.get("needId") and q.get("recipeVersion") and q["ownershipScope"] == "option"
                       for q in parent["pendingQuestions"])
        if case == "C":
            assert [r[0] for r in turns] == ["INTERRUPTED", "COMMITTED"]
            assert turns[0][1] == "user_cancelled"
            assert len(messages) == 2 and all(m[3] == turns[1][4] for m in messages)
            assert summary["status"] == "completed"
            assert len(parent["tasks"]) == 2 and all(t["status"] == "completed" for t in parent["tasks"])
        records.append({
            "case": case, "parent": parent, "summary": summary,
            "ownedLook": context.get("ownedLook"),
            "turns": [{"status": r[0], "errorCode": r[1], "baseVersion": r[2],
                       "committedVersion": r[3]} for r in turns],
            "messages": [{"role": m[0], "text": m[1], "displayPayload": m[2]} for m in messages],
        })
(HERE / "stage5-closeout-app-pg.json").write_text(json.dumps({
    "at": datetime.now(timezone.utc).isoformat(), "mode": "actual PG / actual login app",
    "result": "PASS", "sessions": records,
}, ensure_ascii=False, indent=2), encoding="utf-8")
print("PASS A conditions; B remaining question identity; C cancellation and latest persisted summary")

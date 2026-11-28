"""Evidence comparison and scoped cleanup; never synthesizes an assistant answer."""

import hashlib
import json
import subprocess
import sys
from pathlib import Path

import prepare_data as data

OUT, ROOT = data.OUT, data.ROOT


def rows():
    return [
        json.loads(line) for line in (OUT / "trace.jsonl").read_text(encoding="utf-8").splitlines()
    ]


def verify():
    import psycopg
    from sqlalchemy.engine import make_url

    events = rows()
    starts = [row for row in events if row["kind"] == "turn_start"]
    finals = {row["turn"]: row for row in events if row["kind"] in ("turn_end", "turn_error")}
    turns = [finals.get(row["turn"], {**row, "code": "NO_FINAL_SERVICE_EVENT"}) for row in starts]
    manifest = json.loads((OUT / "manifest.json").read_text(encoding="utf-8"))
    source_ok = all(
        hashlib.sha256((ROOT / item["path"]).read_bytes()).hexdigest() == item["sha256"]
        for item in manifest["sources"]
    )
    url = make_url(data.clone_url(data.DATABASES["chat"])).set(drivername="postgresql")
    saved = []
    with psycopg.connect(url.render_as_string(hide_password=False)) as conn:
        conn.execute("SET TRANSACTION READ ONLY")
        for index, row in enumerate(turns):
            matches = (
                conn.execute(
                    "SELECT conversation_id,display_payload FROM chat_messages "
                    "WHERE role='assistant' AND text=%s AND created_at >= %s ORDER BY created_at",
                    (row.get("answer", ""), starts[index]["at"]),
                ).fetchall()
                if row.get("answer")
                else []
            )
            saved.append(
                {
                    "turn": row["turn"],
                    "row": index,
                    "exactAnswerSaved": bool(matches),
                    "error": row.get("code"),
                    "displayPayloads": [payload for _, payload in matches],
                }
            )
        states = conn.execute(
            "SELECT status,error_code,committed_version FROM chat_turns ORDER BY created_at"
        ).fetchall()
        counts = {
            table: conn.execute("SELECT count(*) FROM " + table).fetchone()[0]
            for table in (
                "chat_messages",
                "chat_conversations",
                "chat_memories",
                "chat_memory_proposals",
            )
        }
        contexts = conn.execute(
            "SELECT context_json FROM chat_conversations ORDER BY created_at"
        ).fetchall()
    result_path = OUT / "verification.json"
    result = json.loads(result_path.read_text(encoding="utf-8")) if result_path.exists() else {}
    result.update(
        sourceUnchanged=source_ok,
        actualModelStarts=sum(row["kind"] == "model_start" for row in events),
        actualModelEnds=sum(row["kind"] == "model_end" for row in events),
        modelCounts={
            name: sum(row["kind"] == "model_start" and row.get("model") == name for row in events)
            for name in {row.get("model") for row in events if row["kind"] == "model_start"}
        },
        pg={
            "database": data.DATABASES["chat"],
            "mode": "actual PG; read-only evidence comparison",
            "saved": saved,
            "counts": counts,
            "turnStates": [{"status": s, "error": e, "committedVersion": v} for s, e, v in states],
            "interruptedNotCommitted": all(v is None for s, e, v in states if s == "INTERRUPTED"),
            "contexts": [context for (context,) in contexts],
        },
    )
    result_path.write_text(
        json.dumps(result, ensure_ascii=False, indent=2, default=str), encoding="utf-8"
    )
    blocks = []
    attribution = []
    for index, event in enumerate(events):
        if event["kind"] != "model_start":
            continue
        turn = event.get("turn")
        method = "direct ContextVar"
        if turn is None and event.get("role") == "g5":
            # G5 runs in another process. These fixed flows have serial search requests.
            later_search = next(
                (
                    r
                    for r in events[index + 1 :]
                    if r["kind"] == "tool_http" and r.get("path") == "/internal/knowledge/search"
                ),
                None,
            )
            if later_search:
                turn = later_search["turn"]
                method = "correlated to next serial G5 search completion; not propagated ID"
        attribution.append(
            {"eventIndex": index, "turn": turn, "model": event["model"], "method": method}
        )
    for i, row in enumerate(turns):
        own = [event for event in attribution if event.get("turn") == row["turn"]]
        saved_answer = saved[i]["exactAnswerSaved"]
        blocks.append(
            f"TURN {i + 1} | {row['turn']} | live configured; actual model HTTP starts="
            f"{len(own)} | {row['at']}\n"
            f"USER: {row['question']}\n"
            + (
                "ASSISTANT (PG saved exactly): " + row["answer"]
                if saved_answer
                else "NO SAVED FINAL ANSWER: " + row.get("code", "discarded/unconfirmed")
            )
        )
        if row.get("answer") and not saved_answer:
            blocks[-1] += "\nSERVER GENERATED ONLY (not a delivered answer): " + row["answer"]
    result["modelAttribution"] = attribution
    result["perTurn"] = [
        {
            "turn": row["turn"],
            "configuredMode": "live",
            "httpStarts": len([e for e in attribution if e["turn"] == row["turn"]]),
            "exactAnswerSaved": saved[i]["exactAnswerSaved"],
        }
        for i, row in enumerate(turns)
    ]
    result_path.write_text(
        json.dumps(result, ensure_ascii=False, indent=2, default=str), encoding="utf-8"
    )
    (OUT / "dialogue.txt").write_text("\n\n".join(blocks) + "\n", encoding="utf-8")
    print(
        json.dumps(
            {
                "turns": len(turns),
                "actualModelStarts": result["actualModelStarts"],
                "sourceUnchanged": source_ok,
                "pgCounts": counts,
            },
            ensure_ascii=False,
        )
    )


def cleanup():
    manifest = json.loads((OUT / "manifest.json").read_text(encoding="utf-8"))
    outcomes = []
    private = Path(manifest["dumps"][0]["privatePath"]).parent
    chat_dump = private / "chat-evaluation.dump"
    assert not chat_dump.exists(), "Preserve previous evidence dump"
    with chat_dump.open("wb") as stream:
        subprocess.run(
            [
                "docker",
                "exec",
                data.PG,
                "pg_dump",
                "-U",
                "g8_eval",
                "-d",
                data.DATABASES["chat"],
                "-Fc",
                "--no-owner",
                "--no-acl",
            ],
            stdout=stream,
            check=True,
        )
    with chat_dump.open("rb") as stream:
        data.record(
            evaluationChatDump={
                "privatePath": str(chat_dump),
                "sha256": hashlib.file_digest(stream, "sha256").hexdigest(),
                "bytes": chat_dump.stat().st_size,
            }
        )
    for role, pid in manifest.get("pids", {}).items():
        result = subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"], capture_output=True)
        outcomes.append({"role": role, "pid": pid, "exitCode": result.returncode})
    for name in (data.PG, data.REDIS):
        obj = data.inspect(name)
        assert obj["Config"]["Labels"]["vishue.g8-evaluation"] == data.LABEL
        result = subprocess.run(["docker", "rm", "-fv", name], capture_output=True)
        outcomes.append({"container": name, "exitCode": result.returncode})
    (OUT / "cleanup.json").write_text(
        json.dumps(
            {
                "outcomes": outcomes,
                "originalAfter": data.source_metadata(),
                "privateDumpsRetained": True,
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    print("Only evaluation processes and labelled containers removed; original preserved")


if __name__ == "__main__":
    {"verify": verify, "cleanup": cleanup}[sys.argv[1]]()

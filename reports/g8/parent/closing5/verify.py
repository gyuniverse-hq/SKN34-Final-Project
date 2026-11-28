"""Verify observed consultation facts against real isolated PG; retain unsuccessful turns."""

import hashlib
import json
import re
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

import run

ROOT, OUT = run.ROOT, run.OUT


def read(name):
    return json.loads((OUT / name).read_text(encoding="utf-8"))


def write(name, value):
    (OUT / name).write_text(
        json.dumps(value, ensure_ascii=False, indent=2, default=str), encoding="utf-8"
    )


def verify():
    import psycopg

    rows = [
        json.loads(line) for line in (OUT / "trace.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    turns = [row for row in rows if row["kind"] == "turn_end"]
    m = read("manifest.json")
    url = run.data.clone_url(run.data.DATABASES["chat"]).set(drivername="postgresql")
    saved, dialogue, used_messages = [], [], set()
    with psycopg.connect(url.render_as_string(hide_password=False)) as conn:
        conn.execute("SET TRANSACTION READ ONLY")
        for n, row in enumerate(turns, 1):
            matches = conn.execute(
                "SELECT a.id,a.display_payload FROM chat_messages a "
                "JOIN chat_messages u ON u.conversation_id=a.conversation_id "
                "AND u.request_id=a.request_id AND u.sequence=a.sequence-1 "
                "JOIN chat_turns t ON t.response_message_id=a.id AND t.status='COMMITTED' "
                "WHERE a.role='assistant' AND u.role='user' AND a.text=%s AND u.text=%s "
                "AND a.created_at >= %s ORDER BY a.created_at",
                (row["answer"], row["question"], row["at"]),
            ).fetchall()
            matches = [value for value in matches if value[0] not in used_messages][:1]
            used_messages.update(value[0] for value in matches)
            calls = [r for r in rows if r["kind"] == "model_start" and r.get("turn") == row["turn"]]
            saved.append(
                {
                    "turn": row["turn"],
                    "phase": row["phase"],
                    "exactAnswerSaved": bool(matches),
                    "payloads": [v[1] for v in matches],
                    "pgMatchMethod": (
                        "unique committed request plus adjacent exact user/assistant pair"
                    ),
                    "configuredMode": "live",
                    "attributedModelStarts": len(calls),
                    "models": [r["model"] for r in calls],
                    "ms": row["ms"],
                }
            )
            dialogue.append(
                f"TURN {n} | {row['phase']} | {row['at']} | live HTTP starts={len(calls)}"
                f" | exact PG={bool(matches)}\nUSER: {row['question']}"
                f"\nASSISTANT (verbatim): {row['answer']}"
            )
        contexts = [
            r[0]
            for r in conn.execute(
                "SELECT context_json FROM chat_conversations ORDER BY created_at"
            ).fetchall()
        ]
    (OUT / "dialogue.txt").write_text("\n\n".join(dialogue) + "\n", encoding="utf-8")
    ownership = []
    for row in turns:
        context = row.get("ownedLookContext")
        if not context:
            continue
        refs = (context.get("references") or {}).get("targets", [])
        for target in refs:
            if target["productId"] == "yt-28606e8bcb5aa9552720":
                declaration = context.get("itemDeclarations", {}).get(
                    target["targetId"]
                ) or context.get("productDeclarations", {}).get(target["productId"])
                ownership.append(
                    {
                        "turn": row["turn"],
                        "phase": row["phase"],
                        "question": row["question"],
                        "target": target,
                        "declaration": declaration,
                        "filters": context.get("filters"),
                        "answer": row["answer"],
                    }
                )
    resolutions = [r for r in rows if r["kind"] == "knowledge_resolution"]
    models = [r for r in rows if r["kind"] == "model_start"]
    ended = [r for r in rows if r["kind"] == "model_end"]
    embedding_attribution = []
    for i, row in enumerate(rows):
        if (
            row["kind"] == "model_start"
            and row.get("turn") is None
            and row.get("model") == "text-embedding-3-large"
        ):
            later = next(
                (
                    r
                    for r in rows[i + 1 :]
                    if r["kind"] == "tool_http" and r["path"] == "/internal/knowledge/search"
                ),
                None,
            )
            embedding_attribution.append(
                {
                    "eventIndex": i,
                    "model": row["model"],
                    "turn": later["turn"] if later else None,
                    "method": "next serial knowledge search completion; not propagated ID",
                }
            )
    probes = read("parent-rejection.json")
    parent_final = probes["runs"][-1]
    latest_phase = m["phase"]
    latest_app = [
        r for r in resolutions if r["phase"] == latest_phase and r["turn"] != "knowledge-probe"
    ]
    latest_knowledge = latest_app[-1] if latest_app else None
    own_ok = [
        r
        for r in ownership
        if r["phase"].startswith("final") and (r["declaration"] or {}).get("status") == "present"
    ]
    checks = {
        "allFinalAnswersSavedExactly": all(s["exactAnswerSaved"] for s in saved),
        "finalSourceHashesMatch": all(
            hashlib.sha256((ROOT / p["path"]).read_bytes()).hexdigest() == p["sha256"]
            for p in m[m["phase"] + "Sources"]
        ),
        "priorEvidenceUnchanged": all(
            hashlib.sha256((ROOT / p["path"]).read_bytes()).hexdigest() == p["sha256"]
            for p in m["baselineFiles"]
        ),
        "parentThreeLiveSamplesAccepted": len(parent_final["samples"]) == 3
        and all(s["audit"]["status"] == "validated" for s in parent_final["samples"]),
        "n02ExplicitProductOwnershipStored": bool(own_ok),
        "n02ProductNotUpgradedToOption": bool(own_ok)
        and all(r["declaration"]["scope"] == "product" for r in own_ok),
        "n01FinalActualResolutionObserved": any(r["phase"] == "final" for r in resolutions),
        "n01LatestAppRequirementsFulfilled": bool(latest_knowledge)
        and all(r["fulfilled"] for r in latest_knowledge["coverage"]["requirements"]),
    }
    for item in saved:
        item["embeddingHTTPStarts"] = sum(a["turn"] == item["turn"] for a in embedding_attribution)
        item["modelCountMethod"] = (
            "direct ContextVar plus separately correlated embedding; probes are separate"
        )
        item["compoundOptions"] = [
            {
                "candidateCount": len(payload["compound"]["options"]),
                "outcomes": {
                    outcome: sum(o["outcome"] == outcome for o in payload["compound"]["options"])
                    for outcome in {o["outcome"] for o in payload["compound"]["options"]}
                },
                "batchSizes": [len(b["productIds"]) for b in payload["compound"]["batches"]],
                "optionIds": [
                    o["candidate"]["optionId"] for o in payload["compound"]["options"]
                    if o["outcome"] == "eligible"
                ],
            }
            for payload in item["payloads"] if payload.get("compound")
        ]
    result = {
        "recordedAt": datetime.now(UTC).isoformat(),
        "checks": checks,
        "perTurn": saved,
        "pgContexts": contexts,
        "n02Ownership": ownership,
        "knowledge": [
            {
                "turn": r["turn"],
                "phase": r["phase"],
                "coverage": r["coverage"],
                "audit": r["audit"],
                "status": r["final"]["status"],
            }
            for r in resolutions
        ],
        "latestN01App": latest_knowledge,
        "models": {
            "configuredMode": "live",
            "httpStarts": len(models),
            "httpEnds": len(ended),
            "counts": {
                name: sum(r["model"] == name for r in models)
                for name in {r["model"] for r in models}
            },
            "failedHTTP": [r for r in ended if r["status"] != 200],
            "embeddingAttribution": embedding_attribution,
        },
        "parentProbe": probes,
        "executionFailures": [
            {
                "turn": r["turn"],
                "phase": r["phase"],
                "question": r["question"],
                "reasons": [
                    t["reason"]
                    for t in (r.get("parent") or {}).get("tasks", [])
                    if t["status"] == "failed"
                ],
            }
            for r in turns
            if any(t["status"] == "failed" for t in (r.get("parent") or {}).get("tasks", []))
        ],
        "modes": {
            "app": "actual signed-in Aside",
            "catalog": "actual migrated clone HTTP",
            "postgres": "actual isolated PG17.10",
            "unitModels": "mock; see checks.log",
            "modelSnapshot": "configured names; immutable provider version not captured",
        },
    }
    write("verification.json", result)
    print(
        json.dumps(
            {"checks": checks, "turns": len(turns), "modelStarts": len(models)}, ensure_ascii=False
        )
    )
    return all(checks.values())


def security():
    env = run.environment()
    secrets = [
        value
        for key, value in env.items()
        if any(word in key.upper() for word in ("KEY", "TOKEN", "SECRET", "PASSWORD"))
        and len(value) > 10
        and not key.startswith("EXPO_PUBLIC_")
    ]
    counts = {"protectedValues": 0, "jwt": 0, "privateKey": 0, "email": 0}
    decorator_lines = 0
    files = [p for p in OUT.iterdir() if p.is_file() and p.suffix != ".png"]
    for path in files:
        value = path.read_text(encoding="utf-8", errors="replace")
        counts["protectedValues"] += sum(s in value for s in secrets)
        counts["jwt"] += len(re.findall(r"eyJ[\w-]{12,}\.[\w-]{12,}\.[\w-]{12,}", value))
        counts["privateKey"] += len(re.findall(r"-----BEGIN [A-Z ]*PRIVATE KEY-----", value))
        email_text = value
        if path.name == "manifest.json":
            # Added Python decorators look like email after JSON escapes a diff newline.
            parsed = json.loads(value)
            diff = parsed.get("finalUncommittedSourceDiff", {})
            if "gitDiff" in diff:
                diff["gitDiff"], decorator_lines = re.subn(
                    r"(?m)^([ +\-]*)@pytest\.mark\.(?:anyio|parametrize)\b",
                    r"\1PYTEST_DECORATOR",
                    diff["gitDiff"],
                )
                email_text = json.dumps(parsed)
        counts["email"] += len(re.findall(r"[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}", email_text))
    report = {
        "at": datetime.now(UTC).isoformat(), "textFiles": len(files), "matches": counts,
        "sourcePythonDecoratorLinesClassified": decorator_lines,
    }
    with (OUT / "security.log").open("a", encoding="utf-8") as stream:
        stream.write(json.dumps(report) + "\n")
    print(json.dumps(report))
    assert not any(counts.values()), "Sensitive pattern requires review; values not printed"


def cleanup():
    m = read("manifest.json")
    run.base.stop()
    private = Path(m["dumps"][0]["privatePath"]).parent / "closing5"
    private.mkdir(exist_ok=True)
    dump = private / "chat-evaluation.dump"
    assert not dump.exists()
    with dump.open("wb") as stream:
        subprocess.run(
            [
                "docker",
                "exec",
                run.data.PG,
                "pg_dump",
                "-U",
                "g8_eval",
                "-d",
                run.data.DATABASES["chat"],
                "-Fc",
                "--no-owner",
                "--no-acl",
            ],
            stdout=stream,
            check=True,
        )
    original_same = run.data.source_metadata() == m["originalMetadata"]
    removed = []
    for name in (run.data.PG, run.data.REDIS):
        assert run.data.inspect(name)["Config"]["Labels"]["vishue.g8-evaluation"] == run.data.LABEL
        done = subprocess.run(["docker", "rm", "-fv", name], capture_output=True)
        removed.append({"container": name, "exitCode": done.returncode})
    write(
        "cleanup.json",
        {
            "originalMetadataUnchanged": original_same,
            "originalWrites": 0,
            "privateChatDump": {
                "path": str(dump),
                "sha256": hashlib.sha256(dump.read_bytes()).hexdigest(),
                "bytes": dump.stat().st_size,
            },
            "containers": removed,
        },
    )


if __name__ == "__main__":
    action = sys.argv[1]
    result = {"verify": verify, "security": security, "cleanup": cleanup}[action]()
    if result is False:
        raise SystemExit(1)

"""Compare observed E01 turns with real PG; preserve raw dialogue and scope components."""

import ast
import hashlib
import json
import re
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

import run as runtime

OUT, ROOT = runtime.OUT, runtime.ROOT


def read(name):
    return json.loads((OUT / name).read_text(encoding="utf-8"))


def write(name, value):
    (OUT / name).write_text(
        json.dumps(value, ensure_ascii=False, indent=2, default=str), encoding="utf-8"
    )


def events(phase):
    return [
        json.loads(line)
        for line in (OUT / f"trace-{phase}.jsonl").read_text(encoding="utf-8").splitlines()
    ]


def verify():
    import psycopg

    manifest = read("manifest.json")
    url = runtime.data.clone_url(runtime.data.DATABASES["chat"]).set(drivername="postgresql")
    phases, dialogue = {}, []
    with psycopg.connect(url.render_as_string(hide_password=False)) as conn:
        conn.execute("SET TRANSACTION READ ONLY")
        for phase in ("before", "after"):
            records = events(phase)
            turns = [r for r in records if r["kind"] == "turn_end"]
            verified = []
            for n, turn in enumerate(turns, 1):
                own = [r for r in records if r.get("turn") == turn["turn"]]
                saved = conn.execute(
                    "SELECT display_payload FROM chat_messages "
                    "WHERE role='assistant' AND text=%s AND created_at >= %s",
                    (turn["answer"], turn["at"]),
                ).fetchall()
                models = [r for r in own if r["kind"] == "model_start"]
                tools = [r for r in own if r["kind"] == "tool_http"]
                verified.append(
                    {
                        "turn": turn["turn"],
                        "at": turn["at"],
                        "configuredMode": "live",
                        "modelHTTPStarts": len(models),
                        "models": [r["model"] for r in models],
                        "exactAnswerSaved": bool(saved),
                        "displayPayloads": [row[0] for row in saved],
                        "toolRequests": [
                            {k: r.get(k) for k in ("path", "query", "input", "status")}
                            for r in tools
                        ],
                        "ms": turn["ms"],
                    }
                )
                dialogue.append(
                    f"{phase.upper()} TURN {n} | {turn['at']} | live, HTTP calls={len(models)}"
                    f" | PG exact={bool(saved)}\nUSER: {turn['question']}"
                    f"\nASSISTANT (verbatim): {turn['answer']}"
                )
            phases[phase] = {
                "turns": verified,
                "modelHTTPStarts": sum(r["kind"] == "model_start" for r in records),
                "modelHTTPEnds": sum(r["kind"] == "model_end" for r in records),
                "modelHTTPFailures": [
                    r for r in records if r["kind"] == "model_end" and r["status"] != 200
                ],
                "knowledgeCalls": sum(
                    r["kind"] == "tool_http" and "/knowledge/" in r["path"] for r in records
                ),
            }
        contexts = conn.execute(
            "SELECT context_json FROM chat_conversations ORDER BY created_at"
        ).fetchall()
    before, after = events("before"), events("after")
    bturns = [r for r in before if r["kind"] == "turn_end"]
    aturns = [r for r in after if r["kind"] == "turn_end"]
    successful = [
        r
        for r in aturns
        if any(t["goal"] == "product" and t["status"] == "completed" for t in r["parent"]["tasks"])
    ]
    assert successful, "No actual completed product comparison"
    comparison, retry = successful[-2], aturns[-1]
    product = next(t for t in comparison["parent"]["tasks"] if t["goal"] == "product")
    kept = next(t for t in retry["parent"]["tasks"] if t["taskId"] == product["taskId"])
    style = next(t for t in retry["parent"]["tasks"] if t["goal"] == "style")
    retry_tools = [r for r in after if r.get("turn") == retry["turn"] and r["kind"] == "tool_http"]
    checks = {
        "beforeNamedPairDidNotEnterComparison": any(
            r["kind"] == "search_plan" and "메디필" in r["message"] and not r["directComparison"]
            for r in before
        ),
        "beforeRetryBlockedWithoutTools": "바뀌었어요" in bturns[-1]["answer"]
        and not any(
            r["kind"] == "tool_http" and r.get("turn") == bturns[-1]["turn"] for r in before
        ),
        "afterTwoNamesEnteredComparison": any(
            r["kind"] == "search_plan"
            and len(r["plan"].get("comparisonNames", [])) == 2
            and r["directComparison"]
            for r in after
        ),
        "comparisonInspectedTwo": product["productAssessment"]["inspected"] == 2
        and product["productAssessment"]["matched"] == 2,
        "comparisonAnswerPreserved": product["displayResult"] == kept["displayResult"],
        "comparisonAssessmentPreserved": product["productAssessment"] == kept["productAssessment"],
        "comparisonScopePreserved": product["scopeDigest"] == kept["scopeDigest"],
        "retryStyleSameTask": style["taskId"]
        == next(t for t in comparison["parent"]["tasks"] if t["goal"] == "style")["taskId"],
        "retryDidStyleHTTP": any(
            r["path"] in {"/api/style-looks", "/api/looks"} and r["status"] == 200
            for r in retry_tools
        ),
        "retryNoProductHTTP": not any(
            "/products" in r["path"] or "/options" in r["path"] for r in retry_tools
        ),
        "retryStyleNoLongerFailed": style["status"] != "failed",
        "allAnswersSavedExactly": all(
            t["exactAnswerSaved"] for phase in phases.values() for t in phase["turns"]
        ),
        "finalSourceHashesMatch": all(
            hashlib.sha256((ROOT / s["path"]).read_bytes()).hexdigest() == s["sha256"]
            for s in manifest["finalSources"]
        ),
        "finalSourceASTMatchesActualRun": all(
            hashlib.sha256(
                ast.dump(ast.parse((ROOT / s["path"]).read_text(encoding="utf-8"))).encode()
            ).hexdigest()
            == s["sha256"]
            for s in manifest["afterAST"]
        ),
        "priorEvidenceUnchanged": all(
            hashlib.sha256((ROOT / s["path"]).read_bytes()).hexdigest() == s["sha256"]
            for s in manifest["baselineFiles"]
            if s["path"].startswith("reports/")
        ),
    }
    unique = {}
    for r in before:
        if r["kind"] == "scope":
            unique[r["digest"]] = r["components"]
    changes = []
    for left, first in unique.items():
        for right, second in unique.items():
            if left >= right:
                continue
            different = [key for key in first if first[key] != second[key]]
            if different == ["memoryAvailable"]:
                changes.append(
                    {
                        "oldDigest": left,
                        "nextDigest": right,
                        "changedKeys": different,
                        "old": first,
                        "next": second,
                    }
                )
    write(
        "scope-diff.json",
        {
            "beforeObservedEmptyMemoryShapeDifferences": changes,
            "afterStyleTask": {
                k: style.get(k) for k in ("taskId", "scopeDigest", "scopeSnapshot", "status")
            },
            "afterComparisonTask": {
                k: kept.get(k) for k in ("taskId", "scopeDigest", "scopeSnapshot", "status")
            },
        },
    )
    phases["checks"] = checks
    phases["comparison"] = {
        "answer": product["displayResult"]["answer"],
        "assessment": product["productAssessment"],
    }
    phases["retry"] = {
        "answer": retry["answer"],
        "styleStatus": style["status"],
        "styleCandidates": retry["styleCandidates"],
    }
    phases["savedContexts"] = [row[0] for row in contexts]
    phases["rejectedParentProposals"] = [
        {
            "turn": row["turn"],
            "question": row["question"],
            "answer": row["answer"],
            "audit": item["parentIntent"],
        }
        for row in aturns
        for item in row["tasks"]
        if item.get("parentIntent", {}).get("status") == "rejected_proposal"
    ]
    prior = [
        json.loads(line)
        for line in (runtime.PRIOR / "trace.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    prior_turns = [row for row in prior if row["kind"] == "turn_end"]
    sys.path.insert(0, str(ROOT / "backend/chatbot"))
    from app.services.consultation_task_adapter import fingerprint

    original_scopes = []
    for row in prior_turns[9:12]:
        task = next(t for t in row["parent"]["tasks"] if t["goal"] == "style")
        matched = [value for value in unique.values() if fingerprint(value) == task["scopeDigest"]]
        original_scopes.append(
            {"turn": row["turn"], "digest": task["scopeDigest"], "reconstructed": matched}
        )
    diff = read("scope-diff.json")
    diff["originalClosing4Scopes"] = original_scopes
    write("scope-diff.json", diff)
    n02 = prior_turns[8]
    phases["remainingEvaluation"] = {
        "evidence": "closing4 immutable original run; no new N01/N02 live calls",
        "N01": [
            {
                "question": row["question"],
                "coverage": row["parent"]["tasks"][0]["compoundContext"]["knowledgeSearch"][
                    "coverage"
                ],
            }
            for row in (prior_turns[1], prior_turns[3])
        ],
        "N01Cause": "G5 resolve leaves required coverage unfulfilled. Accepted claims exist; "
        "whole-corpus data absence and exact audit/root cause not proven. "
        "Knowledge ingredient conditions adopted=0; nonempty positive link unverified.",
        "N02": {
            "question": n02["question"],
            "parentChanges": [
                item["parentIntent"]["result"]["changes"]
                for item in n02["tasks"]
                if item.get("parentIntent", {}).get("result")
            ],
            "productDeclarations": (n02.get("ownedLookContext") or {}).get("productDeclarations"),
            "blockingExecutionDefect": "Explicit Clio-owned clause omitted from forwarded "
            "parent change; not a data shortage.",
            "separateDataLimit": "Clio product yt-28606e8bcb5aa9552720: exact sale option "
            "and AR shade unconfirmed; application/substitution evidence "
            "not established. Ordinary guidance remains supported.",
        },
        "stage5Readiness": "Final regression may proceed; closure must remain pending until "
        "N02 ownership omission and N01 required coverage disposition are resolved. "
        "Parent-model rejection observed; do not report all live turns PASS.",
    }
    phases["modes"] = {
        "plannerAndStyle": "actual OpenAI gpt-6-luna",
        "Catalog": "actual cloned data HTTP",
        "PG": "actual isolated PG17.10",
        "fault": "controlled proxy Style HTTP503; other calls real",
        "G5": "OFF; original N01 reused from closing4",
    }
    write("verification.json", phases)
    (OUT / "dialogue.txt").write_text("\n\n".join(dialogue) + "\n", encoding="utf-8")
    print(
        json.dumps(
            {
                "checks": checks,
                "models": {p: phases[p]["modelHTTPStarts"] for p in ("before", "after")},
            },
            ensure_ascii=False,
        )
    )
    assert all(checks.values()), "E01 evidence check failed"


def cleanup():
    manifest = read("manifest.json")
    private = Path(manifest["sourceDump"]["path"]).parent / "e01-fix"
    target = private / "chat-e01-evaluation.dump"
    assert not target.exists(), "Preserve prior dumps"
    with target.open("wb") as stream:
        subprocess.run(
            [
                "docker",
                "exec",
                runtime.data.PG,
                "pg_dump",
                "-U",
                "g8_eval",
                "-d",
                runtime.data.DATABASES["chat"],
                "-Fc",
                "--no-owner",
                "--no-acl",
            ],
            stdout=stream,
            check=True,
        )
    runtime.stop()
    original = runtime.data.source_metadata()
    assert original == manifest["sourceMetadata"], "Original metadata changed"
    results = []
    for name in (runtime.data.PG, runtime.data.REDIS):
        obj = runtime.data.inspect(name)
        assert obj["Config"]["Labels"]["vishue.g8-evaluation"] == runtime.data.LABEL
        result = subprocess.run(["docker", "rm", "-fv", name], capture_output=True)
        results.append({"container": name, "exitCode": result.returncode})
    write(
        "cleanup.json",
        {
            "originalMetadataUnchanged": True,
            "originalWrites": 0,
            "privateChatDump": {
                "path": str(target),
                "sha256": hashlib.sha256(target.read_bytes()).hexdigest(),
                "bytes": target.stat().st_size,
            },
            "containers": results,
        },
    )


def security():
    env = runtime.environment()
    protected = [
        value
        for key, value in env.items()
        if any(word in key.upper() for word in ("KEY", "PASSWORD", "SECRET", "TOKEN"))
        and len(value) > 10
        and not key.startswith("EXPO_PUBLIC_")
    ]
    counts = {"protectedValues": 0, "jwt": 0, "privateKey": 0, "email": 0}
    texts = [p for p in OUT.iterdir() if p.is_file() and p.suffix != ".png"]
    for path in texts:
        value = path.read_text(encoding="utf-8", errors="replace")
        counts["protectedValues"] += sum(secret in value for secret in protected)
        counts["jwt"] += len(re.findall(r"eyJ[\w-]{12,}\.[\w-]{12,}\.[\w-]{12,}", value))
        counts["privateKey"] += len(re.findall(r"-----BEGIN [A-Z ]*PRIVATE KEY-----", value))
        counts["email"] += len(re.findall(r"[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}", value))
    result = {
        "recordedAt": datetime.now(UTC).isoformat(),
        "textFiles": len(texts),
        "matches": counts,
    }
    with (OUT / "security.log").open("a", encoding="utf-8") as stream:
        stream.write(json.dumps(result) + "\n")
    print(json.dumps(result))
    assert not any(counts.values()), "Sensitive pattern requires review; values not printed"


if __name__ == "__main__":
    {"verify": verify, "cleanup": cleanup, "security": security}[sys.argv[1]]()

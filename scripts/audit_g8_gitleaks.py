"""Recompute G8 source-digest findings without emitting detected values.

Input: local unredacted Gitleaks JSON (never commit it). Output: value-free proof.
"""

import argparse
import hashlib
import json
import subprocess
from collections import defaultdict
from pathlib import Path

HISTORICAL_TEST = "backend/chatbot/tests/test_g7_conversation_api_pg.py"


def git(*args):
    return subprocess.check_output(["git", *args], stderr=subprocess.DEVNULL)


def restore_initial_test():
    """Undo two recorded post-run edits; exact anchors fail closed if source differs."""
    source = git("show", f"0e3973f:{HISTORICAL_TEST}").decode("utf-8")
    checkpoint = """            namespaces = conn.execute(
                "SELECT checkpoint_ns FROM checkpoints WHERE thread_id=%s "
                "UNION SELECT checkpoint_ns FROM checkpoint_blobs WHERE thread_id=%s "
                "UNION SELECT checkpoint_ns FROM checkpoint_writes WHERE thread_id=%s",
                (str(thread),) * 3,
            ).fetchall()
            checkpoint_bytes = conn.execute(
                "SELECT blob FROM checkpoint_blobs WHERE thread_id=%s "
                "UNION ALL SELECT blob FROM checkpoint_writes WHERE thread_id=%s "
                "UNION ALL SELECT convert_to(checkpoint::text, 'UTF8') "
                "FROM checkpoints WHERE thread_id=%s",
                (str(thread),) * 3,
            ).fetchall()
        assert namespaces == [("",)]
        forbidden = (b"sale-9", b"chunk8", b"fixture-rag", skin_case.QUESTION.encode())
        assert all(
            marker not in bytes(blob or b"") for (blob,) in checkpoint_bytes for marker in forbidden
        )
"""
    observations = """                "checkpointNamespaces": [ns for (ns,) in namespaces],
                "rawCheckpointMarkersFound": 0,
"""
    citation = """            evidence_id = public["knowledge"]["evidence"][0]["id"]
            assert public["knowledge"]["claims"][0]["citations"] == [evidence_id]
            assert f"{skin_case.CARE_ADVICE} [1]" in public["answer"]
            assert evidence_id not in public["answer"]
"""
    original = """            assert public["knowledge"]["evidence"][0]["id"] in public["answer"]
"""
    for before, after in [(checkpoint, ""), (observations, ""), (citation, original)]:
        if source.count(before) != 1:
            raise ValueError("Historical reconstruction anchor mismatch")
        source = source.replace(before, after, 1)
    return source.replace("\n", "\r\n").encode("utf-8")


def leaves(value, keys=()):
    if isinstance(value, dict):
        for key, child in value.items():
            yield from leaves(child, (*keys, key))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            yield from leaves(child, (*keys, str(index)))
    else:
        yield keys, value


def audit(findings):
    cache, proofs = {}, []
    for index, finding in enumerate(findings, 1):
        commit, trace, line = finding["Commit"], finding["File"], finding["StartLine"]
        proof = {
            "number": index,
            "commit": commit,
            "trace": trace,
            "line": line,
            "rule": finding["RuleID"],
            "fingerprint": finding["Fingerprint"],
            "status": "unconfirmed",
            "sourceMatches": [],
        }
        if trace not in {"reports/g8/n01/trace.jsonl", "reports/g8/first-compound/trace.jsonl"}:
            proofs.append(proof)
            continue
        record = json.loads(git("show", f"{commit}:{trace}").splitlines()[line - 1])
        locations = [k for k, v in leaves(record) if v == finding["Secret"]]
        for keys in locations:
            path = keys[-1]
            if not path.startswith(("backend/", "app/", "components/", "types/", "lib/")):
                continue
            if path not in cache:
                cache[path] = defaultdict(list)
                for revision in (
                    git("log", "--all", "--format=%H", "--", path).decode().splitlines()
                ):
                    try:
                        data = git("show", f"{revision}:{path}")
                        blob = git("rev-parse", f"{revision}:{path}").decode().strip()
                    except subprocess.CalledProcessError:
                        continue
                    for basis, payload in [
                        ("git-blob", data),
                        ("UTF-8-CRLF", data.replace(b"\r\n", b"\n").replace(b"\n", b"\r\n")),
                    ]:
                        cache[path][hashlib.sha256(payload).hexdigest()].append(
                            {
                                "path": path,
                                "sourceCommit": revision,
                                "blob": blob,
                                "byteBasis": basis,
                                "bytes": len(payload),
                            }
                        )
            matches = cache[path].get(finding["Secret"], [])
            if (
                not matches
                and path == HISTORICAL_TEST
                and commit.startswith("5ed8ac1")
                and line == 1
            ):
                restored = restore_initial_test()
                if hashlib.sha256(restored).hexdigest() == finding["Secret"]:
                    matches = [
                        {
                            "path": path,
                            "sourceCommit": git("rev-parse", "0e3973f").decode().strip(),
                            "byteBasis": "UTF-8-CRLF",
                            "bytes": len(restored),
                            "reconstruction": (
                                "restore_initial_test(): reverse checkpoint and citation edits"
                            ),
                        }
                    ]
            proof["sourceMatches"].extend(matches)
            proof["traceField"] = list(keys)
        if proof["sourceMatches"]:
            proof["status"] = "verified_source_digest"
        proofs.append(proof)
    return proofs


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--findings", type=Path, required=True)
    parser.add_argument("--proof", type=Path, required=True)
    parser.add_argument("--ignore", type=Path)
    args = parser.parse_args()
    proofs = audit(json.loads(args.findings.read_text(encoding="utf-8-sig")))
    args.proof.write_text(json.dumps(proofs, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    groups = defaultdict(list)
    for proof in proofs:
        groups[proof["fingerprint"]].append(proof)
    verified = [
        fp
        for fp, group in groups.items()
        if all(p["status"] == "verified_source_digest" for p in group)
    ]
    if args.ignore:
        if args.ignore.exists():
            raise ValueError("Refusing to overwrite an existing ignore file")
        args.ignore.write_text(
            "# Verified G8 source SHA-256 only. See reports/g8/security/gitleaks-audit.md.\n"
            "# All findings sharing each fingerprint were recomputed; no path/rule exclusions.\n"
            + "\n".join(sorted(verified))
            + "\n",
            encoding="utf-8",
        )
    print(
        json.dumps(
            {
                "findings": len(proofs),
                "verified": sum(p["status"] == "verified_source_digest" for p in proofs),
                "verifiedFingerprints": len(verified),
            }
        )
    )


if __name__ == "__main__":
    main()

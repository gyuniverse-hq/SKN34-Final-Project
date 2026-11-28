"""Build/verify the approved 17-file G8 evidence bundle from immutable private backups.

No model, Catalog or DB calls. Cleanup unlinks only the pinned 1,461-file list.
"""

import argparse
import hashlib
import json
import re
import subprocess
import zipfile
from contextlib import contextmanager
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE = "5208f89b83de9ebebf9d78c6016b3b2fda327a87"
BASE = "991dd634dba33b99ceeb1c03de4dd8d921ce07f9"
ORIGINAL_SHA = "3067bfa59e94a3e7c216d8a333dd538ddd5a2161619ef0eff10287d2f8cd856e"
OVERLAY_SHA = "2801d4cce619ab4e243d5381cd9c06d32b97113dea8e51571a5e78fd3abd3a92"
EXCLUDE_SHA = "4513a4224a1750c7889452f6042ae8a1c7bbd1fb73b42531833b01df3b9c1294"
BACKUP = Path.home() / ".codex/private-evidence/vishue-g8/5208f89b"
INDEX = "reports/g8/EVIDENCE-INDEX.json"
MATRIX = "reports/g8/CLOSURE-MATRIX.json"
VERIFY = "reports/g8/VERIFICATION.json"
TOOL = "scripts/g8_evidence_export.py"
DOCS = ["docs/ai-design/G8-IMPLEMENTATION-SPEC.md", "docs/ai-design/G8-WORKLOG.md"]
UPSERTS = [INDEX, MATRIX, VERIFY, TOOL, *DOCS]
PRIVATE_KEYS = {
    "quote",
    "text",
    "content",
    "prompt",
    "answer",
    "arguments",
    "body",
    "userId",
    "memberId",
    "conversationId",
    "requestId",
    "sessionId",
}
PATH_PATTERN = re.compile(r"reports/g8/[A-Za-z0-9_./-]+")
STATES = ("bundles", "capabilities", "scenarios", "representativeCases")


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()


def git(*args):
    return subprocess.check_output(["git", *args], cwd=ROOT, stderr=subprocess.PIPE)


def file_info(path):
    raw = (ROOT / path).read_bytes()
    data = raw if path.endswith(".png") else raw.replace(b"\r\n", b"\n")
    return {
        "path": path,
        "bytes": len(data),
        "sha256": sha(data),
        "hashBasis": "binary" if path.endswith(".png") else "utf8-lf",
    }


def safe_path(path):
    item = ROOT / path
    assert not Path(path).is_absolute() and ".." not in Path(path).parts
    assert not item.is_symlink() and item.resolve().is_relative_to(ROOT)
    return item


def write(path, data):
    safe_path(path).write_text(
        json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


def read(path):
    return json.loads((ROOT / path).read_text(encoding="utf-8"))


@contextmanager
def snapshots():
    om = json.loads((BACKUP / "g8-originals.manifest.json").read_text(encoding="utf-8"))
    dm = json.loads((BACKUP / "g8-public-derivatives.manifest.json").read_text(encoding="utf-8"))
    assert om["head"] == dm["sourceHead"] == SOURCE
    with (
        zipfile.ZipFile(BACKUP / "g8-originals.zip") as original,
        zipfile.ZipFile(BACKUP / "g8-public-derivatives.zip") as overlay,
    ):
        for manifest, z, name, digest, count in [
            (om, original, "g8-originals.zip", ORIGINAL_SHA, 1475),
            (dm, overlay, "g8-public-derivatives.zip", OVERLAY_SHA, 45),
        ]:
            assert sha((BACKUP / name).read_bytes()) == digest
            entries = manifest["entries"]
            assert len(entries) == count and set(z.namelist()) == {e["path"] for e in entries}
            for entry in entries:
                safe_path(entry["path"])
                raw = z.read(entry["path"])
                assert len(raw) == entry["bytes"] and sha(raw) == entry["sha256"], (
                    "Backup hash mismatch"
                )
        excluded = [e["path"] for e in dm["exclude1461"]]
        assert len(excluded) == len(set(excluded)) == 1461
        assert sha(("\n".join(sorted(excluded)) + "\n").encode()) == EXCLUDE_SHA
        assert dm["excludeListSha256"] == EXCLUDE_SHA
        assert len(dm["keep14"]) == 14 and len(dm["preserveSecurity"]) == 4
        assert set(excluded).isdisjoint(e["path"] for e in dm["keep14"] + dm["preserveSecurity"])
        assert set(excluded) | {e["path"] for e in dm["keep14"]} == {
            e["path"] for e in om["entries"]
        }
        yield om, dm, original, overlay


def guard(dm):
    assert git("rev-parse", "HEAD").decode().strip() == SOURCE, "Cleanup source HEAD changed"
    assert not git("diff", "--cached", "--name-only").strip(), "Preserve staged work"
    allowed = {e["path"] for e in dm["exclude1461"]} | set(UPSERTS)
    changed = set(git("diff", "--name-only").decode().splitlines())
    changed.update(git("ls-files", "--others", "--exclude-standard").decode().splitlines())
    assert changed <= allowed, "Changes outside approved 1,467 paths"
    return allowed


def preserved(dm):
    for entry in dm["keep14"] + dm["preserveSecurity"]:
        raw = (ROOT / entry["path"]).read_bytes()
        if sha(raw) != entry["sha256"]:
            assert not entry["path"].endswith(".png"), "Retained image changed"
            assert raw.replace(b"\r\n", b"\n") == git("show", SOURCE + ":" + entry["path"]), (
                "Retained file content changed"
            )


def private_text(value):
    return {"privateText": True, "characters": len(value), "sha256": sha(value.encode())}


def quote_corpus(original, old_index):
    quotes = set()

    def walk(value):
        if isinstance(value, dict):
            if (
                isinstance(value.get("quote"), str)
                and value["quote"]
                and "documentId" in value
                and "sourceFileId" in value
                and value.get("sourceVersion") != "fixture-rag"
            ):
                quotes.add(value["quote"])
            for child in value.values():
                walk(child)
        elif isinstance(value, list):
            for child in value:
                walk(child)

    for entry in old_index["entries"]:
        path = entry["path"]
        if Path(path).suffix not in {".json", ".jsonl"}:
            continue
        text = original.read(path).decode("utf-8-sig")
        docs = (
            [json.loads(s) for s in text.splitlines() if s.strip()]
            if path.endswith(".jsonl")
            else [json.loads(text)]
        )
        for doc in docs:
            walk(doc)
    assert len(quotes) == 95
    return quotes


def sanitizer(om, dm, quotes):
    originals = {e["path"]: e for e in om["entries"]}
    overlays = {e["path"]: e for e in dm["entries"]}

    def reference(path):
        path = path.rstrip(".")
        assert path in originals or path in overlays, "Unknown archived evidence reference"
        return {
            "archiveEntry": path,
            "original": originals.get(path),
            "overlay": overlays.get(path),
        }

    def clean(value, key=""):
        if isinstance(value, dict):
            return {k: clean(v, k) for k, v in value.items()}
        if isinstance(value, list):
            return [clean(v, key) for v in value]
        if not isinstance(value, str):
            return value
        if key in PRIVATE_KEYS or any(q in value for q in quotes):
            return private_text(value)
        paths = PATH_PATTERN.findall(value.replace("\\", "/"))
        if paths:
            return {
                "archivedText": private_text(value),
                "archiveReferences": [reference(p) for p in dict.fromkeys(paths)],
            }
        if re.search(
            r"eyJ[\w-]{12,}\.[\w-]{12,}\.[\w-]{12,}|[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}", value
        ):
            return private_text(value)
        return value

    return clean, reference


def recorded_states(matrix):
    return {
        key: [(r["id"], r["status"], r.get("g8OwnedContractStatus")) for r in matrix[key]]
        for key in STATES
    }


def build():
    with snapshots() as (om, dm, original, overlay):
        guard(dm)
        preserved(dm)
        if (ROOT / INDEX).exists():
            assert read(INDEX).get("layout") != "local_compacted", (
                "Use verify for a compacted bundle"
            )
        old_index = json.loads(overlay.read(INDEX))
        quotes = quote_corpus(original, old_index)
        clean, ref = sanitizer(om, dm, quotes)
        old_matrix_path = "reports/g8/parent/closing-last/closure-matrix.json"
        old_matrix = json.loads(original.read(old_matrix_path))
        matrix = clean(
            {
                k: v
                for k, v in old_matrix.items()
                if k not in {"publication", "mergeReady", "requiredBeforeMerge", "pushPrDeploy"}
            }
        )
        assert recorded_states(matrix) == recorded_states(old_matrix)
        matrix.update(
            schemaVersion=2,
            sourceHead=SOURCE,
            sourceEvidence=ref(old_matrix_path),
            decisionScope="Recorded supported product contracts; publication policy separate",
            mergeReady=False,
            requiredBeforeMerge=[
                {"id": "P1_GIT_HISTORY_PUBLICATION", "status": "OPEN"},
                {"id": "TEAM_REVIEW", "status": "NOT_RUN"},
            ],
        )
        historical = {}
        for key in (
            "at",
            "overallG8Stage",
            "closingStage",
            "newProductCodeEdits",
            "approvedChangedFiles",
            "finalSecurityAndCleanup",
        ):
            if key in matrix:
                historical[key] = matrix.pop(key)
        matrix.update(
            historicalSourceExecution=historical,
            overallG8Stage=7,
            closingStage=6,
            currentProductCodeEdits=0,
        )
        lifecycle_path = "reports/g8/parent/review-p1/lifecycle-verification.json"
        lifecycle = json.loads(original.read(lifecycle_path))
        performance_path = "reports/g8/parent/closing-last/performance.json"
        performance = json.loads(original.read(performance_path))
        performance = {k: v for k, v in performance.items() if k != "usage"}
        verification = {
            "schemaVersion": 2,
            "sourceHead": SOURCE,
            "sourceEvidence": [ref(lifecycle_path), ref(performance_path)],
            "remoteCI": {
                "head": SOURCE,
                "ciRun": 46156366255,
                "secretsRun": 46156366207,
                "app": {"passed": 1387, "suitesPassed": 113},
                "api": {"passed": 700, "skipped": 42, "warnings": 1},
                "chatbot": {"passed": 1938, "skipped": 29},
                "gitleaks": {"commits": 699, "findings": 0},
                "scope": "Previously observed CI on source HEAD; not this uncommitted layout",
            },
            "lifecycleRegression": clean(lifecycle["finalResult"]),
            "testedProductSources": lifecycle["publication"]["implementationFiles"],
            "recordedPerformance": clean(performance),
            "performanceScope": "Historical limited samples, retries/rephrases; not a new load run",
            "previousPublicationChecks": clean(old_index["checks"]),
            "imageReview": old_index["imageReview"],
            "privacyDerivatives": {
                "archivedFiles": 41,
                "knownSourceQuotes": 95,
                "remainingKnownQuotes": 0,
                "sourceIndex": ref(INDEX),
                "originalRecordDetails": "private backups",
            },
            "modelAndCatalogCallsAdded": 0,
            "currentChecks": [],
        }
        index = {
            "schemaVersion": 2,
            "sourceHead": SOURCE,
            "integratedDevelop": BASE,
            "layout": "summaries_ready",
            "historicalGitPublicationP1": "OPEN",
            "archives": [
                {
                    "role": "originals",
                    "file": "g8-originals.zip",
                    "sha256": ORIGINAL_SHA,
                    "files": 1475,
                    "bytes": om["archive"]["bytes"],
                },
                {
                    "role": "current45Overlay",
                    "file": "g8-public-derivatives.zip",
                    "sha256": OVERLAY_SHA,
                    "files": 45,
                    "bytes": dm["archive"]["bytes"],
                },
            ],
            "archiveAccess": "Approved private local directory outside Git; not uploaded",
            "originalEntries": om["entries"],
            "overlayEntries": dm["entries"],
            "excludedEntries": dm["exclude1461"],
            "excludeListSha256": EXCLUDE_SHA,
            "retainedExisting": dm["keep14"],
            "sharedSecurity": dm["preserveSecurity"],
            "summaries": [INDEX, MATRIX, VERIFY],
            "targetPrEvidenceFiles": 17,
            "expectedProspectivePrFiles": 129,
            "summaryHashes": [],
            "sourceIdentity": [],
            "commitPushMergeDeploy": "NOT_RUN",
        }
        for path, value in [(MATRIX, matrix), (VERIFY, verification), (INDEX, index)]:
            raw = json.dumps(value, ensure_ascii=False)
            assert not any(
                q in raw or json.dumps(q, ensure_ascii=False)[1:-1] in raw for q in quotes
            )
            write(path, value)
        print(
            "build PASS: 6 bundles / 14 capabilities / 12 scenarios / 4 cases; "
            "source statuses preserved"
        )


def cleanup():
    with snapshots() as (_, dm, _, _):
        guard(dm)
        preserved(dm)
        index = read(INDEX)
        assert index["schemaVersion"] == 2 and index["excludeListSha256"] == EXCLUDE_SHA
        assert read(MATRIX)["sourceHead"] == read(VERIFY)["sourceHead"] == SOURCE
        # Validate the entire whitelist before unlinking any file.
        for entry in dm["exclude1461"]:
            path = safe_path(entry["path"])
            if path.exists():
                assert path.is_file() and sha(path.read_bytes()) == entry["sha256"], (
                    "Independently changed evidence; preserve it"
                )
        removed = 0
        for entry in dm["exclude1461"]:
            path = safe_path(entry["path"])
            if path.exists():
                path.unlink()
                removed += 1
        index["layout"] = "local_compacted"
        index["cleanup"] = {
            "approved": 1461,
            "removedThisRun": removed,
            "remainingExcluded": 0,
            "recursiveDelete": False,
        }
        write(INDEX, index)
        print(json.dumps({"cleanup": "PASS", "removedThisRun": removed}))


def seal():
    index = read(INDEX)
    assert index["schemaVersion"] == 2 and index["sourceHead"] == SOURCE
    index["summaryHashes"] = [file_info(p) for p in [MATRIX, VERIFY]]
    index["sourceIdentity"] = [file_info(p) for p in [TOOL, *DOCS]]
    index["hashBasis"] = {
        "summaryHashesAndSourceIdentity": "binary PNG; UTF-8 LF text, matching Git blob bytes",
        "archiveEntriesAndRetainedExisting": "original snapshot bytes; ZIP hashes unchanged",
        "retainedTextVerification": "original byte hash or identical SOURCE Git LF content",
    }
    write(INDEX, index)
    print("seal PASS: summary/tool/document hashes")


def verify():
    with snapshots() as (om, dm, original, overlay):
        preserved(dm)
        index, matrix, verification = read(INDEX), read(MATRIX), read(VERIFY)
        assert index["schemaVersion"] == 2 and index["layout"] == "local_compacted"
        expected = {p["path"] for p in dm["keep14"]} | {INDEX, MATRIX, VERIFY}
        actual = {
            p.relative_to(ROOT).as_posix() for p in (ROOT / "reports/g8").rglob("*") if p.is_file()
        }
        shared = expected | {e["path"] for e in dm["preserveSecurity"]}
        local_only = actual - shared
        if local_only:
            ignored = subprocess.run(
                ["git", "check-ignore", "--stdin"],
                cwd=ROOT,
                input=("\n".join(sorted(local_only)) + "\n").encode(),
                capture_output=True,
            )
            assert set(ignored.stdout.decode().splitlines()) == local_only
            assert all("/__pycache__/" in p and p.endswith(".pyc") for p in local_only)
        assert actual - local_only == shared, "Unexpected remaining report files"
        assert len(expected) == 17 and not any(
            (ROOT / e["path"]).exists() for e in dm["exclude1461"]
        )
        for doc in DOCS:
            text = (ROOT / doc).read_text(encoding="utf-8")
            for target in re.findall(r"\]\(([^)]+)\)", text):
                for path in PATH_PATTERN.findall(target):
                    assert path in actual, "Active document link to archived evidence"
        assert index["excludedEntries"] == dm["exclude1461"]
        for entry in index["summaryHashes"] + index["sourceIdentity"]:
            assert file_info(entry["path"]) == entry, "Sealed file changed"
        assert len(index["summaryHashes"]) == 2 and len(index["sourceIdentity"]) == 3
        source_matrix = json.loads(
            original.read("reports/g8/parent/closing-last/closure-matrix.json")
        )
        assert recorded_states(matrix) == recorded_states(source_matrix)
        assert matrix["mergeReady"] is False and index["historicalGitPublicationP1"] == "OPEN"
        assert [len(matrix[k]) for k in STATES] == [6, 14, 12, 4]
        for entry in verification["testedProductSources"]:
            assert (
                git("hash-object", "--path=" + entry["path"], entry["path"]).decode().strip()
                == entry["gitBlob"]
            )
        old_index = json.loads(overlay.read(INDEX))
        quotes = quote_corpus(original, old_index)
        clean, _ = sanitizer(om, dm, quotes)
        source_performance = json.loads(
            original.read("reports/g8/parent/closing-last/performance.json")
        )
        assert verification["recordedPerformance"] == clean(
            {k: v for k, v in source_performance.items() if k != "usage"}
        )
        source_lifecycle = json.loads(
            original.read("reports/g8/parent/review-p1/lifecycle-verification.json")
        )
        assert verification["lifecycleRegression"] == clean(source_lifecycle["finalResult"])
        assert (
            index["originalEntries"] == om["entries"] and index["overlayEntries"] == dm["entries"]
        )
        for path in [INDEX, MATRIX, VERIFY]:
            text = (ROOT / path).read_text(encoding="utf-8")
            assert not any(
                q in text or json.dumps(q, ensure_ascii=False)[1:-1] in text for q in quotes
            )
        changed = set(git("diff", "--name-only").decode().splitlines())
        changed.update(git("ls-files", "--others", "--exclude-standard").decode().splitlines())
        allowed = {e["path"] for e in dm["exclude1461"]} | set(UPSERTS)
        assert changed <= allowed, "Unapproved worktree change"
        assert not git("diff", "--cached", "--name-only").strip(), "Staging changed"
        prospective = set(git("diff", "--name-only", BASE).decode().splitlines())
        prospective.update(git("ls-files", "--others", "--exclude-standard").decode().splitlines())
        assert len(prospective) == 129
        result = {
            "status": "PASS",
            "originalBackupFiles": 1475,
            "overlayFiles": 45,
            "removed": 1461,
            "retainedPrEvidence": 17,
            "sharedSecurity": 4,
            "currentEvidenceBytes": sum((ROOT / p).stat().st_size for p in expected),
            "prospectivePrFiles": len(prospective),
            "knownSourceQuotesRemaining": 0,
            "bundles": 6,
            "capabilities": 14,
            "scenarios": 12,
            "cases": 4,
            "gitHistory": "UNCHANGED",
            "productSourceGitBlobsMatch": True,
            "ignoredLocalCachesPreserved": sorted(local_only),
        }
        print(json.dumps(result), flush=True)
        return result


def selftest():
    fake = {"entries": [{"path": "reports/g8/old.json", "sha256": "a" * 64}]}
    clean, ref = sanitizer(fake, {"entries": []}, {"SYNTHETIC PRIVATE PASSAGE"})
    value = clean(
        {
            "status": "PARTIAL",
            "mode": "live",
            "calls": 2,
            "quote": "SYNTHETIC PRIVATE PASSAGE",
            "userId": "person-linked",
            "proof": "reports/g8/old.json",
        }
    )
    assert value["status"] == "PARTIAL" and value["mode"] == "live" and value["calls"] == 2
    assert value["quote"]["privateText"] and value["userId"]["privateText"]
    assert value["proof"]["archiveReferences"][0]["original"]["sha256"] == "a" * 64
    assert "SYNTHETIC PRIVATE PASSAGE" not in json.dumps(value)
    try:
        ref("reports/g8/unknown.json")
    except AssertionError:
        pass
    else:
        raise AssertionError("Unknown evidence reference accepted")
    try:
        safe_path("../outside")
    except AssertionError:
        pass
    else:
        raise AssertionError("Escaping path accepted")
    print("selftest PASS: private text, personal ID, status/mode/counts, archive refs, path guard")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("selftest", "build", "cleanup", "seal", "verify"))
    args = parser.parse_args()
    if args.action == "selftest":
        selftest()
    else:
        globals()[args.action]()

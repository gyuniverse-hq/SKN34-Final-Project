"""G8 append-only evidence writer. Hash paths are values, never credential-like keys."""

import argparse
import hashlib
import json
import re
import subprocess
import tempfile
from pathlib import Path, PurePosixPath

HASH_FIELDS = {
    "sourceSha256",
    "sourceFileSha256",
    "backendSourceSha256",
    "fileHashes",
    "sourceHashes",
    "files",
}


def read_manifest(value):
    """Read legacy maps and v2 entries without changing historical records."""
    entries = (
        [{"path": p, "sha256": h} for p, h in value.items()] if isinstance(value, dict) else value
    )
    if not isinstance(entries, list):
        raise ValueError("Invalid source manifest")
    result = {}
    for entry in entries:
        if not isinstance(entry, dict) or set(entry) != {"path", "sha256"}:
            raise ValueError("Invalid source entry")
        path, digest = entry["path"], entry["sha256"]
        if (
            not isinstance(path, str)
            or not path
            or "\\" in path
            or ":" in path
            or PurePosixPath(path).is_absolute()
            or ".." in PurePosixPath(path).parts
            or any(ord(c) < 32 for c in path)
            or path in result
            or not isinstance(digest, str)
            or not re.fullmatch(r"[0-9a-f]{64}", digest)
        ):
            raise ValueError("Invalid source entry")
        result[path] = digest
    return result


def source_manifest(root, paths):
    """Hash exact worktree bytes, including local line endings; no normalization."""
    root = Path(root).resolve()
    result = []
    for name in sorted(set(paths)):
        path = (root / name).resolve()
        if not path.is_relative_to(root):
            raise ValueError("Source outside repository")
        result.append(
            {
                "path": path.relative_to(root).as_posix(),
                "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            }
        )
    read_manifest(result)
    return result


def normalize_record(record):
    """Convert only declared source maps in a NEW record; leave task data untouched."""
    result = dict(record)
    for key in HASH_FIELDS:
        if key in result:
            result[key] = [{"path": p, "sha256": h} for p, h in read_manifest(result[key]).items()]
    result["sourceManifestVersion"] = 2
    return result


def append_record(target, record, *, scanner, config):
    """Scan complete serialized keys/values with no history ignore before appending."""
    version = subprocess.run([str(scanner), "version"], capture_output=True)
    if version.returncode or version.stdout.strip() != b"8.30.1":
        raise ValueError("Use the CI-pinned Gitleaks 8.30.1")
    payload = (json.dumps(normalize_record(record), ensure_ascii=False) + "\n").encode("utf-8")
    with tempfile.TemporaryDirectory(prefix="g8-evidence-scan-") as folder:
        path = Path(folder)
        (path / "record.jsonl").write_bytes(payload)
        # Empty ignore file prevents inherited historical fingerprints from hiding new data.
        (path / "empty.ignore").write_text("", encoding="utf-8")
        completed = subprocess.run(
            [
                str(scanner),
                "dir",
                str(path),
                "--config",
                str(Path(config).resolve()),
                "--gitleaks-ignore-path",
                str(path / "empty.ignore"),
                "--redact",
                "--no-banner",
            ],
            capture_output=True,
        )
        if completed.returncode:
            raise ValueError(
                "Evidence rejected: secret finding or scanner failure (contents omitted)"
            )
    with Path(target).open("ab") as stream:
        stream.write(payload)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--record", type=Path, required=True, help="New JSON record, not an old trace"
    )
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--source", action="append", default=[])
    parser.add_argument("--gitleaks", default="gitleaks")
    parser.add_argument("--config", type=Path, default=Path(".gitleaks.toml"))
    args = parser.parse_args()
    record = json.loads(args.record.read_text(encoding="utf-8"))
    if args.source:
        record["sourceSha256"] = source_manifest(args.root, args.source)
        record["sourceByteBasis"] = "worktree-exact"
    try:
        append_record(args.output, record, scanner=args.gitleaks, config=args.config)
    except (ValueError, OSError):
        parser.exit(
            1, "Evidence was not appended; inspect input/scanner locally. Contents omitted.\n"
        )


if __name__ == "__main__":
    main()

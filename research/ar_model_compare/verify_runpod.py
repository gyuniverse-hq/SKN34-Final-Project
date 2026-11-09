"""Check transferred archive hashes before extracting LaPa chunks."""
import argparse
import hashlib
import json
import zipfile
from pathlib import Path


def digest(path):
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--transfer", type=Path, required=True)
    p.add_argument("--destination", type=Path, required=True)
    args = p.parse_args()
    manifest = json.loads((args.transfer / "manifest.json").read_text(encoding="utf-8"))
    for item in manifest["chunks"]:
        path = args.transfer / item["file"]
        if not path.is_file() or path.stat().st_size != item["bytes"] or digest(path) != item["sha256"]:
            raise ValueError(f"Missing or corrupted archive: {path}")
        with zipfile.ZipFile(path) as z:
            if z.testzip() is not None:
                raise ValueError(f"ZIP integrity failure: {path}")
            for name in z.namelist():
                target = (args.destination / name).resolve()
                if not target.is_relative_to(args.destination.resolve()):
                    raise ValueError(f"Unsafe archive path: {name}")
            z.extractall(args.destination)
        print(f"verified {path.name}", flush=True)
    print(f"verified {manifest['total_pairs']} pairs in {len(manifest['chunks'])} chunks")


if __name__ == "__main__":
    main()

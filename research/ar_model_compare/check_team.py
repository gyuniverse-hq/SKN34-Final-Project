"""Check team photo/video names, metadata, and bare/applied pairs; no images are uploaded.

Input: research/data/ar_model_compare/team/<date>/ and meta.csv.
Output: diagnostic messages only; no photo contents are printed.
Run: research/ar_evaluation/.venv/Scripts/python.exe research/ar_model_compare/check_team.py
"""
import csv
import re
from pathlib import Path

TEAM = Path(__file__).resolve().parents[1] / "data/ar_model_compare/team"
PHOTO = re.compile(r"^(?P<person>[^_]+)_(?P<light>normal|dark)_(?P<angle>00|30|45)_(?P<lip>bare|applied)_(?P<finish>matte|satin|glossy|none)\.(?:jpg|jpeg)$", re.I)
VIDEO = re.compile(r"^[^_]+_(normal|dark)_video\.mp4$", re.I)


def inspect(folder):
    issues, groups = [], {}
    meta_path = folder / "meta.csv"
    if meta_path.exists():
        with meta_path.open(encoding="utf-8-sig", newline="") as f:
            reader = csv.DictReader(f)
            rows = list(reader)
            columns = set(reader.fieldnames or [])
        required = {"filename", "device", "time", "product", "hex", "notes"}
        if not required <= columns:
            issues.append(f"meta.csv missing columns: {', '.join(sorted(required - columns))}")
        metadata = {r.get("filename", ""): r for r in rows}
    else:
        metadata = {}
        issues.append("meta.csv missing")
    for f in sorted(folder.iterdir()):
        if not f.is_file() or f.name == "meta.csv":
            continue
        match = PHOTO.fullmatch(f.name)
        if not match and not VIDEO.fullmatch(f.name):
            issues.append(f"invalid filename: {f.name}")
            continue
        if f.name not in metadata:
            issues.append(f"metadata missing: {f.name}")
        if match:
            d = match.groupdict()
            if (d["lip"] == "bare") != (d["finish"] == "none"):
                issues.append(f"invalid lip/finish combination: {f.name}")
            groups.setdefault((d["person"], d["light"], d["angle"]), set()).add(d["lip"])
    for key, states in groups.items():
        if states != {"bare", "applied"}:
            issues.append(f"unpaired: {'/'.join(key)} ({', '.join(sorted(states))})")
    return issues


def main():
    if not TEAM.exists():
        print(f"no team data: {TEAM}")
        return
    for folder in sorted(p for p in TEAM.iterdir() if p.is_dir()):
        issues = inspect(folder)
        print(f"{folder.name}: {len(issues)} issue(s)")
        for issue in issues:
            print(" -", issue)


if __name__ == "__main__":
    main()

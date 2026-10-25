"""Check 숙제 01 photo names against AR_SPEC 8-A-1 (research/protocol/hw01_capture.md).

    python research/protocol/check_names.py [folder]     # default research/data/hw01_raw

Lists files that break the naming rule, applied photos without their bare (_0) partner in the
same person/light/angle/product, and products missing from meta.csv. Exit code 1 if any.
"""
import csv
import re
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
NAME = re.compile(r"^(p\d+)_(day|warm)_(00|30|45)_([a-z0-9]+(?:-[a-z0-9]+)*)_(0|1|3)(-b)?\.jpe?g$")
TEXTURES = {"matte", "velvet", "cream", "satin", "sheer", "glossy", "shimmer"}
HEX = re.compile(r"^#[0-9A-Fa-f]{6}$")


def check(folder: Path):
    bad, pairs, products = [], defaultdict(set), set()
    for p in sorted(folder.iterdir()):
        if p.is_dir() or p.name == "meta.csv":
            continue
        m = NAME.match(p.name)
        if not m:
            bad.append(p.name)
            continue
        person, light, angle, product, n, extra = m.groups()
        products.add(product)
        if not extra:
            pairs[(person, light, angle, product)].add(n)
    no_bare = [f"{'_'.join(k)}_{n}" for k, ns in sorted(pairs.items()) for n in sorted(ns - {"0"}) if "0" not in ns]
    meta_problems = []
    meta = folder / "meta.csv"
    known = {}
    if meta.exists():
        with open(meta, newline="", encoding="utf-8-sig") as f:
            for row in csv.DictReader(f):
                known[row.get("product", "")] = row
        for prod, row in known.items():
            if not HEX.match(row.get("hex", "")):
                meta_problems.append(f"{prod}: hex '{row.get('hex', '')}' is not #RRGGBB")
            if row.get("texture", "") not in TEXTURES:
                meta_problems.append(f"{prod}: texture '{row.get('texture', '')}' not in {sorted(TEXTURES)}")
    missing_meta = sorted(products - set(known))
    return bad, no_bare, missing_meta, meta_problems, meta.exists()


def main():
    folder = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "research/data/hw01_raw"
    if not folder.is_dir():
        sys.exit(f"folder not found: {folder}")
    bad, no_bare, missing_meta, meta_problems, has_meta = check(folder)
    sections = [
        ("이름 규칙 위반 ({사람}_{조명}_{각도}_{제품}_{횟수}.jpg)", bad),
        ("맨입술(_0) 짝이 없는 바른 사진", no_bare),
        ("meta.csv에 없는 제품", missing_meta if has_meta else ["meta.csv 없음"]),
        ("meta.csv 값 오류", meta_problems),
    ]
    failed = False
    for title, items in sections:
        if items:
            failed = True
            print(f"[!] {title}: {len(items)}")
            for it in items:
                print(f"    {it}")
    print("OK" if not failed else "문제 있음")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()

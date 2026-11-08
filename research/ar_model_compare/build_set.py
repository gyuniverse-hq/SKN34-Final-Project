"""Build a reproducible local input manifest from available prepared faces and team photos.

Inputs: research/data/lip_texture/faces, research/data/ar_model_compare/team.
Outputs: research/data/ar_model_compare/set/manifest.csv and local copies of images.
Run: research/ar_evaluation/.venv/Scripts/python.exe research/ar_model_compare/build_set.py

LaPa sampling is not implemented here: this script explicitly reports that omission.
"""
import csv
import hashlib
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "research/data/ar_model_compare"
FACES = ROOT / "research/data/lip_texture/faces"
FIELDS = ["id", "source", "path", "gt_path", "person", "condition", "yaw_bin", "mouth", "tone_bin", "license"]
NAMES = ("hs_a_cc0", "hs_b_by", "hs_c_by", "hs_d_by", "urban_model")


def main():
    out = DATA / "set"
    images = out / "images"
    images.mkdir(parents=True, exist_ok=True)
    rows = []
    for name in NAMES:
        src = FACES / f"{name}.png"
        if not src.is_file():
            print(f"missing: {src}")
            continue
        dest = images / src.name
        shutil.copyfile(src, dest)
        rows.append(dict(id=name, source="cc_faces", path=dest.relative_to(ROOT).as_posix(),
                         gt_path="", person=name, condition="unknown", yaw_bin="unknown",
                         mouth="unknown", tone_bin="unknown", license="source_record_requires_verification"))
    # Team images require validated metadata and consent before inclusion; never silently guess either.
    path = out / "manifest.csv"
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDS, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    print(f"manifest: {path}\nrows: {len(rows)}\nsha256: {digest}")
    print("LaPa stratification and team ingestion: not implemented; missing data is not synthesized.")


if __name__ == "__main__":
    main()

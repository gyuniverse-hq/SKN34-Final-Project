"""Still-photo YouCam vs our offline AR (not the live camera).

Sends consenting-team bare-lip photos to YouCam Makeup VTO and writes the result next to
optional local AR renders. Frames are not used by the Expo app (AR_SPEC 1-4).

    python research/youcam/compare_youcam.py --image face.jpg --hex '#DD5A59' --texture glossy
    python research/youcam/compare_youcam.py --raw research/data/hw01_raw --ar research/data/hw01_ar

Needs YOUCAM_API_KEY. Without --ar, only YouCam images are saved. With --ar, prints lip-region
highlight L (p98) so a flat selfie can be checked: gloss should raise p98, matte should not.
"""
from __future__ import annotations

import argparse
import csv
import re
import sys
from pathlib import Path

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
from youcam_vto import ROOT, load_key, run_lip

NAME = re.compile(r"^(p\d+)_(day|warm)_(00|30|45)_([a-z0-9-]+)_(1|3)\.jpe?g$", re.I)
OUT = ROOT / "research/data/youcam"


def lip_p98(bgr) -> float:
    """p98 of CIE L* in the central third of the image (mouth is usually there on a selfie)."""
    h, w = bgr.shape[:2]
    crop = bgr[h // 3 : 2 * h // 3, w // 4 : 3 * w // 4]
    lab = cv2.cvtColor(crop.astype(np.float32) / 255.0, cv2.COLOR_BGR2LAB)
    return float(np.percentile(lab[..., 0], 98))


def one(image: Path, hex_color: str, texture: str, intensity: int, key: str, ar: Path | None):
    OUT.mkdir(parents=True, exist_ok=True)
    dest = OUT / (image.stem + f"_{texture}_{hex_color.lstrip('#')}.png")
    dest.write_bytes(run_lip(image, key, hex_color, texture, intensity))
    yc = cv2.imread(str(dest))
    row = {"name": image.name, "youcam": str(dest), "hex": hex_color, "texture": texture, "youcam_Lp98": lip_p98(yc) if yc is not None else ""}
    if ar and ar.is_file():
        a = cv2.imread(str(ar))
        row["ar"] = str(ar)
        row["ar_Lp98"] = lip_p98(a) if a is not None else ""
        if yc is not None and a is not None:
            row["dL_hi"] = abs(float(row["youcam_Lp98"]) - float(row["ar_Lp98"]))
    return row


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--image", type=Path)
    ap.add_argument("--hex", default="#DD5A59")
    ap.add_argument("--texture", default="glossy")
    ap.add_argument("--intensity", type=int, default=70)
    ap.add_argument("--raw", type=Path, default=ROOT / "research/data/hw01_raw")
    ap.add_argument("--ar", type=Path, default=ROOT / "research/data/hw01_ar")
    ap.add_argument("--meta", type=Path, default=None)
    ap.add_argument("--limit", type=int, default=0)
    args = ap.parse_args()
    key = load_key()
    if not key:
        sys.exit("Set YOUCAM_API_KEY in .env (research only, never EXPO_PUBLIC_).")
    rows = []
    if args.image:
        ar = None
        if args.ar.is_dir():
            cand = args.ar / (args.image.stem + ".png")
            ar = cand if cand.is_file() else None
        elif args.ar.is_file():
            ar = args.ar
        rows.append(one(args.image, args.hex, args.texture, args.intensity, key, ar))
    else:
        meta_path = args.meta or args.raw / "meta.csv"
        products = {}
        if meta_path.is_file():
            with open(meta_path, newline="", encoding="utf-8") as f:
                for r in csv.DictReader(f):
                    products[r.get("product") or r.get("id") or ""] = r
        n = 0
        for img in sorted(args.raw.glob("*.jpg")) + sorted(args.raw.glob("*.jpeg")):
            m = NAME.match(img.name)
            if not m:
                continue
            _, _, _, product, swipes = m.groups()
            bare = img.with_name(img.name.replace(f"_{swipes}.", "_0."))
            if not bare.is_file():
                continue
            row_meta = products.get(product, {})
            hex_color = row_meta.get("hex") or args.hex
            texture = row_meta.get("texture") or args.texture
            ar = args.ar / (img.stem + ".png")
            rows.append(one(bare, hex_color, texture, 70 if swipes == "1" else 90, key, ar if ar.is_file() else None))
            n += 1
            if args.limit and n >= args.limit:
                break
        if not rows:
            sys.exit(f"No hw01 pairs in {args.raw}. Use --image for a single consenting-team photo.")
    out_csv = OUT / "compare.csv"
    with open(out_csv, "w", newline="", encoding="utf-8") as f:
        wr = csv.DictWriter(f, fieldnames=list(rows[0]))
        wr.writeheader()
        wr.writerows(rows)
    for r in rows:
        print(r)
    print("wrote", out_csv)


if __name__ == "__main__":
    main()

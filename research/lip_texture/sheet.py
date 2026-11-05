"""Side-by-side lip crops: bare | config A | config B | ... for chosen faces and shades.

Run: research/ar_evaluation/.venv/Scripts/python.exe research/lip_texture/sheet.py --tag s1b \
        --faces hs_d_by,urban_model --shades glossy_red,satin_red --configs old,on,sat --out compare.png
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "research" / "data" / "lip_texture"


def crop_box(face: str, width: int) -> tuple[slice, slice]:
    j = json.loads((DATA / "faces" / f"{face}.json").read_text())
    p = np.array(j["outer"])
    p[:, 0] = width - 1 - p[:, 0]
    c, w = p.mean(0), j["mouthWidthPx"]
    x0, y0 = int(c[0] - 0.62 * w), int(c[1] - 0.36 * w)
    return slice(y0, y0 + int(0.72 * w)), slice(x0, x0 + int(1.24 * w))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--tag", required=True)
    ap.add_argument("--faces", required=True)
    ap.add_argument("--shades", required=True)
    ap.add_argument("--configs", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--cell", type=int, default=420)
    args = ap.parse_args()
    d = DATA / "renders" / args.tag
    configs = args.configs.split(",")
    rows = []
    for face in args.faces.split(","):
        off = cv2.imread(str(d / f"{face}__off.png"))
        sl = crop_box(face, off.shape[1])
        for shade in args.shades.split(","):
            cells = [off[sl]] + [cv2.imread(str(d / f"{face}__{shade}__{c}.png"))[sl] for c in configs]
            h = int(args.cell * cells[0].shape[0] / cells[0].shape[1])
            cells = [cv2.resize(c, (args.cell, h), interpolation=cv2.INTER_CUBIC) for c in cells]
            label = np.full((h, 150, 3), 255, np.uint8)
            cv2.putText(label, face[:11], (6, h // 2 - 8), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 0, 0), 1)
            cv2.putText(label, shade, (6, h // 2 + 14), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 0, 0), 1)
            rows.append(np.concatenate([label] + cells, 1))
    head = np.full((30, rows[0].shape[1], 3), 255, np.uint8)
    for i, name in enumerate(["bare"] + configs):
        cv2.putText(head, name, (150 + i * args.cell + 8, 21), cv2.FONT_HERSHEY_SIMPLEX, 0.65, (0, 0, 0), 2)
    out = DATA / args.out
    cv2.imwrite(str(out), np.concatenate([head] + rows, 0))
    print(out)


if __name__ == "__main__":
    main()

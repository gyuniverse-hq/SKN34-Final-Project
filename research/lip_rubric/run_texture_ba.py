"""Render current vs more-texture TUNING on a few faces and score with compare_b0.

Candidate (결): creaseGain 1.0 → 1.4, keep other defaults. Offline research only —
quality_variants.md notes the page often compensates, so pixel deltas may be small.

  research/ar_evaluation/.venv/Scripts/python.exe research/lip_rubric/run_texture_ba.py
  ml/.venv/Scripts/python.exe research/lip_rubric/compare_b0.py pairs <out>/pairs.csv
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import cv2

from build_pack import crop_lips
from common import DATA, ROOT, write_csv
from learn_astra import OUT

WORK = DATA / "expansion_v3" / "work"
TAG = "texture_ba"
FACES = [
    "10044601603_0", "1121134065_1", "11272985704_1", "11344804476_0",
    "11878371606_0", "11895262983_1", "1195693494_0", "123768640_1",
]
SHADES = ["satin_coral", "glossy_red"]
VARIANTS = {
    "before": {},
    "after_texture": {"creaseGain": 1.4, "hlSparkle": 0.15},
}
PY = ROOT / "research" / "ar_evaluation" / ".venv" / "Scripts" / "python.exe"
RENDER = ROOT / "research" / "lip_texture" / "render.py"


def main():
    out = OUT / "texture_ba"
    out.mkdir(parents=True, exist_ok=True)
    configs = []
    for name, tuning in VARIANTS.items():
        configs += ["--config", f"{name}={json.dumps(tuning, separators=(',', ':'))}"]
    cmd = [
        str(PY), str(RENDER), "--tag", TAG, "--faces", ",".join(FACES),
        "--shades", ",".join(SHADES), "--data-dir", str(WORK),
        "--offline-strict", "--no-freeze", *configs,
    ]
    print(" ".join(cmd), flush=True)
    subprocess.run(cmd, cwd=ROOT, check=True)

    pairs, diffs = [], []
    for face in FACES:
        page = json.loads((WORK / "faces" / f"{face}.page.json").read_text(encoding="utf8"))
        for shade in SHADES:
            before = WORK / "renders" / TAG / f"{face}__{shade}__before.png"
            after = WORK / "renders" / TAG / f"{face}__{shade}__after_texture.png"
            if not before.exists() or not after.exists():
                raise FileNotFoundError(before if not before.exists() else after)
            b = cv2.imread(str(before)); a = cv2.imread(str(after))
            bc = crop_lips(b, page); ac = crop_lips(a, page)
            b_path = out / f"{face}__{shade}__before_crop.png"
            a_path = out / f"{face}__{shade}__after_crop.png"
            cv2.imwrite(str(b_path), bc); cv2.imwrite(str(a_path), ac)
            diff = float(cv2.absdiff(bc, ac).mean())
            diffs.append(diff)
            pairs.append({
                "face_id": face, "label": f"{shade}:creaseGain_1.4",
                "before_id": f"{face}__{shade}__before",
                "after_id": f"{face}__{shade}__after_texture",
                "before_crop": str(b_path), "after_crop": str(a_path),
                "pixel_mad": round(diff, 4),
            })
    write_csv(out / "pairs.csv", pairs)
    summary = {
        "faces": len(FACES), "pairs": len(pairs),
        "mean_crop_pixel_mad": round(sum(diffs) / len(diffs), 4),
        "max_crop_pixel_mad": round(max(diffs), 4),
        "candidate": VARIANTS["after_texture"],
        "note": "if mean MAD < 1.0 the offline page likely compensated; B0 delta will be noise",
    }
    (out / "render_summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

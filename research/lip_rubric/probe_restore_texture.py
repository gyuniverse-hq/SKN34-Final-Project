"""Probe: restore bare-lip high frequency into the painted lip (image-space), score with B0.

Not an app change — a direction check. If B0 prefers the restored crop, the real shader should
keep more camera wrinkle contrast under the paint (creaseGain / lipDetail path).

  research/ar_evaluation/.venv/Scripts/python.exe research/lip_rubric/probe_restore_texture.py
  ml/.venv/Scripts/python.exe research/lip_rubric/compare_b0.py pairs <out>/pairs.csv
"""
from __future__ import annotations

import json
from pathlib import Path

import cv2
import numpy as np

from build_pack import crop_lips
from common import DATA, write_csv
from degrade import blend, lip_mask
from learn_astra import OUT
from run_texture_ba import FACES, SHADES, TAG, WORK

STRENGTH = 0.55


def restore(render, off, page, strength=STRENGTH):
    hard, soft, width, _ = lip_mask(page, render.shape)
    if not hard.any():
        return render.copy()
    sigma = max(1.5, 0.02 * width)
    r = render.astype(np.float32)
    o = off.astype(np.float32)
    detail = o - cv2.GaussianBlur(o, (0, 0), sigma)
    # Keep colour of the lipstick; only add high-frequency structure.
    boosted = np.clip(r + detail * strength, 0, 255).astype(np.uint8)
    return blend(render, boosted, soft * strength)


def main():
    out = OUT / "restore_texture_probe"
    out.mkdir(parents=True, exist_ok=True)
    pairs, mads = [], []
    for face in FACES:
        page = json.loads((WORK / "faces" / f"{face}.page.json").read_text(encoding="utf8"))
        off = cv2.imread(str(WORK / "renders" / TAG / f"{face}__off.png"))
        if off is None:
            raise FileNotFoundError(face)
        for shade in SHADES:
            before = cv2.imread(str(WORK / "renders" / TAG / f"{face}__{shade}__before.png"))
            after = restore(before, off, page)
            bc = crop_lips(before, page); ac = crop_lips(after, page)
            b_path = out / f"{face}__{shade}__before_crop.png"
            a_path = out / f"{face}__{shade}__after_crop.png"
            cv2.imwrite(str(b_path), bc); cv2.imwrite(str(a_path), ac)
            mad = float(cv2.absdiff(bc, ac).mean())
            mads.append(mad)
            pairs.append({
                "face_id": face, "label": f"{shade}:restore_hf_{STRENGTH}",
                "before_id": f"{face}__{shade}__before",
                "after_id": f"{face}__{shade}__restore",
                "before_crop": str(b_path), "after_crop": str(a_path),
                "pixel_mad": round(mad, 4),
            })
    write_csv(out / "pairs.csv", pairs)
    summary = {
        "pairs": len(pairs), "strength": STRENGTH,
        "mean_crop_pixel_mad": round(float(np.mean(mads)), 4),
        "max_crop_pixel_mad": round(float(np.max(mads)), 4),
    }
    (out / "probe_summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

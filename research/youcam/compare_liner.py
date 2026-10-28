"""One still-photo YouCam eyeliner vs a local face (research only).

Does not change live hex or EYELINER_PRESET.lineWing. Live AR never calls this.

    python research/youcam/compare_liner.py --image face.jpg --hex '#1A1A1A'
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from youcam_vto import ROOT, load_key, run_liner

OUT = ROOT / "research/data/youcam"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--image", type=Path, required=True)
    ap.add_argument("--hex", default="#1A1A1A")
    ap.add_argument("--texture", default="matte")
    ap.add_argument("--intensity", type=int, default=70)
    args = ap.parse_args()
    key = load_key()
    if not key:
        sys.exit("Set YOUCAM_API_KEY in .env (research only, never EXPO_PUBLIC_).")
    if not args.image.is_file():
        sys.exit(f"missing image {args.image}")
    OUT.mkdir(parents=True, exist_ok=True)
    dest = OUT / (args.image.stem + f"_liner_{args.hex.lstrip('#')}.png")
    dest.write_bytes(run_liner(args.image, key, args.hex, args.texture, args.intensity))
    meta = {"image": str(args.image), "youcam": str(dest), "hex": args.hex, "texture": args.texture}
    (OUT / (args.image.stem + "_liner.json")).write_text(json.dumps(meta, indent=2), encoding="utf-8")
    print(json.dumps(meta, indent=2))


if __name__ == "__main__":
    main()

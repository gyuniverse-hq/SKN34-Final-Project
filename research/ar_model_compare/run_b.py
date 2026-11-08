"""Run fixed-frame app renderer comparisons on five local faces, without editing app code.

Input: research/data/lip_texture/faces and local MediaPipe assets.
Output: research/data/lip_texture/renders/ar_model_compare_b/ (gitignored).
Run: research/ar_evaluation/.venv/Scripts/python.exe research/ar_model_compare/run_b.py
"""
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
TAG = "ar_model_compare_b"
CONFIGS = {
    "current": {},
    "detail": {"lipDetail": 1},
    "wide": {"lipDetail": 1, "wideDetail": 0.5},
    "anisotropic": {"lipDetail": 1, "wideDetail": 0.5, "glossAniso": 0.6},
    "nogloss": {"glossGain": 0, "lipSheen": 0, "lipGlint": 0},
}


def main():
    subprocess.run(["node", "research/lip_texture/build_html.mjs"], cwd=ROOT, check=True)
    cmd = [sys.executable, "research/lip_texture/render.py", "--tag", TAG]
    for name, config in CONFIGS.items():
        cmd.extend(["--config", f"{name}={json.dumps(config)}"])
    subprocess.run(cmd + sys.argv[1:], cwd=ROOT, check=True)


if __name__ == "__main__":
    main()

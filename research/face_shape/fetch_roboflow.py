"""Download one Roboflow Universe face-shape dataset (folder format) into the git-ignored data dir.

Offline calibration only: images never go into the repo or the app, only the fitted numbers do.
Key: ROBOFLOW_API_KEY in .env (read here, never printed).

    python research/face_shape/fetch_roboflow.py [workspace project version]
Default: ashish-workspace face-shape-classification-yoqx4-lfvhe 1 (CC BY 4.0 on its Universe page; image
provenance / consent is not stated there, so keep the images local).
"""
import io
import json
import re
import sys
import urllib.request
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "research" / "data" / "reference" / "face_shape"


def api_key() -> str:
    for line in (ROOT / ".env").read_text(encoding="utf-8").splitlines():
        m = re.match(r"\s*ROBOFLOW_API_KEY\s*=\s*(.+?)\s*$", line)
        if m:
            return m.group(1).strip("\"'")
    raise SystemExit("ROBOFLOW_API_KEY missing in .env")


def main() -> None:
    ws, proj, ver = (sys.argv[1:4] + ["", "", ""])[:3] if len(sys.argv) >= 4 else (
        "ashish-workspace", "face-shape-classification-yoqx4-lfvhe", "1")
    key = api_key()
    meta = json.load(urllib.request.urlopen(f"https://api.roboflow.com/{ws}/{proj}/{ver}/folder?api_key={key}", timeout=60))
    link = meta["export"]["link"]
    dest = OUT / f"{ws}__{proj}__v{ver}"
    dest.mkdir(parents=True, exist_ok=True)
    data = urllib.request.urlopen(link, timeout=600).read()
    zipfile.ZipFile(io.BytesIO(data)).extractall(dest)
    n = sum(1 for p in dest.rglob("*") if p.suffix.lower() in {".jpg", ".jpeg", ".png"})
    print("saved", dest.relative_to(ROOT), n, "images")


if __name__ == "__main__":
    main()

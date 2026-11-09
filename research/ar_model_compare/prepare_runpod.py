"""Prepare isolated, verifiable RunPod bundles under ignored research/data/."""
import hashlib
import json
import re
import zipfile
from pathlib import Path

from segformer_lapa import pairs

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "research/data/ar_model_compare/runpod-transfer"


def digest(path):
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    text = (ROOT / "components/ar/faceTrackerHtml.ts").read_text(encoding="utf-8")
    rings = {"source": "components/ar/faceTrackerHtml.ts", "source_sha256": hashlib.sha256(text.encode()).hexdigest()}
    for name in ("LIPS_OUTER", "LIPS_INNER"):
        match = re.search(r"const " + name + r" = (\[[0-9, ]+\]);", text)
        if not match:
            raise ValueError(f"Could not find {name} in app renderer")
        rings[name] = json.loads(match.group(1))
    tooling = OUT / "comparison-tools.zip"
    scripts = ("segformer_lapa.py", "farl_lapa.py", "bisenet_lapa.py", "landmark_lapa.py", "metrics_a.py", "sam2_prompts.py", "verify_runpod.py")
    with zipfile.ZipFile(tooling, "w", compression=zipfile.ZIP_DEFLATED) as z:
        for script in scripts:
            z.write(ROOT / "research/ar_model_compare" / script, "tools/" + script)
        z.writestr("tools/app_lip_rings.json", json.dumps(rings, indent=2))
        z.write(ROOT / "research/data/models/face_landmarker.task", "tools/face_landmarker.task")
    data = pairs(ROOT / "research/data/LaPa/test")
    manifest = []
    for start in range(0, len(data), 200):
        chunk = data[start:start + 200]
        target = OUT / f"lapa-test-{start // 200 + 1:02}.zip"
        with zipfile.ZipFile(target, "w", compression=zipfile.ZIP_STORED) as z:
            for _, image, label in chunk:
                z.write(image, "lapa/test/images/" + image.name)
                z.write(label, "lapa/test/labels/" + label.name)
        manifest.append({"file": target.name, "pairs": len(chunk), "bytes": target.stat().st_size,
                         "sha256": digest(target)})
    info = {"total_pairs": len(data), "tools": {"file": tooling.name, "bytes": tooling.stat().st_size,
             "sha256": digest(tooling)}, "chunks": manifest}
    (OUT / "manifest.json").write_text(json.dumps(info, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(info, indent=2))


if __name__ == "__main__":
    main()

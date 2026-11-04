"""est_light.py: the app's own sampleScene() on an image, 6 calls 500 ms apart, with the light it estimates.

For each image: light.dir (unit vector, page frame: x right on the mirrored screen, y up, z toward the viewer), dirConf, strength,
skinMeanLum, the number of skin samples the fit used, and the time of one sampleScene() call.

    python research/light_eval/est_light.py IMG [IMG ...] [--out results/est.json] [--page PAGE.ts]

Time: headless Chrome runs under --virtual-time-budget, where performance.now() does not move with CPU work, so the time of one call
is the wall-clock difference between a run with many calls and a run with none, divided by the number of calls. It is a PC
(headless, SwiftShader, one core) figure, NOT a phone figure.
"""
import argparse
import json
import sys
from pathlib import Path

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
import lighteval as L  # noqa: E402


def estimate(paths, page=L.PAGE, tag="est"):
    frames, faces, jobs = {}, {}, []
    for i, p in enumerate(paths):
        img = L.fit(cv2.imread(str(p)))
        lm = L.landmarks(img)
        if lm is None:
            print(f"skip {Path(p).name}: no face")
            continue
        fname, key = f"f{i}.png", f"f{i}"
        frames[fname], faces[key] = img, lm
        h, w = img.shape[:2]
        jobs.append({"name": Path(p).stem, "lm": key, "w": w, "h": h, "frame": fname})
    res, _ = L.run_jobs(jobs, faces, frames, page=page, tag=tag)
    return res


def call_ms(img_path, page=L.PAGE, n_calls=300):
    """PC headless wall-clock cost of one sampleScene() call (see the module docstring)."""
    img = L.fit(cv2.imread(str(img_path)))
    lm = L.landmarks(img)
    h, w = img.shape[:2]
    base = [{"name": "t", "lm": "f", "w": w, "h": h, "frame": "f.png", "calls": 0}]
    many = [{"name": "t", "lm": "f", "w": w, "h": h, "frame": "f.png", "calls": n_calls}]
    walls = {0: [], n_calls: []}
    for _ in range(3):                                     # three alternating pairs: a single pair is noisy
        for key, jobs in ((0, base), (n_calls, many)):
            _, wall = L.run_jobs(jobs, {"f": lm}, {"f.png": img}, page=page, tag="ms")
            walls[key].append(wall)
    return (np.median(walls[n_calls]) - np.median(walls[0])) / n_calls * 1000, walls


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("images", nargs="+")
    ap.add_argument("--out", type=Path, default=None)
    ap.add_argument("--page", type=Path, default=L.PAGE)
    ap.add_argument("--ms", action="store_true", help="also time one sampleScene() call on the first image")
    a = ap.parse_args()
    res = estimate(a.images, a.page)
    for r in res:
        d = r["first"]["dir"]
        print(f"{r['name']:28s} dir ({d[0]:+.2f} {d[1]:+.2f} {d[2]:+.2f})  conf {r['first']['conf']:.2f}  strength {r['first']['strength']:.2f}  samples {r['nSamples']}")
    out = {"page": str(a.page), "results": res}
    if a.ms:
        ms, walls = call_ms(a.images[0], a.page)
        out["call_ms_pc_headless"] = ms
        print(f"sampleScene() one call: {ms:.2f} ms (PC headless; wall runs {walls})")
    if a.out:
        a.out.parent.mkdir(parents=True, exist_ok=True)
        a.out.write_text(json.dumps(out, indent=1))
        print("->", a.out)


if __name__ == "__main__":
    main()

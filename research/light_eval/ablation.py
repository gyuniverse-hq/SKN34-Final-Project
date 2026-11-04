"""ablation.py: what does the light-direction estimate buy? Current page vs a COPY with uLightConf forced to 0 (= frontal light).

uLightConf is the weight of the estimated direction in the lip shader (volume shading and the gloss position). With 0 the shader
behaves as if the light were frontal. The app file is not changed: the copy lives in research/light_eval/_tmp/ only.

The 20 Kaggle pairs (hw01_raw) are rendered with both pages (research/lip_reference/render_ar_offline.py) and compared with the real
photos (research/lip_reference/hw01_compare.py: CIEDE2000 of the mean lip colour, |p90-p10| of L* spread, |p98| highlight, SSIM).
"wins" = pairs where the AR beats the bare lip on that metric (the figure the evaluation reports out of 20).

    python research/light_eval/ablation.py [--out research/light_eval/results/baseline_ablation.json]
"""
import argparse
import csv
import json
import subprocess
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
import lighteval as L  # noqa: E402

CONF_LINE = "gl.uniform1f(u.uLightConf, light.dirConf);"


def summarize(csv_path):
    by = {}
    for r in csv.DictReader(open(csv_path, newline="")):
        by.setdefault(r["name"], {})[r["method"]] = {k: float(r[k]) for k in ("dE", "dL_spread", "dL_hi", "ssim")}
    pairs = [v for v in by.values() if "ar" in v and "bare" in v]
    n = len(pairs)
    win = lambda k, better: sum(better(p["ar"][k], p["bare"][k]) for p in pairs)
    return {"pairs": n, "dE_median": float(np.median([p["ar"]["dE"] for p in pairs])), "dE_mean": float(np.mean([p["ar"]["dE"] for p in pairs])),
            "wins_spread": win("dL_spread", lambda a, b: a < b), "wins_hi": win("dL_hi", lambda a, b: a < b), "wins_ssim": win("ssim", lambda a, b: a > b),
            "spread_median": float(np.median([p["ar"]["dL_spread"] for p in pairs])), "hi_median": float(np.median([p["ar"]["dL_hi"] for p in pairs])),
            "ssim_median": float(np.median([p["ar"]["ssim"] for p in pairs]))}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", type=Path, default=L.HERE / "results/baseline_ablation.json")
    ap.add_argument("--skip-render", action="store_true", help="reuse the renders already in _tmp/ablation")
    a = ap.parse_args()
    tmp = L.HERE / "_tmp/ablation"
    tmp.mkdir(parents=True, exist_ok=True)
    src = L.PAGE.read_text(encoding="utf-8")
    if src.count(CONF_LINE) != 1:
        sys.exit(f"expected exactly one `{CONF_LINE}` in the page, found {src.count(CONF_LINE)}")
    pages = {"current": L.PAGE, "conf0": tmp / "page_conf0.ts.txt"}
    pages["conf0"].write_text(src.replace(CONF_LINE, "gl.uniform1f(u.uLightConf, 0.0);"), encoding="utf-8")
    py = sys.executable
    lip = L.TOOLS / "research/lip_reference"
    if not a.skip_render:
        for tag, page in pages.items():
            print("render", tag, flush=True)
            subprocess.run([py, str(lip / "render_ar_offline.py"), "--raw", str(L.HW01), "--out", str(tmp / f"{tag}_ar"), "--page", str(page)],
                           check=True, capture_output=True, text=True)
    procs = {}
    for tag in pages:
        print("compare", tag, "(several minutes)", flush=True)
        procs[tag] = subprocess.Popen([py, str(lip / "hw01_compare.py"), "--raw", str(L.HW01), "--ar", str(tmp / f"{tag}_ar"),
                                       "--masks", str(tmp / "no_masks"), "--out", str(tmp / f"{tag}_compare.csv")],
                                      stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    for p in procs.values():
        p.wait()
    res = {tag: summarize(tmp / f"{tag}_compare.csv") for tag in pages}
    res["page"] = str(L.PAGE)
    a.out.parent.mkdir(parents=True, exist_ok=True)
    a.out.write_text(json.dumps(res, indent=1))
    keys = [("dE_median", "dE00 median"), ("dE_mean", "dE00 mean"), ("wins_spread", "wins L* spread /20"), ("wins_hi", "wins highlight /20"),
            ("wins_ssim", "wins SSIM /20"), ("spread_median", "spread median"), ("hi_median", "highlight median"), ("ssim_median", "SSIM median")]
    print(f"\n{'':22s}{'current':>10s}{'conf=0':>10s}{'diff':>10s}")
    for k, label in keys:
        c, z = res["current"][k], res["conf0"][k]
        print(f"{label:22s}{c:10.2f}{z:10.2f}{c - z:+10.2f}")
    print("->", a.out)


if __name__ == "__main__":
    main()

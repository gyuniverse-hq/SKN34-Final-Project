"""Render the AR lipstick of the app onto bare-lip photos, offline (숙제 01, AR_SPEC 8-B).

For every applied photo `{p}_{light}_{angle}_{product}_{n}.jpg` (n = 1 or 3) this renders the
product from meta.csv onto its bare partner `..._0.jpg` with the real shader in
components/ar/faceTrackerHtml.ts, and saves research/data/hw01_ar/{applied name}.png. The
compare tool then puts it next to the real applied photo.

The page runs in headless Chrome (SwiftShader WebGL) from a localhost-only server; frames never
leave the PC (AR_SPEC 1-4). Same shader and light estimation as the app, but not the phone camera
pipeline (WebView, GPU, noise), so device captures are still needed for that.

    python research/lip_reference/render_ar_offline.py [--raw DIR] [--out DIR]
"""
import argparse
import base64
import csv
import functools
import http.server
import json
import re
import shutil
import subprocess
import threading
from pathlib import Path

import cv2
import mediapipe as mp
import numpy as np

from eval_lapa import ROOT, make_landmarker

NAME = re.compile(r"^(p\d+)_(day|warm)_(00|30|45)_([a-z0-9-]+)_(1|3)\.jpe?g$")
CHROME = Path("C:/Program Files/Google/Chrome/Application/chrome.exe")
MAX_SIDE = 1280
# 1 swipe / 3 swipes → intensity slider (TUNING.layersPerIntensity = 3).
INTENSITY = {"1": 1 / 3, "3": 1.0}


def page_html(page: Path = ROOT / "components/ar/faceTrackerHtml.ts"):
    """The AR page as the app ships it, with the camera <video> swapped for a canvas we fill."""
    src = page.read_text(encoding="utf-8")
    uv = (ROOT / "components/ar/faceUV.ts").read_text(encoding="utf-8")
    g = lambda n: re.search(n + r": number\[\] = (\[.*?\]);", uv, re.S).group(1)
    html = re.search(r"FACE_TRACKER_HTML = `(.*)`;", src, re.S).group(1)
    ver = re.search(r"MEDIAPIPE_VERSION = '([^']+)'", src).group(1)
    html = (html.replace("${JSON.stringify(FACE_MOUTH_TRIANGLES)}", g("FACE_MOUTH_TRIANGLES"))
            .replace("${MEDIAPIPE_VERSION}", ver).replace("${JSON.stringify(FACE_UV)}", g("FACE_UV"))
            .replace("${JSON.stringify(FACE_TRIANGLES)}", g("FACE_TRIANGLES")))
    if "${" in html:
        raise SystemExit("faceTrackerHtml.ts has a template value this tool does not fill")
    html = html.replace("gl.UNSIGNED_BYTE, video);", "gl.UNSIGNED_BYTE, window.__src || video);")
    for name in ["statsCtx", "grainCtx", "camCtx", "blurCtx", "edgeCropCtx", "lidCtx"]:
        html = html.replace(name + ".drawImage(video,", name + ".drawImage(window.__src || video,")
    harness = r"""
  (async () => { try {
    const jobs = await (await fetch('jobs.json')).json();
    const src = document.createElement('canvas'); window.__src = src;
    masks = paintMasks(); renderer = createGLRenderer();
    if (!renderer) throw new Error('no webgl');
    const load = (u) => new Promise((ok, no) => { const i = new Image(); i.onload = () => ok(i); i.onerror = no; i.src = u; });
    const out = document.createElement('canvas');
    for (const job of jobs) {
      const W = job.w, H = job.h;
      src.width = W; src.height = H;
      src.getContext('2d').drawImage(await load(job.frame), 0, 0, W, H);
      for (let i = 0; i < N_LANDMARKS && i < job.x.length; i++) { sx[i] = job.x[i]; sy[i] = job.y[i]; sz[i] = job.z[i]; }
      hasFace = true; updateMesh(W, H);
      light.samples = 0; if (typeof shownLight !== 'undefined') shownLight.t = 0; lipEdge.samples = 0; lipEdge.conf.fill(0); lipEdge.t.fill(1);
      lipThick.upBase = 0; lipThick.lowBase = 0;
      for (let k = 0; k < 6; k++) { sampleScene(k * 500, W, H); measureLipThickness(W, H); measureLipEdge(W, H); }
      makeup = { lip: { hex: job.hex, intensity: job.intensity, texture: job.texture }, blush: null, eyeshadow: null };
      renderer.upload();
      for (let k = 0; k < 4; k++) renderer.render(W, H);
      out.width = W; out.height = H;
      const o = out.getContext('2d');
      // The page shows a mirrored selfie; flip back so the render lines up with the photo.
      o.setTransform(-1, 0, 0, 1, W, 0); o.drawImage(glCanvas, 0, 0); o.setTransform(1, 0, 0, 1, 0, 0);
      const img = document.createElement('img'); img.className = 'result'; img.dataset.name = job.name;
      img.src = out.toDataURL('image/png'); document.body.appendChild(img);
    }
    document.title = 'OK ' + jobs.length;
  } catch (e) { document.title = 'ERR ' + (e && e.stack || e); } })();
"""
    if "  start();\n" not in html:
        raise SystemExit("start() call not found in the AR page")
    return html.replace("  start();\n", harness, 1)


def read_meta(raw: Path):
    with open(raw / "meta.csv", newline="", encoding="utf-8-sig") as f:
        return {r["product"]: r for r in csv.DictReader(f)}


def fit(img):
    h, w = img.shape[:2]
    s = min(1.0, MAX_SIDE / max(h, w))
    return cv2.resize(img, (round(w * s), round(h * s)), interpolation=cv2.INTER_AREA) if s < 1 else img


class QuietHandler(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *args):
        pass


def serve(folder: Path):
    """Localhost only, random free port: the page needs http (canvas reads) but nothing outside."""
    handler = functools.partial(QuietHandler, directory=str(folder))
    httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    return httpd


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--raw", type=Path, default=ROOT / "research/data/hw01_raw")
    ap.add_argument("--out", type=Path, default=ROOT / "research/data/hw01_ar")
    ap.add_argument("--page", type=Path, default=ROOT / "components/ar/faceTrackerHtml.ts",
                    help="another copy of the AR page, to compare a change before/after")
    args = ap.parse_args()
    meta = read_meta(args.raw)
    work = args.out / "_work"
    shutil.rmtree(work, ignore_errors=True)
    work.mkdir(parents=True)
    lm = make_landmarker()
    jobs = []
    for p in sorted(args.raw.glob("*.jp*g")):
        m = NAME.match(p.name)
        if not m:
            continue
        person, light, angle, product, n = m.groups()
        bare = p.with_name(f"{person}_{light}_{angle}_{product}_0{p.suffix}")
        if not bare.exists() or product not in meta:
            print(f"skip {p.name}: no bare partner or meta row")
            continue
        img = fit(cv2.imread(str(bare)))
        h, w = img.shape[:2]
        res = lm.detect(mp.Image(image_format=mp.ImageFormat.SRGB, data=cv2.cvtColor(img, cv2.COLOR_BGR2RGB)))
        if not res.face_landmarks:
            print(f"skip {p.name}: no face in {bare.name}")
            continue
        frame = f"{len(jobs)}.png"
        cv2.imwrite(str(work / frame), img)
        f = res.face_landmarks[0]
        jobs.append({"name": p.stem, "frame": frame, "w": w, "h": h,
                     "x": [l.x for l in f], "y": [l.y for l in f], "z": [l.z for l in f],
                     "hex": meta[product]["hex"], "texture": meta[product]["texture"], "intensity": INTENSITY[n]})
    if not jobs:
        raise SystemExit("nothing to render")
    (work / "jobs.json").write_text(json.dumps(jobs))
    (work / "index.html").write_text(page_html(args.page), encoding="utf-8")
    httpd = serve(work)
    url = f"http://127.0.0.1:{httpd.server_address[1]}/index.html"
    dom = subprocess.run([str(CHROME), "--headless=new", "--use-angle=swiftshader", "--enable-unsafe-swiftshader",
                          f"--virtual-time-budget={60000 + 15000 * len(jobs)}", "--dump-dom", url],
                         capture_output=True, text=True, encoding="utf-8", timeout=900).stdout
    httpd.shutdown()
    title = re.search(r"<title>([^<]*)", dom)
    print(title.group(1)[:400] if title else "no title")
    saved = 0
    for name, data in re.findall(r'<img class="result" data-name="([^"]+)" src="data:image/png;base64,([^"]+)"', dom):
        (args.out / f"{name}.png").write_bytes(base64.b64decode(data))
        saved += 1
    shutil.rmtree(work, ignore_errors=True)
    print(f"saved {saved} renders to {args.out}")


if __name__ == "__main__":
    main()

"""Shared helpers for the AR light-estimation evaluation (stage 1: measurement only, the app is not changed).

The app page (components/ar/faceTrackerHtml.ts) is built the way research/lip_reference/render_ar_offline.py builds it, then
a harness runs the page's own `sampleScene()` on a given image with given landmarks and reads `light.dir / dirConf / strength`.
Headless Chrome + SwiftShader, a localhost-only server; no image leaves this PC.

Where the lip_reference scripts live: the repo checkout may not carry research/lip_reference (it is tracked only on the branch
that holds the final backup), so LIGHT_EVAL_TOOLS_ROOT can point at a folder that has research/lip_reference, research/data/models,
research/data/ar_eval_public/hw01_raw and components/ar/faceUV.ts.
"""
import base64
import functools
import html as htmllib
import http.server
import json
import os
import re
import shutil
import subprocess
import sys
import threading
from pathlib import Path

import cv2
import numpy as np

REPO = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent


def tools_root():
    env = os.environ.get("LIGHT_EVAL_TOOLS_ROOT")
    for cand in ([Path(env)] if env else []) + [REPO]:
        if (cand / "research/lip_reference/render_ar_offline.py").exists():
            return cand
    raise SystemExit("research/lip_reference not found: set LIGHT_EVAL_TOOLS_ROOT to a folder that has it (see the module docstring)")


TOOLS = tools_root()
sys.path.insert(0, str(TOOLS / "research/lip_reference"))
import render_ar_offline as ro  # noqa: E402  (CHROME, MAX_SIDE, fit, QuietHandler)
from eval_lapa import make_landmarker  # noqa: E402
import mediapipe as mp  # noqa: E402

PAGE = REPO / "components/ar/faceTrackerHtml.ts"
HW01 = TOOLS / "research/data/ar_eval_public/hw01_raw"
fit = ro.fit
FACE_UV_TS = TOOLS / "components/ar/faceUV.ts"
N_MESH = 468

HARNESS = r"""
  (async () => { try {
    const spec = await (await fetch('jobs.json')).json();
    const src = document.createElement('canvas'); window.__src = src;
    masks = paintMasks(); renderer = createGLRenderer();
    if (!renderer) throw new Error('no webgl');
    const load = (u) => new Promise((ok, no) => { const i = new Image(); i.onload = () => ok(i); i.onerror = no; i.src = u; });
    const light0 = JSON.parse(JSON.stringify(light));
    const out = [];
    for (const job of spec.jobs) {
      const lmk = spec.faces[job.lm];
      const W = job.w, H = job.h;
      src.width = W; src.height = H;
      if (job.frame) src.getContext('2d').drawImage(await load(job.frame), 0, 0, W, H);
      for (let i = 0; i < N_LANDMARKS && i < lmk.x.length; i++) { sx[i] = lmk.x[i]; sy[i] = lmk.y[i]; sz[i] = lmk.z[i]; }
      hasFace = true; updateMesh(W, H);
      Object.assign(light, JSON.parse(JSON.stringify(light0)));
      if (typeof shownLight !== 'undefined') shownLight.t = 0;
      const inFrame = (i) => sx[i] > 0.01 && sx[i] < 0.99 && sy[i] > 0.01 && sy[i] < 0.99;
      const res = { name: job.name, nSamples: masks.skinVerts.filter((i) => meshNrm[i * 3 + 2] >= 0.35 && inFrame(i)).length };
      const snap = () => ({ dir: light.dir.slice(), conf: light.dirConf, strength: light.strength, skinMeanLum: light.skinMeanLum,
                            r2: light.fitR2, rel: light.fitRel, shUsed: light.shUsed, shCond: light.shCond,
                            shDirectional: light.shDirectional });
      const calls = job.calls === undefined ? 6 : job.calls;
      for (let k = 0; k < calls; k++) {
        sampleScene(k * 500, W, H);
        if (k === 0) res.first = snap();
      }
      res.last = snap();
      if (job.want_mesh) {
        res.mesh = { nrm: Array.from(meshNrm.slice(0, N_MESH * 3)), x: Array.from(sx.slice(0, N_MESH)), y: Array.from(sy.slice(0, N_MESH)) };
      }
      out.push(res);
    }
    const pre = document.createElement('pre'); pre.id = 'res'; pre.textContent = JSON.stringify(out); document.body.appendChild(pre);
    document.title = 'OK ' + out.length;
  } catch (e) { document.title = 'ERR ' + (e && e.stack || e); } })();
"""


def build_page(page: Path = PAGE, harness: str = HARNESS) -> str:
    """The AR page with the camera <video> swapped for a canvas we fill, and our harness in place of start()."""
    src = Path(page).read_text(encoding="utf-8")
    uv = FACE_UV_TS.read_text(encoding="utf-8")
    g = lambda n: re.search(n + r": number\[\] = (\[.*?\]);", uv, re.S).group(1)
    html = re.search(r"FACE_TRACKER_HTML = `(.*)`;", src, re.S).group(1)
    ver = re.search(r"MEDIAPIPE_VERSION = '([^']+)'", src).group(1)
    html = (html.replace("${JSON.stringify(FACE_MOUTH_TRIANGLES)}", g("FACE_MOUTH_TRIANGLES")).replace("${MEDIAPIPE_VERSION}", ver)
            .replace("${JSON.stringify(FACE_UV)}", g("FACE_UV")).replace("${JSON.stringify(FACE_TRIANGLES)}", g("FACE_TRIANGLES")))
    if "${" in html:
        raise SystemExit("the page has a template value this tool does not fill")
    html = html.replace("gl.UNSIGNED_BYTE, video);", "gl.UNSIGNED_BYTE, window.__src || video);")
    for name in ["statsCtx", "grainCtx", "camCtx", "blurCtx", "edgeCropCtx", "lidCtx"]:
        html = html.replace(name + ".drawImage(video,", name + ".drawImage(window.__src || video,")
    if "  start();\n" not in html:
        raise SystemExit("start() call not found in the AR page")
    return html.replace("  start();\n", harness, 1)


def triangles():
    uv = FACE_UV_TS.read_text(encoding="utf-8")
    return np.array([int(v) for v in re.search(r"FACE_TRIANGLES: number\[\] = \[(.*?)\];", uv, re.S).group(1).split(",")]).reshape(-1, 3)


_landmarker = None


def landmarks(img_bgr):
    """MediaPipe landmarks of a BGR image as {x, y, z} lists (normalized), or None."""
    global _landmarker
    if _landmarker is None:
        _landmarker = make_landmarker()
    res = _landmarker.detect(mp.Image(image_format=mp.ImageFormat.SRGB, data=cv2.cvtColor(img_bgr, cv2.COLOR_BGR2RGB)))
    if not res.face_landmarks:
        return None
    f = res.face_landmarks[0]
    return {"x": [p.x for p in f], "y": [p.y for p in f], "z": [p.z for p in f]}


def run_jobs(jobs, faces, frames, page: Path = PAGE, work: Path = None, tag="run"):
    """Run the harness. jobs: [{name, lm, w, h, frame (file name in frames) | None, calls?, want_mesh?}], faces: {id: {x,y,z}},
    frames: {file name: BGR image or Path}. Returns (results list, wall seconds)."""
    import time
    work = Path(work or (HERE / "_tmp" / f"_work_{tag}"))
    shutil.rmtree(work, ignore_errors=True)
    work.mkdir(parents=True)
    for name, img in frames.items():
        if isinstance(img, np.ndarray):
            cv2.imwrite(str(work / name), img)
        else:
            shutil.copyfile(img, work / name)
    (work / "jobs.json").write_text(json.dumps({"jobs": jobs, "faces": faces}))
    (work / "index.html").write_text(build_page(page), encoding="utf-8")
    handler = functools.partial(ro.QuietHandler, directory=str(work))
    httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    url = f"http://127.0.0.1:{httpd.server_address[1]}/index.html"
    t0 = time.perf_counter()
    dom = subprocess.run([str(ro.CHROME), "--headless=new", "--use-angle=swiftshader", "--enable-unsafe-swiftshader",
                          f"--virtual-time-budget={60000 + 400 * len(jobs)}", "--dump-dom", url],
                         capture_output=True, text=True, encoding="utf-8", timeout=3000).stdout
    wall = time.perf_counter() - t0
    httpd.shutdown()
    shutil.rmtree(work, ignore_errors=True)
    title = re.search(r"<title>([^<]*)", dom)
    if not title or not title.group(1).startswith("OK"):
        raise SystemExit(f"harness failed: {title.group(1)[:600] if title else 'no title'}")
    res = re.search(r'<pre id="res">(.*?)</pre>', dom, re.S)
    return json.loads(htmllib.unescape(res.group(1))), wall


def page_with(tuning: dict, out: Path, page: Path = PAGE) -> Path:
    """A copy of the page with TUNING values replaced (`name: value,` lines), for switch-on runs. The app file is not changed."""
    src = Path(page).read_text(encoding="utf-8")
    for name, value in tuning.items():
        lit = json.dumps(value)
        src, n = re.subn(rf"(\n\s*{name}: )[^,\n]+,", lambda m: m.group(1) + lit + ",", src, count=1)
        if n != 1:
            raise SystemExit(f"TUNING.{name} not found in the page")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(src, encoding="utf-8")
    return out


def angle_deg(a, b):
    a, b = np.asarray(a, float), np.asarray(b, float)
    return float(np.degrees(np.arccos(np.clip(np.dot(a, b) / (np.linalg.norm(a) * np.linalg.norm(b) + 1e-12), -1, 1))))


def light_vec(az_deg, el_deg):
    """Light direction in the page frame (x right on the mirrored screen, y up, z toward the viewer)."""
    az, el = np.radians(az_deg), np.radians(el_deg)
    return np.array([np.sin(az) * np.cos(el), np.sin(el), np.cos(az) * np.cos(el)])


def srgb_to_lin(c):
    c = np.asarray(c, np.float32)
    return np.where(c <= 0.04045, c / 12.92, ((c + 0.055) / 1.055) ** 2.4)


def lin_to_srgb(x):
    x = np.clip(np.asarray(x, np.float32), 0, 1)
    return np.where(x <= 0.0031308, 12.92 * x, 1.055 * np.power(x, 1 / 2.4) - 0.055)

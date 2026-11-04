"""Eyeshadow shimmer / glitter grains, offline: TUNING.lidSparkle on vs off (the old grains).

The real page (components/ar/faceTrackerHtml.ts) paints a shimmer and a glitter shadow on bare-face photos (hw01, see
research/light_eval/lighteval.py for where they live), once as is and once with the lid sparkle forced to zero, so
`sparkle = render - no-sparkle render` holds only the grains and flashes. Each face is also rendered moved 0.5 px and turned
3 degrees (landmarks moved, the photo kept), to see whether grains hold still and whether flashes change.

Per finish and switch, over the faces:
- grains: connected spots brighter than the no-sparkle render by GRAIN_THR (sRGB levels), count and median area (px)
- survive_0.5px: share of grains that still have a grain within 1.5 px after a 0.5 px move (the grid is fixed to the face, so
  a grain that vanishes on a half-pixel move is aliasing, the flicker seen on the phone)
- flash_change_3deg: share of the brightest 5% sparkle pixels that leave that set when the head turns 3 degrees (glitter
  should change, shimmer less)

Headless Chrome + SwiftShader from a localhost-only server; renders stay in research/data/lid_sparkle (gitignored).

    python research/lid_sparkle/lid_eval.py [--faces 8]
"""
import argparse
import base64
import json
import sys
from pathlib import Path

import cv2
import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "light_eval"))
import lighteval as L  # noqa: E402

OUT = L.REPO / "research/data/lid_sparkle"
RESULTS = HERE / "results"
GRAIN_THR = 6
HEX = "#A8785C"
EYE_PTS = [33, 246, 161, 160, 159, 158, 157, 173, 133, 70, 63, 105, 66, 107,
           263, 466, 388, 387, 386, 385, 384, 398, 362, 300, 293, 334, 296, 336]

HARNESS = r"""
  (async () => { try {
    const spec = await (await fetch('jobs.json')).json();
    const src = document.createElement('canvas'); window.__src = src;
    masks = paintMasks(); renderer = createGLRenderer();
    if (!renderer) throw new Error('no webgl');
    const load = (u) => new Promise((ok, no) => { const i = new Image(); i.onload = () => ok(i); i.onerror = no; i.src = u; });
    const light0 = JSON.parse(JSON.stringify(light));
    const out = [], full = document.createElement('canvas'), crop = document.createElement('canvas');
    for (const job of spec.jobs) {
      const lmk = spec.faces[job.lm];
      const W = job.w, H = job.h;
      src.width = W; src.height = H;
      src.getContext('2d').drawImage(await load(job.frame), 0, 0, W, H);
      for (let i = 0; i < N_LANDMARKS && i < lmk.x.length; i++) { sx[i] = lmk.x[i]; sy[i] = lmk.y[i]; sz[i] = lmk.z[i]; }
      hasFace = true; updateMesh(W, H);
      Object.assign(light, JSON.parse(JSON.stringify(light0)));
      if (typeof shownLight !== 'undefined') shownLight.t = 0;
      if (typeof lidSparkle !== 'undefined') lidSparkle.pxPerUv = 0;
      for (let k = 0; k < 6; k++) sampleScene(k * 500, W, H);
      makeup = { lip: null, blush: null, eyeshadow: { hex: job.hex, intensity: 1, texture: 'shimmer', geometry: { shadowFinish: job.finish } } };
      renderer.upload();
      for (let k = 0; k < 3; k++) renderer.render(W, H);
      full.width = W; full.height = H;
      const o = full.getContext('2d');
      o.setTransform(-1, 0, 0, 1, W, 0); o.drawImage(glCanvas, 0, 0); o.setTransform(1, 0, 0, 1, 0, 0);
      const [x0, y0, cw, ch] = job.crop;
      crop.width = cw; crop.height = ch;
      crop.getContext('2d').drawImage(full, x0, y0, cw, ch, 0, 0, cw, ch);
      out.push({ name: job.name, png: crop.toDataURL('image/png'), pxPerUv: typeof lidSparkle !== 'undefined' ? lidSparkle.pxPerUv : 0 });
    }
    const pre = document.createElement('pre'); pre.id = 'res'; pre.textContent = JSON.stringify(out); document.body.appendChild(pre);
    document.title = 'OK ' + out.length;
  } catch (e) { document.title = 'ERR ' + (e && e.stack || e); } })();
"""


def page_variant(src_page: Path, out: Path, sparkle: bool, grains: bool) -> Path:
    text = src_page.read_text(encoding="utf-8")
    text = text.replace("    lidSparkle: true,", f"    lidSparkle: {'true' if sparkle else 'false'},", 1)
    if not grains:
        old = "gl.uniform1f(u.uShadowFlake, eye && eyeFinish.sparkleDensity > 0 ? clamp01(eye.intensity) : 0);"
        if old not in text:
            raise SystemExit("uShadowFlake line not found")
        text = text.replace(old, "gl.uniform1f(u.uShadowFlake, 0);", 1)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(text, encoding="utf-8")
    return out


def moved(lm, w, h, dx_px=0.0, yaw_deg=0.0):
    x = np.array(lm["x"]) * w, np.array(lm["y"]), np.array(lm["z"]) * w
    X, Y, Z = x
    cx, cz = X[:468].mean(), Z[:468].mean()
    a = np.radians(yaw_deg)
    X2 = cx + (X - cx) * np.cos(a) + (Z - cz) * np.sin(a)
    Z2 = cz - (X - cx) * np.sin(a) + (Z - cz) * np.cos(a)
    return {"x": list((X2 + dx_px) / w), "y": list(Y), "z": list(Z2 / w)}


def render(page: Path, jobs, faces, frames, tag):
    import re, shutil, functools, http.server, threading, subprocess, html as htmllib  # noqa: E401
    work = L.HERE / "_tmp" / f"_lid_{tag}"
    shutil.rmtree(work, ignore_errors=True)
    work.mkdir(parents=True)
    for name, img in frames.items():
        cv2.imwrite(str(work / name), img)
    (work / "jobs.json").write_text(json.dumps({"jobs": jobs, "faces": faces}))
    (work / "index.html").write_text(L.build_page(page, HARNESS), encoding="utf-8")
    handler = functools.partial(L.ro.QuietHandler, directory=str(work))
    httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    url = f"http://127.0.0.1:{httpd.server_address[1]}/index.html"
    dom = subprocess.run([str(L.ro.CHROME), "--headless=new", "--use-angle=swiftshader", "--enable-unsafe-swiftshader",
                          f"--virtual-time-budget={60000 + 3000 * len(jobs)}", "--dump-dom", url],
                         capture_output=True, text=True, encoding="utf-8", timeout=3000).stdout
    httpd.shutdown()
    shutil.rmtree(work, ignore_errors=True)
    title = re.search(r"<title>([^<]*)", dom)
    if not title or not title.group(1).startswith("OK"):
        raise SystemExit(f"harness failed ({tag}): {title.group(1)[:800] if title else 'no title'}")
    res = json.loads(htmllib.unescape(re.search(r'<pre id="res">(.*?)</pre>', dom, re.S).group(1)))
    out = {}
    for r in res:
        buf = np.frombuffer(base64.b64decode(r["png"].split(",", 1)[1]), np.uint8)
        out[r["name"]] = (cv2.imdecode(buf, cv2.IMREAD_COLOR), r["pxPerUv"])
    return out


def sparkle_map(img, base):
    lum = lambda im: cv2.cvtColor(im, cv2.COLOR_BGR2GRAY).astype(np.float32)  # noqa: E731
    return np.maximum(lum(img) - lum(base), 0)


def grains(s):
    n, lab, stats, cent = cv2.connectedComponentsWithStats((s > GRAIN_THR).astype(np.uint8), connectivity=8)
    return stats[1:, cv2.CC_STAT_AREA], cent[1:]


def survive(c0, c1, r=1.5, dx=0.5):
    if len(c0) == 0:
        return float("nan")
    if len(c1) == 0:
        return 0.0
    c1 = c1 - np.array([dx, 0])
    d = np.sqrt(((c0[:, None, :] - c1[None, :, :]) ** 2).sum(-1)).min(1)
    return float((d <= r).mean())


def top_change(s0, s1, q=0.95):
    m = s0 > GRAIN_THR
    if m.sum() < 20:
        return float("nan")
    t0 = s0 > np.quantile(s0[m], q)
    t1 = s1 > np.quantile(s1[s1 > GRAIN_THR], q) if (s1 > GRAIN_THR).sum() >= 20 else np.zeros_like(t0)
    return float((t0 & ~t1).sum() / max(t0.sum(), 1))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--faces", type=int, default=8)
    args = ap.parse_args()
    photos = sorted(L.HW01.glob("*_00_*_0.jp*g"))[: args.faces]
    faces, frames, base_jobs = {}, {}, []
    for i, p in enumerate(photos):
        img = L.fit(cv2.imread(str(p)))
        h, w = img.shape[:2]
        lm = L.landmarks(img)
        if lm is None:
            continue
        xs = np.array(lm["x"])[EYE_PTS] * w
        ys = np.array(lm["y"])[EYE_PTS] * h
        pad = 0.15 * (xs.max() - xs.min())
        x0, y0 = int(max(0, xs.min() - pad)), int(max(0, ys.min() - pad))
        crop = [x0, y0, int(min(w, xs.max() + pad)) - x0, int(min(h, ys.max() + pad)) - y0]
        frames[f"{i}.png"] = img
        for pose, (dx, yaw) in {"p0": (0, 0), "dx": (0.5, 0), "yaw": (0, 3)}.items():
            faces[f"{i}_{pose}"] = moved(lm, w, h, dx, yaw)
        for finish in ["shimmer", "glitter"]:
            for pose in ["p0", "dx", "yaw"]:
                base_jobs.append({"name": f"{p.stem}|{finish}|{pose}", "lm": f"{i}_{pose}", "w": w, "h": h,
                                  "frame": f"{i}.png", "hex": HEX, "finish": finish, "crop": crop})
    tmp = L.HERE / "_tmp"
    renders = {}
    for sw in [False, True]:
        for gr in [True, False]:
            page = page_variant(L.PAGE, tmp / f"lid_{int(sw)}{int(gr)}.page", sw, gr)
            renders[(sw, gr)] = render(page, base_jobs, faces, frames, f"{int(sw)}{int(gr)}")
    OUT.mkdir(parents=True, exist_ok=True)
    report = {"hex": HEX, "grain_thr_levels": GRAIN_THR, "faces": len(frames), "by": {}}
    for sw in [False, True]:
        for finish in ["shimmer", "glitter"]:
            counts, areas, surv, flash, ppu = [], [], [], [], []
            for p in photos:
                key = lambda pose: f"{p.stem}|{finish}|{pose}"  # noqa: E731
                if key("p0") not in renders[(sw, True)]:
                    continue
                s = {pose: sparkle_map(renders[(sw, True)][key(pose)][0], renders[(sw, False)][key(pose)][0]) for pose in ["p0", "dx", "yaw"]}
                a0, c0 = grains(s["p0"])
                _, c1 = grains(s["dx"])
                counts.append(len(a0))
                areas.extend(a0.tolist())
                surv.append(survive(c0, c1))
                flash.append(top_change(s["p0"], s["yaw"]))
                ppu.append(renders[(sw, True)][key("p0")][1])
                if p == photos[0]:
                    img = renders[(sw, True)][key("p0")][0]
                    big = cv2.resize(img, None, fx=3, fy=3, interpolation=cv2.INTER_NEAREST)
                    cv2.imwrite(str(OUT / f"{p.stem}_{finish}_{'on' if sw else 'off'}_x3.png"), big)
            report["by"][f"{finish}_{'on' if sw else 'off'}"] = {
                "grains_per_face": float(np.mean(counts)) if counts else None,
                "grain_area_px_median": float(np.median(areas)) if areas else None,
                "survive_0.5px": float(np.nanmean(surv)) if surv else None,
                "flash_change_3deg": float(np.nanmean(flash)) if flash else None,
                "px_per_uv": float(np.mean(ppu)) if ppu and sw else None,
            }
    RESULTS.mkdir(parents=True, exist_ok=True)
    (RESULTS / "lid_sparkle.json").write_text(json.dumps(report, indent=2))
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()

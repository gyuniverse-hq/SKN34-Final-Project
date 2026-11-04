"""Lip paint on open mouths: teeth guard, camera inner line and outer pull-in, each on or off, offline on LaPa test.

The real page (components/ar/faceTrackerHtml.ts) paints a satin lipstick on LaPa test faces scaled to a phone selfie (face
about 600 px tall). A pixel is painted when the render differs from the frame by more than CHANGED (sum of |dRGB|, 8-bit).
Against the LaPa labels (7 upper lip, 9 lower lip, 8 inner mouth = teeth / tongue / dark mouth):
- mouth_px: painted pixels on the inner mouth, share of all painted pixels (the teeth problem)
- spill: painted pixels off the lips and off the mouth (skin), share of all painted
- miss: lip pixels left unpainted, share of the lip
- iou: painted vs lip
Open = inner mouth at least OPEN_SHARE of the lip area; closed faces are the regression check.

Headless Chrome + SwiftShader from a localhost-only server; LaPa stays in research/data (gitignored).

    python research/lip_teeth/lip_teeth_eval.py [--open 80] [--closed 40]
"""
import argparse
import base64
import functools
import html as htmllib
import http.server
import json
import re
import shutil
import subprocess
import sys
import threading
from pathlib import Path

import cv2
import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "light_eval"))
import lighteval as L  # noqa: E402

LAPA = L.REPO / "research/data/reference/lapa/LaPa/test"
RESULTS = HERE / "results"
DUMP = L.REPO / "research/data/lip_teeth"
TMP = HERE.parent / "light_eval/_tmp"
CHANGED = 24
OPEN_SHARE = 0.15
FACE_PX = 600
SHADES = {"pale": "#E6D9AE", "red": "#B3263A"}
SWITCHES = ["lipTeethGuard", "lipInnerMeasure", "lipEdgePull"]
VARIANTS = {"off": [], "guard": ["lipTeethGuard"], "guard+inner": ["lipTeethGuard", "lipInnerMeasure"],
            "all": SWITCHES}

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
      lipEdge.samples = 0; lipEdge.conf.fill(0); lipEdge.t.fill(1);
      lipThick.upBase = 0; lipThick.lowBase = 0;
      for (let k = 0; k < 6; k++) { sampleScene(k * 500, W, H); measureLipThickness(W, H); measureLipEdge(W, H); }
      if (typeof lipInner !== 'undefined') {
        lipInner.conf.fill(0); lipInner.at = -1e9;
        for (let k = 0; k < 3; k++) measureLipInner(W, H, 10000 + k * 1000);
      }
      makeup = { lip: { hex: job.hex, intensity: 1, texture: 'satin' }, blush: null, eyeshadow: null };
      renderer.upload();
      for (let k = 0; k < 3; k++) renderer.render(W, H);
      full.width = W; full.height = H;
      const o = full.getContext('2d');
      o.setTransform(-1, 0, 0, 1, W, 0); o.drawImage(glCanvas, 0, 0); o.setTransform(1, 0, 0, 1, 0, 0);
      const [x0, y0, cw, ch] = job.crop;
      crop.width = cw; crop.height = ch;
      crop.getContext('2d').drawImage(full, x0, y0, cw, ch, 0, 0, cw, ch);
      out.push({ name: job.name, png: crop.toDataURL('image/png') });
    }
    const pre = document.createElement('pre'); pre.id = 'res'; pre.textContent = JSON.stringify(out); document.body.appendChild(pre);
    document.title = 'OK ' + out.length;
  } catch (e) { document.title = 'ERR ' + (e && e.stack || e); } })();
"""


def page_variant(on, out: Path) -> Path:
    text = L.PAGE.read_text(encoding="utf-8")
    for name in SWITCHES:
        text, n = re.subn(rf"(\n\s*{name}: )(true|false),", lambda m: m.group(1) + ("true" if name in on else "false") + ",", text, count=1)
        if n != 1:
            raise SystemExit(f"TUNING.{name} not found")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(text, encoding="utf-8")
    return out


def render(page: Path, jobs, faces, frames, tag):
    work = TMP / f"_teeth_{tag}"
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
                         capture_output=True, text=True, encoding="utf-8", timeout=5000).stdout
    httpd.shutdown()
    shutil.rmtree(work, ignore_errors=True)
    title = re.search(r"<title>([^<]*)", dom)
    if not title or not title.group(1).startswith("OK"):
        raise SystemExit(f"harness failed ({tag}): {title.group(1)[:800] if title else 'no title'}")
    res = json.loads(htmllib.unescape(re.search(r'<pre id="res">(.*?)</pre>', dom, re.S).group(1)))
    return {r["name"]: cv2.imdecode(np.frombuffer(base64.b64decode(r["png"].split(",", 1)[1]), np.uint8), cv2.IMREAD_COLOR)
            for r in res}


def teeth_like(frame, lab):
    """Inner-mouth pixels that look like teeth in the photo: bright (over 0.6 of the lip mean) and not red (under a quarter
    of the way from the skin's redness to the lip's). The wet inner lip, gums and tongue that LaPa also labels 8 drop out."""
    lin = L.srgb_to_lin(frame[..., ::-1].astype(np.float32) / 255)
    s = lin.sum(2) + 1e-4
    red = (lin[..., 0] - lin[..., 1]) / s
    lum = lin @ np.array([0.2126, 0.7152, 0.0722], np.float32)
    lip, skin = np.isin(lab, (7, 9)), lab == 1
    if lip.sum() < 20 or skin.sum() < 20:
        return np.zeros(lab.shape, bool)
    lr, sr = red[lip].mean(), red[skin].mean()
    return (lab == 8) & (lum > 0.6 * lum[lip].mean()) & (red < sr + 0.25 * (lr - sr))


def pick(n_open, n_closed):
    """Faces in file order: open (inner mouth >= OPEN_SHARE of the lip) and closed, scaled to a phone selfie."""
    opens, closed = [], []
    for lab_p in sorted(LAPA.glob("labels/*.png")):
        if len(opens) >= n_open and len(closed) >= n_closed:
            break
        lab = cv2.imread(str(lab_p), cv2.IMREAD_GRAYSCALE)
        lip = np.isin(lab, (7, 9)).sum()
        if lip < 200:
            continue
        share = (lab == 8).sum() / lip
        bucket = opens if share >= OPEN_SHARE else closed if share < 0.02 else None
        if bucket is None or len(bucket) >= (n_open if bucket is opens else n_closed):
            continue
        face = np.isin(lab, (1, 2, 3, 4, 5, 6, 7, 8, 9))
        ys = np.where(face.any(1))[0]
        s = FACE_PX / max(ys.max() - ys.min(), 1)
        if s > 1.0:
            continue
        img = cv2.imread(str(LAPA / "images" / (lab_p.stem + ".jpg")))
        img = cv2.resize(img, None, fx=s, fy=s, interpolation=cv2.INTER_AREA)
        lab = cv2.resize(lab, (img.shape[1], img.shape[0]), interpolation=cv2.INTER_NEAREST)
        bucket.append((lab_p.stem, img, lab))
    return opens, closed


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--open", type=int, default=80)
    ap.add_argument("--closed", type=int, default=40)
    ap.add_argument("--dump", type=int, default=0, help="save frame | render | paint-on-mouth overlays of this many open faces")
    args = ap.parse_args()
    opens, closed = pick(args.open, args.closed)
    faces, frames, jobs, gt = {}, {}, [], {}
    for kind, items in (("open", opens), ("closed", closed)):
        for stem, img, lab in items:
            lm = L.landmarks(img)
            if lm is None:
                continue
            h, w = img.shape[:2]
            xs, ys = np.array(lm["x"]) * w, np.array(lm["y"]) * h
            mouth = [61, 291, 0, 17, 37, 267, 84, 314]
            pad = 0.5 * (xs[mouth].max() - xs[mouth].min())
            x0, y0 = int(max(0, xs[mouth].min() - pad)), int(max(0, ys[mouth].min() - pad))
            x1, y1 = int(min(w, xs[mouth].max() + pad)), int(min(h, ys[mouth].max() + pad))
            crop = [x0, y0, x1 - x0, y1 - y0]
            faces[stem] = lm
            frames[f"{stem}.png"] = img
            gt[stem] = (kind, img[y0:y1, x0:x1], lab[y0:y1, x0:x1])
            for shade, hexv in SHADES.items():
                jobs.append({"name": f"{stem}|{shade}", "lm": stem, "w": w, "h": h, "frame": f"{stem}.png", "hex": hexv, "crop": crop})
    print(f"faces: open {sum(1 for v in gt.values() if v[0] == 'open')}, closed {sum(1 for v in gt.values() if v[0] == 'closed')}")
    report = {"changed": CHANGED, "open_share": OPEN_SHARE, "face_px": FACE_PX, "by": {}}
    for vname, on in VARIANTS.items():
        renders = render(page_variant(on, TMP / f"teeth_{vname}.page"), jobs, faces, frames, vname.replace("+", "_"))
        for kind in ("open", "closed"):
            for shade in SHADES:
                m = {"mouth_px": [], "teeth_painted": [], "spill": [], "miss": [], "iou": []}
                for stem, (k, frame, lab) in gt.items():
                    if k != kind:
                        continue
                    r = renders[f"{stem}|{shade}"]
                    painted = np.abs(r.astype(int) - frame.astype(int)).sum(2) > CHANGED
                    lip = np.isin(lab, (7, 9))
                    mouth = lab == 8
                    n = max(painted.sum(), 1)
                    m["mouth_px"].append((painted & mouth).sum() / n)
                    teeth = teeth_like(frame, lab)
                    if teeth.sum() >= 20:
                        m["teeth_painted"].append((painted & teeth).sum() / teeth.sum())
                    m["spill"].append((painted & ~lip & ~mouth).sum() / n)
                    m["miss"].append((lip & ~painted).sum() / max(lip.sum(), 1))
                    m["iou"].append((painted & lip).sum() / max((painted | lip).sum(), 1))
                report["by"][f"{vname}|{kind}|{shade}"] = {k2: round(float(np.mean(v)), 4) if v else None for k2, v in m.items()} | {
                    "n": len(m["iou"]), "n_teeth": len(m["teeth_painted"])}
        if args.dump:
            DUMP.mkdir(parents=True, exist_ok=True)
            for stem, (k, frame, lab) in list((s, v) for s, v in gt.items() if v[0] == "open")[: args.dump]:
                r = renders[f"{stem}|pale"]
                painted = np.abs(r.astype(int) - frame.astype(int)).sum(2) > CHANGED
                over = frame.copy()
                teeth = teeth_like(frame, lab)
                over[teeth] = (0.5 * over[teeth] + [0, 120, 0]).astype(np.uint8)
                over[painted & teeth] = (255, 0, 255)
                cv2.imwrite(str(DUMP / f"{stem}_{vname}.png"), np.hstack([frame, r, over]))
        print(vname, json.dumps({k: v for k, v in report["by"].items() if k.startswith(vname + "|")}))
    RESULTS.mkdir(parents=True, exist_ok=True)
    (RESULTS / "lip_teeth.json").write_text(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()

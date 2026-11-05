"""synth_light.py: faces with a KNOWN light, to measure the angle error of the app's light estimate.

A real frontal photo only supplies the MediaPipe landmarks. The app's own updateMesh() turns them into vertex normals (meshNrm);
the face image is then drawn with Lambert shading from a known light L:

    linear intensity at a vertex = exposure * (ambient + max(n . L, 0)),  colour = albedo * intensity,  sRGB encoded, 8 bit,
    interpolated over the mesh triangles (barycentric), flat grey outside the mesh.

The app's sampleScene() is run on that image and the angle between its light.dir and L is the error. This is the clean upper bound:
the shading is exactly Lambertian, there is no texture, shadow, specular, noise or camera processing. A real face is harder.

Grid: azimuth -60..+60 in 15 deg steps (9), elevation -40..+40 in 20 deg steps (5; 15 deg steps do not land on +-40),
ambient 0.2 and 0.5, albedo light / medium / dark (linear RGB, chosen here, not measured), 3 faces.

    python research/light_eval/synth_light.py [--faces 3] [--out research/light_eval/results/baseline_synth.json]
"""
import argparse
import itertools
import json
import sys
from pathlib import Path

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
import lighteval as L  # noqa: E402
from eval_lapa import frontal_score  # noqa: E402

ALBEDO = {"light": (0.62, 0.44, 0.36), "medium": (0.42, 0.28, 0.20), "dark": (0.17, 0.11, 0.08)}   # linear RGB (assumed)
AMBIENT = (0.2, 0.5)
AZ = list(range(-60, 61, 15))
EL = [-40, -20, 0, 20, 40]
EXPOSURE = 0.5
BACKGROUND = 0.2          # linear grey outside the mesh
SPEC_K, SPEC_P = 1.0, 80  # --spec: white highlight peak (linear, clips at 1) and sharpness (chosen here, not measured)


def pick_faces(n):
    """The n most frontal bare faces among the hw01 photos (nose midway between the eye corners), at distinct face sizes."""
    cands = []
    for p in sorted(L.HW01.glob("p*_0.jpg")):
        img = L.fit(cv2.imread(str(p)))
        lm = L.landmarks(img)
        if lm is None:
            continue
        h, w = img.shape[:2]
        pts = np.stack([np.array(lm["x"]) * w, np.array(lm["y"]) * h], 1)
        cands.append((frontal_score(pts), p.stem, img, lm))
    cands.sort(key=lambda c: -c[0])
    return cands[:n]


def raster_maps(sx, sy, tris, W, H):
    """Per pixel: the triangle it falls in (-1 outside) and its barycentric weights."""
    tid = np.full((H, W), -1, np.int32)
    bary = np.zeros((H, W, 3), np.float32)
    px, py = sx * W, sy * H
    for t, (a, b, c) in enumerate(tris):
        x0, x1 = int(np.floor(min(px[a], px[b], px[c]))), int(np.ceil(max(px[a], px[b], px[c])))
        y0, y1 = int(np.floor(min(py[a], py[b], py[c]))), int(np.ceil(max(py[a], py[b], py[c])))
        x0, y0, x1, y1 = max(x0, 0), max(y0, 0), min(x1, W - 1), min(y1, H - 1)
        if x1 < x0 or y1 < y0:
            continue
        gx, gy = np.meshgrid(np.arange(x0, x1 + 1) + 0.5, np.arange(y0, y1 + 1) + 0.5)
        d = (py[b] - py[c]) * (px[a] - px[c]) + (px[c] - px[b]) * (py[a] - py[c])
        if abs(d) < 1e-9:
            continue
        w0 = ((py[b] - py[c]) * (gx - px[c]) + (px[c] - px[b]) * (gy - py[c])) / d
        w1 = ((py[c] - py[a]) * (gx - px[c]) + (px[a] - px[c]) * (gy - py[c])) / d
        w2 = 1 - w0 - w1
        inside = (w0 >= -1e-6) & (w1 >= -1e-6) & (w2 >= -1e-6)
        sub_t = tid[y0:y1 + 1, x0:x1 + 1]; sub_b = bary[y0:y1 + 1, x0:x1 + 1]
        free = inside & (sub_t < 0)
        sub_t[free] = t
        sub_b[free] = np.stack([w0, w1, w2], -1)[free]
    return tid, bary


def shade(tid, bary, tris, nrm, light, ambient, albedo, spec=False):
    """Image (BGR uint8) of the mesh under light L (unit vector) with ambient and albedo.
    spec: add white specular spots, SPEC_K * max(n . H, 0)^SPEC_P with H halfway between L and the viewer (0, 0, 1),
    not tinted by the albedo. Small bright patches where a mirror reflection of L would be (forehead, nose, cheekbone)."""
    inten = EXPOSURE * (ambient + np.maximum(nrm @ light, 0))                    # per vertex
    v = tris[np.maximum(tid, 0)]                                                  # (H, W, 3) vertex ids
    pix = (inten[v] * bary).sum(-1)                                              # interpolated intensity
    lin = pix[..., None] * np.array(albedo, np.float32)[None, None, :]
    if spec:
        h = light + np.array([0, 0, 1.0]); h /= np.linalg.norm(h)
        sv = SPEC_K * np.maximum(nrm @ h, 0) ** SPEC_P
        lin = lin + (sv[v] * bary).sum(-1)[..., None]
    lin = np.where(tid[..., None] >= 0, lin, BACKGROUND)
    return (L.lin_to_srgb(lin)[..., ::-1] * 255 + 0.5).astype(np.uint8)          # RGB -> BGR


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--faces", type=int, default=3)
    ap.add_argument("--out", type=Path, default=L.HERE / "results/baseline_synth.json")
    ap.add_argument("--page", type=Path, default=L.PAGE)
    ap.add_argument("--spec", action="store_true", help="add white specular spots (see shade())")
    a = ap.parse_args()
    tris = L.triangles()
    faces = pick_faces(a.faces)
    print("faces:", [(c[1], round(c[0], 2)) for c in faces])

    # 1. the page's own vertex normals for each face
    jobs, fdict, frames = [], {}, {}
    for i, (_, name, img, lm) in enumerate(faces):
        h, w = img.shape[:2]
        fdict[f"f{i}"] = lm; frames[f"f{i}.png"] = img
        jobs.append({"name": name, "lm": f"f{i}", "w": w, "h": h, "frame": f"f{i}.png", "calls": 0, "want_mesh": True})
    mesh, _ = L.run_jobs(jobs, fdict, frames, page=a.page, tag="mesh")

    # 2. synthetic images
    jobs, frames, truth = [], {}, []
    for i, ((_, name, img, lm), m) in enumerate(zip(faces, mesh)):
        h, w = img.shape[:2]
        nrm = np.array(m["mesh"]["nrm"], np.float32).reshape(-1, 3)
        tid, bary = raster_maps(np.array(m["mesh"]["x"]), np.array(m["mesh"]["y"]), tris, w, h)
        for (az, el), amb, (alb, rgb) in itertools.product(itertools.product(AZ, EL), AMBIENT, ALBEDO.items()):
            fname = f"s{len(jobs)}.png"
            frames[fname] = shade(tid, bary, tris, nrm, L.light_vec(az, el), amb, rgb, a.spec)
            jobs.append({"name": fname, "lm": f"f{i}", "w": w, "h": h, "frame": fname, "calls": 1})
            truth.append({"face": name, "az": az, "el": el, "ambient": amb, "albedo": alb})
    print(f"{len(jobs)} synthetic images; estimating with the app's sampleScene() ...")
    res, wall = L.run_jobs(jobs, fdict, frames, page=a.page, tag="synth")
    rows = []
    for t, r in zip(truth, res):
        d = r["first"]["dir"]
        rows.append({**t, "err": L.angle_deg(d, L.light_vec(t["az"], t["el"])), "est": d, "conf": r["first"]["conf"],
                     "strength": r["first"]["strength"], "n": r["nSamples"], "r2": r["first"].get("r2"), "rel": r["first"].get("rel")})
    out = {"page": str(a.page), "spec": a.spec, "grid": {"az": AZ, "el": EL, "ambient": AMBIENT, "albedo": ALBEDO, "exposure": EXPOSURE},
           "faces": [c[1] for c in faces], "rows": rows}
    a.out.parent.mkdir(parents=True, exist_ok=True)
    a.out.write_text(json.dumps(out))

    # summary tables
    err = lambda sel: np.array([r["err"] for r in rows if sel(r)])
    med = lambda v: f"{np.median(v):5.1f}" if len(v) else "  -  "
    print("\nangle error of the estimate, degrees (median [p90]); az = left/right angle of the true light")
    print(f"{'':10s}" + "".join(f"{lab:>16s}" for lab in ("front az 0", "az +-15/30", "az +-45", "az +-60")))
    bins = {"front az 0": lambda r: abs(r["az"]) == 0, "az +-15/30": lambda r: abs(r["az"]) in (15, 30), "az +-45": lambda r: abs(r["az"]) == 45, "az +-60": lambda r: abs(r["az"]) == 60}
    for alb in ALBEDO:
        print(f"{alb:10s}" + "".join(f"{med(err(lambda r, b=b: r['albedo'] == alb and bins[b](r))):>9s} [{np.percentile(err(lambda r, b=b: r['albedo'] == alb and bins[b](r)), 90):4.0f}]" for b in bins))
    print(f"{'all':10s}" + "".join(f"{med(err(bins[b])):>9s} [{np.percentile(err(bins[b]), 90):4.0f}]" for b in bins))
    for amb in AMBIENT:
        print(f"ambient {amb}: median " + "  ".join(f"{b} {med(err(lambda r, b=b: r['ambient'] == amb and bins[b](r)))}" for b in bins))
    print(f"overall median {np.median(err(lambda r: True)):.1f} deg, p90 {np.percentile(err(lambda r: True), 90):.1f}, max {err(lambda r: True).max():.1f}")
    print("->", a.out)


if __name__ == "__main__":
    main()

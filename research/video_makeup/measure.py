"""Measure the drawn eyeliner and blush from a before / after frame pair, in the AR's own units.

The after frame is warped onto the before frame's face mesh (piecewise affine over the 468 points), exposure is
matched on the chin, and the change says where makeup went on. Colour is only used to find the area; the numbers
are shape:
- eyeliner (per eye, then averaged): wing length and solid thickness at the outer corner as shares of the eye width,
  wing angle above the eye axis in degrees, whether the lower lid is lined, and the nearest AR chip (lib/linerLooks.ts),
- blush (per cheek): centre offset from the AR apple centre in face widths, nearest placement (apple / under_eye /
  side, same formula as blushShape in faceTrackerHtml.ts), size as a multiple of the AR ellipse, softness 0..1.

Run: research/ar_evaluation/.venv/Scripts/python.exe research/video_makeup/measure.py VIDEO_ID [...]
Needs timeline.py first. Output: research/data/video_makeup/<id>/measure.json and overlay_*.png (git-ignored).
"""

from __future__ import annotations

import argparse
import math
from pathlib import Path

import cv2
import numpy as np

from common import (BLUSH_RADII, CHEEKS, EYES, LINER_CHIPS, LIPS_OUTER, cheek_poly, chin_mask, detect, eye_frame,
                    face_width, lab, landmarker, poly_mask, read_json, to_eye, video_dir, write_json)

# Liner vs shadow (i4SZIHG76RI final pair, median L change by height above the upper lid): the lash line drops
# 22..28, a smoky shadow above it 1..10. So a liner pixel needs a drop past -15; a shadow only past -4.
DARK_DL = -15.0       # L drop that counts as drawn liner
DARK_BELOW_SKIN = 25  # and the after pixel is at least this much darker than the chin
SHADE_DL = -4.0       # median L drop of a height band that counts as shadow
BLUSH_DA = 2.0        # a* rise that starts to count as blush


# ── alignment ──
def triangles(pts: np.ndarray, shape: tuple[int, int]) -> np.ndarray:
    h, w = shape
    sub = cv2.Subdiv2D((0, 0, w, h))
    inside = [i for i, (x, y) in enumerate(pts) if 0 <= x < w and 0 <= y < h]
    for i in inside:
        sub.insert((float(pts[i, 0]), float(pts[i, 1])))
    tris = []
    for t in sub.getTriangleList().reshape(-1, 3, 2):
        idx = []
        for v in t:
            d = np.linalg.norm(pts - v, axis=1)
            j = int(np.argmin(d))
            if d[j] > 1.0:
                break
            idx.append(j)
        if len(idx) == 3:
            tris.append(idx)
    return np.array(tris, dtype=np.int32)


def warp_to(src: np.ndarray, src_pts: np.ndarray, dst_pts: np.ndarray, shape: tuple[int, int]) -> tuple[np.ndarray, np.ndarray]:
    """``src`` resampled so its face mesh lands on ``dst_pts``; also the covered mask."""
    h, w = shape
    out = np.zeros((h, w, 3), np.uint8)
    covered = np.zeros((h, w), bool)
    for tri in triangles(dst_pts, shape):
        s = src_pts[tri].astype(np.float32)
        d = dst_pts[tri].astype(np.float32)
        x, y, bw, bh = cv2.boundingRect(d)
        x0, y0, x1, y1 = max(x, 0), max(y, 0), min(x + bw, w), min(y + bh, h)
        if x1 <= x0 or y1 <= y0:
            continue
        m = cv2.getAffineTransform(s, d - np.array([x0, y0], np.float32))
        patch = cv2.warpAffine(src, m, (x1 - x0, y1 - y0), flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_REFLECT)
        tm = np.zeros((y1 - y0, x1 - x0), np.uint8)
        cv2.fillConvexPoly(tm, np.round(d - [x0, y0]).astype(np.int32), 1)
        tm = tm.astype(bool)
        out[y0:y1, x0:x1][tm] = patch[tm]
        covered[y0:y1, x0:x1] |= tm
    return out, covered


def makeup_free(shape: tuple[int, int], pts: np.ndarray) -> np.ndarray:
    """Face minus the eye areas and the lips, where makeup alone changes a pixel by more than ΔE 30."""
    keep = np.ones(shape, bool)
    box = np.array([[-1.15, -0.45], [0.75, -0.45], [0.75, 0.65], [-1.15, 0.65]])
    for k in (0, 1):
        keep &= ~poly_mask(shape, box * eye_frame(pts, k)[2] @ eye_frame(pts, k)[1] + eye_frame(pts, k)[0])
    lips = poly_mask(shape, pts[LIPS_OUTER]).astype(np.uint8)
    grow = max(int(0.04 * face_width(pts)), 3)
    keep &= ~cv2.dilate(lips, np.ones((grow, grow), np.uint8)).astype(bool)
    return keep


def change(before: np.ndarray, after_w: np.ndarray, covered: np.ndarray, pts: np.ndarray) -> dict:
    lb, la = lab(before), lab(after_w)
    shape = before.shape[:2]
    free = makeup_free(shape, pts) & covered
    # Exposure reference: the face outside the eyes, lips and cheeks, minus pixels a caption, hand or hair changed
    # (raw ΔE > 25). The chin alone broke when a caption sat on it (BD_3e4xCwi8, Mvy0fr98Fds: whole cheeks read as blush).
    ref = free & ~poly_mask(shape, cheek_poly(pts, 0)) & ~poly_mask(shape, cheek_poly(pts, 1))
    ref &= np.linalg.norm(la - lb, axis=2) < 25
    if ref.sum() < 200:
        ref = chin_mask(shape, pts) & covered
    offset = np.median((la - lb)[ref], axis=0) if ref.sum() >= 20 else np.zeros(3, np.float32)
    d = la - lb - offset
    ref_after = float(np.median(la[..., 0][ref])) if ref.sum() >= 20 else float(np.median(la[..., 0][covered]))
    # Outside the eyes and lips, makeup moves a pixel by well under ΔE 30; bangs, captions, a hand or a brush do more.
    big = (np.linalg.norm(d, axis=2) > 30) & free
    return {"dL": d[..., 0], "da": d[..., 1], "L_after": la[..., 0], "ref_after": ref_after, "covered": covered,
            "exposure": [round(float(v), 2) for v in offset],
            "occlusion": round(float(big.sum() / max(free.sum(), 1)), 4)}


# ── eyeliner ──
def lid_curves(pts: np.ndarray, k: int, frame) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    e = EYES[k]
    up = to_eye(pts[[e["inner"], *e["upper"], e["outer"]]], frame)
    low = to_eye(pts[[e["inner"], *e["lower"], e["outer"]]], frame)
    up, low = up[np.argsort(up[:, 0])], low[np.argsort(low[:, 0])]
    return up[:, 0], up[:, 1], low[:, 0], low[:, 1]


def measure_liner_eye(ch: dict, pts: np.ndarray, k: int) -> dict:
    frame = eye_frame(pts, k)
    ew = frame[2]
    h, w = ch["dL"].shape
    corners = np.array([[-1.15, -0.45], [0.75, -0.45], [0.75, 0.65], [-1.15, 0.65]])
    box = corners * ew @ frame[1] + frame[0]
    x0, y0 = np.maximum(np.floor(box.min(0)).astype(int), 0)
    x1, y1 = np.minimum(np.ceil(box.max(0)).astype(int), [w, h])
    if x1 <= x0 or y1 <= y0:
        return {"ok": False, "reason": "eye outside the frame"}
    yy, xx = np.mgrid[y0:y1, x0:x1]
    uv = to_eye(np.stack([xx.ravel(), yy.ravel()], 1), frame)
    u, v = uv[:, 0].reshape(xx.shape), uv[:, 1].reshape(xx.shape)
    uu, uvv, lu, lv = lid_curves(pts, k, frame)
    top = np.interp(u, uu, uvv)
    bot = np.interp(u, lu, lv)
    dL = ch["dL"][y0:y1, x0:x1]
    cov = ch["covered"][y0:y1, x0:x1]
    dark = (dL < DARK_DL) & (ch["L_after"][y0:y1, x0:x1] < ch["ref_after"] - DARK_BELOW_SKIN) & cov
    opening = (u > -1.0) & (u < 0.0) & (v < top - 0.01) & (v > bot + 0.01)
    band = (u >= -1.0) & (u <= 0.0) & (v >= top - 0.03) & (v <= top + 0.3)
    tail = (u > 0.0) & (u <= 0.7) & (v >= -0.15) & (v <= 0.45)
    mask = (dark & (band | tail) & ~opening).astype(np.uint8)
    if ew >= 80:
        mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, np.ones((2, 2), np.uint8))
    n, labels = cv2.connectedComponents(mask, connectivity=8)
    seed = (u >= -0.15) & (u <= 0.05) & (v >= top - 0.03) & (v <= top + 0.12)
    keep_ids = set(np.unique(labels[(labels > 0) & seed]).tolist())
    kept = np.isin(labels, list(keep_ids)) if keep_ids else np.zeros_like(mask, bool)

    min_px = max(8, int((0.02 * ew) ** 2))
    tail_px = kept & (u > 0)
    # A wing tapers to its tip, so a percentile cuts it short: the tip is the farthest kept pixel (the opening and the
    # corner-connected component already dropped specks). Length runs along the wing, like the AR chip.
    reach = float(u[tail_px].max()) if tail_px.sum() >= min_px else 0.0
    angle = 0.0
    length = 0.0
    if reach >= 0.05:
        tip = kept & (u >= 0.8 * reach)
        angle = math.degrees(math.atan2(float(v[tip].mean()), float(u[tip].mean())))
        length = reach / max(math.cos(math.radians(angle)), 0.5)

    near = (u >= -0.15) & (u <= -0.02)
    hgt = v - top
    thickness = 0.0
    for step in np.arange(0.0, 0.3, 0.01):
        strip = near & (hgt >= step) & (hgt < step + 0.01)
        if strip.sum() == 0 or kept[strip].mean() < 0.5:
            break
        thickness = step + 0.01

    shadow = 0.0
    lid_mid = (u >= -0.7) & (u <= -0.2) & cov
    for step in np.arange(0.0, 0.5, 0.02):
        strip = lid_mid & (hgt >= step) & (hgt < step + 0.02)
        if strip.sum() < 10 or float(np.median(dL[strip])) > SHADE_DL:
            break
        shadow = step + 0.02

    lower_band = (u >= -0.8) & (u <= -0.05) & (v >= bot - 0.08) & (v <= bot)
    lower_frac = float((dark & lower_band & ~opening).sum() / max(lower_band.sum(), 1))
    halo = cv2.dilate(kept.astype(np.uint8), np.ones((max(int(0.03 * ew), 3),) * 2, np.uint8)).astype(bool)
    partial = halo & ~kept & (dL < SHADE_DL) & cov
    soft = float(partial.sum() / max(partial.sum() + kept.sum(), 1))
    return {
        "ok": bool(kept.sum() >= min_px),
        "eyeWidthPx": round(ew, 1),
        "length": round(max(length, 0.0), 3),
        "angle": round(angle, 1),
        "thickness": round(thickness, 3),
        "lowerFraction": round(lower_frac, 3),
        "linerLower": lower_frac > 0.25,
        "softness": round(soft, 2),
        "shadowHeight": round(shadow, 2),
        "pixels": int(kept.sum()),
        "_mask": (kept, (x0, y0)),
    }


def nearest_chip(m: dict) -> tuple[str, float]:
    best, best_d = "natural", math.inf
    for name, chip in LINER_CHIPS.items():
        d = ((m["length"] - chip["length"]) / 0.35) ** 2 + ((m["thickness"] - chip["thickness"]) / 0.15) ** 2
        if m["length"] >= 0.05 or chip["length"] >= 0.05:
            d += ((m["angle"] - chip["angle"]) / 25) ** 2
        d = math.sqrt(d) + (0.5 if m["linerLower"] != chip["linerLower"] else 0)
        if d < best_d:
            best, best_d = name, d
    return best, round(best_d, 2)


def measure_liner(eyes: list[dict]) -> dict:
    good = [e for e in eyes if e["ok"]]
    out: dict = {"eyes": [{k: v for k, v in e.items() if not k.startswith("_")} for e in eyes]}
    if good:
        mean = {key: round(float(np.mean([e[key] for e in good])), 3) for key in ("length", "angle", "thickness", "softness")}
        geometry = {"length": mean["length"], "angle": mean["angle"], "thickness": mean["thickness"],
                    "linerSoftness": mean["softness"], "linerLower": sum(e["linerLower"] for e in good) * 2 > len(good)}
        chip, d = nearest_chip(geometry)
        out.update({"geometry": geometry, "nearestChip": chip, "chipDistance": d,
                    "shadowHeight": round(float(np.mean([e["shadowHeight"] for e in good])), 2),
                    "lowConfidence": any(e["eyeWidthPx"] < 60 for e in good)})
        if len(good) == 2:
            out["eyeGap"] = {key: round(abs(good[0][key] - good[1][key]), 3) for key in ("length", "angle", "thickness")}
    return out


# ── blush ──
def blush_templates(pts: np.ndarray, k: int) -> dict:
    c = CHEEKS[k]
    p = pts.astype(np.float64)
    inner, outer, lid, low = p[c["inner"]], p[c["outer"]], p[c["lid"]], p[c["low"]]
    apple = lid + (low - lid) * 0.5 + (outer - inner) * 0.15
    return {"apple": apple, "under_eye": apple + (lid - apple) * 0.5, "side": apple + (outer - apple) * 0.45}


def measure_blush_cheek(ch: dict, pts: np.ndarray, k: int) -> dict:
    shape = ch["da"].shape
    fw = face_width(pts)
    region = poly_mask(shape, cheek_poly(pts, k)) & ch["covered"]
    wmap = np.clip(ch["da"] - BLUSH_DA, 0, None) * region
    sigma = max(0.02 * fw, 1.0)
    wmap = cv2.GaussianBlur(wmap.astype(np.float32), (0, 0), sigma) * region
    peak = float(wmap.max())
    tpl = blush_templates(pts, k)
    if peak < 1.5:
        return {"ok": False, "peak": round(peak, 2), "_map": wmap}
    yy, xx = np.nonzero(wmap > 0)
    wv = wmap[yy, xx]
    ctr = np.array([(xx * wv).sum() / wv.sum(), (yy * wv).sum() / wv.sum()])
    dists = {name: float(np.linalg.norm(ctr - pos) / fw) for name, pos in tpl.items()}
    placement = min(dists, key=dists.get)
    _, axes, _ = eye_frame(pts, CHEEKS[k]["eye"])
    off = (ctr - tpl["apple"]) / fw
    a25, a50, a75 = ((wmap > f * peak).sum() for f in (0.25, 0.5, 0.75))
    r0 = fw * math.sqrt(BLUSH_RADII[0] * BLUSH_RADII[1])
    return {
        "ok": True,
        "peak": round(peak, 2),
        "offsetFromApple": {"outward": round(float(off @ axes[0]), 3), "up": round(float(off @ axes[1]), 3)},
        "distance": {n: round(d, 3) for n, d in dists.items()},
        "blushPlacement": placement,
        "blushSize": round(float(np.clip(math.sqrt(a50 / math.pi) / r0, 0.4, 2.5)), 2),
        "blushSoftness": round(float(np.clip((1 - a75 / max(a25, 1)) / 0.79, 0, 1)), 2),
        "_map": wmap,
        "_ctr": ctr,
    }


def measure_blush(ch: dict, pts: np.ndarray) -> dict:
    cheeks = [measure_blush_cheek(ch, pts, k) for k in (0, 1)]
    good = [c for c in cheeks if c["ok"]]
    out: dict = {"cheeks": [{k: v for k, v in c.items() if not k.startswith("_")} for c in cheeks]}
    if good:
        votes = [c["blushPlacement"] for c in good]
        out["geometry"] = {
            "blushPlacement": max(set(votes), key=votes.count),
            "blushSize": round(float(np.mean([c["blushSize"] for c in good])), 2),
            "blushSoftness": round(float(np.mean([c["blushSoftness"] for c in good])), 2),
        }
    return out, cheeks


# ── pairs ──
def overlay(before: np.ndarray, after_w: np.ndarray, pts: np.ndarray, liner: list[dict], cheeks: list[dict], path: Path) -> None:
    vis = before.copy()
    for e in liner:
        if "_mask" in e:
            kept, (x0, y0) = e["_mask"]
            sub = vis[y0:y0 + kept.shape[0], x0:x0 + kept.shape[1]]
            sub[kept] = (0.35 * sub[kept] + 0.65 * np.array([255, 0, 255])).astype(np.uint8)
    for k, c in enumerate(cheeks):
        wm = c["_map"]
        if wm.max() > 0:
            heat = (wm / max(wm.max(), 1e-6))[..., None]
            vis = (vis * (1 - 0.6 * heat) + np.array([0, 255, 0]) * 0.6 * heat).astype(np.uint8)
        for name, pos in blush_templates(pts, k).items():
            color = {"apple": (255, 255, 0), "under_eye": (0, 255, 255), "side": (255, 128, 0)}[name]
            cv2.circle(vis, (int(pos[0]), int(pos[1])), 5, color, -1)
        if "_ctr" in c:
            cv2.drawMarker(vis, (int(c["_ctr"][0]), int(c["_ctr"][1])), (255, 0, 0), cv2.MARKER_CROSS, 18, 3)
    oval = pts.astype(int)
    x0, y0 = np.maximum(oval.min(0) - 20, 0)
    x1, y1 = np.minimum(oval.max(0) + 20, [before.shape[1], before.shape[0]])
    strip = np.concatenate([before[y0:y1, x0:x1], after_w[y0:y1, x0:x1], vis[y0:y1, x0:x1]], axis=1)
    scale = min(1.0, 1800 / strip.shape[1])
    strip = cv2.resize(strip, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA)
    cv2.imwrite(str(path), cv2.cvtColor(strip, cv2.COLOR_RGB2BGR))


# Pilot (5 videos): clean pairs 0.002..0.012; a brush or tweezers over the face 0.016..0.036; bangs or a caption 0.06..0.47.
OCCLUSION_MAX = 0.015


class Frames:
    """Full-resolution frames and their face points, each detected once."""

    def __init__(self, lm) -> None:
        self._lm = lm
        self._cache: dict[Path, tuple[np.ndarray, np.ndarray | None]] = {}

    def get(self, path: Path) -> tuple[np.ndarray, np.ndarray | None]:
        if path not in self._cache:
            rgb = cv2.cvtColor(cv2.imread(str(path)), cv2.COLOR_BGR2RGB)
            self._cache[path] = (rgb, detect(self._lm, rgb))
        return self._cache[path]


def measure_pair(frames: Frames, before_path: Path, after_path: Path) -> tuple[dict, tuple | None]:
    before, pb = frames.get(before_path)
    after, pa = frames.get(after_path)
    if pb is None or pa is None:
        return {"ok": False, "reason": "no face on full-resolution frame"}, None
    after_w, covered = warp_to(after, pa, pb, before.shape[:2])
    ch = change(before, after_w, covered, pb)
    eyes = [measure_liner_eye(ch, pb, k) for k in (0, 1)]
    liner = measure_liner(eyes)
    blush, cheeks = measure_blush(ch, pb)
    # A lowered or turned gaze moves the lid and lashes, which reads as a drawn line (HPMfv3YbqWU 635→636 s).
    ob, oa = eye_openness(pb), eye_openness(pa)
    # Makeup only adds: cheeks clearly less red after means the pair runs backwards (a finished-look intro first).
    cheek_area = (poly_mask(before.shape[:2], cheek_poly(pb, 0)) | poly_mask(before.shape[:2], cheek_poly(pb, 1))) & covered
    cheek_da = float(np.median(ch["da"][cheek_area])) if cheek_area.any() else 0.0
    result = {"ok": True, "exposure": ch["exposure"], "occlusion": ch["occlusion"],
              "eyesDiffer": bool(abs(ob - oa) / max(ob, oa, 1e-6) > 0.3), "eyeOpen": [round(ob, 3), round(oa, 3)],
              "reversed": cheek_da < -2.0, "cheekDa": round(cheek_da, 2),
              "faceWidthPx": round(face_width(pb), 1), "eyeliner": liner, "blush": blush}
    return result, (before, after_w, pb, eyes, cheeks)


def eye_openness(pts: np.ndarray) -> float:
    return float(np.mean([np.linalg.norm(pts[e["lid_top"]] - pts[e["lid_low"]]) / np.linalg.norm(pts[e["outer"]] - pts[e["inner"]])
                          for e in EYES]))


def clean(result: dict) -> bool:
    return result["occlusion"] <= OCCLUSION_MAX and not result["eyesDiffer"] and not result["reversed"]


def measure_candidates(frames: Frames, befores: list[tuple[float, Path]], afters: list[tuple[float, Path]],
                       overlay_path: Path) -> dict:
    """Best-scored pairs first; the first clean one wins (see ``clean``), else the least bad one, flagged."""
    order = sorted(((i, j) for i in range(len(befores)) for j in range(len(afters))), key=lambda p: (sum(p), p[0]))
    tried, chosen = [], None

    def badness(r: dict) -> tuple:
        return (r["reversed"], r["eyesDiffer"], r["occlusion"])

    for i, j in order:
        result, vis = measure_pair(frames, befores[i][1], afters[j][1])
        if not result["ok"]:
            continue
        tried.append({"before": befores[i][0], "after": afters[j][0], "occlusion": result["occlusion"],
                      "eyesDiffer": result["eyesDiffer"], "reversed": result["reversed"]})
        if chosen is None or badness(result) < badness(chosen[0]):
            chosen = (result, vis, befores[i][0], afters[j][0])
        if clean(result):
            break
    if chosen is None:
        return {"ok": False, "reason": "no face on any candidate frame"}
    result, vis, tb, ta = chosen
    overlay(*vis, overlay_path)
    return {"before": tb, "after": ta, "rejected": not clean(result), "tried": tried, **result}


def run(video_id: str) -> dict:
    folder = video_dir(video_id)
    tl = read_json(folder / "timeline.json")
    frames_dir = folder / "frames"
    frames = Frames(landmarker())
    for old in folder.glob("overlay_*.png"):
        old.unlink()

    def candidates(zone: str, side: str) -> list[tuple[float, Path]]:
        times = tl["frames"].get(f"{zone}_{side}", [])
        return [(t, frames_dir / f"{zone}_{side}_{i}.png") for i, t in enumerate(times)]

    out: dict = {"videoId": video_id, "pairs": {}}
    for zone in ("eyeliner", "blush"):
        b, a = candidates(zone, "before"), candidates(zone, "after")
        if b and a:
            out["pairs"][zone] = {"window": tl["windows"].get(zone),
                                  **measure_candidates(frames, b, a, folder / f"overlay_{zone}.png")}
    final = candidates("final", "after")
    bare = candidates("final", "before")
    if bare and final:
        out["pairs"]["final"] = measure_candidates(frames, bare, final, folder / "overlay_final.png")
    write_json(folder / "measure.json", out)
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("video_ids", nargs="+")
    args = ap.parse_args()
    for video_id in args.video_ids:
        out = run(video_id)
        for name, pair in out["pairs"].items():
            liner = pair.get("eyeliner", {})
            blush = pair.get("blush", {})
            print(f"{video_id} {name} ({pair.get('before')}→{pair.get('after')}s, occlusion {pair.get('occlusion')}"
                  f"{' REJECTED' if pair.get('rejected') else ''}): liner {liner.get('geometry')} → "
                  f"{liner.get('nearestChip')}; blush {blush.get('geometry')}")


if __name__ == "__main__":
    main()

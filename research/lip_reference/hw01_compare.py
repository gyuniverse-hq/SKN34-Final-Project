"""How close is each AR method to the real applied lip? (숙제 01, AR_SPEC 8-B, track A/B split)

For every real applied photo `{p}_{light}_{angle}_{product}_{n}.jpg` (n = 1 or 3), candidates
made from the same person's bare photo `..._0.jpg` are compared with it inside the lip:

  bare      - no makeup (sanity floor: every method must beat it)
  ar        - the app's shader, from render_ar_offline.py (research/data/hw01_ar/)
  transfer  - plan B "color statistics transfer": the bare→applied change in Lab mean/spread
              measured on ANOTHER person with the same product, light and swipes, applied here
              (leave-one-person-out, so it never sees the answer photo)

Metrics (lip pixels; head moves between swipes, so color/brightness use region statistics):
  dE        - CIEDE2000 between mean lip Lab of candidate and real (track B, 1-12)
  dL_spread - |(p90-p10) of L| difference: shading/volume kept (low = same contrast as real)
  dL_hi     - |p98 of L| difference: highlight strength (gloss)
  ssim      - SSIM of L after aligning the candidate to the real photo with face landmarks (track A)

    python research/lip_reference/hw01_compare.py [--raw DIR] [--ar DIR]
Writes research/data/hw01_compare.csv and prints a per-method summary. Nothing leaves the PC.
"""
import argparse
import csv
import re
from collections import defaultdict
from pathlib import Path

import cv2
import mediapipe as mp
import numpy as np

from eval_lapa import LIPS_INNER, LIPS_OUTER, ROOT, make_landmarker
from render_ar_offline import MAX_SIDE, fit

NAME = re.compile(r"^(p\d+)_(day|warm)_(00|30|45)_([a-z0-9-]+)_(1|3)\.jpe?g$")
ALIGN = LIPS_OUTER + LIPS_INNER + [1, 33, 263, 61, 291, 152, 10]


def ciede2000(lab1, lab2):
    """CIEDE2000 for Lab arrays (..., 3), CIE L* 0-100 scale."""
    L1, a1, b1 = np.moveaxis(np.asarray(lab1, np.float64), -1, 0)
    L2, a2, b2 = np.moveaxis(np.asarray(lab2, np.float64), -1, 0)
    C1, C2 = np.hypot(a1, b1), np.hypot(a2, b2)
    Cm = (C1 + C2) / 2
    G = 0.5 * (1 - np.sqrt(Cm ** 7 / (Cm ** 7 + 25 ** 7)))
    a1p, a2p = (1 + G) * a1, (1 + G) * a2
    C1p, C2p = np.hypot(a1p, b1), np.hypot(a2p, b2)
    h1p = np.degrees(np.arctan2(b1, a1p)) % 360
    h2p = np.degrees(np.arctan2(b2, a2p)) % 360
    dLp, dCp = L2 - L1, C2p - C1p
    dh = h2p - h1p
    dh = np.where(C1p * C2p == 0, 0, np.where(dh > 180, dh - 360, np.where(dh < -180, dh + 360, dh)))
    dHp = 2 * np.sqrt(C1p * C2p) * np.sin(np.radians(dh / 2))
    Lpm, Cpm = (L1 + L2) / 2, (C1p + C2p) / 2
    hs = h1p + h2p
    hpm = np.where(C1p * C2p == 0, hs, np.where(np.abs(h1p - h2p) <= 180, hs / 2, np.where(hs < 360, (hs + 360) / 2, (hs - 360) / 2)))
    T = (1 - 0.17 * np.cos(np.radians(hpm - 30)) + 0.24 * np.cos(np.radians(2 * hpm))
         + 0.32 * np.cos(np.radians(3 * hpm + 6)) - 0.20 * np.cos(np.radians(4 * hpm - 63)))
    dth = 30 * np.exp(-(((hpm - 275) / 25) ** 2))
    Rc = 2 * np.sqrt(Cpm ** 7 / (Cpm ** 7 + 25 ** 7))
    Sl = 1 + 0.015 * (Lpm - 50) ** 2 / np.sqrt(20 + (Lpm - 50) ** 2)
    Sc, Sh = 1 + 0.045 * Cpm, 1 + 0.015 * Cpm * T
    Rt = -np.sin(np.radians(2 * dth)) * Rc
    return np.sqrt((dLp / Sl) ** 2 + (dCp / Sc) ** 2 + (dHp / Sh) ** 2 + Rt * (dCp / Sc) * (dHp / Sh))


def to_lab(img_bgr):
    """8-bit BGR → CIE Lab with L in 0-100 (OpenCV float path)."""
    return cv2.cvtColor(img_bgr.astype(np.float32) / 255.0, cv2.COLOR_BGR2LAB)


def ssim(x, y, mask):
    """Mean SSIM of two L images (0-100) over mask, 11px Gaussian window."""
    x, y = x.astype(np.float64), y.astype(np.float64)
    c1, c2 = (0.01 * 100) ** 2, (0.03 * 100) ** 2
    blur = lambda im: cv2.GaussianBlur(im, (11, 11), 1.5)
    mx, my = blur(x), blur(y)
    sxx, syy, sxy = blur(x * x) - mx * mx, blur(y * y) - my * my, blur(x * y) - mx * my
    s = ((2 * mx * my + c1) * (2 * sxy + c2)) / ((mx * mx + my * my + c1) * (sxx + syy + c2))
    return float(s[mask].mean())


class Faces:
    def __init__(self):
        self.lm = make_landmarker()

    def points(self, img):
        res = self.lm.detect(mp.Image(image_format=mp.ImageFormat.SRGB, data=cv2.cvtColor(img, cv2.COLOR_BGR2RGB)))
        if not res.face_landmarks:
            return None
        h, w = img.shape[:2]
        return np.array([[l.x * w, l.y * h] for l in res.face_landmarks[0]])


def lip_mask(pts, shape, inset):
    """Outer minus inner lip polygon, eroded so landmark error at the edge is not compared."""
    m = np.zeros(shape, np.uint8)
    cv2.fillPoly(m, [np.round(pts[LIPS_OUTER]).astype(np.int32)], 1)
    cv2.fillPoly(m, [np.round(pts[LIPS_INNER]).astype(np.int32)], 0)
    if inset > 0:
        m = cv2.erode(m, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2 * inset + 1, 2 * inset + 1)))
    return m.astype(bool)


def stats(lab, mask):
    v = lab[mask]
    L = v[:, 0]
    return {"mean": v.mean(0), "std": v.std(0) + 1e-6, "p10": np.percentile(L, 10), "p90": np.percentile(L, 90),
            "p98": np.percentile(L, 98)}


def transfer(bare_bgr, mask, ref_bare, ref_applied, feather):
    """Apply another person's bare→applied Lab change (mean shift, spread scale) inside the lip."""
    lab = to_lab(bare_bgr)
    own = stats(lab, mask)
    out = lab.copy()
    scale = ref_applied["std"] / ref_bare["std"]
    # a, b: move to the product's color on that reference lip, keep this lip's relative variation.
    for c in (1, 2):
        out[..., c] = ref_applied["mean"][c] + (lab[..., c] - own["mean"][c]) * scale[c]
    # L: shift by the reference's change, keep this lip's own shading.
    out[..., 0] = own["mean"][0] + (ref_applied["mean"][0] - ref_bare["mean"][0]) + (lab[..., 0] - own["mean"][0]) * scale[0]
    out[..., 0] = np.clip(out[..., 0], 0, 100)
    rgb = cv2.cvtColor(out.astype(np.float32), cv2.COLOR_LAB2BGR)
    soft = cv2.GaussianBlur(mask.astype(np.float32), (0, 0), feather)[..., None]
    return np.clip((bare_bgr.astype(np.float32) / 255.0) * (1 - soft) + np.clip(rgb, 0, 1) * soft, 0, 1) * 255


def skin_ring(pts, shape, mouth_w):
    """Skin around the mouth (no lipstick there): fine alignment target that every candidate shares."""
    outer = np.zeros(shape, np.uint8)
    cv2.fillPoly(outer, [np.round(pts[LIPS_OUTER]).astype(np.int32)], 255)
    k = lambda r: cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2 * r + 1, 2 * r + 1))
    return cv2.dilate(outer, k(max(3, round(0.3 * mouth_w)))) & ~cv2.dilate(outer, k(max(2, round(0.04 * mouth_w))))


def align(src_L, src_pts, dst_pts, dst_L, ring):
    """Warp src onto dst by ECC on the skin ring, started from no motion (tripod) and from the
    landmark transform; keep the start that matches the skin best. Landmarks alone are not enough:
    lipstick shifts them (seen: 2.5% scale, 12 px on the same unmoved face), which breaks SSIM."""
    h, w = dst_L.shape
    lm, _ = cv2.estimateAffinePartial2D(src_pts[ALIGN], dst_pts[ALIGN])
    # Inverse of the landmark transform: ECC maps template (dst) coords into input (src) coords.
    starts = [np.eye(2, 3, dtype=np.float32), cv2.invertAffineTransform(lm).astype(np.float32)]
    src32, dst32 = src_L.astype(np.float32), dst_L.astype(np.float32)
    best, best_cc = starts[1], -1.0
    for start in starts:
        try:
            cc, E = cv2.findTransformECC(dst32, src32, start.copy(), cv2.MOTION_AFFINE,
                                         (cv2.TERM_CRITERIA_EPS | cv2.TERM_CRITERIA_COUNT, 200, 1e-6), ring, 5)
        except cv2.error:
            continue
        if cc > best_cc:
            best, best_cc = E, cc
    return cv2.warpAffine(src_L, best, (w, h), flags=cv2.INTER_LINEAR | cv2.WARP_INVERSE_MAP,
                          borderMode=cv2.BORDER_REPLICATE)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--raw", type=Path, default=ROOT / "research/data/hw01_raw")
    ap.add_argument("--ar", type=Path, default=ROOT / "research/data/hw01_ar")
    ap.add_argument("--masks", type=Path, default=ROOT / "research/data/hw01_masks")
    ap.add_argument("--out", type=Path, default=ROOT / "research/data/hw01_compare.csv")
    args = ap.parse_args()
    faces = Faces()

    # Pass 1: load every applied/bare pair, its lip mask and lip statistics.
    sets = []
    for p in sorted(args.raw.glob("*.jp*g")):
        m = NAME.match(p.name)
        if not m:
            continue
        person, light, angle, product, n = m.groups()
        bare_p = p.with_name(f"{person}_{light}_{angle}_{product}_0{p.suffix}")
        if not bare_p.exists():
            continue
        real, bare = fit(cv2.imread(str(p))), fit(cv2.imread(str(bare_p)))
        rp, bp = faces.points(real), faces.points(bare)
        if rp is None or bp is None:
            print(f"skip {p.name}: face not found")
            continue
        mouth_w = np.linalg.norm(rp[61] - rp[291])
        inset = max(1, round(0.03 * mouth_w))
        hand = args.masks / f"{p.stem}.png"
        if hand.exists():
            hm = cv2.imread(str(hand), cv2.IMREAD_GRAYSCALE)
            real_mask = fit(hm) > 127 if hm.shape[:2] != real.shape[:2] else hm > 127
        else:
            real_mask = lip_mask(rp, real.shape[:2], inset)
        bare_mask = lip_mask(bp, bare.shape[:2], inset)
        sets.append({"name": p.stem, "person": person, "key": (light, angle, product, n), "real": real, "bare": bare,
                     "rp": rp, "bp": bp, "real_mask": real_mask, "bare_mask": bare_mask, "feather": max(1.0, 0.02 * mouth_w),
                     "ring": skin_ring(rp, real.shape[:2], mouth_w),
                     "real_stats": stats(to_lab(real), real_mask), "bare_stats": stats(to_lab(bare), bare_mask),
                     "hand_mask": hand.exists()})
    by_key = defaultdict(list)
    for s in sets:
        by_key[s["key"]].append(s)

    # Pass 2: score candidates against the real applied lip.
    rows = []
    for s in sets:
        real_lab = to_lab(s["real"])
        cands = {"bare": s["bare"]}
        ar_p = args.ar / f"{s['name']}.png"
        if ar_p.exists():
            ar = cv2.imread(str(ar_p))
            cands["ar"] = ar if ar.shape[:2] == s["bare"].shape[:2] else cv2.resize(ar, s["bare"].shape[1::-1])
        refs = [r for r in by_key[s["key"]] if r["person"] != s["person"]]
        if refs:
            ref_app = {k: np.mean([r["real_stats"][k] for r in refs], 0) for k in ("mean", "std")}
            ref_bare = {k: np.mean([r["bare_stats"][k] for r in refs], 0) for k in ("mean", "std")}
            cands["transfer"] = transfer(s["bare"], s["bare_mask"], ref_bare, ref_app, s["feather"]).astype(np.uint8)
        rs = s["real_stats"]
        for method, img in cands.items():
            cs = stats(to_lab(img), s["bare_mask"])
            warped = align(to_lab(img)[..., 0], s["bp"], s["rp"], real_lab[..., 0], s["ring"])
            rows.append({
                "name": s["name"], "method": method, "hand_mask": int(s["hand_mask"]),
                "dE": float(ciede2000(cs["mean"], rs["mean"])),
                "dL_spread": float(abs((cs["p90"] - cs["p10"]) - (rs["p90"] - rs["p10"]))),
                "dL_hi": float(abs(cs["p98"] - rs["p98"])),
                "ssim": ssim(warped, real_lab[..., 0], s["real_mask"]),
            })
    if not rows:
        raise SystemExit(f"no applied/bare pairs in {args.raw}")
    with open(args.out, "w", newline="") as f:
        wr = csv.DictWriter(f, fieldnames=list(rows[0]))
        wr.writeheader()
        wr.writerows(rows)
    print(f"{len(sets)} applied photos, max side {MAX_SIDE}px → {args.out}")
    print(f"{'method':9s} {'n':>4s} {'dE↓':>7s} {'dL_spread↓':>11s} {'dL_hi↓':>8s} {'ssim↑':>7s}")
    for method in ("bare", "ar", "transfer"):
        r = [x for x in rows if x["method"] == method]
        if r:
            med = lambda k: np.median([x[k] for x in r])
            print(f"{method:9s} {len(r):4d} {med('dE'):7.2f} {med('dL_spread'):11.2f} {med('dL_hi'):8.2f} {med('ssim'):7.3f}")
    print("(median per method; dE = CIEDE2000 of mean lip color, the rest on L*)")


if __name__ == "__main__":
    main()

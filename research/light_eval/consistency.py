"""consistency.py: does the light estimate behave when the picture is changed in ways that should (or should not) move it?

For each of the 20 hw01 people (same person, same session: the bare photo `_0` and the lip-makeup photo `_3`):
  * same session   : angle between the direction from `_0` and from `_3`  (small if the estimate is stable; the lips differ)
  * darker         : `_0` with linear intensity x0.4          -> direction should not move
  * colour shifted : `_0` with linear R x0.7 and B x1.2       -> direction should not move
                     (the multipliers are the ones the spec gives; R down and B up is really a bluer cast)
  * rotated 15 deg : `_0` rotated in the image plane, landmarks re-detected -> the azimuth (angle of the xy part of the direction)
                     should turn by about 15 degrees (sign depends on the mirrored screen frame, so |delta| is judged)
Azimuth is only judged where the xy part of the direction is at least 0.15 long in both pictures: for a near frontal light it is noise.

    python research/light_eval/consistency.py [--out research/light_eval/results/baseline_consistency.json]
"""
import argparse
import json
import sys
from pathlib import Path

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
import lighteval as L  # noqa: E402
from est_light import estimate  # noqa: E402

XY_MIN = 0.15


def variant(img, kind):
    if kind == "dark" or kind == "warm":
        lin = L.srgb_to_lin(img[..., ::-1] / 255.0)
        lin = lin * 0.4 if kind == "dark" else lin * np.array([0.7, 1.0, 1.2], np.float32)
        return (L.lin_to_srgb(lin)[..., ::-1] * 255 + 0.5).astype(np.uint8)
    h, w = img.shape[:2]
    M = cv2.getRotationMatrix2D((w / 2, h / 2), 15, 1.0)
    return cv2.warpAffine(img, M, (w, h), flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_REPLICATE)


def azimuth(d):
    return float(np.degrees(np.arctan2(d[1], d[0])))


def wrap(a):
    return (a + 180) % 360 - 180


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", type=Path, default=L.HERE / "results/baseline_consistency.json")
    ap.add_argument("--page", type=Path, default=L.PAGE)
    a = ap.parse_args()
    tmp = L.HERE / "_tmp/consistency"
    tmp.mkdir(parents=True, exist_ok=True)
    paths, who = [], []
    for bare in sorted(L.HW01.glob("p*_0.jpg")):
        real = bare.with_name(bare.name.replace("_0.jpg", "_3.jpg"))
        img = L.fit(cv2.imread(str(bare)))
        person = bare.name[:3]
        items = {"base": bare, "real": real}
        for kind in ("dark", "warm", "rot"):
            p = tmp / f"{person}_{kind}.png"
            cv2.imwrite(str(p), variant(img, "rot" if kind == "rot" else kind))
            items[kind] = p
        for kind, p in items.items():
            paths.append(p); who.append((person, kind))
    res = estimate(paths, a.page, tag="cons")
    est = {}
    names = {Path(p).stem: w for p, w in zip(paths, who)}
    for r in res:
        person, kind = names[r["name"]]
        est.setdefault(person, {})[kind] = r["first"]
    rows = []
    for person, e in sorted(est.items()):
        if "base" not in e:
            continue
        row = {"person": person, "base": e["base"]["dir"], "conf": e["base"]["conf"]}
        for kind in ("real", "dark", "warm", "rot"):
            if kind in e:
                row[f"angle_{kind}"] = L.angle_deg(e["base"]["dir"], e[kind]["dir"])
        if "rot" in e:
            b, r_ = e["base"]["dir"], e["rot"]["dir"]
            if np.hypot(b[0], b[1]) >= XY_MIN and np.hypot(r_[0], r_[1]) >= XY_MIN:
                row["d_azimuth"] = wrap(azimuth(r_) - azimuth(b))
        rows.append(row)
    a.out.parent.mkdir(parents=True, exist_ok=True)
    a.out.write_text(json.dumps({"page": str(a.page), "rows": rows}, indent=1))

    med = lambda k: np.median([r[k] for r in rows if k in r])
    p90 = lambda k: np.percentile([r[k] for r in rows if k in r], 90)
    print(f"{len(rows)} people. angle between directions, degrees (median [p90]):")
    print(f"  bare vs lip-makeup photo (same session) : {med('angle_real'):5.1f} [{p90('angle_real'):4.1f}]")
    print(f"  bare vs the same photo x0.4 darker      : {med('angle_dark'):5.1f} [{p90('angle_dark'):4.1f}]   (should be ~0)")
    print(f"  bare vs the same photo, colour shifted  : {med('angle_warm'):5.1f} [{p90('angle_warm'):4.1f}]   (should be ~0)")
    print(f"  bare vs the same photo rotated 15 deg   : {med('angle_rot'):5.1f} [{p90('angle_rot'):4.1f}]")
    da = [r["d_azimuth"] for r in rows if "d_azimuth" in r]
    if da:
        print(f"  azimuth change on rotation ({len(da)} people with a lateral light): median |delta| {np.median(np.abs(da)):.1f} deg, "
              f"signed median {np.median(da):+.1f}; within 15 +-7.5 deg: {sum(abs(abs(x) - 15) <= 7.5 for x in da)}/{len(da)}")
    print(f"  directions with a lateral part (xy >= {XY_MIN}) in the bare photos: {sum(np.hypot(r['base'][0], r['base'][1]) >= XY_MIN for r in rows)}/{len(rows)}; "
          f"z at the 0.15 floor: {sum(r['base'][2] < 0.16 for r in rows)}/{len(rows)}")
    print("->", a.out)


if __name__ == "__main__":
    main()

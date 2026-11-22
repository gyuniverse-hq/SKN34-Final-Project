"""Score a phone AR screenshot (or still) with the frozen DINOv2 + Ridge absolute head.

Pipeline (no Playwright): MediaPipe face align → 720×960 → lip crop → compare_score.

  research/ar_evaluation/.venv/Scripts/python.exe research/lip_rubric/score_capture.py path/to/shot.png
  research/ar_evaluation/.venv/Scripts/python.exe research/lip_rubric/score_capture.py shots/*.png --pass-line 4.5

Scoring step uses ml/.venv via subprocess when this process lacks torch.
Scores are isotonic-calibrated onto the R5 human scale when
research/data/lip_rubric/learn_astra/calibration_<encoder>.json exists
(see calibrate_score.py). Pass/fail uses that calibrated score vs pass_line.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(ROOT / "research" / "lip_texture"))

from build_pack import crop_lips  # noqa: E402
from common import write_csv  # noqa: E402
from learn_astra import OUT  # noqa: E402
from prep import FACE_OVAL, LIPS_OUTER, W, H, detect, landmarker  # noqa: E402

ML_PY = ROOT / "ml" / ".venv" / "Scripts" / "python.exe"
MODEL = ROOT / "research" / "data" / "models" / "face_landmarker.task"


def align_frame(bgr: np.ndarray, lm, face_width: float = 0.55) -> tuple[np.ndarray, dict]:
    rgb = cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)
    pts = detect(lm, rgb)
    if pts is None:
        raise ValueError("얼굴을 찾지 못했습니다")
    oval = pts[FACE_OVAL]
    fw = float(oval[:, 0].max() - oval[:, 0].min())
    if fw < 2:
        raise ValueError("얼굴이 너무 작습니다")
    scale = (face_width * W) / fw
    cx, cy = float(oval[:, 0].mean()), float(oval[:, 1].mean())
    m = np.array([[scale, 0, W / 2 - scale * cx], [0, scale, 0.47 * H - scale * cy]], dtype=np.float32)
    crop = cv2.warpAffine(
        rgb, m, (W, H),
        flags=cv2.INTER_AREA if scale < 1 else cv2.INTER_CUBIC,
        borderMode=cv2.BORDER_REPLICATE,
    )
    pts2 = detect(lm, crop)
    if pts2 is None:
        raise ValueError("정렬 후 얼굴을 찾지 못했습니다")
    # Screenshot/display coords: lips already as seen. Store mirrored so crop_lips' mirror lands correct.
    page = {
        "x": (W - 1 - pts2[:, 0]).astype(float).tolist(),
        "y": pts2[:, 1].astype(float).tolist(),
    }
    return cv2.cvtColor(crop, cv2.COLOR_RGB2BGR), page


def prepare_one(path: Path, work: Path, lm) -> dict:
    bgr = cv2.imread(str(path))
    if bgr is None:
        raise FileNotFoundError(path)
    frame, page = align_frame(bgr, lm)
    stem = path.stem
    face_path = work / "faces" / f"{stem}.png"
    crop_path = work / "crops" / f"{stem}_crop.png"
    face_path.parent.mkdir(parents=True, exist_ok=True)
    crop_path.parent.mkdir(parents=True, exist_ok=True)
    cv2.imwrite(str(face_path), frame)
    (work / "faces" / f"{stem}.page.json").write_text(json.dumps(page), encoding="utf8")
    lip = crop_lips(frame, page)
    # Sanity: lip ring should cover meaningful area
    ring = np.array([[float(page["x"][i]), float(page["y"][i])] for i in LIPS_OUTER], np.float32)
    # page was pre-mirrored; crop_lips mirrors again → display space. Check crop variance.
    if float(lip.std()) < 1.0:
        raise ValueError(f"{stem}: 크롭이 비어 있습니다")
    cv2.imwrite(str(crop_path), lip)
    return {
        "image_id": stem,
        "source": str(path.resolve()),
        "face_path": str(face_path),
        "crop_path": str(crop_path),
        "lip_bbox_w": round(float(np.ptp(ring[:, 0])), 1),
    }


def run_score(crops_csv: Path, encoder: str, out_csv: Path) -> list[dict]:
    from common import read_csv

    if ML_PY.is_file():
        cmd = [
            str(ML_PY), str(ROOT / "research" / "lip_rubric" / "compare_score.py"),
            "score", str(crops_csv), "--encoder", encoder, "--out", str(out_csv),
        ]
        subprocess.check_call(cmd, cwd=str(ROOT))
        return read_csv(out_csv)
    # Same process if torch available
    from compare_score import score_paths

    rows = read_csv(crops_csv)
    scores, meta = score_paths([r["crop_path"] for r in rows], encoder)
    out = [{**r, "score": round(float(scores[i]), 4), **meta} for i, r in enumerate(rows)]
    write_csv(out_csv, out)
    return out


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("images", nargs="+", type=Path, help="screenshot PNG/JPG paths")
    p.add_argument("--encoder", default="dinov2_vits14")
    p.add_argument(
        "--pass-line",
        type=float,
        default=None,
        help="human-scale pass line (default: pass_anchors.json pass_line_active or 4.68)",
    )
    p.add_argument("--out", type=Path, default=None)
    args = p.parse_args(argv)

    if not MODEL.is_file():
        raise SystemExit(f"MediaPipe model missing: {MODEL}")

    pass_line = args.pass_line
    if pass_line is None:
        anchors = OUT / "pass_gallery" / "pass_anchors.json"
        if anchors.is_file():
            pass_line = float(json.loads(anchors.read_text(encoding="utf8"))["pass_line_active"])
        else:
            pass_line = 4.68
    args.pass_line = pass_line

    work = args.out or (OUT / "score_capture")
    work.mkdir(parents=True, exist_ok=True)
    lm = landmarker()
    prepared = []
    for path in args.images:
        if not path.is_file():
            raise FileNotFoundError(path)
        prepared.append(prepare_one(path, work, lm))

    crops_csv = work / "crops.csv"
    write_csv(crops_csv, [{"image_id": r["image_id"], "crop_path": r["crop_path"]} for r in prepared])
    scored = run_score(crops_csv, args.encoder, work / "scores_raw.csv")
    by_id = {r["image_id"]: r for r in scored}

    rows = []
    for r in prepared:
        s = by_id[r["image_id"]]
        # compare_score score column is calibrated when calibration_*.json exists.
        cal = float(s["score"])
        passed = cal >= args.pass_line
        rows.append({
            **r,
            "calibrated_score": round(cal, 4),
            "human_pass_line": args.pass_line,
            "pass": passed,
            "note": (
                "calibrated_score is DINOv2+Ridge mapped onto R5 human totals "
                "(isotonic; see calibrate_score.py). Compare to human_pass_line."
            ),
        })

    write_csv(work / "results.csv", rows)
    summary = {
        "n": len(rows),
        "encoder": args.encoder,
        "human_pass_line": args.pass_line,
        "mean_calibrated_score": round(float(np.mean([r["calibrated_score"] for r in rows])), 4),
        "n_pass": int(sum(1 for r in rows if r["pass"])),
        "out": str(work),
        "pass_gallery": str(OUT / "pass_gallery" / "index.html"),
    }
    (work / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf8")
    print(json.dumps({"summary": summary, "results": rows}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

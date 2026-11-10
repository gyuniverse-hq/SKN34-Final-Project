"""LaPa test 후보를 산출한다. 화장 여부와 인물 일치는 사람이 확인해야 한다."""
import argparse
import csv
import hashlib
import json
import math
import re
import sys
from pathlib import Path

import cv2
import mediapipe as mp
import numpy as np
from mediapipe.tasks.python import BaseOptions, vision
from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "research/data/lip_rubric"
sys.path.insert(0, str(ROOT / "research/lip_texture"))
from metrics import de2000  # noqa: E402

OPEN_THRESHOLD = 0.1  # AR_SPEC 6-5-3 innerInset transition begins at 0.1; heuristic, not truth.
MODEL = ROOT / "research/data/models/face_landmarker.task"


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def image_pairs(root):
    images = {p.stem: p for p in (root / "images").glob("*.jpg")}
    masks = {p.stem: p for p in (root / "labels").glob("*.png")}
    if not images or images.keys() != masks.keys():
        raise ValueError("LaPa test의 images/*.jpg와 labels/*.png 짝이 맞지 않습니다")
    return [(images[k], masks[k]) for k in sorted(images)]


def provisional_face_id(stem):
    # A shared image prefix groups face crops of the same source image, not verified identities.
    match = re.fullmatch(r"(.+)_\d+", stem)
    return "source_" + (match.group(1) if match else stem)


def median_lab(bgr, selection):
    if int(selection.sum()) < 10:
        return None
    lab = cv2.cvtColor(bgr.astype(np.float32) / 255.0, cv2.COLOR_BGR2LAB)
    return np.median(lab[selection], axis=0)


def bins(values, n=4):
    usable = [float(v) for v in values if v not in (None, "") and np.isfinite(float(v))]
    if not usable:
        return [], ["unknown"] * len(values)
    thresholds = np.quantile(usable, np.arange(1, n) / n).tolist()
    return thresholds, ["unknown" if v in (None, "") else f"q{1 + int(np.searchsorted(thresholds, float(v), side='right'))}" for v in values]


def make_sheets(rows, size=40):
    target = DATA / "candidate_sheets"
    target.mkdir(parents=True, exist_ok=True)
    for start in range(0, len(rows), size):
        group = rows[start:start + size]
        sheet = Image.new("RGB", (5 * 180, 8 * 190), "white")
        draw = ImageDraw.Draw(sheet)
        for i, row in enumerate(group):
            path = Path(row["image_path"])
            with Image.open(path) as image:
                image = image.convert("RGB")
                image.thumbnail((170, 160))
                x, y = (i % 5) * 180, (i // 5) * 190
                sheet.paste(image, (x + (170-image.width)//2, y))
                draw.text((x+3, y+161), f"{row['candidate_index']:04} {row['lapa_stem'][:19]}", fill="black")
                draw.text((x+3, y+175), f"{row['mouth']} {row['detected']}", fill="black")
        sheet.save(target / f"candidates_{start+1:04d}_{start+len(group):04d}.png")


def main():
    p = argparse.ArgumentParser(description="LaPa test 경로를 받아 맨입술 후보를 사람이 확인하도록 정리합니다.")
    p.add_argument("dataset", type=Path, help="images/와 labels/가 있는 LaPa test 폴더")
    p.add_argument("--limit", type=int, default=0, help="스모크 테스트용 상한. 0이면 전체")
    p.add_argument("--overwrite", action="store_true", help="기존 후보 목록과 사람 라벨을 덮어씀")
    args = p.parse_args()
    if (DATA / 'candidates.csv').exists() and not args.overwrite:
        raise FileExistsError('기존 candidates.csv를 보존합니다. 백업한 뒤 --overwrite를 사용하세요.')
    dataset = args.dataset.resolve()
    if dataset != (ROOT / 'research/data/LaPa/test').resolve():
        raise ValueError('지정된 로컬 LaPa test 경로만 사용합니다: research/data/LaPa/test')
    pairs = image_pairs(dataset)
    if args.limit < 0:
        p.error("--limit은 0 이상이어야 합니다")
    if args.limit:
        pairs = pairs[:args.limit]
    if not MODEL.exists():
        raise FileNotFoundError(f"로컬 Face Landmarker 모델이 없습니다: {MODEL}")
    DATA.mkdir(parents=True, exist_ok=True)
    opts = vision.FaceLandmarkerOptions(base_options=BaseOptions(model_asset_path=str(MODEL)), num_faces=1)
    lm = vision.FaceLandmarker.create_from_options(opts)
    rows = []
    try:
        for index, (image_path, label_path) in enumerate(pairs, 1):
            image, label = cv2.imread(str(image_path)), cv2.imread(str(label_path), cv2.IMREAD_UNCHANGED)
            if image is None or label is None or image.shape[:2] != label.shape:
                raise ValueError(f"이미지/마스크 손상 또는 크기 불일치: {image_path.name}")
            h0, w0 = image.shape[:2]
            scale = min(1, 960 / max(h0, w0))
            size = (max(1, round(w0*scale)), max(1, round(h0*scale)))
            rgb = cv2.cvtColor(cv2.resize(image, size, interpolation=cv2.INTER_AREA), cv2.COLOR_BGR2RGB)
            im = cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR)
            labmask = cv2.resize(label, size, interpolation=cv2.INTER_NEAREST)
            result = lm.detect(mp.Image(image_format=mp.ImageFormat.SRGB, data=np.ascontiguousarray(rgb)))
            row = {"candidate_index":index,"lapa_stem":image_path.stem,"face_id":provisional_face_id(image_path.stem),
                   "identity_reviewed":"","identity_method":"source_image_prefix_provisional_not_person_verified",
                   "source":"LaPa","source_split":"test","image_path":str(image_path),"label_path":str(label_path),
                   "image_sha256":sha(image_path),"label_sha256":sha(label_path),"detected":int(bool(result.face_landmarks)),
                   "ita":"","ita_bin":"","monk":"","mouth":"unknown","mouth_ratio":"","yaw_proxy":"","yaw_bin":"",
                   "lip_chroma":"","lip_skin_de2000":"","human_label":"","finish":""}
            if result.face_landmarks:
                points = result.face_landmarks[0]
                w, h = size
                xy = np.array([[v.x*w, v.y*h] for v in points])
                mouth_w = float(np.linalg.norm(xy[61] - xy[291]))
                ratio = float(np.linalg.norm(xy[13] - xy[14]) / max(mouth_w, 1e-6))
                cheek = np.zeros((h, w), np.uint8)
                for k in (205, 425):
                    cv2.circle(cheek, tuple(np.rint(xy[k]).astype(int)), max(4, round(mouth_w * .3)), 1, -1)
                skin = median_lab(im, (labmask == 1) & (cheek > 0))
                lip = median_lab(im, np.isin(labmask, [7, 9]))
                yaw = abs(float(points[234].z - points[454].z)) / max(abs(float(points[234].x - points[454].x)), 1e-6)
                row.update(mouth="open" if ratio >= OPEN_THRESHOLD else "closed", mouth_ratio=round(ratio, 5), yaw_proxy=round(yaw, 5))
                if skin is not None:
                    row['ita'] = round(math.degrees(math.atan2(float(skin[0])-50, float(skin[2]))), 3)
                if lip is not None:
                    row['lip_chroma'] = round(float(np.hypot(lip[1], lip[2])), 3)
                if lip is not None and skin is not None:
                    row['lip_skin_de2000'] = round(de2000(lip, skin), 3)
            rows.append(row)
            if index % 100 == 0:
                print(f"{index}/{len(pairs)}", flush=True)
    finally:
        lm.close()
    ita_edges, ita_labels = bins([r['ita'] for r in rows])
    yaw_edges, yaw_labels = bins([r['yaw_proxy'] for r in rows], 3)
    for r, a, b in zip(rows, ita_labels, yaw_labels):
        r['ita_bin'], r['yaw_bin'] = a, b
    output = DATA / "candidates.csv"
    with output.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=rows[0].keys()); w.writeheader(); w.writerows(rows)
    make_sheets(rows)
    (DATA / "selection_metadata.json").write_text(json.dumps({"dataset":"LaPa test", "dataset_path":str(dataset),
        "images":len(rows),"landmarker_sha256":sha(MODEL),"mouth_open_ratio_threshold":OPEN_THRESHOLD,
        "mouth_threshold_source":"docs/AR_SPEC.md 6-5-3 innerInset 0.1; heuristic, no clinical validity",
        "yaw":"absolute landmark depth difference / horizontal landmark span, relative proxy; not degrees",
        "bin_method":"dataset quantiles, sampling strata only, not classification cutoffs", "ita_quantiles":ita_edges,
        "yaw_quantiles":yaw_edges,"identity":"source image filename prefix only; NOT verified person identity; manually reconcile before splitting",
        "monk":"not assigned; no validated image-to-Monk mapping available", "human_label":"unreviewed"}, ensure_ascii=False, indent=2), encoding="utf8")
    print(f"완료: {output} ({len(rows)}장). human_label과 face_id는 사람이 확인해야 합니다.")


if __name__ == "__main__":
    main()

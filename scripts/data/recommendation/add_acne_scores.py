"""Add v4.1 acne scores to the retained recommendation splits."""

import argparse
import csv
import hashlib
import json
import math
from pathlib import Path

import numpy as np
import torch
from PIL import Image, ImageOps

ROOT = Path(__file__).resolve().parents[3]
SOURCE = ROOT / "ml/data/recommendation-v2/reviewed-20261114"
METADATA = ROOT / "ml/data/recommendation-v2/model-ready-20261111/x_metadata.csv"
BUNDLE = ROOT / "ml/runs/skin-analysis-v4.1/skin-analysis-v4.1"
PARTS = ("training", "validation", "test")


def sha256(path):
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def label_key(path):
    return path.replace("\\", "/").split("2.데이터(NIA)/")[-1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--image-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    root = args.image_root.resolve(strict=True)
    output = args.output.resolve()
    if output.exists():
        raise FileExistsError(f"Output already exists: {output}")

    protocol = json.loads((SOURCE / "protocol.json").read_text(encoding="utf-8"))
    rows = {}
    source_hashes = {}
    for part in PARTS:
        path = SOURCE / f"{part}.jsonl"
        source_hashes[part] = sha256(path)
        with path.open(encoding="utf-8") as handle:
            rows[part] = [json.loads(line) for line in handle if line.strip()]
        if len(rows[part]) != protocol["counts"][part]:
            raise ValueError(f"Unexpected row count: {part}")
    for i, part in enumerate(PARTS):
        for other in PARTS[i + 1:]:
            for field in ("source", "group_id", "original_group_id", "image_group_id"):
                if {r[field] for r in rows[part]} & {r[field] for r in rows[other]}:
                    raise ValueError(f"Cross-split overlap: {field}")

    mapping = {}
    with METADATA.open(encoding="utf-8-sig", newline="") as handle:
        for row in csv.DictReader(handle):
            key = label_key(row["label_path"])
            if key in mapping:
                raise ValueError("Duplicate metadata label path")
            mapping[key] = row

    manifest = json.loads((BUNDLE / "manifest.json").read_text(encoding="utf-8"))
    if manifest["schema"] != "skin-binary-three-roi-type-and-acne-v1":
        raise ValueError("Unexpected model bundle")
    model_record = manifest["models"]["acne"]
    checkpoint = (BUNDLE / model_record["file"]).resolve(strict=True)
    if not checkpoint.is_relative_to(BUNDLE.resolve()) or sha256(checkpoint) != model_record["sha256"]:
        raise ValueError("Invalid acne checkpoint")
    if model_record["score_type"] != "uncalibrated_ldl_aggregated_score":
        raise ValueError("Unexpected acne output")

    torch.set_num_threads(4)
    model = torch.jit.load(str(checkpoint), map_location="cpu").eval()
    mean = np.array(model_record["normalization_mean"], dtype=np.float32)
    std = np.array(model_record["normalization_std"], dtype=np.float32)
    cache = {}
    output_rows = {}
    with torch.inference_mode():
        for part in PARTS:
            output_rows[part] = []
            for index, row in enumerate(rows[part], 1):
                meta = mapping[row["source"].rsplit(":", 1)[0]]
                if meta["image_group_id"] != row["image_group_id"]:
                    raise ValueError("Image group mismatch")
                image_path = (root / meta["image_path"]).resolve(strict=True)
                if not image_path.is_relative_to(root) or sha256(image_path) != row["image_group_id"]:
                    raise ValueError("Image content mismatch")
                group = row["image_group_id"]
                if group not in cache:
                    with Image.open(image_path) as image:
                        image = ImageOps.exif_transpose(image).convert("RGB")
                        image = image.resize((256, 256), Image.Resampling.BILINEAR)
                        image = image.resize((224, 224), Image.Resampling.BILINEAR)
                        pixels = (np.asarray(image, dtype=np.float32) / 255 - mean) / std
                    tensor = torch.from_numpy(pixels.transpose(2, 0, 1).copy()).unsqueeze(0)
                    score = float(model(tensor).reshape(-1)[0])
                    if not math.isfinite(score) or not 0 <= score <= 1:
                        raise ValueError("Invalid acne score")
                    cache[group] = score
                scores = {key: float(meta[key]) for key in (
                    "pore_score", "wrinkle_score", "pigmentation_score"
                )}
                if any(not math.isfinite(value) or not 0 <= value <= 1 for value in scores.values()):
                    raise ValueError("Invalid existing score")
                scores["acne_score"] = cache[group]
                output_rows[part].append({**row, "image_scores": scores})
                if index % 250 == 0:
                    print(f"{part}: {index}/{len(rows[part])}; unique images: {len(cache)}", flush=True)

    output.mkdir(parents=True, exist_ok=False)
    auxiliary_hashes = {}
    for name in ("encoding_metadata.json", "folds.json"):
        data = (SOURCE / name).read_bytes()
        (output / name).write_bytes(data)
        auxiliary_hashes[name] = hashlib.sha256(data).hexdigest()
    result_hashes = {}
    summary = {}
    for part in PARTS:
        path = output / f"{part}.jsonl"
        with path.open("x", encoding="utf-8", newline="\n") as handle:
            for row in output_rows[part]:
                handle.write(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n")
        result_hashes[part] = sha256(path)
        scores = [r["image_scores"]["acne_score"] for r in output_rows[part]]
        summary[part] = {"rows": len(scores), "mean": sum(scores) / len(scores),
                         "below_threshold": sum(score < model_record["threshold"] for score in scores),
                         "at_or_above_threshold": sum(score >= model_record["threshold"] for score in scores)}
    result = {"schema": "recommendation-acne-features-v1", "counts": protocol["counts"],
              "source_split_sha256": source_hashes, "output_split_sha256": result_hashes,
              "metadata_sha256": sha256(METADATA), "auxiliary_sha256": auxiliary_hashes,
              "model_manifest_sha256": sha256(BUNDLE / "manifest.json"),
              "acne_model_sha256": model_record["sha256"], "image_groups": len(cache),
              "image_scores": ["pore_score", "wrinkle_score", "pigmentation_score", "acne_score"],
              "acne_threshold": model_record["threshold"], "summary": summary}
    (output / "protocol.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, ensure_ascii=True), flush=True)


if __name__ == "__main__":
    main()

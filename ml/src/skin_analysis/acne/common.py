"""Versioned data/model contracts, independent of the multilabel experiment."""

import hashlib
import json
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
DEFAULT_CONFIG = ROOT / "configs/acne_binary.toml"
CLASSES = {"정상": 0, "여드름": 1}
ARCHITECTURE = "acne-resnet50-linear1-v1"
PREPROCESSING = {
    "image_size": [256, 256], "resize": "full_image_stretch", "color": "RGB",
    "exif_transpose": True, "interpolation": "bilinear", "antialias": True,
    "mean": [.485, .456, .406], "std": [.229, .224, .225],
    "augmentation": {"horizontal_flip": .5, "rotation_degrees": 5},
}


def load_config(path=DEFAULT_CONFIG):
    with Path(path).open("rb") as handle:
        config = tomllib.load(handle)
    for section, key in (("data", "root"), ("data", "output"), ("train", "output"),
                         ("initialization", "nia_config")):
        config[section][key] = str((ROOT / config[section][key]).resolve())
    return config


def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                     allow_nan=False).encode()).hexdigest()


def file_hash(path):
    with Path(path).open("rb") as handle:
        return hashlib.file_digest(handle, "sha256").hexdigest()


def read_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def write_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False)
                         + "\n", encoding="utf-8")
    temporary.replace(path)


def archive_path(root, relative):
    path = (Path(root) / relative).resolve(strict=True)
    if not path.is_relative_to(Path(root).resolve()) or not path.is_file():
        raise ValueError("Archive must be inside the audited dataset root")
    return path


def load_manifest(config, *, verify_archives=True):
    manifest = read_json(Path(config["data"]["output"]) / "manifest.json")
    fingerprint = manifest.pop("fingerprint")
    if digest(manifest) != fingerprint or manifest.get("schema") != "acne-manifest-v1":
        raise ValueError("Invalid acne manifest fingerprint/schema")
    manifest["fingerprint"] = fingerprint
    if manifest["root"] != config["data"]["root"] or not manifest["training_ready"]:
        raise ValueError("Dataset root changed or audit has unresolved errors")
    groups = {}
    pixels = {}
    for row in manifest["records"]:
        if row["split"] == "quarantine":
            continue
        for seen, key in ((groups, "group_id"), (pixels, "pixel_sha256")):
            prior = seen.setdefault(row[key], row["split"])
            if prior != row["split"]:
                raise ValueError("Data leakage in audited manifest")
    if verify_archives:
        for archive in manifest["archives"]:
            if file_hash(archive_path(manifest["root"], archive["path"])) != archive["sha256"]:
                raise ValueError("Source archive changed; rerun the audit")
    return manifest

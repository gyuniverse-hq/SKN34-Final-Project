"""Versioned contracts for three independent smartphone grade classifiers."""

import hashlib
import json
import tomllib
from pathlib import Path

from ..config import PROJECT_ROOT, digest, write_json

TASKS = {
    "pore": {"classes": 6, "areas": {"pore": [5, 6]}},
    "pigmentation": {
        "classes": 6,
        "areas": {"forehead_pigmentation": [1], "cheek_pigmentation": [5, 6]},
    },
    "wrinkle": {
        "classes": 7,
        "areas": {
            "forehead_wrinkle": [1],
            "glabellus_wrinkle": [2],
            "perocular_wrinkle": [3, 4],
        },
    },
}
PREPROCESSING = "nia-square-jpeg-256-rgb-imagenet-v1"
DEFAULT_CONFIG = PROJECT_ROOT / "configs/nia_smartphone.toml"
PORE_COARSE_MAPPING = [0, 0, 1, 1, 2, 2]


def classification_contract(settings, task):
    mapping = settings.get("target_mapping")
    if mapping is None:
        if "classes" in settings:
            raise ValueError("Changing output classes requires an explicit target mapping")
        return TASKS[task]["classes"], None, task
    if task != "pore" or mapping != PORE_COARSE_MAPPING or settings.get("classes") != 3:
        raise ValueError("Only explicit pore 0,1 / 2,3 / 4,5 target mapping is supported")
    return 3, list(mapping), "pore_coarse"


def file_hash(path):
    value = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            value.update(block)
    return value.hexdigest()


def load_config(path=DEFAULT_CONFIG):
    config = tomllib.loads(Path(path).read_text(encoding="utf-8"))
    for section, keys in {"data": ("root", "output"), "train": ("output",)}.items():
        for key in keys:
            config[section][key] = str((PROJECT_ROOT / config[section][key]).resolve())
    return config


def load_manifest(config):
    path = Path(config["data"]["output"]) / "manifest.json"
    manifest = json.loads(path.read_text(encoding="utf-8"))
    claimed = manifest.pop("fingerprint")
    if digest(manifest) != claimed:
        raise ValueError("Smartphone manifest fingerprint mismatch")
    manifest["fingerprint"] = claimed
    if manifest["schema"] not in {
        "nia-smartphone-data-v1",
        "nia-smartphone-rare-grade-device-mix-v1",
    } or manifest["preprocessing"] != PREPROCESSING:
        raise ValueError("Incompatible smartphone data contract")
    assert_disjoint(manifest["records"])
    return manifest


def assert_disjoint(records):
    owners = {}
    for record in records:
        source_device = record.get("source_device", "smartphone")
        if (
            record["split"] not in {"train", "valid", "test"}
            or record["device"] != 3
            or source_device not in {"smartphone", "digital_camera", "smart_pad"}
            or (record["split"] != "train" and source_device != "smartphone")
        ):
            raise ValueError("Non-phone source images are allowed only in training records")
        for field in ("subject", "group", "image_sha256", "pixel_sha256"):
            key = field, record[field]
            if key in owners and owners[key] != record["split"]:
                raise ValueError(f"Cross-split leakage: {field}")
            owners[key] = record["split"]


__all__ = [
    "TASKS",
    "PREPROCESSING",
    "DEFAULT_CONFIG",
    "file_hash",
    "load_config",
    "load_manifest",
    "assert_disjoint",
    "digest",
    "write_json",
]

"""Configuration and JSON helpers shared by the local commands."""

import hashlib
import json
import tomllib
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CONFIG = PROJECT_ROOT / "configs/resnet50_multilabel.toml"
PUBLIC_CLASSES = (
    "Acne",
    "Blackheads",
    "Dark Spots",
    "Dry Skin",
    "Eye bags",
    "Normal Skin",
    "Oily Skin",
    "Pores",
    "Skin Redness",
    "Wrinkles",
)
SPLITS = ("train", "valid", "test")
SPLIT_RATIOS = (0.7, 0.2, 0.1)


def positive_support_minima(settings: dict, total_positive: int) -> dict[str, int]:
    """Explicit support policy; proportion targets remain soft for indivisible groups."""
    policy = settings.get("positive_support_policy", "fixed")
    if policy == "fixed":
        return {
            "train": 1,
            "valid": settings["min_eval_positive"],
            "test": settings["min_eval_positive"],
        }
    if policy == "proportional":
        return {
            "train": 1,
            "valid": max(1, total_positive * 2 // 10),
            "test": max(1, total_positive // 10),
        }
    raise ValueError(f"Unknown positive_support_policy: {policy}")


def load_config(path: str | Path = DEFAULT_CONFIG) -> dict:
    with Path(path).open("rb") as handle:
        config = tomllib.load(handle)
    for section, keys in {
        "data": ("root", "evidence", "metadata", "duplicate_reviews"),
        "audit": ("output",),
        "train": ("output",),
    }.items():
        for key in keys:
            config[section][key] = str((PROJECT_ROOT / config[section][key]).resolve())
    return config


def read_json(path: str | Path) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def write_json(path: str | Path, value: dict | list) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8"
    )


def digest(value: object) -> str:
    raw = json.dumps(value, sort_keys=True, ensure_ascii=False, allow_nan=False)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def class_key(name: str) -> str:
    return " ".join(name.replace("_", " ").replace("-", " ").casefold().split())

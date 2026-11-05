"""Definitions verified against tool/test.py and tool/data_loader.py at SOURCE_COMMIT."""

import re

SOURCE_COMMIT = "3e1704799587bef889e11203612eba46b529a66a"
SOURCE_URL = f"https://github.com/leejeongho3214/NIA/tree/{SOURCE_COMMIT}"

# mode, output dimension, original-unit multiplier, allowed split keys
TASKS = {
    "class/wrinkle": ("class", 7, 1, ["forehead_wrinkle", "glabellus_wrinkle", "perocular_wrinkle"]),
    "class/dryness": ("class", 5, 1, ["dryness"]),
    "class/pigmentation": ("class", 6, 1, ["forehead_pigmentation", "cheek_pigmentation"]),
    "class/pore": ("class", 6, 1, ["pore"]),
    "class/sagging": ("class", 6, 1, ["sagging"]),
    "regression/pigmentation": ("regression", 1, 350, ["pigmentation"]),
    "regression/moisture": ("regression", 1, 100,
                            ["forehead_moisture", "cheek_moisture", "chin_moisture"]),
    "regression/elasticity_R2": ("regression", 1, 1,
                                 ["forehead_elasticity_R2", "cheek_elasticity_R2", "chin_elasticity_R2"]),
    "regression/wrinkle_Ra": ("regression", 1, 50, ["perocular_wrinkle_Ra"]),
    "regression/pore": ("regression", 1, 2600, ["cheek_pore"]),
}


def validate_model(config):
    if not isinstance(config, dict):
        raise ValueError("Model configuration must be an object")
    config = {**config}
    if any(not isinstance(config.get(k), str) or not config[k].strip() for k in ("id", "checkpoint")):
        raise ValueError("Nonempty model id and checkpoint path are required")
    if config.get("architecture") != "resnet50" or config.get("resolution") != 256:
        raise ValueError("Only explicitly confirmed ResNet-50 / 256px checkpoints are supported")
    if not isinstance(config.get("task"), str) or config["task"] not in TASKS:
        raise ValueError("Unsupported original NIA task")
    mode, outputs, _, areas = TASKS[config["task"]]
    if any(not isinstance(config.get(k), str) or not config[k].strip() for k in ("source", "label_evidence")):
        raise ValueError("Checkpoint provenance and label/ROI evidence are required")
    if not isinstance(config.get("sha256"), str) or not re.fullmatch(r"[0-9a-fA-F]{64}", config["sha256"]):
        raise ValueError("Expected checkpoint SHA-256 is required")
    if not isinstance(config.get("areas"), dict) or not config["areas"] or any(area not in areas for area in config["areas"]):
        raise ValueError("Configure only areas verified for this checkpoint")
    config["areas"] = {area: ids if isinstance(ids, list) else [ids] for area, ids in config["areas"].items()}
    if any(not ids or any(type(part) is not int or part < 0 for part in ids) or len(ids) != len(set(ids))
           or (0 in ids and len(ids) > 1) for ids in config["areas"].values()):
        raise ValueError("areas must map split keys to verified facepart IDs; whole-face ROI cannot be mixed")
    if mode == "class" and (config.get("grades") != list(range(outputs)) or any(type(g) is not int for g in config["grades"])):
        raise ValueError("Explicit grade order must match the official output head")
    if mode == "regression" and (not isinstance(config.get("unit"), str) or not config["unit"].strip()):
        raise ValueError("An evidenced original measurement unit is required")
    return config

"""Run the uncapped side of the paired pore SAM cap ablation."""

import argparse
import json
import sys
from pathlib import Path

import torch

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))


def main():
    from skin_analysis.runtime import select_cuda
    from skin_analysis.smartphone.common import load_config, load_manifest
    from skin_analysis.smartphone.train import train_task, verify_crops

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("config", type=Path)
    args = parser.parse_args()
    config = load_config(args.config)
    settings = config["train"]
    if settings["class_weight_cap"] != "none":
        raise ValueError("This runner accepts only the explicit class_weight_cap='none' config")
    if settings["optimizer"] != "sam_adamw" or settings["weight_exponent"] != 0.5:
        raise ValueError("The ablation must keep sqrt-WCE and SAM+AdamW fixed")
    settings["class_weight_cap"] = None
    manifest = load_manifest(config)
    verify_crops(manifest)
    device = select_cuda(settings["device_uuid"])
    torch.set_num_threads(4)
    train_task(config, manifest, "pore", device)
    result_path = Path(settings["output"]) / "pore" / "summary.json"
    print(json.dumps({"status": "completed", "result": str(result_path)}), flush=True)


if __name__ == "__main__":
    main()

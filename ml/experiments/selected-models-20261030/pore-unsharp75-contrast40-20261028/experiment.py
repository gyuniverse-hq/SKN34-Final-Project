"""Fixed unsharp-mask comparison on the original full-ROI split."""
import argparse
import json
from pathlib import Path

import numpy as np
import torch
from PIL import Image, ImageEnhance, ImageFilter
from torchvision import transforms

from skin_analysis.config import digest, write_json
from skin_analysis.runtime import select_cuda
from skin_analysis.smartphone.common import load_config, load_manifest
from skin_analysis.smartphone.data import GradeDataset
from skin_analysis.smartphone.train import verify_crops
import skin_analysis.smartphone.regression_study as study

BASE = Path("runs/pore-unsharp75-contrast40-20261028")
SOURCE = Path("runs/batch-diversity-ablation-20261027/cv-head1-6fold/fold-1/manifest/manifest.json")
CONFIG = BASE / "config.toml"
PIPELINE = {"name": "pillow-unsharp-r1-p75-t0-contrast140-v1", "radius": 1.0, "percent": 75, "threshold": 0, "contrast_factor": 1.4, "input": "cached 256x256 RGB uint8", "order": "unsharp, then contrast, before random training augmentation and ImageNet normalization"}


class FixedUnsharp:
    def __call__(self, image):
        return ImageEnhance.Contrast(image.filter(ImageFilter.UnsharpMask(radius=1.0, percent=75, threshold=0))).enhance(1.4)


class TextureDataset(GradeDataset):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.transform = transforms.Compose([FixedUnsharp(), self.transform])
        self.repeat_transforms = {
            grade: transforms.Compose([FixedUnsharp(), transform])
            for grade, transform in self.repeat_transforms.items()
        }


def prepare():
    source = json.loads(SOURCE.read_text(encoding="utf-8"))
    claimed = source.pop("fingerprint")
    if digest(source) != claimed:
        raise ValueError("Source fingerprint mismatch")
    source["fingerprint"] = claimed
    verify_crops(source)
    manifest = {k: v for k, v in source.items() if k != "fingerprint"}
    manifest["experiment_texture_preprocessing"] = PIPELINE
    manifest["source_manifest_fingerprint"] = claimed
    manifest["fingerprint"] = digest(manifest)
    mdir = BASE / "manifest"
    mdir.mkdir(parents=True, exist_ok=False)
    write_json(mdir / "manifest.json", manifest)
    path = mdir.resolve().as_posix()
    text = f'''[data]\nroot = "."\noutput = "{path}"\nseed = 42\nfolds = 7\nvalid_fold = 1\ntest_fold = 0\n\n[train]\noutput = "runs/pore-unsharp75-contrast40-20261028"\nseed = 42\ndevice_uuid = "GPU-9ed09563-0d58-cdc7-f6bc-b2c84d8da0e3"\nbatch_size = 16\neffective_batch = 16\nnum_workers = 4\nfreeze_epochs = 2\nfinetune_epochs = 18\nhead_lr = 0.001\nfinetune_head_lr = 0.0001\nbackbone_lr = 0.00001\nweight_decay = 0.0001\npatience = 6\namp = true\nweight_exponent = 0.2\nrecord_train_metrics = true\noptimizer = "sam_adamw"\nsam_rho = 0.05\ndeterministic_samples = true\ngrade_diverse_batches = true\nsqrt_oversampling = true\nfixed_epochs = false\n'''
    CONFIG.write_text(text, encoding="utf-8")
    # Only training ROIs are used for this fixed preprocessing preview.
    records = [r for r in manifest["records"] if r["task"] == "pore" and r["split"] == "train"]
    selected = []
    for grade in range(6):
        seen = set()
        for r in records:
            if r["truth"] == grade and r["subject"] not in seen:
                selected.append(r)
                seen.add(r["subject"])
                if len(seen) == 3:
                    break
    cache = np.load(Path(manifest["root"]) / manifest["pixel_cache"]["path"], mmap_mode="r")
    preview = Image.new("RGB", (512, 256 * 6))
    diff, original_clipped, processed_clipped, total = 0, 0, 0, 0
    for i, r in enumerate(selected):
        original = Image.fromarray(cache[r["cache_index"]])
        result = FixedUnsharp()(original)
        a, b = np.asarray(original, dtype=np.int16), np.asarray(result, dtype=np.int16)
        diff += int(np.abs(a-b).sum())
        original_clipped += int(((a == 0) | (a == 255)).sum())
        processed_clipped += int(((b == 0) | (b == 255)).sum())
        total += a.size
        if i % 3 == 0:
            preview.paste(original, (0, (i // 3) * 256))
            preview.paste(result, (256, (i // 3) * 256))
    preview.save(BASE / "training-preview-original-left-unsharp-right.png")
    preview_stats = {"pipeline": PIPELINE, "training_roi_count": len(selected), "training_subject_count": len({r['subject'] for r in selected}), "mean_absolute_rgb_difference_0_255": diff / total, "original_fraction_channel_values_0_or_255": original_clipped / total, "processed_fraction_channel_values_0_or_255": processed_clipped / total, "preview": str(BASE / 'training-preview-original-left-unsharp-right.png'), "source_fingerprint": claimed, "new_fingerprint": manifest['fingerprint']}
    write_json(BASE / "preview-stats.json", preview_stats)
    print(json.dumps(preview_stats, indent=2), flush=True)


def train():
    config = load_config(CONFIG)
    manifest = load_manifest(config)
    if manifest.get("experiment_texture_preprocessing") != PIPELINE:
        raise ValueError("Preprocessing contract mismatch")
    verify_crops(manifest)
    study.GradeDataset = TextureDataset
    device = select_cuda(config["train"]["device_uuid"])
    torch.set_num_threads(4)
    study.train(config, manifest, "huber", BASE / "huber", device, "sam_adamw")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=["prepare", "train"])
    args = parser.parse_args()
    if args.action == "prepare":
        prepare()
    else:
        train()

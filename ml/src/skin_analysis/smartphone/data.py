"""The same cached 256px NIA crop is used in training and inference."""

import hashlib
import multiprocessing
from pathlib import Path

import numpy as np
import torch
from PIL import Image
from torch.utils.data import Dataset
from torchvision import transforms

from .common import PORE_COARSE_MAPPING


class GradeDataset(Dataset):
    def __init__(
        self,
        manifest,
        task,
        split,
        training=False,
        target_mapping=None,
        training_seed=None,
        augmentation=None,
        repeat_augmentation_by_grade=None,
    ):
        if target_mapping is not None and (task != "pore" or target_mapping != PORE_COARSE_MAPPING):
            raise ValueError("Only declared pore coarse targets are supported")
        self.target_mapping = list(target_mapping) if target_mapping is not None else None
        self.root = Path(manifest["root"])
        self.cache_path = manifest.get("pixel_cache", {}).get("path")
        self._cache = None
        self.training_seed = training_seed
        self.epoch = multiprocessing.Value("i", 0) if training_seed is not None else None
        self.records = [r for r in manifest["records"] if r["task"] == task and r["split"] == split]
        options = {
            "degrees": 5,
            "translate": 0.02,
            "brightness": 0.1,
            "contrast": 0.1,
            "saturation": 0.05,
            "reflect_pad": 0,
            "center_crop_size": 256,
        }
        if augmentation:
            if set(augmentation) - set(options):
                raise ValueError("Unknown augmentation setting")
            options.update(augmentation)
        self.transform = self._make_transform(options, training)
        self.repeat_transforms = {}
        for grade, repeat_options in (repeat_augmentation_by_grade or {}).items():
            if not isinstance(grade, int) or grade < 0 or set(repeat_options) - set(options):
                raise ValueError("Invalid repeat augmentation grade or setting")
            selected = dict(options)
            selected.update(repeat_options)
            self.repeat_transforms[grade] = self._make_transform(selected, training)

    @staticmethod
    def _make_transform(options, training):
        spatial = []
        if training and options["reflect_pad"]:
            spatial.append(transforms.Pad(options["reflect_pad"], padding_mode="reflect"))
        if training:
            spatial.append(
                transforms.RandomAffine(
                    degrees=options["degrees"],
                    translate=(options["translate"], options["translate"]),
                )
            )
        spatial.append(transforms.CenterCrop(options["center_crop_size"]))
        color = transforms.ColorJitter(
            brightness=options["brightness"],
            contrast=options["contrast"],
            saturation=options["saturation"],
        )
        # No horizontal flips: laterality and facial ROI semantics are preserved.
        return transforms.Compose(
            [
                *spatial,
                *([color] if training else []),
                transforms.ToTensor(),
                transforms.Normalize([0.485, 0.456, 0.406], [0.229, 0.224, 0.225]),
            ]
        )

    def __len__(self):
        return len(self.records)

    def target(self, record):
        truth = record["truth"]
        return self.target_mapping[truth] if self.target_mapping is not None else truth

    def set_epoch(self, epoch):
        if self.epoch is not None:
            self.epoch.value = epoch

    def transform_record(self, image, record, occurrence=0):
        if self.training_seed is None:
            return self.transform(image)
        grade = self.target(record)
        transform = (
            self.repeat_transforms.get(grade, self.transform) if occurrence > 0 else self.transform
        )
        # Independent of batch size, worker scheduling, persistent workers and resume.
        suffix = f":repeat:{occurrence}" if occurrence else ""
        identity = f"{self.training_seed}:{self.epoch.value}:{record['id']}{suffix}".encode()
        seed = int.from_bytes(hashlib.sha256(identity).digest()[:8], "little")
        with torch.random.fork_rng(devices=[]):
            torch.set_rng_state(torch.Generator().manual_seed(seed).get_state())
            return transform(image)

    def __getitem__(self, index):
        occurrence = 0
        if isinstance(index, tuple):
            index, occurrence = index
        record = self.records[index]
        if self.cache_path:
            if self._cache is None:
                self._cache = np.load(self.root / self.cache_path, mmap_mode="r")
            image = Image.fromarray(self._cache[record["cache_index"]])
            return (
                self.transform_record(image, record, occurrence),
                torch.tensor(self.target(record), dtype=torch.long),
                index,
            )
        path = (self.root / record["path"]).resolve(strict=True)
        if not path.is_relative_to(self.root.resolve()):
            raise ValueError("Crop path escapes the audited dataset")
        with Image.open(path) as source:
            if source.size != (256, 256):
                raise ValueError("Expected an audited 256px crop")
            image = self.transform_record(source.convert("RGB"), record, occurrence)
        return image, torch.tensor(self.target(record), dtype=torch.long), index

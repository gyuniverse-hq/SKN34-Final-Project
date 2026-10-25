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
        self, manifest, task, split, training=False, target_mapping=None, training_seed=None
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
        augment = [
            transforms.RandomAffine(degrees=5, translate=(0.02, 0.02)),
            transforms.ColorJitter(brightness=0.1, contrast=0.1, saturation=0.05),
        ]
        # No horizontal flips: laterality and facial ROI semantics are preserved.
        self.transform = transforms.Compose(
            [
                *(augment if training else []),
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

    def transform_record(self, image, record):
        if self.training_seed is None:
            return self.transform(image)
        # Independent of batch size, worker scheduling, persistent workers and resume.
        identity = f"{self.training_seed}:{self.epoch.value}:{record['id']}".encode()
        seed = int.from_bytes(hashlib.sha256(identity).digest()[:8], "little")
        with torch.random.fork_rng(devices=[]):
            torch.set_rng_state(torch.Generator().manual_seed(seed).get_state())
            return self.transform(image)

    def __getitem__(self, index):
        record = self.records[index]
        if self.cache_path:
            if self._cache is None:
                self._cache = np.load(self.root / self.cache_path, mmap_mode="r")
            image = Image.fromarray(self._cache[record["cache_index"]])
            return (
                self.transform_record(image, record),
                torch.tensor(self.target(record), dtype=torch.long),
                index,
            )
        path = (self.root / record["path"]).resolve(strict=True)
        if not path.is_relative_to(self.root.resolve()):
            raise ValueError("Crop path escapes the audited dataset")
        with Image.open(path) as source:
            if source.size != (256, 256):
                raise ValueError("Expected an audited 256px crop")
            image = self.transform_record(source.convert("RGB"), record)
        return image, torch.tensor(self.target(record), dtype=torch.long), index

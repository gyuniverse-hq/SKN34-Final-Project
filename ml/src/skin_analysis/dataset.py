"""Manifest-backed datasets keep every original class in its audited order."""

import random
from pathlib import Path

import numpy as np
import torch
from PIL import Image, ImageOps
from torch.utils.data import DataLoader, Dataset

from .audit import DataContractError, safe_image_path
from .transforms import make_transform


class SkinDataset(Dataset):
    def __init__(self, manifest: dict, split: str, *, training: bool = False):
        self.root = Path(manifest["root"])
        self.classes = manifest["classes"]
        self.records = [record for record in manifest["records"] if record["split"] == split]
        self.transform = make_transform(training)
        for record in self.records:
            if len(record["labels"]) != len(self.classes) or any(
                value not in (0, 1) for value in record["labels"]
            ):
                raise DataContractError(
                    f"Training requires complete binary labels: {record['path']}"
                )

    def __len__(self):
        return len(self.records)

    def __getitem__(self, index):
        record = self.records[index]
        with Image.open(safe_image_path(self.root, record["path"])) as source:
            image = self.transform(ImageOps.exif_transpose(source).convert("RGB"))
        return image, torch.tensor(record["labels"], dtype=torch.float32), index


def seed_worker(worker_id: int) -> None:
    seed = torch.initial_seed() % 2**32
    random.seed(seed)
    np.random.seed(seed)


def make_loader(
    dataset: SkinDataset,
    batch_size: int,
    workers: int,
    seed: int,
    shuffle: bool = False,
    generator: torch.Generator | None = None,
) -> DataLoader:
    generator = generator or torch.Generator().manual_seed(seed)
    return DataLoader(
        dataset,
        batch_size=batch_size,
        shuffle=shuffle,
        num_workers=workers,
        pin_memory=torch.cuda.is_available(),
        worker_init_fn=seed_worker,
        generator=generator,
        persistent_workers=False,
    )

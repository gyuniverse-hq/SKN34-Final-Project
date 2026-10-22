"""The same cached 256px NIA crop is used in training and inference."""

from pathlib import Path

import torch
from PIL import Image
from torch.utils.data import Dataset
from torchvision import transforms


class GradeDataset(Dataset):
    def __init__(self, manifest, task, split, training=False):
        self.root = Path(manifest["root"])
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

    def __getitem__(self, index):
        record = self.records[index]
        path = (self.root / record["path"]).resolve(strict=True)
        if not path.is_relative_to(self.root.resolve()):
            raise ValueError("Crop path escapes the audited dataset")
        with Image.open(path) as source:
            if source.size != (256, 256):
                raise ValueError("Expected an audited 256px crop")
            image = self.transform(source.convert("RGB"))
        return image, torch.tensor(record["truth"], dtype=torch.long), index

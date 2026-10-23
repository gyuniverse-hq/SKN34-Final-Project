"""Lazy ZIP access: worker-local handles, one decoded image per item."""

import io
import os
import zipfile

import torch
from PIL import Image, ImageOps
from torch.utils.data import Dataset
from torchvision import transforms as T
from torchvision.transforms import InterpolationMode

from .common import PREPROCESSING, archive_path


def transform(training=False):
    operations = [T.Resize((256, 256), interpolation=InterpolationMode.BILINEAR, antialias=True)]
    if training:
        operations += [T.RandomHorizontalFlip(.5),
                       T.RandomRotation(5, interpolation=InterpolationMode.BILINEAR,
                                        fill=(124, 116, 104))]
    return T.Compose([*operations, T.ToTensor(),
                      T.Normalize(PREPROCESSING["mean"], PREPROCESSING["std"])])


def prepare_image(raw):
    with Image.open(io.BytesIO(raw)) as image:
        if image.format not in ("PNG", "JPEG") or image.width * image.height > 30_000_000:
            raise ValueError("Only JPEG/PNG up to 30 megapixels are supported")
        image.load()
        return transform()(ImageOps.exif_transpose(image).convert("RGB"))


class AcneDataset(Dataset):
    def __init__(self, manifest, split, training=False):
        self.root = manifest["root"]
        self.records = [r for r in manifest["records"] if r["split"] == split]
        self.transform = transform(training)
        self.handles = {}
        self.pid = os.getpid()
        if not self.records:
            raise ValueError(f"Empty dataset split: {split}")

    def __len__(self):
        return len(self.records)

    def __getstate__(self):
        return {**self.__dict__, "handles": {}}

    def __getitem__(self, index):
        if self.pid != os.getpid():
            self.handles = {}
            self.pid = os.getpid()
        row = self.records[index]
        name = row["archive"]
        if name not in self.handles:
            self.handles[name] = zipfile.ZipFile(archive_path(self.root, name))
        raw = self.handles[name].read(row["member"])
        with Image.open(io.BytesIO(raw)) as image:
            image = self.transform(ImageOps.exif_transpose(image).convert("RGB"))
        return image, torch.tensor([row["label"]], dtype=torch.float32), index

    def close(self):
        for handle in self.handles.values():
            handle.close()
        self.handles.clear()

    def __del__(self):
        self.close()

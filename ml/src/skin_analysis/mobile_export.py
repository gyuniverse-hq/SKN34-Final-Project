"""Shared deterministic fixtures for the retained v3/v4 exporters.

The retired NIA SAM export entry point was removed on 2026-11-12.
"""

import hashlib
import io
import json
from pathlib import Path

import numpy as np
from PIL import Image
from server.nia.imaging import prepare

from .acne.data import prepare_image

ROOT = Path(__file__).resolve().parents[3]
OUTPUT_ROOT = ROOT / "ml/runs/skin-mobile"


def digest(path):
    with Path(path).open("rb") as handle:
        return hashlib.file_digest(handle, "sha256").hexdigest()


def fixtures(output):
    records = []
    for name, width, height, bbox in (
        ("identity", 256, 256, None),
        ("downsample", 773, 517, None),
        ("upsample", 117, 151, None),
        ("crop", 513, 397, [43, 37, 311, 283]),
    ):
        y, x = np.indices((height, width))
        rgb = np.stack(
            ((x * 7 + y * 3) % 256, (x * 2 + y * 11) % 256, ((x // 9 + y // 7) % 2) * 255), axis=-1
        ).astype(np.uint8)
        buffer = io.BytesIO()
        Image.fromarray(rgb).save(buffer, format="PNG")
        raw = buffer.getvalue()
        (output / f"{name}.png").write_bytes(raw)
        tensor = prepare(raw, bbox, 5, False, False)[0] if bbox else prepare_image(raw).unsqueeze(0)
        tensor.numpy().astype("<f4").tofile(output / f"{name}.f32")
        records.append(
            dict(image=f"{name}.png", tensor=f"{name}.f32", bbox=bbox, maxAbsoluteError=1e-5)
        )
    (output / "fixtures.json").write_text(json.dumps(records, indent=2), encoding="utf-8")
    return records

from __future__ import annotations

import io
import json
import shutil
from dataclasses import dataclass
from pathlib import Path

from PIL import Image, ImageOps


@dataclass(frozen=True)
class ImageSet:
    id: str
    real: Path
    ar: Path
    bare: Path | None
    meta: dict


def _find(folder: Path, stem: str) -> Path | None:
    found = [p for p in folder.iterdir() if p.is_file() and p.stem.lower() == stem
             and p.suffix.lower() in {'.jpg', '.jpeg', '.png'}]
    if len(found) > 1:
        raise ValueError(f'{folder}: duplicate {stem} images')
    return found[0] if found else None


def discover(data: Path) -> tuple[list[ImageSet], list[str]]:
    sets, errors = [], []
    root = data / 'sets'
    if not root.exists():
        return [], [f'{root}: sets directory not found']
    for folder in sorted(p for p in root.iterdir() if p.is_dir()):
        try:
            real, ar, bare = (_find(folder, name) for name in ('real', 'ar', 'bare'))
            if not real or not ar:
                errors.append(f'{folder.name}: missing real or ar')
                continue
            meta_path = folder / 'meta.json'
            meta = json.loads(meta_path.read_text(encoding='utf-8')) if meta_path.exists() else {}
            if not isinstance(meta, dict):
                raise TypeError('meta.json must be an object')
            for path in (real, ar, bare):
                if path:
                    with Image.open(path) as im:
                        ImageOps.exif_transpose(im).load()
            sets.append(ImageSet(folder.name, real, ar, bare, meta))
        except (OSError, ValueError, TypeError) as exc:
            errors.append(f'{folder.name}: {exc}')
    return sets, errors


def load_image(path: Path) -> Image.Image:
    with Image.open(path) as im:
        return ImageOps.exif_transpose(im).convert('RGB')


def lip_box(image: Image.Image, model_path: Path | None = None) -> tuple[tuple[float, float, float, float], str]:
    # The optional Face Landmarker model must be provided locally; no downloads are performed.
    if model_path and model_path.is_file():
        try:
            import mediapipe as mp
            from mediapipe.tasks import python
            from mediapipe.tasks.python import vision

            options = vision.FaceLandmarkerOptions(base_options=python.BaseOptions(model_asset_path=str(model_path)), num_faces=1)
            with vision.FaceLandmarker.create_from_options(options) as landmarker:
                import numpy as np
                result = landmarker.detect(mp.Image(image_format=mp.ImageFormat.SRGB, data=np.asarray(image)))
            if result.face_landmarks:
                points = [result.face_landmarks[0][i] for i in (61, 291, 0, 17, 37, 267, 84, 314)]
                x0, x1 = min(p.x for p in points), max(p.x for p in points)
                y0, y1 = min(p.y for p in points), max(p.y for p in points)
                dx, dy = (x1-x0)*0.4, (y1-y0)*0.4
                return (max(0, x0-dx), max(0, y0-dy), min(1, x1+dx), min(1, y1+dy)), 'landmarker'
        except (ImportError, RuntimeError, ValueError, OSError):
            pass
    return (0.25, 0.50, 0.75, 1.0), 'fallback'


def jpeg(image: Image.Image, box: tuple[float, float, float, float] | None = None) -> bytes:
    if box:
        w, h = image.size
        image = image.crop((round(box[0]*w), round(box[1]*h), round(box[2]*w), round(box[3]*h)))
    image = image.copy()
    image.thumbnail((1024, 1024), Image.Resampling.LANCZOS)
    out = io.BytesIO()
    image.save(out, format='JPEG', quality=90, exif=b'')
    return out.getvalue()


def import_existing(src: Path, data: Path) -> int:
    # Only copy folders with explicit role filenames; never guess correspondence or alter originals.
    count = 0
    destination = data / 'sets'
    for folder in [src, *sorted(p for p in src.rglob('*') if p.is_dir())]:
        try:
            real, ar = _find(folder, 'real'), _find(folder, 'ar')
            if not real or not ar:
                continue
            dest = destination / folder.name
            if dest.exists():
                raise FileExistsError(f'{dest} already exists')
            dest.mkdir(parents=True)
            for stem in ('bare', 'real', 'ar'):
                path = _find(folder, stem)
                if path:
                    shutil.copy2(path, dest / path.name)
            if (folder / 'meta.json').exists():
                shutil.copy2(folder / 'meta.json', dest / 'meta.json')
            count += 1
        except FileNotFoundError:
            continue
    return count

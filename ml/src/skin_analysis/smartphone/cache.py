"""Build a shared read-only pixel cache instead of reopening JPEGs each epoch."""

import argparse
from pathlib import Path

import numpy as np
from PIL import Image

from .common import DEFAULT_CONFIG, digest, file_hash, load_config, load_manifest, write_json


def build_cache(config):
    manifest = load_manifest(config)
    root = Path(manifest["root"])
    if "pixel_cache" in manifest or (root / "pixels.npy").exists():
        raise FileExistsError("Pixel cache already exists; never overwrite an audited cache")
    unique = {r["path"]: r["crop_sha256"] for r in manifest["records"]}
    cache = np.lib.format.open_memmap(
        root / "pixels.npy", mode="w+", dtype=np.uint8, shape=(len(unique), 256, 256, 3)
    )
    indices = {}
    for index, (relative, expected) in enumerate(sorted(unique.items())):
        path = (root / relative).resolve(strict=True)
        if not path.is_relative_to(root) or file_hash(path) != expected:
            raise ValueError("Audited JPEG changed or escaped the dataset root")
        with Image.open(path) as image:
            if image.size != (256, 256):
                raise ValueError("Unexpected crop size")
            cache[index] = np.asarray(image.convert("RGB"))
        indices[relative] = index
        if index % 2000 == 0:
            print(f"Cached {index}/{len(unique)} ROIs", flush=True)
    cache.flush()
    del cache
    manifest["pixel_cache"] = dict(
        path="pixels.npy",
        sha256=file_hash(root / "pixels.npy"),
        count=len(unique),
        dtype="uint8",
        shape=[256, 256, 3],
    )
    manifest["records"] = [{**r, "cache_index": indices[r["path"]]} for r in manifest["records"]]
    manifest.pop("fingerprint")
    manifest["fingerprint"] = digest(manifest)
    write_json(root / "manifest.before-pixel-cache.json", load_manifest(config))
    write_json(root / "manifest.json", manifest)
    write_json(
        root / "summary.json",
        {
            k: manifest[k]
            for k in (
                "schema",
                "fingerprint",
                "summary",
                "excluded",
                "source_photo_count",
                "split_method",
                "pixel_cache",
            )
        },
    )
    print(f"Pixel cache ready: {len(unique)} ROIs", flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    args = parser.parse_args()
    build_cache(load_config(args.config))


if __name__ == "__main__":
    main()

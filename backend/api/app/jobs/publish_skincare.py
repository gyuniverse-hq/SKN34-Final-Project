"""Validate a reviewed serving bundle; dry-run by default. Never enables mappings."""

import argparse
import asyncio
import json
from pathlib import Path

from app.schemas.skincare import SkincareSnapshot
from app.services.skincare_refresh_service import MANIFEST, publish_reviews
from app.services.skincare_service import review_preview


async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("bundle", type=Path)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--manifest", type=Path, default=MANIFEST)
    args = parser.parse_args()
    snapshot = SkincareSnapshot.model_validate_json(args.bundle.read_text(encoding="utf-8"))
    print(json.dumps(review_preview(snapshot), indent=2, ensure_ascii=False))
    if args.apply:
        print(await publish_reviews(args.manifest, expected=snapshot))


if __name__ == "__main__":
    asyncio.run(main())

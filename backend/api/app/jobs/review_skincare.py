"""Read-only coverage preview, or record an operator decision and publish atomically."""

import argparse
import asyncio
import json
from pathlib import Path

from app.services.skincare_refresh_service import MANIFEST, preview_reviews, publish_reviews


async def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, default=MANIFEST)
    parser.add_argument("--mapping")
    parser.add_argument("--state", choices=("enabled", "disabled"))
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    if args.apply:
        if not args.mapping or not args.state:
            parser.error("--apply requires --mapping and --state")
        print(await publish_reviews(args.manifest, switch=(args.mapping, args.state == "enabled")))
    else:
        if args.mapping or args.state:
            parser.error("Use --apply to submit a review; omit review arguments to preview")
        print(json.dumps(await preview_reviews(args.manifest), indent=2, ensure_ascii=False))


if __name__ == "__main__":
    asyncio.run(main())

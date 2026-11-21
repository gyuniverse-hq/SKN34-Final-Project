"""Register the mention-only makeup videos and give each an unpublished look.

``uv run python -m app.jobs.register_look_videos --inventory <look-tag-review-db.json>
[--tags <look-tag-v3-final-ai.json>] [--write]``

Without ``--write`` it only prints the plan. See app.services.look_video_registration_service.
"""

import argparse
import asyncio
import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from app.core.db import dispose_engine, session_scope
from app.services.look_video_registration_service import register_look_videos


async def run(
    inventory: Mapping[str, Any], tag_videos: Mapping[str, Mapping[str, Any]], write: bool
) -> int:
    try:
        async with session_scope() as session:
            report = await register_look_videos(session, inventory, tag_videos, write)
    finally:
        await dispose_engine()
    planned, new = report.planned, report.new
    print(f"mention-only videos: {len(planned)} (new {len(new)})")
    if new:
        print(f"new ids: {new[0].id} .. {new[-1].id}")
    placeholders = sum(item.title.startswith("YouTube video ") for item in planned)
    print(f"placeholder titles: {placeholders}")
    print(f"start_seconds > 0: {sum(item.start_seconds > 0 for item in planned)}")
    print(("applied: " if write else "dry run (add --write to apply): ") + str(report.counts))
    return 0


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--inventory", type=Path, required=True)
    parser.add_argument("--tags", type=Path)
    parser.add_argument("--write", action="store_true")
    args = parser.parse_args()
    # Files are read before the event loop starts so the async job never blocks on disk.
    inventory = json.loads(args.inventory.read_text(encoding="utf-8"))
    tag_videos = json.loads(args.tags.read_text(encoding="utf-8"))["videos"] if args.tags else {}
    raise SystemExit(asyncio.run(run(inventory, tag_videos, args.write)))


if __name__ == "__main__":
    main()

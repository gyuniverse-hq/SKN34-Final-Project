"""Register the mention-only makeup videos and give each an unpublished look.

``uv run python -m app.jobs.register_look_videos --inventory <look-tag-review-db.json>
[--tags <look-tag-v3-final-ai.json>] [--write]``

The 105 videos whose products are in raw_yt_product_mention but which have no youtube_videos
row get the same shape as the three pilot videos: a youtube_videos row and a makeup_looks row.
Looks stay unpublished until AR settings and products are reviewed. Without ``--write`` it
only prints the plan. Running it again keeps the ids it already gave and only refreshes the
start time from a newer tag file, so the pilot rows are never touched.
"""

import argparse
import asyncio
import json
import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sqlalchemy import select

from app.core.db import dispose_engine, session_scope
from app.models.idol_look import MakeupLookRow, YoutubeVideoRow

STYLE_PLACEHOLDER = "Video is registered. Makeup style has not been verified."
_NUMBERED_ID = re.compile(r"^(?:VIDEO|LOOK)-(\d+)$")


@dataclass(frozen=True)
class PlannedVideo:
    id: str
    look_id: str
    video_id: str
    youtube_url: str
    start_seconds: int
    title: str
    channel_name: str
    thumbnail_url: str
    description: str | None
    analysis_status: str
    is_new: bool


def mention_only_videos(inventory: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Videos known from product mentions that have no youtube_videos row yet."""
    return [
        video
        for video in inventory["videos"]
        if "db_mention_only" in video.get("origins", []) and not video.get("db_video_id")
    ]


def primary_start(tag_video: Mapping[str, Any] | None) -> int:
    """Start of the earliest finished-look segment the tagging marked as primary, else 0."""
    segments = (tag_video or {}).get("finished_look_segments") or []
    starts = [
        int(segment["start_seconds"])
        for segment in segments
        if segment.get("role") == "primary" and segment.get("start_seconds") is not None
    ]
    return min(starts) if starts else 0


def _number(row_id: str) -> int:
    match = _NUMBERED_ID.match(row_id)
    return int(match.group(1)) if match else 0


def plan_registrations(
    videos: Iterable[Mapping[str, Any]],
    tag_videos: Mapping[str, Mapping[str, Any]],
    existing: Mapping[str, str],
    used_ids: Iterable[str],
) -> list[PlannedVideo]:
    """Give new videos the next VIDEO-/LOOK- number and keep ids of rows already registered.

    ``existing`` maps a YouTube id to its youtube_videos.id; ``used_ids`` holds every
    youtube_videos and makeup_looks id so a new number never collides with either table.
    """
    next_number = max((_number(row_id) for row_id in used_ids), default=0) + 1
    planned: list[PlannedVideo] = []
    for video in videos:
        youtube_id = video["video_id"]
        row_id = existing.get(youtube_id)
        is_new = row_id is None
        if row_id is None:
            row_id = f"VIDEO-{next_number:03d}"
            next_number += 1
        number = _number(row_id)
        title = (video.get("title") or "").strip()
        planned.append(
            PlannedVideo(
                id=row_id,
                look_id=f"LOOK-{number:03d}",
                video_id=youtube_id,
                youtube_url=video.get("video_url")
                or f"https://www.youtube.com/watch?v={youtube_id}",
                start_seconds=primary_start(tag_videos.get(youtube_id)),
                title=(title or f"YouTube video {youtube_id}")[:300],
                channel_name=(video.get("channel") or "")[:200],
                thumbnail_url=video.get("thumbnail_url")
                or f"https://i.ytimg.com/vi/{youtube_id}/hqdefault.jpg",
                description=video.get("description") or None,
                # A title from the inventory counts as registered; refresh_youtube_metadata
                # later turns both states into metadata_ready.
                analysis_status="registered" if title else "metadata_unavailable",
                is_new=is_new,
            )
        )
    return planned


async def apply(planned: list[PlannedVideo], write: bool) -> dict[str, int]:
    async with session_scope() as session:
        rows = {
            row.video_id: row
            for row in await session.scalars(
                select(YoutubeVideoRow).where(
                    YoutubeVideoRow.video_id.in_([item.video_id for item in planned])
                )
            )
        }
        look_ids = set(await session.scalars(select(MakeupLookRow.id)))
        counts = {"videos_added": 0, "looks_added": 0, "start_updated": 0}
        for item in planned:
            row = rows.get(item.video_id)
            if row is None:
                session.add(
                    YoutubeVideoRow(
                        id=item.id,
                        video_id=item.video_id,
                        youtube_url=item.youtube_url,
                        start_seconds=item.start_seconds,
                        title=item.title,
                        channel_name=item.channel_name,
                        thumbnail_url=item.thumbnail_url,
                        description=item.description,
                        published_at=None,
                        analysis_status=item.analysis_status,
                        product_mapping_status="unreviewed",
                    )
                )
                counts["videos_added"] += 1
            elif item.start_seconds and row.start_seconds != item.start_seconds:
                row.start_seconds = item.start_seconds
                counts["start_updated"] += 1
            if item.look_id not in look_ids:
                session.add(
                    MakeupLookRow(
                        id=item.look_id,
                        video_id=item.id,
                        display_name=item.title,
                        style_description=STYLE_PLACEHOLDER,
                        is_published=False,
                    )
                )
                counts["looks_added"] += 1
        if write:
            await session.commit()
        else:
            await session.rollback()
    return counts


async def run(
    inventory: Mapping[str, Any], tag_videos: Mapping[str, Mapping[str, Any]], write: bool
) -> int:
    videos = mention_only_videos(inventory)
    try:
        async with session_scope() as session:
            existing = {
                video_id: row_id
                for video_id, row_id in await session.execute(
                    select(YoutubeVideoRow.video_id, YoutubeVideoRow.id)
                )
            }
            used_ids = list(await session.scalars(select(YoutubeVideoRow.id)))
            used_ids += list(await session.scalars(select(MakeupLookRow.id)))
        planned = plan_registrations(videos, tag_videos, existing, used_ids)
        new = [item for item in planned if item.is_new]
        print(f"mention-only videos: {len(videos)} (new {len(new)})")
        if new:
            print(f"new ids: {new[0].id} .. {new[-1].id}")
        placeholders = sum(item.title.startswith("YouTube video ") for item in planned)
        print(f"placeholder titles: {placeholders}")
        print(f"start_seconds > 0: {sum(item.start_seconds > 0 for item in planned)}")
        counts = await apply(planned, write)
    finally:
        await dispose_engine()
    print(("applied: " if write else "dry run (add --write to apply): ") + str(counts))
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

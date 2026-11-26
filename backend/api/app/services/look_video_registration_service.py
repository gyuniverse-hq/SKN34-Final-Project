"""Register the mention-only makeup videos and give each an unpublished look.

The 105 videos whose products are in raw_yt_product_mention but which have no youtube_videos
row get the same shape as the three pilot videos: a youtube_videos row and a makeup_looks row.
Looks stay unpublished until AR settings and products are reviewed. A re-run keeps the ids it
already gave and only refreshes the start time, so the pilot rows are never touched.
"""

import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.repositories.look_video_repository import LookVideoRepository
from app.schemas.look_video import PlannedVideo

_NUMBERED_ID = re.compile(r"^(?:VIDEO|LOOK)-(\d+)$")


@dataclass(frozen=True)
class RegistrationReport:
    planned: list[PlannedVideo]
    counts: dict[str, int]

    @property
    def new(self) -> list[PlannedVideo]:
        return [item for item in self.planned if item.is_new]


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
        title = (video.get("title") or "").strip()
        planned.append(
            PlannedVideo(
                id=row_id,
                look_id=f"LOOK-{_number(row_id):03d}",
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


async def register_look_videos(
    session: AsyncSession,
    inventory: Mapping[str, Any],
    tag_videos: Mapping[str, Mapping[str, Any]],
    write: bool,
) -> RegistrationReport:
    repository = LookVideoRepository(session)
    existing, used_ids = await repository.registered_ids()
    planned = plan_registrations(mention_only_videos(inventory), tag_videos, existing, used_ids)
    counts = await repository.register(planned, write)
    return RegistrationReport(planned, counts)

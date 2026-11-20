"""Persist official YouTube metadata for the registered idol videos.

Run after setting YOUTUBE_API_KEY: ``uv run python -m app.jobs.refresh_youtube_metadata``.
Every youtube_videos row not yet ``metadata_ready`` is refreshed; ``--all`` refreshes every row.
"""

import argparse
import asyncio
from dataclasses import dataclass

from app.core.db import dispose_engine, session_scope
from app.core.errors import UpstreamError
from app.services.idol_look_service import IdolLookService, idol_look_service_for

VIDEO_IDS = ("fDqBPI1SaWY", "S2nXySh1WuU", "mXUMB45414A")


@dataclass(frozen=True)
class RefreshSummary:
    updated: tuple[str, ...]
    unchanged: tuple[str, ...]
    failed: tuple[str, ...]


async def refresh_registered_metadata(
    service: IdolLookService, video_ids: tuple[str, ...] = VIDEO_IDS
) -> RefreshSummary:
    """Refresh every registered video even when one upstream request fails."""
    updated: list[str] = []
    unchanged: list[str] = []
    failed: list[str] = []
    for video_id in video_ids:
        try:
            was_updated = await service.refresh_metadata(video_id)
        except UpstreamError as exc:
            failed.append(video_id)
            print(f"YouTube metadata failed: {video_id} ({exc})")
            continue
        (updated if was_updated else unchanged).append(video_id)
    return RefreshSummary(tuple(updated), tuple(unchanged), tuple(failed))


async def main(refresh_all: bool) -> None:
    try:
        async with session_scope() as session:
            service = idol_look_service_for(session)
            video_ids = await service.registered_video_ids(include_ready=refresh_all)
            print(f"videos to refresh: {len(video_ids)}")
            summary = await refresh_registered_metadata(service, video_ids)
        print(
            "YouTube metadata refresh complete: "
            f"updated={len(summary.updated)}, unchanged={len(summary.unchanged)}, "
            f"failed={len(summary.failed)}"
        )
    finally:
        await dispose_engine()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--all", action="store_true", help="also refresh metadata_ready rows")
    asyncio.run(main(parser.parse_args().all))

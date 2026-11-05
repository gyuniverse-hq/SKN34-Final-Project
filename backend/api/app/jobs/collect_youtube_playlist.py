"""Collect review candidates from a public YouTube playlist using the official API.

uv run python -m app.jobs.collect_youtube_playlist PLAYLIST_ID
"""

import argparse
import asyncio
import csv
from collections import Counter
from pathlib import Path

from app.services.youtube_playlist_service import (
    PlaylistCollection,
    YoutubeCandidate,
    get_youtube_playlist_service,
)

DEFAULT_OUTPUT = Path("seed/source/youtube_candidates.csv")
FIELDNAMES = (
    "playlistId",
    "playlistItemId",
    "playlistPosition",
    "videoId",
    "youtubeUrl",
    "title",
    "channelName",
    "description",
    "thumbnailUrl",
    "publishedAt",
    "durationISO8601",
    "durationSeconds",
    "subjectName",
    "lookStyle",
    "reviewStatus",
)


def _row(candidate: YoutubeCandidate) -> dict[str, str | int]:
    return {
        "playlistId": candidate.playlist_id,
        "playlistItemId": candidate.playlist_item_id,
        "playlistPosition": candidate.playlist_position,
        "videoId": candidate.video_id,
        "youtubeUrl": candidate.youtube_url,
        "title": candidate.title,
        "channelName": candidate.channel_name,
        "description": candidate.description,
        "thumbnailUrl": candidate.thumbnail_url,
        "publishedAt": candidate.published_at,
        "durationISO8601": candidate.duration_iso8601,
        "durationSeconds": candidate.duration_seconds,
        "subjectName": candidate.subject_name,
        "lookStyle": candidate.look_style,
        "reviewStatus": candidate.review_status,
    }


def write_candidates(collection: PlaylistCollection, output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=FIELDNAMES)
        writer.writeheader()
        writer.writerows(_row(candidate) for candidate in collection.candidates)


async def collect(playlist_id: str, output: Path) -> PlaylistCollection:
    service = get_youtube_playlist_service()
    if not service.configured:
        raise RuntimeError("YOUTUBE_API_KEY is not configured")
    result = await service.collect(playlist_id)
    write_candidates(result, output)
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("playlist_id")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    result = asyncio.run(collect(args.playlist_id, args.output))
    reasons = Counter(item.reason for item in result.excluded)
    print(
        f"playlist_items={result.playlist_items} "
        f"candidates={len(result.candidates)} excluded={len(result.excluded)}"
    )
    for reason, count in sorted(reasons.items()):
        print(f"excluded[{reason}]={count}")
    for item in result.excluded:
        print(
            f"excluded_item position={item.playlist_position} "
            f"video_id={item.video_id} reason={item.reason}"
        )
    print(f"output={args.output}")


if __name__ == "__main__":
    main()

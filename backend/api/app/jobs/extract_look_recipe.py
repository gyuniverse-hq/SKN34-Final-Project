"""Draft makeup recipes from public videos and write them for team review (plan step 3).

``uv run python -m app.jobs.extract_look_recipe --video-id ID [--ids-file FILE]``

Two sources, both write to a review file as unreviewed:
- ``description`` (default): reads the official description through the YouTube Data API (needs
  YOUTUBE_API_KEY). Chapters give zone, order and start time; a style is filled only when the
  chapter names one, so most styles are left for the team. A video without chapters gets no entry.
- ``gemini``: Gemini watches the public video 3 times and votes (needs GEMINI_API_KEY).

Nothing reaches the app until a person sets ``approved`` and ``reviewer`` (and fills ``lookId``
and any style) and runs ``app.jobs.apply_look_recipe``.
"""

import argparse
import asyncio
import json
from pathlib import Path

from app.core.errors import UpstreamError
from app.schemas.look_recipe import ReviewEntry
from app.services.description_recipe_service import description_recipe_service_for_batch
from app.services.look_recipe_service import RUNS, look_recipe_service_for_batch

DEFAULT_REVIEW = Path("seed/source/look_recipe_review.json")


def load_entries(path: Path) -> dict[str, ReviewEntry]:
    if not path.exists():
        return {}
    items = json.loads(path.read_text(encoding="utf-8"))
    return {entry.video_id: entry for entry in (ReviewEntry.model_validate(i) for i in items)}


def save_entries(path: Path, entries: dict[str, ReviewEntry]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    data = [e.model_dump(mode="json") for e in entries.values()]
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


async def run(video_ids: list[str], review: Path, runs: int, source: str) -> int:
    gemini = look_recipe_service_for_batch() if source == "gemini" else None
    description = description_recipe_service_for_batch() if source == "description" else None
    if gemini is None and description is None:
        print("GEMINI_API_KEY is not set" if source == "gemini" else "YOUTUBE_API_KEY is not set")
        return 1
    entries = load_entries(review)
    failed = no_recipe = 0
    for video_id in video_ids:
        if (previous := entries.get(video_id)) and previous.approved:
            print(f"{video_id}: already approved, left as is")
            continue
        try:
            if gemini is not None:
                recipe = await gemini.extract(video_id, runs)
            else:
                recipe = await description.extract(video_id)  # type: ignore[union-attr]
        except UpstreamError as exc:
            failed += 1
            print(f"{video_id}: failed ({exc})")
            continue
        if recipe is None:
            no_recipe += 1
            continue
        entries[video_id] = ReviewEntry(
            video_id=video_id, look_id=previous.look_id if previous else None, recipe=recipe
        )
        print(f"{video_id}: {len(recipe.steps)} steps, unreviewed")
    save_entries(review, entries)
    print(f"written {len(entries)} entries; no chapters: {no_recipe}; failed: {failed}")
    return 1 if failed else 0


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--video-id", action="append", default=[])
    parser.add_argument("--ids-file", type=Path, help="one video id per line")
    parser.add_argument("--review", type=Path, default=DEFAULT_REVIEW)
    parser.add_argument("--runs", type=int, default=RUNS)
    parser.add_argument("--source", choices=("description", "gemini"), default="description")
    args = parser.parse_args()
    ids = list(args.video_id)
    if args.ids_file:
        lines = args.ids_file.read_text(encoding="utf-8").splitlines()
        ids += [line.strip() for line in lines if line.strip()]
    if not ids:
        parser.error("give --video-id or --ids-file")
    unique = list(dict.fromkeys(ids))
    raise SystemExit(asyncio.run(run(unique, args.review, args.runs, args.source)))


if __name__ == "__main__":
    main()

"""Apply approved recipes to the looks AR settings (plan step 3).

``uv run python -m app.jobs.apply_look_recipe``

Only entries with ``approved``, a ``reviewer`` and a ``lookId`` are applied, and only into a
zone setting the look already has (the color is never made up). Style ids become geometry
(highlighter, contour, eyeliner, blush, eyeshadow, lip).
"""

import argparse
import asyncio
from pathlib import Path

from app.core.db import dispose_engine, session_scope
from app.jobs.extract_look_recipe import DEFAULT_REVIEW, load_entries
from app.services.look_recipe_service import LookRecipeService


async def run(review: Path) -> int:
    entries = list(load_entries(review).values())
    service = LookRecipeService(None)  # applying never calls Gemini
    try:
        async with session_scope() as session:
            result = await service.apply_to_database(entries, session)
    finally:
        await dispose_engine()
    print(result)
    return 0


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--review", type=Path, default=DEFAULT_REVIEW)
    args = parser.parse_args()
    raise SystemExit(asyncio.run(run(args.review)))


if __name__ == "__main__":
    main()

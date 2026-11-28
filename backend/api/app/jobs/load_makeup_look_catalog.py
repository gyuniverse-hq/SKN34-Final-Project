"""Classify makeup looks from the style/celebrity curation (see makeup_look_catalog_service).

``uv run python -m app.jobs.load_makeup_look_catalog [--write]``

Without ``--write`` it only prints the plan. Conflicts with values already in the database
stop the run without writing anything.
"""

import argparse
import asyncio
import json
from collections import Counter
from pathlib import Path
from typing import Any

from app.core.db import dispose_engine, session_scope
from app.services.makeup_look_catalog_service import load_makeup_look_catalog

CATALOG_DATA = Path(__file__).resolve().parents[1] / "catalog_data"


async def run(style: list[dict[str, Any]], celebrity: list[dict[str, Any]], write: bool) -> int:
    try:
        async with session_scope() as session:
            plan = await load_makeup_look_catalog(session, style, celebrity, write)
    finally:
        await dispose_engine()
    kinds = Counter(values["look_type"] for values in plan.looks.values())
    published = sum(values["is_catalog_published"] for values in plan.looks.values())
    print(f"looks to classify: {len(plan.looks)} {dict(kinds)} (catalog published {published})")
    print(f"looks already classified: {plan.unchanged_looks}")
    print(f"unclassified looks left: {plan.unclassified}")
    print(f"payloads to fill: {len(plan.payloads)} (already filled {plan.unchanged_payloads})")
    if plan.conflicts:
        print(f"conflicts ({len(plan.conflicts)}), nothing written:")
        for conflict in plan.conflicts[:20]:
            print(f"  {conflict}")
        return 1
    print("applied" if write else "dry run (add --write to apply)")
    return 0


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--write", action="store_true")
    args = parser.parse_args()
    style = json.loads((CATALOG_DATA / "style_looks.json").read_text(encoding="utf-8"))
    celebrity = json.loads((CATALOG_DATA / "celebrity_videos.json").read_text(encoding="utf-8"))
    raise SystemExit(asyncio.run(run(style, celebrity, args.write)))


if __name__ == "__main__":
    main()

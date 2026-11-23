"""Load the merged look tags into look_video_tags.

``uv run python -m app.jobs.load_look_tags --merged <look-tag-v3-final-merged.json>
[--overrides <overrides.json>] [--write]``

Overrides settle merge conflicts: {"<youtube id>": {"<field>": ["<code>", ...]}}.
Without ``--write`` it only prints the plan. See app.services.look_tag_load_service.
"""

import argparse
import asyncio
import json
from collections import Counter
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from app.core.db import dispose_engine, session_scope
from app.services.look_tag_load_service import load_codebook, load_look_tags


async def run(
    merged: Mapping[str, Any], overrides: Mapping[str, Mapping[str, list[str]]], write: bool
) -> int:
    try:
        async with session_scope() as session:
            plan = await load_look_tags(session, merged, overrides, write)
    finally:
        await dispose_engine()
    rows = plan.rows
    print(f"tag rows: {len(rows)}; skipped: {dict(plan.skipped)}")
    axes = load_codebook().scores
    scored = Counter(axis for row in rows for axis in axes if row[axis] is not None)
    print(f"scores filled: {dict(scored)}")
    fields = sum(len(row["attributes"]) for row in rows) / max(len(rows), 1)
    print(f"attribute fields per row (avg): {fields:.1f}")
    print(f"free tags: {sum(len(r['free_tags']) for r in rows)}")
    print(f"merge status: {dict(plan.statuses)}")
    print(f"unresolved conflicts: {plan.unresolved or 'none'}")
    print(f"dropped codes: {plan.dropped_values or 'none'}")
    print("applied" if write else "dry run (add --write to apply)")
    return 1 if plan.unresolved else 0


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--merged", type=Path, required=True)
    parser.add_argument("--overrides", type=Path)
    parser.add_argument("--write", action="store_true")
    args = parser.parse_args()
    # Files are read before the event loop starts so the async job never blocks on disk.
    merged = json.loads(args.merged.read_text(encoding="utf-8"))
    overrides = json.loads(args.overrides.read_text(encoding="utf-8")) if args.overrides else {}
    raise SystemExit(asyncio.run(run(merged, overrides, args.write)))


if __name__ == "__main__":
    main()

"""Validate a reviewed serving bundle; dry-run by default. Never enables mappings."""

import argparse
import asyncio
from pathlib import Path

from app.core.db import session_scope
from app.schemas.skincare import GOALS, SkincareRequest, SkincareSnapshot
from app.services.skincare_service import recommend, skincare_service_for_session


async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("bundle", type=Path)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    snapshot = SkincareSnapshot.model_validate_json(args.bundle.read_text(encoding="utf-8"))
    for goal in GOALS:
        result = recommend(
            snapshot,
            SkincareRequest(primary_goal=goal, goal_policy_version="care-goals-v1", limit=20),
        )
        active = [m for m in snapshot.mappings if m.eligible() and m.target_concern == goal]
        count = len(
            {
                o.product.id
                for o in snapshot.options
                if o.available
                and o.identity_verified
                and any(set(m.ingredient_codes).issubset(o.ingredient_codes) for m in active)
            }
        )
        print(goal, result.coverage[0].status, "activeMappings", len(active), "products", count)
    if args.apply:
        async with session_scope() as session:
            await skincare_service_for_session(session).publish(snapshot)
    # Publishing through the service keeps jobs out of the repository layer.


if __name__ == "__main__":
    asyncio.run(main())

"""Link the products mentioned in each look video to serving catalog products.

``uv run python -m app.jobs.link_look_products [--write]``

Without ``--write`` it only prints the plan. See app.services.look_product_link_service.
"""

import argparse
import asyncio
from collections import Counter

from app.core.db import dispose_engine, session_scope
from app.services.look_product_link_service import link_look_products


async def run(write: bool) -> int:
    try:
        async with session_scope() as session:
            report = await link_look_products(session, write)
    finally:
        await dispose_engine()
    plan = report.plan
    print(f"mentions on a reviewed path: {report.mentions}")
    print(f"look products: {len(plan.rows)} (merged duplicates {plan.merged})")
    print(f"with shade: {sum(row['shade_id'] is not None for row in plan.rows)}")
    print(f"skipped zone: {dict(plan.skipped_zone.most_common())}")
    print(f"zones: {dict(Counter(row['makeup_zone'] for row in plan.rows).most_common())}")
    print(f"videos mapped: {len(report.mapped)}, no_verified_products: {len(report.unmapped)}")
    print("applied" if write else "dry run (add --write to apply)")
    return 0


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--write", action="store_true")
    raise SystemExit(asyncio.run(run(parser.parse_args().write)))


if __name__ == "__main__":
    main()

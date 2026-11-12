"""Store reviewed YouTube source-ID to app-catalog product links in local PostgreSQL."""

from __future__ import annotations

import argparse
import asyncio
import getpass
from collections import defaultdict
import os
from pathlib import Path

import asyncpg

from build_approved_non_oy_catalog import read_approved


async def run(args: argparse.Namespace) -> None:
    if args.host not in {"127.0.0.1", "localhost"}:
        raise ValueError("Only a local PostgreSQL host is supported")

    rows = read_approved(args.approved)
    source_targets: dict[str, set[str]] = defaultdict(set)
    target_sources: dict[str, set[str]] = defaultdict(set)
    evidence: dict[tuple[str, str], str | None] = {}
    for row in rows:
        for source_id in row["source_yt_product_ids"].split(";"):
            pair = (source_id, row["serving_product_id"])
            source_targets[source_id].add(row["serving_product_id"])
            target_sources[row["serving_product_id"]].add(source_id)
            evidence[pair] = row["evidence_url"] or None

    links = []
    for (source_id, serving_id), evidence_url in sorted(evidence.items()):
        if len(source_targets[source_id]) > 1:
            link_type = "split"
        elif len(target_sources[serving_id]) > 1:
            link_type = "merged"
        elif source_id == serving_id:
            link_type = "direct"
        else:
            link_type = "corrected"
        links.append((source_id, serving_id, link_type, evidence_url))

    password = os.environ.get("POSTGRES_PASSWORD") or getpass.getpass(
        "Local PostgreSQL password: "
    )
    conn = await asyncpg.connect(
        host=args.host,
        port=args.port,
        database=args.database,
        user=args.user,
        password=password,
        ssl=False,
        server_settings={"application_name": "yt_approved_catalog_link"},
    )
    try:
        required_tables = await conn.fetchval(
            """SELECT to_regclass('public.yt_catalog_product_link') IS NOT NULL
                      AND to_regclass('public.raw_yt_product') IS NOT NULL
                      AND to_regclass('public.raw_yt_product_mention') IS NOT NULL"""
        )
        if not required_tables:
            raise ValueError("Apply Alembic revision 0017 before linking catalog products")

        source_ids = sorted(source_targets)
        serving_ids = sorted(target_sources)
        async with conn.transaction(readonly=True):
            found_sources = {
                row["yt_product_id"]
                for row in await conn.fetch(
                    "SELECT yt_product_id FROM public.raw_yt_product WHERE yt_product_id = ANY($1::text[])",
                    source_ids,
                )
            }
            found_products = {
                row["id"]
                for row in await conn.fetch(
                    "SELECT id FROM public.products WHERE id = ANY($1::text[])", serving_ids
                )
            }
            confirmed_oy = {
                row["yt_product_id"]
                for row in await conn.fetch(
                    """SELECT yt_product_id FROM public.yt_oy_product_match
                       WHERE yt_product_id = ANY($1::text[]) AND decision_status = 'confirmed'""",
                    source_ids,
                )
            }
            existing = await conn.fetch(
                """SELECT source_yt_product_id, serving_product_id, link_type, evidence_url
                   FROM public.yt_catalog_product_link
                   WHERE source_yt_product_id = ANY($1::text[])""",
                source_ids,
            )

        if missing := sorted(set(source_ids) - found_sources):
            raise ValueError(f"Missing raw YouTube source IDs: {missing}")
        if missing := sorted(set(serving_ids) - found_products):
            raise ValueError(f"Missing serving product IDs: {missing}")
        if confirmed_oy:
            raise ValueError(
                "Refusing non-Olive-Young links for confirmed Olive Young products: "
                f"{sorted(confirmed_oy)}"
            )

        expected = {(source, serving): (kind, url) for source, serving, kind, url in links}
        actual = {
            (row["source_yt_product_id"], row["serving_product_id"]): (
                row["link_type"],
                row["evidence_url"],
            )
            for row in existing
        }
        conflicts = {
            pair: (actual.get(pair), expected.get(pair))
            for pair in set(actual) & set(expected)
            if actual.get(pair) != expected.get(pair)
        }
        unexpected = sorted(set(actual) - set(expected))
        if conflicts or unexpected:
            raise ValueError(
                "Existing curated links conflict with approved CSV: "
                f"conflicting={conflicts}; unexpected={unexpected}"
            )

        mention_count = await conn.fetchval(
            "SELECT COUNT(*) FROM public.raw_yt_product_mention WHERE yt_product_id = ANY($1::text[])",
            source_ids,
        )
        type_counts = {kind: sum(link[2] == kind for link in links) for kind in (
            "direct", "merged", "split", "corrected"
        )}
        new_count = len(set(expected) - set(actual))
        print(
            f"Approved associations: {len(links)}; source products: {len(source_ids)}; "
            f"serving products: {len(serving_ids)}"
        )
        print(f"Association types: {type_counts}; matching video mentions: {mention_count}")
        print(f"Existing identical links: {len(actual)}; links to add: {new_count}")
        if not args.apply:
            print("Preflight passed; no database rows were written")
            return

        async with conn.transaction():
            await conn.executemany(
                """INSERT INTO public.yt_catalog_product_link
                   (source_yt_product_id, serving_product_id, link_type, evidence_url)
                   VALUES ($1, $2, $3, $4)
                   ON CONFLICT (source_yt_product_id, serving_product_id) DO NOTHING""",
                links,
            )
        print(f"Committed {new_count} reviewed source-to-serving links")
    finally:
        await conn.close()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--approved", type=Path, default=Path(__file__).with_name("approved_non_oy_catalog.csv")
    )
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=15432)
    parser.add_argument("--database", default="vishue_db")
    parser.add_argument("--user", default="vishue")
    parser.add_argument("--apply", action="store_true")
    asyncio.run(run(parser.parse_args()))


if __name__ == "__main__":
    main()

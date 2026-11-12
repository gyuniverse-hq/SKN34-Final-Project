"""Link one reviewed YouTube source product to its split serving products."""

from __future__ import annotations

import argparse
import asyncio
import csv
import getpass
import os
from pathlib import Path

import asyncpg


def read_links(path: Path) -> list[tuple[str, str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as stream:
        reader = csv.DictReader(stream)
        expected = {"source_yt_product_id", "serving_product_id", "product_url"}
        if not expected.issubset(reader.fieldnames or ()):
            raise ValueError(f"Link CSV must include: {sorted(expected)}")
        rows = [
            (
                (row["source_yt_product_id"] or "").strip(),
                (row["serving_product_id"] or "").strip(),
                (row["product_url"] or "").strip(),
            )
            for row in reader
        ]
    if not rows or len({(source, target) for source, target, _ in rows}) != len(rows):
        raise ValueError("Link CSV is empty or contains duplicate source/target pairs")
    if any(not source.startswith("yt-") or not target.startswith("yt-") for source, target, _ in rows):
        raise ValueError("YouTube source and serving IDs must start with 'yt-'")
    if any(not url.startswith("https://www.glowpick.com/products/") for _, _, url in rows):
        raise ValueError("Evidence URLs must be Glowpick product pages")
    return rows


async def run(args: argparse.Namespace) -> None:
    if args.host not in {"127.0.0.1", "localhost"}:
        raise ValueError("Only a local PostgreSQL host is supported")
    rows = read_links(args.links)
    source_ids = sorted({source for source, _, _ in rows})
    serving_ids = sorted({target for _, target, _ in rows})
    password = os.environ.get("POSTGRES_PASSWORD") or getpass.getpass("Local PostgreSQL password: ")
    conn = await asyncpg.connect(
        host=args.host,
        port=args.port,
        database=args.database,
        user=args.user,
        password=password,
        ssl=False,
        server_settings={"application_name": "yt_split_catalog_link"},
    )
    try:
        if not await conn.fetchval("SELECT to_regclass('public.yt_catalog_product_link') IS NOT NULL"):
            raise ValueError("Apply Alembic revision 0017 or newer before linking products")
        async with conn.transaction(readonly=True):
            found_sources = {
                row["yt_product_id"] for row in await conn.fetch(
                    "SELECT yt_product_id FROM public.raw_yt_product WHERE yt_product_id = ANY($1::text[])", source_ids
                )
            }
            found_products = {
                row["id"] for row in await conn.fetch(
                    "SELECT id FROM public.products WHERE id = ANY($1::text[])", serving_ids
                )
            }
            confirmed_oy = {
                row["yt_product_id"] for row in await conn.fetch(
                    "SELECT yt_product_id FROM public.yt_oy_product_match WHERE yt_product_id = ANY($1::text[]) AND decision_status='confirmed'", source_ids
                )
            }
            existing_rows = await conn.fetch(
                "SELECT source_yt_product_id, serving_product_id, link_type, evidence_url FROM public.yt_catalog_product_link WHERE source_yt_product_id = ANY($1::text[])",
                source_ids,
            )
        if set(source_ids) != found_sources:
            raise ValueError(f"Source products missing from raw table: {sorted(set(source_ids)-found_sources)}")
        if set(serving_ids) != found_products:
            raise ValueError(f"Serving products missing from products: {sorted(set(serving_ids)-found_products)}")
        if confirmed_oy:
            raise ValueError(f"Refusing split link for Olive Young-confirmed source: {sorted(confirmed_oy)}")
        expected = {(source, target): url for source, target, url in rows}
        actual = {(r["source_yt_product_id"], r["serving_product_id"]): (r["link_type"], r["evidence_url"]) for r in existing_rows}
        conflicts = [pair for pair in actual if pair in expected and actual[pair] != ("split", expected[pair])]
        unexpected = [pair for pair in actual if pair not in expected]
        if conflicts or unexpected:
            raise ValueError(f"Existing links conflict; conflicts={conflicts}; unexpected={unexpected}")
        add = [(source, target, "split", url) for source, target, url in rows if (source, target) not in actual]
        mentions = await conn.fetchval(
            "SELECT COUNT(*) FROM public.raw_yt_product_mention WHERE yt_product_id = ANY($1::text[])", source_ids
        )
        print(f"Split links: {len(rows)}; source products: {len(source_ids)}; serving products: {len(serving_ids)}; video mentions: {mentions}; links to add: {len(add)}")
        if not args.apply:
            print("Preflight passed; no database rows were written")
            return
        async with conn.transaction():
            await conn.executemany(
                "INSERT INTO public.yt_catalog_product_link (source_yt_product_id, serving_product_id, link_type, evidence_url) VALUES ($1,$2,$3,$4) ON CONFLICT (source_yt_product_id,serving_product_id) DO NOTHING",
                add,
            )
        print(f"Committed {len(add)} split source-to-serving links")
    finally:
        await conn.close()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--links", type=Path, default=Path(__file__).with_name("youtube-etude-contour-brush-split.csv"))
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=15432)
    parser.add_argument("--database", default="vishue_db")
    parser.add_argument("--user", default="vishue")
    parser.add_argument("--apply", action="store_true")
    asyncio.run(run(parser.parse_args()))


if __name__ == "__main__":
    main()

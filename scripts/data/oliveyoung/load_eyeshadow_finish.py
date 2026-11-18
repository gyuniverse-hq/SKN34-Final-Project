"""Load the reviewed eyeshadow finish of each option into raw_oy_option_finish.

Run after alembic revision 0026. Without --apply it only checks the CSV against the database
and prints what would be added. Rows already loaded (same option and review time) are skipped,
so running it twice adds nothing.
"""

from __future__ import annotations

import argparse
import asyncio
import csv
import getpass
import os
from collections import Counter
from datetime import datetime
from pathlib import Path

import asyncpg

HERE = Path(__file__).resolve().parent
DEFAULT_CSV = HERE / "eyeshadow_finish_review_20261118" / "option_finishes.csv"
COLUMNS = [
    "option_id",
    "goods_no",
    "option_name",
    "finish_code",
    "judge_step",
    "judge_reason",
    "collected_at",
]
JUDGE_STEPS = {"manual_image", "manual_detail_page", "manual_bulk"}


def read_rows(path: Path) -> list[dict]:
    with path.open(encoding="utf-8", newline="") as file:
        reader = csv.DictReader(file)
        if reader.fieldnames != COLUMNS:
            raise SystemExit(f"Unexpected columns: {reader.fieldnames}")
        rows = list(reader)
    ids = Counter(row["option_id"] for row in rows)
    duplicates = [option_id for option_id, count in ids.items() if count > 1]
    if duplicates:
        raise SystemExit(f"Duplicate option_id in CSV: {duplicates[:5]}")
    for row in rows:
        if row["judge_step"] not in JUDGE_STEPS:
            raise SystemExit(f"Unknown judge_step {row['judge_step']!r}: {row['option_id']}")
        row["collected_at"] = datetime.strptime(row["collected_at"], "%Y-%m-%d %H:%M:%S.%f")
    return rows


async def run(args: argparse.Namespace) -> None:
    rows = read_rows(args.csv)
    password = os.environ.get("POSTGRES_PASSWORD") or getpass.getpass("Local PostgreSQL password: ")
    conn = await asyncpg.connect(
        host=args.host,
        port=args.port,
        database=args.database,
        user=args.user,
        password=password,
        server_settings={"application_name": "oy_eyeshadow_finish_load"},
    )
    try:
        if not await conn.fetchval("SELECT to_regclass('public.raw_oy_option_finish')"):
            raise SystemExit("raw_oy_option_finish is missing; run alembic upgrade 0026 first")
        codes = {
            r["finish_code"] for r in await conn.fetch("SELECT finish_code FROM raw_oy_finish_type")
        }
        unknown_codes = {row["finish_code"] for row in rows} - codes
        if unknown_codes:
            raise SystemExit(f"finish_code not in raw_oy_finish_type: {sorted(unknown_codes)}")
        ids = [row["option_id"] for row in rows]
        found = {
            r["option_id"]
            for r in await conn.fetch(
                "SELECT option_id FROM raw_oy_product_option WHERE option_id = ANY($1::text[])", ids
            )
        }
        missing = [option_id for option_id in ids if option_id not in found]
        if missing:
            raise SystemExit(
                f"{len(missing)} option_id not in raw_oy_product_option: {missing[:5]}"
            )
        loaded = {
            (r["option_id"], r["collected_at"])
            for r in await conn.fetch(
                "SELECT option_id, collected_at FROM raw_oy_option_finish "
                "WHERE option_id = ANY($1::text[])",
                ids,
            )
        }
        new_rows = [row for row in rows if (row["option_id"], row["collected_at"]) not in loaded]
        print(f"CSV rows: {len(rows):,}; already loaded: {len(rows) - len(new_rows):,}")
        for code, count in sorted(Counter(row["finish_code"] for row in rows).items()):
            print(f"  {code}: {count:,}")
        print(f"Rows to add: {len(new_rows):,}")
        if not args.apply:
            print("Preview only; no rows were written")
            return
        async with conn.transaction():
            await conn.executemany(
                "INSERT INTO raw_oy_option_finish "
                "(option_id, collected_at, finish_code, judge_step, judge_reason, source_file) "
                "VALUES ($1, $2, $3, $4, $5, $6) "
                "ON CONFLICT (option_id, collected_at) DO NOTHING",
                [
                    (
                        row["option_id"],
                        row["collected_at"],
                        row["finish_code"],
                        row["judge_step"],
                        row["judge_reason"] or None,
                        f"{args.csv.parent.name}/{args.csv.name}",
                    )
                    for row in new_rows
                ],
            )
            stored = await conn.fetchval(
                "SELECT COUNT(DISTINCT option_id) FROM raw_oy_option_finish "
                "WHERE option_id = ANY($1::text[])",
                ids,
            )
            if stored != len(rows):
                raise SystemExit(
                    f"Options with a finish: {stored}, expected {len(rows)}; rolled back"
                )
        print(f"Added {len(new_rows):,} rows; options with a finish: {stored:,}")
    finally:
        await conn.close()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=15432)
    parser.add_argument("--database", default="vishue_db")
    parser.add_argument("--user", default="vishue")
    parser.add_argument("--csv", type=Path, default=DEFAULT_CSV)
    parser.add_argument("--apply", action="store_true")
    asyncio.run(run(parser.parse_args()))


if __name__ == "__main__":
    main()

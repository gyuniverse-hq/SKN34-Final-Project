"""Load the existing Olive Young v29 makeup CSV snapshot into raw_oy_* tables.

Run this from backend/api's uv environment after applying Alembic migrations.
The migration seeds raw_oy_texture_type, so texture_type.csv is deliberately skipped.
Shared Supabase imports require an explicit target and execute flag.
"""

from __future__ import annotations

import argparse
import asyncio
import csv
import getpass
import os
import ssl
from pathlib import Path

import asyncpg

# Parent tables precede tables that reference them by foreign key.
TABLES = (
    "crawl_run",
    "brand",
    "supplier",
    "category",
    "survey_question",
    "survey_answer",
    "ingredient",
    "product",
    "product_notice",
    "product_option",
    "product_texture",
    "image",
    "image_applied",
    "price_snapshot",
    "option_color",
    "review_summary",
    "review_ai_feature",
    "review_survey",
    "option_ingredient",
    "crawl_log",
)

SERIAL_COLUMNS = (
    ("crawl_run", "run_id"),
    ("crawl_log", "log_id"),
    ("ingredient", "ingredient_id"),
    ("image", "image_id"),
    ("price_snapshot", "snapshot_id"),
    ("review_summary", "summary_id"),
)

# v29 did not export the nullable option delisting field added to the DB model.
ALLOWED_MISSING_COLUMNS = {"product_option": {"delisted_at"}}


def inspect_csv(path: Path) -> tuple[list[str], int]:
    with path.open("r", encoding="utf-8-sig", newline="") as source:
        reader = csv.reader(source)
        try:
            columns = next(reader)
        except StopIteration as exc:
            raise ValueError(f"Empty CSV: {path}") from exc
        if not columns or len(columns) != len(set(columns)):
            raise ValueError(f"Missing or duplicated header columns: {path}")
        count = 0
        for record in reader:
            count += 1
            if len(record) != len(columns):
                raise ValueError(
                    f"{path.name}: record {count} has {len(record)} fields; "
                    f"header has {len(columns)}"
                )
    return columns, count


async def load(args: argparse.Namespace) -> None:
    if args.target == "shared":
        if not args.project_ref:
            raise ValueError("--project-ref is required for a shared import")
        if not args.host.endswith(".pooler.supabase.com"):
            raise ValueError("Shared imports must use the Supabase session pooler host")
        if args.port != 5432 or args.database != "postgres":
            raise ValueError(
                "Shared imports require the session pooler port and database"
            )
        if args.user != f"postgres.{args.project_ref}":
            raise ValueError("Shared database user does not match --project-ref")
        if not args.preflight and not args.execute_shared:
            raise ValueError(
                "Run --preflight first, then use --execute-shared to import"
            )
    elif args.execute_shared:
        raise ValueError("--execute-shared is only valid with --target shared")
    elif args.ssl_ca_file:
        raise ValueError("--ssl-ca-file is only valid with --target shared")

    ssl_config: bool | ssl.SSLContext = False
    if args.target == "shared":
        if args.ssl_ca_file:
            ca_file = Path(args.ssl_ca_file).resolve()
            if not ca_file.is_file():
                raise ValueError(f"SSL CA certificate is missing: {ca_file}")
            ssl_config = ssl.create_default_context(
                purpose=ssl.Purpose.SERVER_AUTH,
                cafile=str(ca_file),
            )
        else:
            ssl_config = True

    input_dir = Path(args.input_dir).resolve()
    if not input_dir.is_dir():
        raise ValueError(f"Input directory does not exist: {input_dir}")

    files: dict[str, tuple[Path, list[str], int]] = {}
    for short_name in TABLES:
        path = input_dir / f"{short_name}.csv"
        if not path.is_file():
            raise ValueError(f"Required CSV is missing: {path}")
        columns, rows = inspect_csv(path)
        files[short_name] = (path, columns, rows)
        print(f"Checked {path.name}: {rows:,} data rows", flush=True)

    if args.target == "shared":
        password = getpass.getpass("Shared PostgreSQL password: ")
    else:
        password = os.environ.get("POSTGRES_PASSWORD") or getpass.getpass(
            "Local PostgreSQL password: "
        )
    connection = await asyncpg.connect(
        host=args.host,
        port=args.port,
        database=args.database,
        user=args.user,
        password=password,
        ssl=ssl_config,
        server_settings={"application_name": "oliveyoung_v29_initial_load"},
    )
    try:
        database = await connection.fetchval("SELECT current_database()")
        print(f"Connected to {args.host}:{args.port}/{database}", flush=True)

        for short_name in TABLES:
            table_name = f"raw_oy_{short_name}"
            path, columns, _ = files[short_name]
            db_columns = {
                row["column_name"]
                for row in await connection.fetch(
                    """SELECT column_name FROM information_schema.columns
                       WHERE table_schema = 'public' AND table_name = $1""",
                    table_name,
                )
            }
            if not db_columns:
                raise ValueError(f"Database table is missing: public.{table_name}")
            unexpected = set(columns) - db_columns
            missing = db_columns - set(columns)
            allowed = ALLOWED_MISSING_COLUMNS.get(short_name, set())
            if unexpected or missing != allowed:
                raise ValueError(
                    f"{path.name} vs {table_name}: "
                    f"unexpected={sorted(unexpected)}, missing={sorted(missing)}"
                )
            existing = await connection.fetchval(
                f"SELECT EXISTS (SELECT 1 FROM public.{table_name} LIMIT 1)"
            )
            if existing:
                raise ValueError(
                    f"public.{table_name} already contains data; "
                    "inspect the previous load before rerunning"
                )

        texture_codes = await connection.fetchval(
            "SELECT COUNT(*) FROM public.raw_oy_texture_type"
        )
        if texture_codes != 7:
            raise ValueError(
                "raw_oy_texture_type must contain the 7 migration seed rows; "
                f"found {texture_codes}"
            )

        if args.preflight:
            print("Preflight passed; no rows were written", flush=True)
            return

        print("Starting one transaction for all 20 CSV files", flush=True)
        async with connection.transaction():
            for short_name in TABLES:
                path, columns, expected_rows = files[short_name]
                table_name = f"raw_oy_{short_name}"
                # PostgreSQL maps fields by the CSV header order via columns=.
                # In particular, product_option.csv omits nullable delisted_at.
                status = await connection.copy_to_table(
                    table_name,
                    schema_name="public",
                    source=path,
                    columns=columns,
                    format="csv",
                    header=True,
                    encoding="UTF8",
                )
                imported_rows = int(status.rsplit(" ", 1)[-1])
                if imported_rows != expected_rows:
                    raise ValueError(
                        f"{path.name}: CSV has {expected_rows} rows, "
                        f"but PostgreSQL copied {imported_rows}"
                    )
                print(f"Loaded {table_name}: {imported_rows:,} rows", flush=True)

            # Explicit IDs in CSV do not advance PostgreSQL's serial sequences.
            for short_name, column in SERIAL_COLUMNS:
                table_name = f"raw_oy_{short_name}"
                sequence = await connection.fetchval(
                    "SELECT pg_get_serial_sequence($1, $2)",
                    f"public.{table_name}",
                    column,
                )
                if sequence is not None:
                    maximum = await connection.fetchval(
                        f"SELECT MAX({column}) FROM public.{table_name}"
                    )
                    if maximum is not None:
                        await connection.fetchval(
                            "SELECT setval($1::regclass, $2, true)",
                            sequence,
                            maximum,
                        )

        print("Committed all 20 CSV files successfully", flush=True)
    finally:
        await connection.close()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input-dir", required=True)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=15432)
    parser.add_argument("--database", default="vishue")
    parser.add_argument("--user", default="vishue")
    parser.add_argument("--target", choices=("local", "shared"), default="local")
    parser.add_argument(
        "--project-ref", help="Supabase project ref, required for shared"
    )
    parser.add_argument(
        "--preflight", action="store_true", help="Check without writing rows"
    )
    parser.add_argument(
        "--execute-shared", action="store_true", help="Allow shared DB import"
    )
    parser.add_argument(
        "--ssl-ca-file", help="Supabase CA certificate file for TLS verification"
    )
    asyncio.run(load(parser.parse_args()))


if __name__ == "__main__":
    main()

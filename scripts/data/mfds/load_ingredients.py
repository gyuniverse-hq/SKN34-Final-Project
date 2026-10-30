"""Load a complete MFDS ingredient JSONL snapshot into raw_mfds_ingredient.

The source fields are kept verbatim. Only the matching key normalizes Unicode and
whitespace. A complete snapshot is required before any database write.
"""

from __future__ import annotations

import argparse
import asyncio
import getpass
import hashlib
import json
import os
import ssl
import unicodedata
from pathlib import Path

import asyncpg

SOURCE_FIELDS = frozenset(
    {"INGR_KOR_NAME", "INGR_ENG_NAME", "CAS_NO", "ORIGIN_MAJOR_KOR_NAME", "INGR_SYNONYM"}
)
STAGE_COLUMNS = (
    "name_key",
    "name_ko",
    "name_en",
    "cas_no_raw",
    "origin_ko_raw",
    "synonym_raw",
    "source_payload_json",
    "source_hash",
)


def name_key(name: str) -> str:
    """Conservatively normalize whitespace; keep chemical punctuation and digits."""
    return " ".join(unicodedata.normalize("NFKC", name).split())


def read_snapshot(path: Path) -> tuple[list[tuple[str | None, ...]], str]:
    path = path.resolve()
    metadata_path = path.with_name(path.name + ".meta.json")
    if not path.is_file() or not metadata_path.is_file():
        raise ValueError(f"Snapshot or metadata is missing: {path}")
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    if metadata.get("source") != "MFDS cosmetic ingredient API":
        raise ValueError("Metadata does not identify the MFDS ingredient API")
    if metadata.get("complete") is not True:
        raise ValueError("Snapshot is incomplete; a one-page sample cannot be loaded")
    reported_count = metadata.get("total_count_reported")
    if not isinstance(reported_count, int) or reported_count < 1:
        raise ValueError("Metadata has no valid total_count_reported")
    if metadata.get("rows_saved") != reported_count:
        raise ValueError("Metadata rows_saved does not match total_count_reported")
    if set(metadata.get("fields_seen", [])) != SOURCE_FIELDS:
        raise ValueError("Snapshot fields differ from the five expected API fields")

    digest = hashlib.sha256()
    rows: list[tuple[str | None, ...]] = []
    seen_keys: set[str] = set()
    with path.open("rb") as source:
        for line_number, raw_line in enumerate(source, 1):
            digest.update(raw_line)
            try:
                record = json.loads(raw_line)
            except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                raise ValueError(f"Invalid JSON on line {line_number}") from exc
            if not isinstance(record, dict) or set(record) != SOURCE_FIELDS:
                raise ValueError(f"Unexpected fields on line {line_number}")
            if not all(value is None or isinstance(value, str) for value in record.values()):
                raise ValueError(f"Non-text value on line {line_number}")
            if any("■" in value for value in record.values() if isinstance(value, str)):
                raise ValueError(f"Square bullet requires review on line {line_number}")
            source_name = record["INGR_KOR_NAME"]
            if not isinstance(source_name, str) or not source_name.strip():
                raise ValueError(f"Korean ingredient name is missing on line {line_number}")
            key = name_key(source_name)
            if key in seen_keys:
                raise ValueError(f"Duplicate normalized Korean name on line {line_number}")
            seen_keys.add(key)
            payload = json.dumps(record, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
            source_hash = hashlib.sha256(payload.encode("utf-8")).hexdigest()
            rows.append(
                (
                    key,
                    source_name,
                    record["INGR_ENG_NAME"],
                    record["CAS_NO"],
                    record["ORIGIN_MAJOR_KOR_NAME"],
                    record["INGR_SYNONYM"],
                    payload,
                    source_hash,
                )
            )
    if len(rows) != reported_count:
        raise ValueError(f"Snapshot has {len(rows)} rows; metadata reports {reported_count}")
    return rows, digest.hexdigest()


async def load(args: argparse.Namespace) -> None:
    rows, snapshot_hash = read_snapshot(args.input)
    print(f"Validated {len(rows):,} source records; SHA-256 {snapshot_hash}", flush=True)
    if args.validate_only:
        print("Validation passed; no database connection or write", flush=True)
        return

    if args.target == "shared":
        if not args.project_ref or args.user != f"postgres.{args.project_ref}":
            raise ValueError("Shared database user and --project-ref must match")
        if not args.host.endswith(".pooler.supabase.com"):
            raise ValueError("Shared imports require a Supabase session pooler host")
        if args.port != 5432 or args.database != "postgres":
            raise ValueError("Shared imports require port 5432 and database postgres")
        if not args.ssl_ca_file or not args.ssl_ca_file.is_file():
            raise ValueError("Shared imports require an existing --ssl-ca-file")
        if not args.preflight and not args.execute_shared:
            raise ValueError("Use --preflight first, then --execute-shared to write")
        ssl_config: ssl.SSLContext | bool = ssl.create_default_context(
            cafile=str(args.ssl_ca_file.resolve())
        )
        password = getpass.getpass("Shared PostgreSQL password: ")
    else:
        if args.execute_shared or args.project_ref or args.ssl_ca_file:
            raise ValueError("Shared-only options cannot be used with --target local")
        ssl_config = False
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
        server_settings={"application_name": "mfds_ingredient_snapshot_load"},
    )
    try:
        database = await connection.fetchval("SELECT current_database()")
        table = await connection.fetchval("SELECT to_regclass('public.raw_mfds_ingredient')")
        if table is None:
            raise ValueError("public.raw_mfds_ingredient is missing; apply Alembic revision 0006")
        current_before = await connection.fetchval(
            "SELECT COUNT(*) FROM public.raw_mfds_ingredient WHERE is_current"
        )
        print(
            f"Connected to {args.host}:{args.port}/{database}; "
            f"current ingredient rows before load: {current_before:,}",
            flush=True,
        )
        if args.preflight:
            print("Preflight passed; no rows were written", flush=True)
            return

        async with connection.transaction():
            await connection.execute(
                """CREATE TEMP TABLE mfds_ingredient_stage (
                     name_key text PRIMARY KEY,
                     name_ko text NOT NULL,
                     name_en text,
                     cas_no_raw text,
                     origin_ko_raw text,
                     synonym_raw text,
                     source_payload_json text NOT NULL,
                     source_hash varchar(64) NOT NULL
                   ) ON COMMIT DROP"""
            )
            await connection.copy_records_to_table(
                "mfds_ingredient_stage", records=rows, columns=STAGE_COLUMNS
            )
            staged = await connection.fetchval("SELECT COUNT(*) FROM mfds_ingredient_stage")
            if staged != len(rows):
                raise ValueError(f"Staged {staged} rows, expected {len(rows)}")
            await connection.execute(
                """INSERT INTO public.raw_mfds_ingredient AS target (
                     name_key, name_ko, name_en, cas_no_raw, origin_ko_raw, synonym_raw,
                     source_payload, source_hash, first_seen_at, last_seen_at, is_current
                   )
                   SELECT name_key, name_ko, name_en, cas_no_raw, origin_ko_raw, synonym_raw,
                          source_payload_json::jsonb, source_hash, now(), now(), true
                   FROM mfds_ingredient_stage
                   WHERE true
                   ON CONFLICT (name_key) DO UPDATE SET
                     name_ko = EXCLUDED.name_ko,
                     name_en = EXCLUDED.name_en,
                     cas_no_raw = EXCLUDED.cas_no_raw,
                     origin_ko_raw = EXCLUDED.origin_ko_raw,
                     synonym_raw = EXCLUDED.synonym_raw,
                     source_payload = EXCLUDED.source_payload,
                     source_hash = EXCLUDED.source_hash,
                     last_seen_at = EXCLUDED.last_seen_at,
                     is_current = true"""
            )
            deactivated = await connection.execute(
                """UPDATE public.raw_mfds_ingredient AS target
                   SET is_current = false
                   WHERE target.is_current
                     AND NOT EXISTS (
                       SELECT 1 FROM mfds_ingredient_stage AS stage
                       WHERE stage.name_key = target.name_key
                     )"""
            )
            current_after = await connection.fetchval(
                "SELECT COUNT(*) FROM public.raw_mfds_ingredient WHERE is_current"
            )
            if current_after != len(rows):
                raise ValueError(f"Current rows after load: {current_after}; expected {len(rows)}")
        print(
            f"Committed {current_after:,} current ingredients; {deactivated} marked inactive",
            flush=True,
        )
    finally:
        await connection.close()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--validate-only", action="store_true")
    parser.add_argument("--target", choices=("local", "shared"), default="local")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=15432)
    parser.add_argument("--database", default="vishue")
    parser.add_argument("--user", default="vishue")
    parser.add_argument("--project-ref")
    parser.add_argument("--ssl-ca-file", type=Path)
    parser.add_argument("--preflight", action="store_true")
    parser.add_argument("--execute-shared", action="store_true")
    args = parser.parse_args()
    if args.validate_only:
        rows, snapshot_hash = read_snapshot(args.input)
        print(f"Validated {len(rows):,} source records; SHA-256 {snapshot_hash}")
        print("Validation passed; no database connection or write")
        return
    asyncio.run(load(args))


if __name__ == "__main__":
    main()

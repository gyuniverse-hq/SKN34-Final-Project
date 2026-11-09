"""Import the collected CosIng CSVs into empty CosIng tables (develop + 0018).

Set DATABASE_URL to a local PostgreSQL URL. Run with --input-dir pointing to
the collection directory; add --apply to write. Existing rows are never
overwritten. A fresh database can reproduce the import using the same CSVs.
"""

import argparse
import asyncio
import csv
import json
import os
from collections import Counter
from datetime import datetime
from pathlib import Path
from urllib.parse import urlsplit

import asyncpg

CONCERNS = {
    "수분": "dryness",
    "유분": "oiliness",
    "민감진정 케어": "sensitivity",
    "톤잡티 케어": "pigmentation",
    "주름 케어": "wrinkles",
    "트러블 케어": "blemish",
    "모공 케어": "pores",
}
STATUSES = {
    "accepted",
    "accepted_no_functions",
    "missing_english_name",
    "multiple_candidates",
    "no_results",
    "incomplete_response",
    "name_mismatch",
    "wrong_source",
    "missing_or_multiple_substance_id",
}
TABLES = (
    "ingredient_function",
    "function_concern",
    "cosing_ingredient_lookup",
    "cosing_function",
)


def read_csv(path):
    with path.open(encoding="utf-8-sig", newline="") as file:
        return list(csv.DictReader(file))


def read_inputs(directory):
    tags = read_csv(directory / "cosing_function_tags.csv")
    ingredients = read_csv(directory / "cosing_ingredients.csv")
    names = [row["functionName"] for row in tags]
    if (
        not names
        or any(not name.strip() for name in names)
        or len(set(names)) != len(names)
    ):
        raise ValueError("Function names must be nonempty and unique")
    tag_set = set(names)
    concern_links = []
    for tag in tags:
        for label, concern in CONCERNS.items():
            value = tag[label]
            if value not in ("0", "1"):
                raise ValueError(f"Invalid category value for {tag['functionName']}")
            if value == "1":
                concern_links.append((tag["functionName"], concern))

    lookup = []
    links = []
    snapshot = []
    seen_ids = set()
    counts = Counter()
    for row in ingredients:
        ingredient_id = int(row["ingredient_id"])
        if ingredient_id in seen_ids:
            raise ValueError(f"Duplicate ingredient ID {ingredient_id}")
        seen_ids.add(ingredient_id)
        status = row["status"]
        if status not in STATUSES:
            raise ValueError(f"Unexpected status {status!r} for {ingredient_id}")
        method = row["method"] or None
        if method not in (None, "exact", "normalized"):
            raise ValueError(f"Unexpected matching method for {ingredient_id}")
        functions = json.loads(row["function_names"]) if row["function_names"] else []
        if not isinstance(functions, list) or not all(
            isinstance(x, str) for x in functions
        ):
            raise ValueError(f"Invalid functions for {ingredient_id}")
        if len(set(functions)) != len(functions) or not set(functions) <= tag_set:
            raise ValueError(f"Duplicate or unknown function for {ingredient_id}")
        if (status == "accepted") != bool(functions):
            raise ValueError(f"Status and function list disagree for {ingredient_id}")
        if status in ("accepted", "accepted_no_functions") and (
            not row["substance_id"]
            or method not in ("exact", "normalized")
            or row["response_count"] != "1"
            or row["http_status"] != "200"
        ):
            raise ValueError(
                f"Incomplete accepted match provenance for {ingredient_id}"
            )
        returned_inci = (
            json.loads(row["returned_inci"]) if row["returned_inci"] else None
        )
        cas = json.loads(row["cosing_cas"]) if row["cosing_cas"] else None
        if any(
            value is not None
            and (
                not isinstance(value, list)
                or not all(isinstance(x, str) for x in value)
            )
            for value in (returned_inci, cas)
        ):
            raise ValueError(f"Invalid returned names or CAS for {ingredient_id}")
        collected = (
            datetime.fromisoformat(row["updated_at"]) if row["updated_at"] else None
        )
        if collected and collected.utcoffset() is None:
            raise ValueError(f"Timestamp lacks timezone for {ingredient_id}")
        lookup.append(
            (
                ingredient_id,
                status,
                method,
                row["query_name"] or None,
                int(row["http_status"]) if row["http_status"] else None,
                int(row["response_count"]) if row["response_count"] else None,
                json.dumps(returned_inci, ensure_ascii=False)
                if returned_inci is not None
                else None,
                json.dumps(cas, ensure_ascii=False) if cas is not None else None,
                row["substance_id"] or None,
                row["detail"] or None,
                collected,
            )
        )
        snapshot.append(
            (ingredient_id, row["name_ko"], row["input_inci"], row["mfds_cas"])
        )
        links.extend((ingredient_id, tag) for tag in functions)
        counts.update(functions)
    for row in tags:
        if int(row["ingredient_count"]) != counts[row["functionName"]]:
            raise ValueError(f"Function count mismatch: {row['functionName']}")
    if not snapshot:
        raise ValueError("Empty input")
    return names, concern_links, lookup, links, snapshot


async def run(args):
    names, concerns, lookup, links, snapshot = read_inputs(args.input_dir)
    url = os.environ.get("DATABASE_URL", "").replace(
        "postgresql+asyncpg://", "postgresql://", 1
    )
    if urlsplit(url).hostname not in {"localhost", "127.0.0.1", "::1"}:
        raise ValueError("DATABASE_URL must point to a local PostgreSQL server")
    conn = await asyncpg.connect(url, timeout=10)
    try:
        async with conn.transaction(isolation="repeatable_read"):
            await conn.execute(
                "CREATE TEMP TABLE cosing_snapshot_check (ingredient_id bigint, name_ko text, name_en text, cas text) ON COMMIT DROP"
            )
            await conn.copy_records_to_table(
                "cosing_snapshot_check",
                records=snapshot,
                columns=("ingredient_id", "name_ko", "name_en", "cas"),
            )
            mismatches = await conn.fetchval("""SELECT count(*) FROM cosing_snapshot_check s
                LEFT JOIN raw_mfds_ingredient f USING (ingredient_id)
                WHERE f.ingredient_id IS NULL OR NOT f.is_current
                   OR f.name_ko IS DISTINCT FROM s.name_ko
                   OR COALESCE(f.name_en, '') <> s.name_en
                   OR COALESCE(f.cas_no_raw, '') <> s.cas""")
            if mismatches:
                raise ValueError(
                    f"{mismatches} source rows differ from local MFDS records; import aborted"
                )
            current = await conn.fetchval(
                "SELECT count(*) FROM raw_mfds_ingredient WHERE is_current"
            )
            if current != len(snapshot):
                raise ValueError(
                    "The local MFDS ingredient set differs from the collected snapshot"
                )
            codes = set(
                await conn.fetchval("SELECT array_agg(target_concern) FROM rec_concern")
                or []
            )
            if not set(CONCERNS.values()) <= codes:
                raise ValueError("Required existing concern codes are missing")
            existing = {
                table: await conn.fetchval(f"SELECT count(*) FROM {table}")
                for table in TABLES
            }
            print(
                f"Functions: {len(names)}; ingredient lookups: {len(lookup)}; ingredient-function links: {len(links)}; concern links: {len(concerns)}"
            )
            print(f"Existing destination rows: {existing}")
            if not args.apply:
                print("Preview only; no persistent changes")
                return
            # Prevent accidental replacement or stale links on re-runs.
            await conn.execute(
                "LOCK TABLE cosing_function, cosing_ingredient_lookup, ingredient_function, function_concern IN EXCLUSIVE MODE"
            )
            for table in TABLES:
                if await conn.fetchval(f"SELECT EXISTS (SELECT FROM {table})"):
                    raise ValueError(
                        "Destination is not empty; no existing data was overwritten"
                    )
            await conn.executemany(
                "INSERT INTO cosing_function (function_name) VALUES ($1)",
                [(name,) for name in names],
            )
            await conn.copy_records_to_table(
                "cosing_ingredient_lookup",
                records=lookup,
                columns=(
                    "ingredient_id",
                    "status",
                    "match_method",
                    "query_name",
                    "http_status",
                    "response_count",
                    "returned_inci",
                    "cosing_cas",
                    "substance_id",
                    "detail",
                    "collected_at",
                ),
            )
            await conn.execute(
                "CREATE TEMP TABLE cosing_link_stage (ingredient_id bigint, function_name text) ON COMMIT DROP"
            )
            await conn.copy_records_to_table(
                "cosing_link_stage",
                records=links,
                columns=("ingredient_id", "function_name"),
            )
            await conn.execute(
                "INSERT INTO ingredient_function SELECT s.ingredient_id, f.function_id FROM cosing_link_stage s JOIN cosing_function f USING (function_name)"
            )
            await conn.execute(
                "CREATE TEMP TABLE cosing_concern_stage (function_name text, target_concern text) ON COMMIT DROP"
            )
            await conn.copy_records_to_table(
                "cosing_concern_stage",
                records=concerns,
                columns=("function_name", "target_concern"),
            )
            await conn.execute(
                "INSERT INTO function_concern SELECT f.function_id, s.target_concern FROM cosing_concern_stage s JOIN cosing_function f USING (function_name)"
            )
        print("Import committed")
    finally:
        await conn.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input-dir", required=True, type=Path)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    asyncio.run(run(args))


if __name__ == "__main__":
    main()

"""Match Olive Young ingredient names to current MFDS dictionary entries.

Run from backend/api's uv environment. Preview is the default; --apply writes
confirmed matches. Existing mappings, including manual decisions, are never
overwritten. Unmatched and ambiguous names remain in a local review CSV.
"""

from __future__ import annotations

import argparse
import asyncio
import csv
import getpass
import os
import ssl
import unicodedata
from collections import defaultdict
from pathlib import Path

import asyncpg

RULE_VERSION = "v1"
MATCH_COLUMNS = (
    "oy_ingredient_id",
    "oy_ingredient_name",
    "mfds_ingredient_id",
    "mfds_name_ko",
    "match_method",
)
REVIEW_COLUMNS = (
    "oy_ingredient_id",
    "oy_ingredient_name",
    "reason",
    "mfds_candidate_ids",
    "mfds_candidate_names",
)


def name_key(value: str | None) -> str:
    """Use the same conservative key as the MFDS snapshot loader."""
    return " ".join(unicodedata.normalize("NFKC", value or "").split())


def build_candidates(
    oy_rows: list[asyncpg.Record], mfds_rows: list[asyncpg.Record]
) -> tuple[list[tuple[int, str, int, str, str]], list[tuple[int, str, str, str, str]]]:
    standards = {row["name_key"]: row for row in mfds_rows}
    synonyms: dict[str, dict[int, asyncpg.Record]] = defaultdict(dict)
    for row in mfds_rows:
        # '/' occurs inside valid chemical names; only commas separate aliases.
        for alias in (row["synonym_raw"] or "").replace("，", ",").split(","):
            alias_key = name_key(alias)
            if alias_key:
                synonyms[alias_key][row["ingredient_id"]] = row

    matches: list[tuple[int, str, int, str, str]] = []
    review: list[tuple[int, str, str, str, str]] = []
    for oy in oy_rows:
        oy_id = oy["ingredient_id"]
        oy_name = oy["ingredient_name"] or ""
        key = name_key(oy_name)
        if not key:
            review.append((oy_id, oy_name, "empty_name", "", ""))
            continue

        # An exact official standard name takes precedence over all synonyms.
        standard = standards.get(key)
        if standard is not None:
            matches.append(
                (
                    oy_id,
                    oy_name,
                    standard["ingredient_id"],
                    standard["name_ko"],
                    "exact_name",
                )
            )
            continue

        alias_hits = list(synonyms.get(key, {}).values())
        if len(alias_hits) == 1:
            mfds = alias_hits[0]
            matches.append(
                (
                    oy_id,
                    oy_name,
                    mfds["ingredient_id"],
                    mfds["name_ko"],
                    "official_synonym",
                )
            )
        else:
            alias_hits.sort(key=lambda row: row["ingredient_id"])
            reason = "ambiguous_synonym" if alias_hits else "no_match"
            review.append(
                (
                    oy_id,
                    oy_name,
                    reason,
                    ";".join(str(row["ingredient_id"]) for row in alias_hits),
                    ";".join(row["name_ko"] for row in alias_hits),
                )
            )
    return matches, review


def write_csv(path: Path, columns: tuple[str, ...], rows: list[tuple]) -> None:
    with path.open("w", encoding="utf-8-sig", newline="") as file:
        writer = csv.writer(file)
        writer.writerow(columns)
        writer.writerows(rows)


async def run(args: argparse.Namespace) -> None:
    if args.target == "shared":
        if not args.project_ref or args.user != f"postgres.{args.project_ref}":
            raise ValueError("Shared database user and --project-ref must match")
        if not args.host.endswith(".pooler.supabase.com"):
            raise ValueError("Shared imports require a Supabase session pooler host")
        if args.port != 5432 or args.database != "postgres":
            raise ValueError("Shared imports require port 5432 and database postgres")
        if not args.ssl_ca_file or not args.ssl_ca_file.is_file():
            raise ValueError("Shared imports require an existing --ssl-ca-file")
        if args.apply and not args.execute_shared:
            raise ValueError("Shared writes require both --apply and --execute-shared")
        ssl_config: ssl.SSLContext | bool = ssl.create_default_context(
            cafile=str(args.ssl_ca_file.resolve())
        )
        password = getpass.getpass("Shared PostgreSQL password: ")
    else:
        if args.project_ref or args.ssl_ca_file or args.execute_shared:
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
        server_settings={"application_name": "oy_mfds_ingredient_match"},
    )
    try:
        for table in (
            "raw_oy_ingredient",
            "raw_mfds_ingredient",
            "oy_mfds_ingredient_map",
        ):
            if (
                await connection.fetchval("SELECT to_regclass($1)", f"public.{table}")
                is None
            ):
                raise ValueError(
                    f"public.{table} is missing; apply the latest migration"
                )

        oy_rows = await connection.fetch(
            "SELECT ingredient_id, ingredient_name FROM public.raw_oy_ingredient "
            "ORDER BY ingredient_id"
        )
        mfds_rows = await connection.fetch(
            "SELECT ingredient_id, name_ko, name_key, synonym_raw "
            "FROM public.raw_mfds_ingredient WHERE is_current ORDER BY ingredient_id"
        )
        if not oy_rows or not mfds_rows:
            raise ValueError("Both source ingredient tables must contain rows")

        matches, review = build_candidates(oy_rows, mfds_rows)
        if len(matches) + len(review) != len(oy_rows):
            raise ValueError(
                "Candidate classification did not cover every Olive Young ingredient"
            )

        existing = {
            row["oy_ingredient_id"]: row
            for row in await connection.fetch(
                "SELECT oy_ingredient_id, mfds_ingredient_id, match_method "
                "FROM public.oy_mfds_ingredient_map"
            )
        }
        new_matches = [row for row in matches if row[0] not in existing]
        conflicts = [
            row
            for row in matches
            if row[0] in existing and existing[row[0]]["mfds_ingredient_id"] != row[2]
        ]
        review.extend(
            (row[0], row[1], "existing_mapping_differs", str(row[2]), row[3])
            for row in conflicts
        )

        args.report_dir.mkdir(parents=True, exist_ok=True)
        write_csv(
            args.report_dir / "exact-name-candidates.csv",
            MATCH_COLUMNS,
            [row for row in matches if row[4] == "exact_name"],
        )
        write_csv(
            args.report_dir / "official-synonym-candidates.csv",
            MATCH_COLUMNS,
            [row for row in matches if row[4] == "official_synonym"],
        )
        write_csv(args.report_dir / "review-required.csv", REVIEW_COLUMNS, review)
        exact_count = sum(row[4] == "exact_name" for row in matches)
        print(f"Connected to {args.host}:{args.port}/{args.database}")
        print(
            f"Source rows: Olive Young {len(oy_rows):,}; current MFDS {len(mfds_rows):,}"
        )
        print(
            f"Candidates: exact name {exact_count:,}; official synonym "
            f"{len(matches) - exact_count:,}; unmatched or ambiguous "
            f"{len(oy_rows) - len(matches):,}"
        )
        print(
            f"Existing mappings: {len(existing):,}; new confirmed matches: "
            f"{len(new_matches):,}; existing mapping conflicts: {len(conflicts):,}"
        )
        print(f"Review files: {args.report_dir.resolve()}")
        if not args.apply:
            print("Preview complete; no database rows were written")
            return

        async with connection.transaction():
            await connection.execute(
                "CREATE TEMP TABLE oy_mfds_match_stage ("
                "oy_ingredient_id bigint PRIMARY KEY, mfds_ingredient_id bigint NOT NULL, "
                "match_method text NOT NULL, rule_version text NOT NULL) ON COMMIT DROP"
            )
            await connection.copy_records_to_table(
                "oy_mfds_match_stage",
                records=[(row[0], row[2], row[4], RULE_VERSION) for row in new_matches],
                columns=(
                    "oy_ingredient_id",
                    "mfds_ingredient_id",
                    "match_method",
                    "rule_version",
                ),
            )
            status = await connection.execute(
                "INSERT INTO public.oy_mfds_ingredient_map "
                "(oy_ingredient_id, mfds_ingredient_id, match_method, rule_version) "
                "SELECT oy_ingredient_id, mfds_ingredient_id, match_method, rule_version "
                "FROM oy_mfds_match_stage ON CONFLICT (oy_ingredient_id) DO NOTHING"
            )
        print(f"Committed {status}; existing mappings were preserved")
    finally:
        await connection.close()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--target", choices=("local", "shared"), default="local")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=15432)
    parser.add_argument("--database", default="vishue_v29")
    parser.add_argument("--user", default="vishue")
    parser.add_argument("--project-ref")
    parser.add_argument("--ssl-ca-file", type=Path)
    parser.add_argument(
        "--report-dir",
        type=Path,
        default=Path.home() / "Downloads" / "ingredient-mapping-review",
    )
    parser.add_argument("--apply", action="store_true", help="Write confirmed matches")
    parser.add_argument("--execute-shared", action="store_true")
    asyncio.run(run(parser.parse_args()))


if __name__ == "__main__":
    main()

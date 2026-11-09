"""Match Olive Young ingredient names to current MFDS dictionary entries.

Run from backend/api's uv environment. Preview is the default; --apply writes
confirmed matches. Existing mappings, including manual decisions, are never
overwritten. Unmatched and ambiguous names remain in a local review CSV. Spellings a reviewer
approved in ingredient_aliases.csv are written as manual matches.
"""

from __future__ import annotations

import argparse
import asyncio
import csv
import getpass
import os
import re
import ssl
import unicodedata
from collections import defaultdict
from datetime import date
from pathlib import Path

import asyncpg

RULE_VERSION = "v3"
AMOUNT_METHODS = ("amount_suffix_exact", "amount_suffix_synonym")
AMOUNT_SUFFIX_RE = re.compile(
    r"\s*\(\s*\d+(?:,\d{3})*(?:\.\d+)?\s*(?:ppm|ppb|%|iu)\s*\)\s*$",
    re.IGNORECASE,
)
# Keep delimiter interpretation consistent with the read-only IngredientIdentityRepository.
# The code change does not update mappings; data owners must review a preview before --apply.
OFFICIAL_SYNONYM_SEPARATOR = r"\s*(?:\^|(?<![0-9A-Za-z]),|,(?![0-9A-Za-z])|,(?=[A-Za-z]{2,}))\s*"

MATCH_COLUMNS = (
    "oy_ingredient_id",
    "oy_ingredient_name",
    "mfds_ingredient_id",
    "mfds_name_ko",
    "match_method",
)
ALIAS_COLUMNS = ("oy_name", "mfds_name", "reviewed_by", "reviewed_at", "review_note")
DEFAULT_ALIAS_PATH = Path(__file__).resolve().parent / "ingredient_aliases.csv"
REVIEW_COLUMNS = (
    "oy_ingredient_id",
    "oy_ingredient_name",
    "reason",
    "mfds_candidate_ids",
    "mfds_candidate_names",
)
MANUAL_COLUMNS = (*MATCH_COLUMNS, "reviewed_by", "reviewed_at", "review_note")


def name_key(value: str | None) -> str:
    """Use the same conservative key as the MFDS snapshot loader."""
    return " ".join(unicodedata.normalize("NFKC", value or "").split())


def official_synonyms(value: str | None) -> set[str]:
    """Read mixed MFDS aliases, preserving chemical locants such as 1,2- and N,N-."""
    return {
        normalized
        for alias in re.split(OFFICIAL_SYNONYM_SEPARATOR, value or "")
        if (normalized := name_key(alias))
    }


def without_trailing_amount(value: str) -> str | None:
    """Drop only one final parenthesized numeric concentration, never name content."""
    normalized = name_key(value)
    amount = AMOUNT_SUFFIX_RE.search(normalized)
    if amount is None:
        return None
    return normalized[: amount.start()].strip() or None


def load_aliases(path: Path) -> dict[str, tuple[str, str, str, str]]:
    """Read spellings a reviewer approved. Official MFDS data is never edited."""
    if not path.is_file():
        return {}
    aliases: dict[str, tuple[str, str, str, str]] = {}
    with path.open(encoding="utf-8-sig", newline="") as file:
        reader = csv.DictReader(file)
        if tuple(reader.fieldnames or ()) != ALIAS_COLUMNS:
            raise ValueError(f"Alias file columns must be {ALIAS_COLUMNS}")
        for line, row in enumerate(reader, 2):
            oy_key = name_key(row["oy_name"])
            mfds_key = name_key(row["mfds_name"])
            reviewer = (row["reviewed_by"] or "").strip()
            reviewed = (row["reviewed_at"] or "").strip()
            if not (oy_key and mfds_key and reviewer and reviewed):
                raise ValueError(f"Alias line {line} needs both names, a reviewer and a date")
            if oy_key == mfds_key:
                raise ValueError(f"Alias line {line} repeats the dictionary spelling")
            if oy_key in aliases:
                raise ValueError(f"Alias line {line} repeats {row['oy_name']}")
            date.fromisoformat(reviewed)
            aliases[oy_key] = (mfds_key, reviewer, reviewed, (row["review_note"] or "").strip())
    return aliases


def apply_aliases(
    review: list[tuple[int, str, str, str, str]],
    mfds_rows: list[asyncpg.Record],
    aliases: dict[str, tuple[str, str, str, str]],
) -> tuple[list[tuple], list[tuple[int, str, str, str, str]]]:
    """Resolve only the names a reviewer approved; the rest stay under review."""
    standards = {row["name_key"]: row for row in mfds_rows}
    manual: list[tuple] = []
    remaining: list[tuple[int, str, str, str, str]] = []
    for row in review:
        approved = aliases.get(name_key(row[1]))
        if approved is None:
            remaining.append(row)
            continue
        mfds_key, reviewer, reviewed, note = approved
        standard = standards.get(mfds_key)
        if standard is None:
            remaining.append((row[0], row[1], "alias_target_missing", "", mfds_key))
            continue
        manual.append(
            (
                row[0],
                row[1],
                standard["ingredient_id"],
                standard["name_ko"],
                "manual",
                reviewer,
                reviewed,
                note,
            )
        )
    return manual, remaining


def build_candidates(
    oy_rows: list[asyncpg.Record], mfds_rows: list[asyncpg.Record]
) -> tuple[list[tuple[int, str, int, str, str]], list[tuple[int, str, str, str, str]]]:
    standards = {row["name_key"]: row for row in mfds_rows}
    synonyms: dict[str, dict[int, asyncpg.Record]] = defaultdict(dict)
    for row in mfds_rows:
        for alias_key in official_synonyms(row["synonym_raw"]):
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
        elif alias_hits:
            alias_hits.sort(key=lambda row: row["ingredient_id"])
            review.append(
                (
                    oy_id,
                    oy_name,
                    "ambiguous_synonym",
                    ";".join(str(row["ingredient_id"]) for row in alias_hits),
                    ";".join(row["name_ko"] for row in alias_hits),
                )
            )
        else:
            base = without_trailing_amount(key)
            if base is not None and (standard := standards.get(base)) is not None:
                matches.append(
                    (
                        oy_id,
                        oy_name,
                        standard["ingredient_id"],
                        standard["name_ko"],
                        "amount_suffix_exact",
                    )
                )
                continue
            amount_hits = list(synonyms.get(base, {}).values()) if base else []
            if len(amount_hits) == 1:
                mfds = amount_hits[0]
                matches.append(
                    (
                        oy_id,
                        oy_name,
                        mfds["ingredient_id"],
                        mfds["name_ko"],
                        "amount_suffix_synonym",
                    )
                )
                continue
            amount_hits.sort(key=lambda row: row["ingredient_id"])
            review.append(
                (
                    oy_id,
                    oy_name,
                    "ambiguous_amount_synonym" if amount_hits else "no_match",
                    ";".join(str(row["ingredient_id"]) for row in amount_hits),
                    ";".join(row["name_ko"] for row in amount_hits),
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
            if await connection.fetchval("SELECT to_regclass($1)", f"public.{table}") is None:
                raise ValueError(f"public.{table} is missing; apply the latest migration")

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
        # A reviewer's approved spelling is the last resort, after every official rule.
        manual_matches, review = apply_aliases(review, mfds_rows, load_aliases(args.alias_file))
        if len(matches) + len(manual_matches) + len(review) != len(oy_rows):
            raise ValueError("Candidate classification did not cover every Olive Young ingredient")

        existing = {
            row["oy_ingredient_id"]: row
            for row in await connection.fetch(
                "SELECT oy_ingredient_id, mfds_ingredient_id, match_method "
                "FROM public.oy_mfds_ingredient_map"
            )
        }
        confirmed = [*matches, *(row[:5] for row in manual_matches)]
        new_matches = [row for row in matches if row[0] not in existing]
        new_manual = [row for row in manual_matches if row[0] not in existing]
        conflicts = [
            row
            for row in confirmed
            if row[0] in existing and existing[row[0]]["mfds_ingredient_id"] != row[2]
        ]
        review.extend(
            (row[0], row[1], "existing_mapping_differs", str(row[2]), row[3]) for row in conflicts
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
        write_csv(
            args.report_dir / "amount-suffix-candidates.csv",
            (*MATCH_COLUMNS, "compared_name"),
            [
                (*row, without_trailing_amount(row[1]))
                for row in matches
                if row[4] in AMOUNT_METHODS
            ],
        )
        write_csv(
            args.report_dir / "manual-alias-candidates.csv", MANUAL_COLUMNS, manual_matches
        )
        write_csv(args.report_dir / "review-required.csv", REVIEW_COLUMNS, review)
        method_counts = {
            method: sum(row[4] == method for row in matches)
            for method in ("exact_name", "official_synonym", *AMOUNT_METHODS)
        }
        print(f"Connected to {args.host}:{args.port}/{args.database}")
        print(f"Source rows: Olive Young {len(oy_rows):,}; current MFDS {len(mfds_rows):,}")
        print(
            f"Candidates: exact name {method_counts['exact_name']:,}; official synonym "
            f"{method_counts['official_synonym']:,}; amount suffix exact "
            f"{method_counts['amount_suffix_exact']:,}; amount suffix synonym "
            f"{method_counts['amount_suffix_synonym']:,}; reviewed alias "
            f"{len(manual_matches):,}; unmatched or ambiguous "
            f"{len(oy_rows) - len(matches) - len(manual_matches):,}"
        )
        print(
            f"Existing mappings: {len(existing):,}; new confirmed matches: "
            f"{len(new_matches) + len(new_manual):,} (reviewed alias {len(new_manual):,}); "
            f"existing mapping conflicts: {len(conflicts):,}"
        )
        print(f"Review files: {args.report_dir.resolve()}")
        if not args.apply:
            print("Preview complete; no database rows were written")
            return

        if any(row[4] in AMOUNT_METHODS for row in new_matches):
            constraint = await connection.fetchval(
                "SELECT pg_get_constraintdef(oid) FROM pg_constraint "
                "WHERE conrelid='public.oy_mfds_ingredient_map'::regclass "
                "AND conname='ck_oy_mfds_ingredient_map_method'"
            )
            if not constraint or not all(method in constraint for method in AMOUNT_METHODS):
                raise ValueError("Apply Alembic migration 0011 before amount-suffix matches")

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
            if new_manual:
                await connection.execute(
                    "CREATE TEMP TABLE oy_mfds_manual_stage ("
                    "oy_ingredient_id bigint PRIMARY KEY, mfds_ingredient_id bigint NOT NULL, "
                    "reviewed_by text NOT NULL, reviewed_at text NOT NULL, review_note text) "
                    "ON COMMIT DROP"
                )
                await connection.copy_records_to_table(
                    "oy_mfds_manual_stage",
                    records=[
                        (row[0], row[2], row[5], row[6], row[7] or None) for row in new_manual
                    ],
                    columns=(
                        "oy_ingredient_id",
                        "mfds_ingredient_id",
                        "reviewed_by",
                        "reviewed_at",
                        "review_note",
                    ),
                )
                manual_status = await connection.execute(
                    "INSERT INTO public.oy_mfds_ingredient_map (oy_ingredient_id, "
                    "mfds_ingredient_id, match_method, reviewed_by, reviewed_at, review_note) "
                    "SELECT oy_ingredient_id, mfds_ingredient_id, 'manual', reviewed_by, "
                    "reviewed_at::timestamptz, review_note FROM oy_mfds_manual_stage "
                    "ON CONFLICT (oy_ingredient_id) DO NOTHING"
                )
                print(f"Reviewed aliases: {manual_status}")
        print(f"Committed {status}; existing mappings were preserved")
    finally:
        await connection.close()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--target", choices=("local", "shared"), default="local")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=15432)
    parser.add_argument("--database", default="vishue_db")
    parser.add_argument("--user", default="vishue")
    parser.add_argument("--project-ref")
    parser.add_argument("--ssl-ca-file", type=Path)
    parser.add_argument(
        "--report-dir",
        type=Path,
        default=Path.home() / "Downloads" / "ingredient-mapping-review",
    )
    parser.add_argument("--alias-file", type=Path, default=DEFAULT_ALIAS_PATH)
    parser.add_argument("--apply", action="store_true", help="Write confirmed matches")
    parser.add_argument("--execute-shared", action="store_true")
    asyncio.run(run(parser.parse_args()))


if __name__ == "__main__":
    main()

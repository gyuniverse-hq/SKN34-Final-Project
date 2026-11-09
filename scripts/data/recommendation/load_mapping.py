"""Validate and load only evidence-backed v0.3 recommendation rules.

Required CSVs: recommendation_reason.csv, evidence_sources.csv,
ingredient_dictionary.csv, recommendation_mapping.csv, mapping_ingredients.csv,
and mapping_evidence.csv. There is intentionally no manual-review queue file.
Preview is the default; --apply replaces the operational rule snapshot.
"""

import argparse
import asyncio
import csv
import getpass
import json
import os
import ssl
from collections import defaultdict
from pathlib import Path

import asyncpg

DEFAULT_DIR = Path.home() / "Downloads" / "VISHUE_Recommendation_v0_3"
CONCERNS = {"dryness", "sensitivity", "pigmentation", "wrinkles", "pores", "blemish", "oiliness"}
STUDY_TYPES = {
    "human_intervention",
    "human_observational",
    "in_vitro",
    "animal",
    "method_validation",
    "review",
    "other",
}
SCOPES = {"ingredient_level", "formula_specific"}


def read_csv(path: Path, required: set[str]) -> list[dict[str, str]]:
    if not path.is_file():
        raise SystemExit(f"Required file missing: {path}")
    with path.open(encoding="utf-8-sig", newline="") as stream:
        reader = csv.DictReader(stream)
        missing = required - set(reader.fieldnames or ())
        if missing:
            raise SystemExit(f"{path.name}: required columns missing: {sorted(missing)}")
        return [{key: (value or "").strip() for key, value in row.items()} for row in reader]


def flag(value: str, label: str) -> bool:
    normalized = value.strip().lower()
    if normalized in {"1", "true", "y", "yes"}:
        return True
    if normalized in {"0", "false", "n", "no"}:
        return False
    raise ValueError(f"{label}: expected true/false, got {value!r}")


def load_sources(folder: Path) -> dict[str, list[dict[str, str]]]:
    return {
        "concerns": read_csv(
            folder / "recommendation_reason.csv",
            {"target_concern", "display_label", "recommendation_reason"},
        ),
        "evidence": read_csv(
            folder / "evidence_sources.csv",
            {
                "evidence_id",
                "pmid",
                "title",
                "source_url",
                "study_limit",
                "study_type",
                "publication_year",
            },
        ),
        "dictionary": read_csv(
            folder / "ingredient_dictionary.csv", {"ingredient_code", "name_ko", "inci_name"}
        ),
        "mappings": read_csv(
            folder / "recommendation_mapping.csv",
            {
                "mapping_id",
                "mapping_type",
                "target_concern",
                "applicability_scope",
                "runtime_enabled",
            },
        ),
        "ingredients": read_csv(
            folder / "mapping_ingredients.csv", {"mapping_id", "ingredient_code", "component_order"}
        ),
        "evidence_links": read_csv(
            folder / "mapping_evidence.csv",
            {
                "mapping_id",
                "evidence_id",
                "supported_endpoint",
                "study_conditions",
                "applicability_note",
            },
        ),
    }


def validate_and_normalize(src: dict[str, list[dict[str, str]]]):
    errors = []
    concerns = {r["target_concern"] for r in src["concerns"]}
    evidence_by_id = {r["evidence_id"]: r for r in src["evidence"]}
    codes = {r["ingredient_code"] for r in src["dictionary"]}
    maps_by_id = {r["mapping_id"]: r for r in src["mappings"]}
    if len(concerns) != len(src["concerns"]):
        errors.append("duplicate concern code")
    if concerns - CONCERNS:
        errors.append(f"unsupported concerns: {sorted(concerns - CONCERNS)}")
    if len(evidence_by_id) != len(src["evidence"]):
        errors.append("duplicate evidence_id")
    if len(codes) != len(src["dictionary"]):
        errors.append("duplicate ingredient_code")
    if len(maps_by_id) != len(src["mappings"]):
        errors.append("duplicate mapping_id")

    for row in src["evidence"]:
        if not row["title"] or not row["source_url"]:
            errors.append(f"{row['evidence_id']}: title/source_url required")
        if row["study_type"] not in STUDY_TYPES:
            errors.append(f"{row['evidence_id']}: invalid or missing study_type")
        if row["publication_year"]:
            try:
                year = int(row["publication_year"])
                if not 1800 <= year <= 2200:
                    raise ValueError
            except ValueError:
                errors.append(f"{row['evidence_id']}: invalid publication_year")

    components = defaultdict(list)
    for row in src["ingredients"]:
        if row["mapping_id"] not in maps_by_id:
            errors.append(f"ingredient row references unknown mapping {row['mapping_id']}")
        if row["ingredient_code"] not in codes:
            errors.append(f"{row['mapping_id']}: unknown ingredient code {row['ingredient_code']}")
        try:
            order = int(row["component_order"])
            if order < 1:
                raise ValueError
        except ValueError:
            errors.append(f"{row['mapping_id']}: component_order must be >= 1")
            continue
        components[row["mapping_id"]].append((order, row["ingredient_code"]))

    links = defaultdict(list)
    seen_mapping_evidence = {}
    for row in src["evidence_links"]:
        if row["mapping_id"] not in maps_by_id:
            errors.append(f"evidence row references unknown mapping {row['mapping_id']}")
        if row["evidence_id"] not in evidence_by_id:
            errors.append(f"{row['mapping_id']}: unknown evidence {row['evidence_id']}")
        if not row["supported_endpoint"]:
            errors.append(f"{row['mapping_id']}/{row['evidence_id']}: supported_endpoint required")
        try:
            conditions = json.loads(row["study_conditions"] or "{}")
            if not isinstance(conditions, dict):
                raise TypeError("must be a JSON object")
            row["_conditions"] = conditions
        except (json.JSONDecodeError, TypeError) as exc:
            errors.append(
                f"{row['mapping_id']}/{row['evidence_id']}: invalid study_conditions: {exc}"
            )
            row["_conditions"] = {}
        links[row["mapping_id"]].append(row)
        pair = (row["mapping_id"], row["evidence_id"])
        claim = (row["supported_endpoint"], row["study_conditions"], row["applicability_note"])
        if pair in seen_mapping_evidence and seen_mapping_evidence[pair] != claim:
            errors.append(
                f"{row['mapping_id']}/{row['evidence_id']}: conflicting duplicate evidence claims"
            )
        seen_mapping_evidence[pair] = claim

    parsed_mappings = {}
    for row in src["mappings"]:
        mid = row["mapping_id"]
        items = sorted(components[mid])
        member_codes = [code for _, code in items]
        unique_codes = set(member_codes)
        kind = row["mapping_type"]
        concern = row["target_concern"]
        scope = row["applicability_scope"]
        if concern not in concerns:
            errors.append(f"{mid}: missing concern definition for {concern}")
        if scope not in SCOPES:
            errors.append(f"{mid}: invalid applicability_scope {scope!r}")
        if (
            (kind == "single" and len(unique_codes) != 1)
            or (kind == "combination" and len(unique_codes) < 2)
            or kind not in {"single", "combination"}
        ):
            errors.append(f"{mid}: mapping_type does not match distinct ingredient count")
        if len(unique_codes) != len(member_codes):
            errors.append(f"{mid}: duplicate ingredient_code in composition")
        if not links[mid]:
            errors.append(f"{mid}: at least one evidence link is required")
        try:
            runtime = flag(row["runtime_enabled"], f"{mid}.runtime_enabled")
        except ValueError as exc:
            errors.append(str(exc))
            runtime = False
        parsed_mappings[mid] = {
            "mapping_id": mid,
            "mapping_type": kind,
            "target_concern": concern,
            "applicability_scope": scope,
            "runtime_enabled": runtime,
            "ingredient_codes": member_codes,
        }

    # Consolidate repeated rules; one canonical mapping keeps all evidence links.
    groups = defaultdict(list)
    for mid, mapping in parsed_mappings.items():
        signature = (
            mapping["target_concern"],
            mapping["applicability_scope"],
            tuple(sorted(mapping["ingredient_codes"])),
        )
        groups[signature].append(mid)
    canonical_for = {}
    normalized = []
    for mids in groups.values():
        canonical = min(mids)
        combined = dict(parsed_mappings[canonical])
        combined["runtime_enabled"] = any(parsed_mappings[mid]["runtime_enabled"] for mid in mids)
        combined["source_mapping_ids"] = mids
        normalized.append(combined)
        for mid in mids:
            canonical_for[mid] = canonical

    merged_evidence_claims = {}
    for source_id, canonical_id in canonical_for.items():
        for row in links[source_id]:
            key = (canonical_id, row["evidence_id"])
            claim = (row["supported_endpoint"], row["_conditions"], row["applicability_note"])
            if key in merged_evidence_claims and merged_evidence_claims[key] != claim:
                errors.append(
                    f"merged rule {canonical_id}/{row['evidence_id']}: conflicting endpoint/conditions"
                )
            merged_evidence_claims[key] = claim

    if errors:
        print("Input validation failed:")
        for error in errors[:40]:
            print(" -", error)
        raise SystemExit(
            f"Stopped with {len(errors)} validation issue(s); no database writes were made"
        )
    return normalized, canonical_for, components, links, evidence_by_id


async def connect(args):
    ssl_context: ssl.SSLContext | bool = False
    if args.target == "shared":
        if not args.ssl_ca_file:
            raise SystemExit("--ssl-ca-file required for shared target")
        if args.apply and not args.execute_shared:
            raise SystemExit("Shared writes require both --apply and --execute-shared")
        ssl_context = ssl.create_default_context(cafile=args.ssl_ca_file)
        password = getpass.getpass("Shared PostgreSQL password: ")
    else:
        password = os.environ.get("POSTGRES_PASSWORD") or getpass.getpass(
            "Local PostgreSQL password: "
        )
    return await asyncpg.connect(
        host=args.host,
        port=args.port,
        database=args.database,
        user=args.user,
        password=password,
        ssl=ssl_context,
    )


async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dir", type=Path, default=DEFAULT_DIR)
    parser.add_argument("--target", choices=("local", "shared"), default="local")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=15432)
    parser.add_argument("--database", default="vishue_db")
    parser.add_argument("--user", default="vishue")
    parser.add_argument("--ssl-ca-file")
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--execute-shared", action="store_true")
    args = parser.parse_args()

    src = load_sources(args.dir)
    mappings, _, components, evidence_links, _ = validate_and_normalize(src)
    print(
        f"Validated: concerns {len(src['concerns'])}, studies {len(src['evidence'])}, "
        f"ingredients {len(src['dictionary'])}, unique rules {len(mappings)}"
    )
    print(
        f"Evidence links: {sum(len(v) for v in evidence_links.values())}; "
        f"runtime-enabled ingredient-level rules: "
        f"{sum(m['runtime_enabled'] and m['applicability_scope'] == 'ingredient_level' for m in mappings)}"
    )

    conn = await connect(args)
    try:
        old_kill_switches = {
            row["mapping_id"]: row["runtime_enabled"]
            for row in await conn.fetch("SELECT mapping_id, runtime_enabled FROM rec_mapping")
        }
        counts = {
            table: await conn.fetchval(f"SELECT COUNT(*) FROM public.{table}")
            for table in ("rec_concern", "rec_evidence", "rec_ingredient_dictionary", "rec_mapping")
        }
        print("Existing rows:", counts)
        if not args.apply:
            print("Preview only; no rows were written")
            return

        async with conn.transaction():
            for row in src["concerns"]:
                await conn.execute(
                    """INSERT INTO rec_concern VALUES ($1,$2,$3)
                    ON CONFLICT (target_concern) DO UPDATE SET display_label=EXCLUDED.display_label,
                    recommendation_reason=EXCLUDED.recommendation_reason""",
                    row["target_concern"],
                    row["display_label"],
                    row["recommendation_reason"],
                )
            for row in src["evidence"]:
                await conn.execute(
                    """INSERT INTO rec_evidence (evidence_id,pmid,title,source_url,study_limit,study_type,publication_year)
                    VALUES ($1,$2,$3,$4,$5,$6,$7)
                    ON CONFLICT (evidence_id) DO UPDATE SET pmid=EXCLUDED.pmid,title=EXCLUDED.title,
                    source_url=EXCLUDED.source_url,study_limit=EXCLUDED.study_limit,
                    study_type=EXCLUDED.study_type,publication_year=EXCLUDED.publication_year""",
                    row["evidence_id"],
                    row["pmid"] or None,
                    row["title"],
                    row["source_url"],
                    row["study_limit"] or None,
                    row["study_type"],
                    int(row["publication_year"]) if row["publication_year"] else None,
                )
            for row in src["dictionary"]:
                await conn.execute(
                    """INSERT INTO rec_ingredient_dictionary VALUES ($1,$2,$3)
                    ON CONFLICT (ingredient_code) DO UPDATE SET name_ko=EXCLUDED.name_ko,inci_name=EXCLUDED.inci_name""",
                    row["ingredient_code"],
                    row["name_ko"],
                    row["inci_name"] or None,
                )

            await conn.execute("DELETE FROM rec_concern_match")
            await conn.execute("DELETE FROM rec_mapping_evidence")
            await conn.execute("DELETE FROM rec_mapping_ingredient")
            await conn.execute("DELETE FROM rec_mapping")
            for mapping in mappings:
                enabled = mapping["runtime_enabled"] and all(
                    old_kill_switches.get(source_id, True)
                    for source_id in mapping["source_mapping_ids"]
                )
                await conn.execute(
                    "INSERT INTO rec_mapping VALUES ($1,$2,$3,$4,$5)",
                    mapping["mapping_id"],
                    mapping["mapping_type"],
                    mapping["target_concern"],
                    mapping["applicability_scope"],
                    enabled,
                )
                for order, code in sorted(components[mapping["mapping_id"]]):
                    await conn.execute(
                        "INSERT INTO rec_mapping_ingredient VALUES ($1,$2,$3)",
                        mapping["mapping_id"],
                        code,
                        order,
                    )
                for source_id in mapping["source_mapping_ids"]:
                    for row in evidence_links[source_id]:
                        await conn.execute(
                            """INSERT INTO rec_mapping_evidence
                            (mapping_id,evidence_id,supported_endpoint,study_conditions,applicability_note)
                            VALUES ($1,$2,$3,$4::jsonb,$5)
                            ON CONFLICT (mapping_id,evidence_id) DO NOTHING""",
                            mapping["mapping_id"],
                            row["evidence_id"],
                            row["supported_endpoint"],
                            json.dumps(row["_conditions"], ensure_ascii=False),
                            row["applicability_note"] or None,
                        )
        print(
            f"Committed {len(mappings)} validated unique mapping rules; prior kill switches preserved"
        )
    finally:
        await conn.close()


if __name__ == "__main__":
    asyncio.run(main())

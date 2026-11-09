"""Rebuild ingredient links from unique exact identity and versioned explicit rules."""

import argparse
import asyncio
import csv
import getpass
import importlib.util
import os
import ssl
import sys
from collections import defaultdict
from pathlib import Path

import asyncpg

ROOT = Path(__file__).resolve().parents[3]
MOD = ROOT / "scripts" / "data" / "oliveyoung" / "collectors" / "oliveyoung_erd_v30.py"
sys.path.insert(0, str(MOD.parent))
spec = importlib.util.spec_from_file_location("oy_erd_v30", MOD)
oy = importlib.util.module_from_spec(spec)
sys.modules["oy_erd_v30"] = oy
spec.loader.exec_module(oy)
norm = oy.norm
RULE_DIR = Path(__file__).resolve().parent
METHOD_PRIORITY = {
    "standard_id": 0,
    "exact_name": 1,
    "verified_alias": 2,
    "verified_group_member": 3,
}


def read_rules(path: Path, required: set[str]) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open(encoding="utf-8-sig", newline="") as stream:
        reader = csv.DictReader(stream)
        missing = required - set(reader.fieldnames or ())
        if missing:
            raise SystemExit(f"{path.name}: missing columns {sorted(missing)}")
        rows = [{k: (v or "").strip() for k, v in row.items()} for row in reader]
    for row in rows:
        if not all(row.get(key) for key in required):
            raise SystemExit(f"{path.name}: rule rows must fill every required field: {row}")
    return rows


async def connect(args):
    ssl_context: ssl.SSLContext | bool = False
    if args.target == "shared":
        if not args.ssl_ca_file:
            raise SystemExit("--ssl-ca-file required for shared target")
        if args.apply and not args.execute_shared:
            raise SystemExit("Shared writes require --apply and --execute-shared")
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
    parser.add_argument("--target", choices=("local", "shared"), default="local")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=15432)
    parser.add_argument("--database", default="vishue_db")
    parser.add_argument("--user", default="vishue")
    parser.add_argument("--ssl-ca-file")
    parser.add_argument("--alias-rules", type=Path, default=RULE_DIR / "ingredient_alias_rules.csv")
    parser.add_argument(
        "--group-rules", type=Path, default=RULE_DIR / "ingredient_group_members.csv"
    )
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--execute-shared", action="store_true")
    args = parser.parse_args()

    aliases = read_rules(
        args.alias_rules, {"ingredient_code", "oy_ingredient_name", "rule_version", "source_ref"}
    )
    groups = read_rules(
        args.group_rules,
        {
            "ingredient_code",
            "member_name",
            "rule_version",
            "source_ref",
            "applicability_conditions",
        },
    )
    conn = await connect(args)
    try:
        dictionary = await conn.fetch(
            "SELECT ingredient_code, name_ko FROM rec_ingredient_dictionary ORDER BY ingredient_code"
        )
        if not dictionary:
            raise SystemExit("rec_ingredient_dictionary is empty; load validated rules first")
        current_oy = await conn.fetch(
            "SELECT ingredient_id, ingredient_name FROM raw_oy_ingredient"
        )
        raw_by_norm = defaultdict(list)
        for row in current_oy:
            raw_by_norm[norm(row["ingredient_name"])].append(row)
        candidates = defaultdict(list)

        # A standard identifier is used only when the recommendation name exactly
        # equals a current MFDS standard name and the existing crosswalk is present.
        standard_rows = await conn.fetch("""SELECT d.ingredient_code, om.oy_ingredient_id
            FROM rec_ingredient_dictionary d
            JOIN raw_mfds_ingredient m ON m.is_current AND m.name_ko = d.name_ko
            JOIN oy_mfds_ingredient_map om ON om.mfds_ingredient_id = m.ingredient_id""")
        for row in standard_rows:
            candidates[row["oy_ingredient_id"]].append((row["ingredient_code"], "standard_id"))

        for item in dictionary:
            hits = raw_by_norm.get(norm(item["name_ko"]), [])
            if len(hits) == 1:
                candidates[hits[0]["ingredient_id"]].append((item["ingredient_code"], "exact_name"))

        rule_names = []
        for row in aliases:
            rule_names.append(
                (row["ingredient_code"], row["oy_ingredient_name"], "verified_alias", row)
            )
        for row in groups:
            rule_names.append(
                (row["ingredient_code"], row["member_name"], "verified_group_member", row)
            )
        known_codes = {row["ingredient_code"] for row in dictionary}
        for code, name, method, record in rule_names:
            if code not in known_codes:
                raise SystemExit(f"Rule references unknown ingredient_code {code}")
            hits = raw_by_norm.get(norm(name), [])
            if len(hits) != 1:
                print(f"[skip] {method} name has {len(hits)} exact DB rows: {name}")
                continue
            candidates[hits[0]["ingredient_id"]].append((code, method))

        planned, ambiguous = [], []
        for ingredient_id, rows in candidates.items():
            codes = {code for code, _ in rows}
            if len(codes) != 1:
                ambiguous.append((ingredient_id, sorted(codes)))
                continue
            code = next(iter(codes))
            method = min((m for c, m in rows if c == code), key=METHOD_PRIORITY.get)
            planned.append((code, ingredient_id, method))

        linked_codes = {row[0] for row in planned}
        print(f"Recommendation codes: {len(dictionary)}; deterministic links: {len(planned)}")
        print(f"Codes linked: {len(linked_codes)}; unlinked: {len(dictionary) - len(linked_codes)}")
        print(f"Ambiguous source ingredients skipped: {len(ambiguous)}")
        print(f"Versioned alias rules: {len(aliases)}; group-member rules: {len(groups)}")
        if not args.apply:
            print("Preview only; no rows were written")
            return
        async with conn.transaction():
            await conn.execute("DELETE FROM rec_ingredient_link")
            await conn.executemany(
                "INSERT INTO rec_ingredient_link (ingredient_code,oy_ingredient_id,link_method) VALUES ($1,$2,$3)",
                planned,
            )
        print(f"Rebuilt rec_ingredient_link: {len(planned)} links")
    finally:
        await conn.close()


if __name__ == "__main__":
    asyncio.run(main())

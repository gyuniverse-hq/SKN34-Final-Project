"""Put the reviewed eyeshadow finish on serving shades, in the database and the seed file.

Run after alembic revision 0027 and load_eyeshadow_finish.py. Only the latest finish of each
option is used, and only the six finishes: tools, palettes and other categories leave the shade
empty. Serving shade IDs come from several builders (the option ID in lower case, the option
number, or the shade code such as "p201"), so a shade is matched to its raw option within the
same product by any of those and by shade name (both when both fit). When the shade still fits
several options (the same shade sold alone and in a set), the finish is used only if all of
those options agree; otherwise the shade is left empty.
Without --apply it only prints what would change.
"""

from __future__ import annotations

import argparse
import asyncio
import getpass
import json
import os
from collections import Counter, defaultdict
from pathlib import Path

import asyncpg

API_ROOT = Path(__file__).resolve().parents[3] / "backend" / "api"

FINISH_SQL = """
SELECT f.option_id, f.finish_code
FROM (
    SELECT DISTINCT ON (option_id) option_id, finish_code
    FROM raw_oy_option_finish
    ORDER BY option_id, collected_at DESC
) f
JOIN raw_oy_finish_type t ON t.finish_code = f.finish_code
WHERE t.is_finish
"""
OPTIONS_SQL = """
SELECT option_id, goods_no, option_no, shade_code, shade_name
FROM raw_oy_product_option
WHERE goods_no = ANY($1::text[])
"""


def norm(value: str | None) -> str:
    return " ".join((value or "").lower().split())


class Resolver:
    """Find the raw options behind a serving shade of an OY product."""

    def __init__(self, options) -> None:
        by_key: dict[tuple[str, str], set[str]] = defaultdict(set)
        by_name: dict[tuple[str, str], set[str]] = defaultdict(set)
        for o in options:
            goods = o["goods_no"]
            for key in (o["option_id"], o["option_no"], o["shade_code"]):
                if norm(key):
                    by_key[(goods, norm(key))].add(o["option_id"])
            if norm(o["shade_name"]):
                by_name[(goods, norm(o["shade_name"]))].add(o["option_id"])
        self.by_key = dict(by_key)
        self.by_name = dict(by_name)

    def __call__(self, product_id: str, shade_id: str, shade_name: str) -> set[str]:
        if not product_id.startswith("oy-"):
            return set()
        goods = product_id[3:].upper()
        by_key = self.by_key.get((goods, norm(shade_id)), set())
        by_name = self.by_name.get((goods, norm(shade_name)), set())
        # A product that sells one shade code in two lines (old and renewed) needs the name too.
        return (by_key & by_name) or by_key or by_name


def finish_of(options: set[str], finishes: dict[str, str]) -> str | None:
    """The finish shared by every matched option, or None when they differ or have none."""
    found = {finishes.get(option) for option in options}
    return found.pop() if len(found) == 1 else None


def plan(shades, finishes: dict[str, str], resolve: Resolver) -> list[tuple]:
    """(product_id, shade_id, current, wanted) for each shade whose finish must change."""
    changes = []
    for product_id, shade_id, name, current in shades:
        wanted = finish_of(resolve(product_id, shade_id, name), finishes)
        if current != wanted:
            changes.append((product_id, shade_id, current, wanted))
    return changes


def update_seed(
    path: Path, finishes: dict[str, str], resolve: Resolver, apply: bool
) -> Counter[str]:
    seed = json.loads(path.read_text(encoding="utf-8"))
    counts: Counter[str] = Counter()
    for product in seed["products"]:
        for shade in product.get("shades", []):
            options = resolve(product["id"], shade["id"], shade.get("name", ""))
            wanted = finish_of(options, finishes)
            if shade.get("finish") == wanted:
                continue
            if wanted is None:
                shade.pop("finish", None)
                counts["cleared"] += 1
            else:
                shade["finish"] = wanted
                counts[wanted] += 1
    if apply and counts:
        serialized = (json.dumps(seed, ensure_ascii=False, indent=2) + "\n").replace("\n", "\r\n")
        path.write_bytes(serialized.encode("utf-8"))
    return counts


async def serving_shades(conn: asyncpg.Connection) -> list[tuple]:
    rows = await conn.fetch(
        "SELECT product_id, id, name, finish FROM shades WHERE product_id LIKE 'oy-%'"
    )
    return [(r["product_id"], r["id"], r["name"], r["finish"]) for r in rows]


async def run(args: argparse.Namespace) -> None:
    password = os.environ.get("POSTGRES_PASSWORD") or getpass.getpass("Local PostgreSQL password: ")
    conn = await asyncpg.connect(
        host=args.host,
        port=args.port,
        database=args.database,
        user=args.user,
        password=password,
        server_settings={"application_name": "oy_eyeshadow_finish_apply"},
    )
    try:
        has_column = await conn.fetchval(
            "SELECT 1 FROM information_schema.columns "
            "WHERE table_name = 'shades' AND column_name = 'finish'"
        )
        if not has_column:
            raise SystemExit("shades.finish is missing; run alembic upgrade 0027 first")
        finishes = {r["option_id"]: r["finish_code"] for r in await conn.fetch(FINISH_SQL)}
        goods = sorted({option.rsplit("-", 1)[0] for option in finishes})
        resolve = Resolver(await conn.fetch(OPTIONS_SQL, goods))
        shades = await serving_shades(conn)
        reviewed_products = {"oy-" + g.lower() for g in goods}
        in_reviewed = [s for s in shades if s[0] in reviewed_products]
        matched = sum(1 for p, s, n, _ in in_reviewed if finish_of(resolve(p, s, n), finishes))
        changes = plan(shades, finishes, resolve)
        print(f"Reviewed options with a finish: {len(finishes):,}")
        print(f"Serving shades of reviewed products: {len(in_reviewed):,}; matched: {matched:,}")
        for wanted, count in sorted(Counter(c[3] or "(clear)" for c in changes).items()):
            print(f"  {wanted}: {count:,}")
        print(f"Database shades to change: {len(changes):,}")
        unmatched = [s for s in in_reviewed if not resolve(s[0], s[1], s[2])]
        mixed = [
            s for s in in_reviewed if len({finishes.get(o) for o in resolve(s[0], s[1], s[2])}) > 1
        ]
        print(f"Not matched to any option: {len(unmatched):,}; options disagree: {len(mixed):,}")
        for label, items in (("not matched", unmatched), ("options disagree", mixed)):
            for product_id, shade_id, name, _ in items[:10]:
                print(f"  {label}: {product_id} {shade_id} {name}")
        seed_counts = update_seed(args.seed, finishes, resolve, args.apply)
        seed_detail = dict(sorted(seed_counts.items()))
        print(f"Seed shades to change: {sum(seed_counts.values()):,} {seed_detail}")
        if not args.apply:
            print("Preview only; no database rows or seed file were changed")
            return
        async with conn.transaction():
            await conn.executemany(
                "UPDATE shades SET finish = $3 WHERE product_id = $1 AND id = $2",
                [(p, s, wanted) for p, s, _, wanted in changes],
            )
            left = plan(await serving_shades(conn), finishes, resolve)
            if left:
                raise SystemExit(f"{len(left)} shades still differ; rolled back")
        print(f"Database shades changed: {len(changes):,}; seed file updated")
    finally:
        await conn.close()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=15432)
    parser.add_argument("--database", default="vishue_db")
    parser.add_argument("--user", default="vishue")
    parser.add_argument("--seed", type=Path, default=API_ROOT / "seed" / "catalog.json")
    parser.add_argument("--apply", action="store_true")
    asyncio.run(run(parser.parse_args()))


if __name__ == "__main__":
    main()

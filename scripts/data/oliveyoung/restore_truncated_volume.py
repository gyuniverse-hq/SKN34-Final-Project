"""Restore OY product volumes that the old 50-character limit cut off.

Run after alembic revision 0025. A value is restored only when the serving value is 49-50
characters long and, once cleaned, a prefix of the cleaned raw notice volume. Placeholder
text taken from the source ("상세페이지 참고") and any other differing value stay as they are.
Without --apply it only prints what would change.
"""

from __future__ import annotations

import argparse
import asyncio
import getpass
import json
import os
import sys
from pathlib import Path

import asyncpg

sys.path.insert(0, str(Path(__file__).resolve().parent))
from build_catalog import API_ROOT, clean  # noqa: E402

FETCH_SQL = """
SELECT p.id, p.volume AS serving, n.volume AS raw
FROM products p
JOIN raw_oy_product_notice n ON p.id = 'oy-' || lower(n.goods_no)
WHERE p.id LIKE 'oy-%'
ORDER BY p.id
"""


def classify(rows) -> tuple[dict[str, tuple[str, str]], dict[str, int]]:
    restore: dict[str, tuple[str, str]] = {}
    counts = {
        "same": 0,
        "restore": 0,
        "cut_but_not_prefix": 0,
        "other_difference": 0,
        "no_raw_volume": 0,
    }
    for row in rows:
        serving = row["serving"] or ""
        full = clean(row["raw"])
        cut = len(serving) in (49, 50)
        # Older builds stored the raw text without clean(), so compare cleaned forms.
        if not full:
            counts["no_raw_volume"] += 1
        elif full == serving:
            counts["same"] += 1
        elif cut and len(full) > len(clean(serving)) and full.startswith(clean(serving)):
            restore[row["id"]] = (serving, full)
            counts["restore"] += 1
        elif cut:
            counts["cut_but_not_prefix"] += 1
        else:
            counts["other_difference"] += 1
    return restore, counts


def update_seed(path: Path, restore: dict[str, tuple[str, str]], apply: bool) -> int:
    seed = json.loads(path.read_text(encoding="utf-8"))
    changed = 0
    for product in seed["products"]:
        target = restore.get(product["id"])
        if target and product.get("volume") == target[0]:
            product["volume"] = target[1]
            changed += 1
    if apply and changed:
        serialized = (json.dumps(seed, ensure_ascii=False, indent=2) + "\n").replace("\n", "\r\n")
        path.write_bytes(serialized.encode("utf-8"))
    return changed


async def run(args: argparse.Namespace) -> None:
    password = os.environ.get("POSTGRES_PASSWORD") or getpass.getpass("Local PostgreSQL password: ")
    conn = await asyncpg.connect(
        host=args.host,
        port=args.port,
        database=args.database,
        user=args.user,
        password=password,
        server_settings={"application_name": "oy_volume_restore"},
    )
    try:
        column_type = await conn.fetchval(
            "SELECT data_type FROM information_schema.columns "
            "WHERE table_name = 'products' AND column_name = 'volume'"
        )
        if column_type != "text":
            raise SystemExit(f"products.volume is {column_type}; run alembic upgrade 0025 first")
        restore, counts = classify(await conn.fetch(FETCH_SQL))
        for name, count in counts.items():
            print(f"{name}: {count:,}")
        for product_id, (old, new) in list(restore.items())[:5]:
            print(f"- {product_id}: {len(old)} -> {len(new)} chars | {new[:80]}")
        seed_changed = update_seed(args.seed, restore, args.apply)
        print(f"Seed products to restore: {seed_changed:,}")
        if not args.apply:
            print("Preview only; no database rows or seed file were changed")
            return
        async with conn.transaction():
            updated = 0
            for product_id, (old, new) in restore.items():
                result = await conn.execute(
                    "UPDATE products SET volume = $1 WHERE id = $2 AND volume = $3",
                    new,
                    product_id,
                    old,
                )
                updated += int(result.split()[-1])
            if updated != len(restore):
                raise SystemExit(f"Updated {updated} rows, expected {len(restore)}; rolled back")
        print(f"Database products restored: {updated:,}; seed file updated: {seed_changed:,}")
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

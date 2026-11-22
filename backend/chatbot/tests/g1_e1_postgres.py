"""Read-only PostgreSQL fingerprint and product/shade identity check for E1.

Run with backend/api's existing Python. This is an evaluation process, never chatbot service code.
No connection string or exception detail is printed.
"""

import asyncio
import json
import os
import sys
from pathlib import Path

from dotenv import dotenv_values
from sqlalchemy import bindparam, text
from sqlalchemy.ext.asyncio import create_async_engine

ROOT = Path(__file__).resolve().parents[3]


async def run(request):
    manifest = json.loads(
        (ROOT / "docs/ai-alignment/04_llm_stage4_evaluation/g1_manifest_PROPOSED.json").read_text(
            encoding="utf-8"
        )
    )["catalogFixtureBinding"]
    env = dotenv_values(Path(os.environ.get("G1_E1_ENV_PATH", ROOT / ".env.local")))
    if not env.get("DATABASE_URL"):
        return {"status": "BLOCKED_DEPENDENCY", "reason": "database_not_configured"}
    engine = create_async_engine(env["DATABASE_URL"], connect_args={"timeout": 15})
    try:
        async with engine.connect() as conn:
            await conn.execute(text("SET TRANSACTION READ ONLY"))
            rows = (await conn.execute(text(manifest["reproductionSqlReadOnly"]))).mappings().all()
            if len(rows) != 1:
                return {"status": "BLOCKED_DATA", "reason": "fixture_row_count_mismatch"}
            fixture = rows[0]
            if (
                fixture["fixture_sha256"] != manifest["fixtureRowSha256PostgresJsonbText"]
                or fixture["value"] != manifest["fixtureRowValue"]
                or fixture["alembic"] != manifest["alembicVersion"]
            ):
                return {"status": "BLOCKED_DATA", "reason": "fixture_fingerprint_mismatch"}
            ids = request.get("productIds", [])
            products, shades = [], []
            if ids:
                query = text(
                    "SELECT id, brand, name, name_ko, category, price_krw FROM public.products "
                    "WHERE id IN :ids"
                ).bindparams(bindparam("ids", expanding=True))
                product_rows = (await conn.execute(query, {"ids": ids})).mappings().all()
                products = [dict(row) for row in product_rows]
                query = text(
                    "SELECT product_id, id, name, hex FROM public.shades WHERE product_id IN :ids"
                ).bindparams(bindparam("ids", expanding=True))
                shade_rows = (await conn.execute(query, {"ids": ids})).mappings().all()
                shades = [dict(row) for row in shade_rows]
            return {
                "status": "OK",
                "fixtureRowSha256": fixture["fixture_sha256"],
                "fixtureValue": fixture["value"],
                "alembicVersion": fixture["alembic"],
                "catalogFixtureRef": manifest["fixtureSnapshotId"],
                "products": products,
                "shades": shades,
                "transactionReadOnly": True,
                "scope": "selected fixture rows and requested product IDs; not a full DB snapshot",
            }
    finally:
        await engine.dispose()


if __name__ == "__main__":
    try:
        sys.stdin.reconfigure(encoding="utf-8")
        sys.stdout.reconfigure(encoding="utf-8")
        print(json.dumps(asyncio.run(run(json.load(sys.stdin))), ensure_ascii=False))
    except Exception as exc:
        print(json.dumps({"status": "BLOCKED_DEPENDENCY", "reason": type(exc).__name__}))

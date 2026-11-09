"""Read-only skincare export using a reviewed category manifest."""

import argparse
import asyncio
import hashlib
import json
import sys
from pathlib import Path

import asyncpg

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "backend" / "api"))
from app.core.config import Settings
from app.repositories.skincare_build_repository import build_snapshot


async def build(args):
    raw = args.manifest.read_bytes()
    manifest = json.loads(raw)
    conn = await asyncpg.connect(
        Settings().database_url.replace("postgresql+asyncpg://", "postgresql://")
    )
    stats = {}
    try:
        await conn.execute("BEGIN ISOLATION LEVEL REPEATABLE READ READ ONLY")
        snapshot = await build_snapshot(conn, manifest, hashlib.sha256(raw).hexdigest(), stats)
    finally:
        await conn.close()
    args.output.write_text(snapshot.model_dump_json(by_alias=True, indent=2), encoding="utf-8")
    print(json.dumps(stats, ensure_ascii=False))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("manifest", type=Path)
    parser.add_argument("output", type=Path)
    asyncio.run(build(parser.parse_args()))

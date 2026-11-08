"""Atomically recompute option matches and publish the skincare snapshot."""

import hashlib
import json
from datetime import UTC, datetime

import asyncpg

from app.core.config import get_settings
from app.repositories.skincare_build_repository import SEED, build_snapshot
from app.schemas.skincare import SkincareSnapshot

LOCK_ID = 7_284_732

MATCH_SQL = (SEED / "match.sql").read_text(encoding="utf-8")
LINK_SQL = (SEED / "link.sql").read_text(encoding="utf-8").replace(":policy", "$1")


async def read_preview(raw_manifest: bytes):
    url = get_settings().database_url.replace("postgresql+asyncpg://", "postgresql://")
    conn = await asyncpg.connect(url)
    try:
        async with conn.transaction(isolation="repeatable_read", readonly=True):
            return await build_snapshot(
                conn, json.loads(raw_manifest), hashlib.sha256(raw_manifest).hexdigest()
            )
    finally:
        await conn.close()


async def refresh(
    raw_manifest: bytes,
    *,
    switch: tuple[str, bool] | None = None,
    expected: SkincareSnapshot | None = None,
) -> str:
    manifest = json.loads(raw_manifest)
    manifest_hash = hashlib.sha256(raw_manifest).hexdigest()
    url = get_settings().database_url.replace("postgresql+asyncpg://", "postgresql://")
    conn = await asyncpg.connect(url)
    try:
        async with conn.transaction(isolation="repeatable_read"):
            if not await conn.fetchval("SELECT pg_try_advisory_xact_lock($1)", LOCK_ID):
                return "busy"
            if switch:
                mapping_id, enabled = switch
                changed = await conn.execute(
                    "UPDATE rec_mapping SET runtime_enabled=$2 WHERE mapping_id=$1",
                    mapping_id,
                    enabled,
                )
                if changed != "UPDATE 1":
                    raise ValueError("Unknown mapping ID")
            snapshot = await build_snapshot(conn, manifest, manifest_hash)
            if not snapshot.options or not snapshot.mappings:
                raise ValueError("Refusing to replace skincare snapshot with empty inputs")
            if expected is not None and expected != snapshot:
                raise ValueError(
                    "Bundle differs from current reviewed data; rebuild before publishing"
                )
            old_payload = await conn.fetchval("SELECT payload FROM skincare_serving WHERE id = 1")
            current = snapshot.model_dump(mode="json", by_alias=True)
            previous = json.loads(old_payload) if old_payload else None
            if previous:
                previous.pop("dataVersion", None)
            current.pop("dataVersion", None)
            if current == previous:
                return "unchanged"
            snapshot.data_version = f"{manifest['version']}-{datetime.now(UTC):%Y%m%dT%H%M%S%fZ}"
            payload = snapshot.model_dump_json(by_alias=True)
            await conn.execute(
                "INSERT INTO skincare_serving (id, data_version, payload) "
                "VALUES (1, $1, $2::jsonb) "
                "ON CONFLICT (id) DO UPDATE SET data_version = EXCLUDED.data_version, "
                "payload = EXCLUDED.payload",
                snapshot.data_version,
                payload,
            )
            return f"published {snapshot.data_version} ({len(snapshot.options)} options)"
    finally:
        await conn.close()

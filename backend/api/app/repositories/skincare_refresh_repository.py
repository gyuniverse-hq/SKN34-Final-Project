"""Atomically recompute option matches and publish the skincare snapshot."""

import hashlib
import json

import asyncpg

from app.core.config import get_settings
from app.repositories.skincare_build_repository import build_snapshot

LOCK_ID = 7_284_732

MATCH_SQL = """
INSERT INTO rec_concern_match (mapping_id, option_id, computed_at)
SELECT mi.mapping_id, oi.option_id, now()
FROM rec_mapping_ingredient mi
JOIN rec_ingredient_link l ON l.ingredient_code = mi.ingredient_code
JOIN raw_oy_option_ingredient oi ON oi.ingredient_id = l.oy_ingredient_id
GROUP BY mi.mapping_id, oi.option_id
HAVING count(DISTINCT mi.ingredient_code) = (
    SELECT count(DISTINCT x.ingredient_code) FROM rec_mapping_ingredient x
    WHERE x.mapping_id = mi.mapping_id
)
"""


async def refresh(raw_manifest: bytes) -> str:
    manifest = json.loads(raw_manifest)
    manifest_hash = hashlib.sha256(raw_manifest).hexdigest()
    url = get_settings().database_url.replace("postgresql+asyncpg://", "postgresql://")
    conn = await asyncpg.connect(url)
    try:
        async with conn.transaction(isolation="repeatable_read"):
            if not await conn.fetchval("SELECT pg_try_advisory_xact_lock($1)", LOCK_ID):
                return "busy"
            state = await conn.fetchrow(
                "SELECT revision, published_revision FROM skincare_refresh_state WHERE id = 1"
            )
            if state is None:
                raise ValueError("Missing skincare refresh state")
            existing_hash = await conn.fetchval(
                "SELECT payload->'sourceManifest'->>'manifestSha256' "
                "FROM skincare_serving WHERE id = 1"
            )
            if state["revision"] == state["published_revision"] and existing_hash == manifest_hash:
                return "unchanged"
            await conn.execute("DELETE FROM rec_concern_match")
            await conn.execute(MATCH_SQL)
            snapshot = await build_snapshot(conn, manifest, manifest_hash)
            if not snapshot.options or not snapshot.mappings:
                raise ValueError("Refusing to replace skincare snapshot with empty inputs")
            snapshot.data_version = f"{manifest['version']}-r{state['revision']}"
            payload = snapshot.model_dump_json(by_alias=True)
            await conn.execute(
                "INSERT INTO skincare_serving (id, data_version, payload) "
                "VALUES (1, $1, $2::jsonb) "
                "ON CONFLICT (id) DO UPDATE SET data_version = EXCLUDED.data_version, "
                "payload = EXCLUDED.payload",
                snapshot.data_version,
                payload,
            )
            await conn.execute(
                "UPDATE skincare_refresh_state SET published_revision = $1 WHERE id = 1",
                state["revision"],
            )
            return f"published {snapshot.data_version} ({len(snapshot.options)} options)"
    finally:
        await conn.close()

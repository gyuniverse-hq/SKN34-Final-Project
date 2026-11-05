"""Requires a migrated disposable copy of the local database."""

import json
import os
from pathlib import Path
from types import SimpleNamespace

import asyncpg
import pytest

from app.repositories import skincare_refresh_repository as repository

URL = os.environ.get("TEST_DATABASE_URL")
pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(not URL, reason="TEST_DATABASE_URL not set"),
]
MANIFEST = Path(__file__).resolve().parents[1] / "skincare_manifest.json"


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.mark.anyio
async def test_refresh_detects_changes_and_rolls_back_invalid_snapshot(monkeypatch):
    monkeypatch.setattr(repository, "get_settings", lambda: SimpleNamespace(database_url=URL))
    url = URL.replace("postgresql+asyncpg://", "postgresql://")
    conn = await asyncpg.connect(url)
    raw = MANIFEST.read_bytes()
    try:
        assert (await repository.refresh(raw)).startswith("published ")
        assert await repository.refresh(raw) == "unchanged"
        before = await conn.fetchval("SELECT payload FROM skincare_serving WHERE id = 1")
        matches = await conn.fetchval("SELECT count(*) FROM rec_concern_match")
        option = json.loads(before)["options"][0]
        await conn.execute(
            "UPDATE raw_oy_price_snapshot SET sale_price = sale_price + 1 "
            "WHERE option_id = $1 AND is_latest = true",
            option["optionId"],
        )
        invalid = json.loads(raw)
        invalid["categories"] = {}
        with pytest.raises(ValueError, match="empty inputs"):
            await repository.refresh(json.dumps(invalid).encode())
        assert await conn.fetchval("SELECT payload FROM skincare_serving WHERE id = 1") == before
        assert await conn.fetchval("SELECT count(*) FROM rec_concern_match") == matches
        assert (await repository.refresh(raw)).startswith("published ")
        updated = json.loads(
            await conn.fetchval("SELECT payload FROM skincare_serving WHERE id = 1")
        )
        actual = next(o for o in updated["options"] if o["optionId"] == option["optionId"])
        assert actual["priceKRW"] == option["priceKRW"] + 1
        single = {m["mappingId"]: m for m in updated["mappings"] if m["mappingType"] == "single"}
        matched_option = next(
            o for o in updated["options"] if set(o["matchedMappingIds"]) & single.keys()
        )
        mapping_id = next(m for m in matched_option["matchedMappingIds"] if m in single)
        code = single[mapping_id]["ingredientCodes"][0]
        await conn.execute(
            "DELETE FROM raw_oy_option_ingredient WHERE option_id = $1 AND ingredient_id IN "
            "(SELECT oy_ingredient_id FROM rec_ingredient_link WHERE ingredient_code = $2)",
            matched_option["optionId"],
            code,
        )
        assert (await repository.refresh(raw)).startswith("published ")
        assert not await conn.fetchval(
            "SELECT EXISTS (SELECT 1 FROM rec_concern_match "
            "WHERE mapping_id = $1 AND option_id = $2)",
            mapping_id,
            matched_option["optionId"],
        )
        updated = json.loads(
            await conn.fetchval("SELECT payload FROM skincare_serving WHERE id = 1")
        )
        actual = next(o for o in updated["options"] if o["optionId"] == matched_option["optionId"])
        assert mapping_id not in actual["matchedMappingIds"]
        async with conn.transaction():
            await conn.execute("SELECT pg_advisory_xact_lock($1)", repository.LOCK_ID)
            assert await repository.refresh(raw) == "busy"
    finally:
        await conn.close()

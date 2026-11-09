"""Requires a migrated disposable copy of the local database."""

import json
import os
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

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
    suffix = uuid4().hex
    goods = f"test-{suffix}"
    options = [f"{goods}-1", f"{goods}-2"]
    previous = await conn.fetchrow(
        "SELECT data_version, payload FROM skincare_serving WHERE id = 1"
    )
    oy_id = mfds_id = function_id = None
    try:
        await conn.execute(
            "INSERT INTO products (id, brand, name, name_ko, category, price_krw, volume, "
            "description, key_ingredients, tags, image_url, search_keyword, search_text) "
            "VALUES ($1, 'test', 'test', 'test', 'skincare', 100, '1', '', '[]', '[]', '', '', '')",
            f"oy-{goods}",
        )
        await conn.execute(
            "INSERT INTO raw_oy_product (goods_no, std_category_code, sale_status, is_in_catalog) "
            "VALUES ($1, '크림', '정상', true)",
            goods,
        )
        for option_id in options:
            await conn.execute(
                "INSERT INTO raw_oy_product_option (option_id, goods_no, option_name) "
                "VALUES ($1, $2, 'test')",
                option_id,
                goods,
            )
            await conn.execute(
                "INSERT INTO raw_oy_price_snapshot (option_id, sale_price, is_sold_out, is_latest) "
                "VALUES ($1, 100, false, true)",
                option_id,
            )
        oy_id = await conn.fetchval(
            "INSERT INTO raw_oy_ingredient (ingredient_name, ingredient_norm) "
            "VALUES ('test', $1) RETURNING ingredient_id",
            suffix,
        )
        mfds_id = await conn.fetchval(
            "INSERT INTO raw_mfds_ingredient (name_ko, name_key, name_en, source_payload, "
            "source_hash, first_seen_at, last_seen_at, is_current) "
            "VALUES ('test', $1, 'TEST', '{}', $2, now(), now(), true) RETURNING ingredient_id",
            suffix,
            "0" * 64,
        )
        await conn.execute(
            "INSERT INTO oy_mfds_ingredient_map "
            "(oy_ingredient_id, mfds_ingredient_id, match_method, rule_version) "
            "VALUES ($1, $2, 'exact_name', 'test')",
            oy_id,
            mfds_id,
        )
        await conn.executemany(
            "INSERT INTO raw_oy_option_ingredient (option_id, ingredient_id) VALUES ($1, $2)",
            [(option_id, oy_id) for option_id in options],
        )
        function_id = await conn.fetchval(
            "INSERT INTO cosing_function (function_name) VALUES ($1) RETURNING function_id",
            suffix,
        )
        await conn.execute(
            "INSERT INTO cosing_ingredient_lookup "
            "(ingredient_id, status, match_method, query_name, substance_id) "
            "VALUES ($1, 'accepted', 'exact', 'TEST', 'test')",
            mfds_id,
        )
        await conn.execute("INSERT INTO ingredient_function VALUES ($1, $2)", mfds_id, function_id)
        await conn.execute("INSERT INTO function_concern VALUES ($1, 'pores')", function_id)
        result = await repository.refresh(raw)
        assert result == "unchanged" or result.startswith("published ")
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
        single = {
            m["mappingId"]: m for m in updated["mappings"] if m["mappingId"].startswith("cosing:")
        }
        matched_option = next(
            o for o in updated["options"] if set(o["matchedMappingIds"]) & single.keys()
        )
        mapping_id = next(m for m in matched_option["matchedMappingIds"] if m in single)
        ingredient_id = int(single[mapping_id]["ingredientCodes"][0].removeprefix("cosing:mfds:"))
        deleted = await conn.execute(
            "DELETE FROM raw_oy_option_ingredient WHERE option_id = $1 AND ingredient_id IN "
            "(SELECT oy_ingredient_id FROM oy_mfds_ingredient_map WHERE mfds_ingredient_id = $2)",
            matched_option["optionId"],
            ingredient_id,
        )
        assert deleted != "DELETE 0"
        assert (await repository.refresh(raw)).startswith("published ")
        assert await conn.fetchval("SELECT count(*) FROM rec_concern_match") == matches
        updated = json.loads(
            await conn.fetchval("SELECT payload FROM skincare_serving WHERE id = 1")
        )
        actual = next(o for o in updated["options"] if o["optionId"] == matched_option["optionId"])
        assert mapping_id not in actual["matchedMappingIds"]
        async with conn.transaction():
            await conn.execute("SELECT pg_advisory_xact_lock($1)", repository.LOCK_ID)
            assert await repository.refresh(raw) == "busy"
    finally:
        if function_id is not None:
            await conn.execute("DELETE FROM function_concern WHERE function_id = $1", function_id)
            await conn.execute(
                "DELETE FROM ingredient_function WHERE function_id = $1", function_id
            )
            await conn.execute("DELETE FROM cosing_function WHERE function_id = $1", function_id)
        if mfds_id is not None:
            await conn.execute(
                "DELETE FROM cosing_ingredient_lookup WHERE ingredient_id = $1", mfds_id
            )
        if oy_id is not None:
            await conn.execute(
                "DELETE FROM raw_oy_option_ingredient WHERE ingredient_id = $1", oy_id
            )
            await conn.execute(
                "DELETE FROM oy_mfds_ingredient_map WHERE oy_ingredient_id = $1", oy_id
            )
            await conn.execute("DELETE FROM raw_oy_ingredient WHERE ingredient_id = $1", oy_id)
        if mfds_id is not None:
            await conn.execute("DELETE FROM raw_mfds_ingredient WHERE ingredient_id = $1", mfds_id)
        await conn.execute(
            "DELETE FROM raw_oy_price_snapshot WHERE option_id = ANY($1::text[])", options
        )
        await conn.execute("DELETE FROM raw_oy_product_option WHERE goods_no = $1", goods)
        await conn.execute("DELETE FROM raw_oy_product WHERE goods_no = $1", goods)
        await conn.execute("DELETE FROM products WHERE id = $1", f"oy-{goods}")
        await conn.execute("DELETE FROM skincare_serving WHERE id = 1")
        if previous:
            await conn.execute(
                "INSERT INTO skincare_serving (id, data_version, payload) VALUES (1, $1, $2)",
                previous["data_version"],
                previous["payload"],
            )
        await conn.close()

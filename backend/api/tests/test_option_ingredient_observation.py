"""Synthetic observation contract + opt-in isolated PostgreSQL ingestion tests."""

import csv
import json
import os
import sys
from pathlib import Path
from unittest.mock import AsyncMock

import asyncpg
import pytest

from app.repositories.ingredient_repository import IngredientRepository, _source_version
from tests.test_ingredient_api import observation_fixture

SCRIPTS = Path(__file__).resolve().parents[3] / "scripts/data/oliveyoung"
sys.path.insert(0, str(SCRIPTS))
sys.path.insert(0, str(SCRIPTS / "collectors"))
import load_snapshot as loader  # noqa: E402
import oliveyoung_erd_v30 as collector  # noqa: E402
import oliveyoung_skincare_v2 as skincare  # noqa: E402


@pytest.fixture
def anyio_backend():
    return "asyncio"


def record(raw="Water,Salicylic Acid(0.44%),Salicylic Acid", when="2026-11-02 10:00:00"):
    option = dict(goodsNumber="G-SYNTHETIC", optionNumber="001", optionName="Cream")
    return collector.ingredient_observation(
        raw, [option], option, when, "https://example.test/fixture"
    )


def files(tmp_path, observation):
    path = tmp_path / "option_ingredient_observation.csv"
    columns = collector.SCHEMA["option_ingredient_observation"]
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=columns)
        writer.writeheader()
        writer.writerow(observation)
    return {"option_ingredient_observation": (path, columns, 1)}


@pytest.mark.anyio
async def test_equal_timestamp_conflicting_bodies_have_no_latest_winner():
    from datetime import datetime

    raw = (
        "option",
        "goods",
        None,
        None,
        None,
        None,
        None,
        "url",
        "Water",
        datetime(2026, 11, 2),
        None,
    )
    a = observation_fixture(raw, [(1, "Water", 1)])
    b = observation_fixture(raw, [(2, "Panthenol", 1)])
    repository = IngredientRepository(None, mappings=[])
    repository._rows = AsyncMock(return_value=[(a,), (b,)])
    latest, rows = await repository._observations(["option"])
    assert latest == rows == {}


@pytest.mark.anyio
@pytest.mark.skipif(not os.getenv("G_TEST_DSN"), reason="requires isolated G_TEST_DSN")
async def test_postgres_atomic_replay_history_and_originals(tmp_path):
    dsn = os.environ["G_TEST_DSN"]
    assert "127.0.0.1:15439/" in dsn, "Only the dedicated G restore may be mutated"
    conn = await asyncpg.connect(dsn)
    transaction = conn.transaction()
    await transaction.start()
    try:
        await conn.execute("INSERT INTO raw_oy_product(goods_no) VALUES ('G-SYNTHETIC')")
        await conn.execute(
            "INSERT INTO raw_oy_product_option(option_id,goods_no) "
            "VALUES ('G-SYNTHETIC-001','G-SYNTHETIC')"
        )

        async def ingest(observation):
            loader.validate_observation(observation)
            # Each real invocation commits/discards staging in its transaction.
            await conn.execute("DROP TABLE IF EXISTS pg_temp.stg_option_ingredient_observation")
            batch = files(tmp_path, observation)
            await loader._stage(conn, batch)
            await loader._apply_observations(conn, batch)

        old = record()
        await ingest(old)
        await ingest(old)
        assert (
            await conn.fetchval(
                "SELECT count(*) FROM raw_oy_option_ingredient_observation "
                "WHERE option_id='G-SYNTHETIC-001'"
            )
            == 1
        )
        newer = record("Water,Salicylic Acid", "2026-11-03 10:00:00")
        await ingest(newer)
        await ingest(old)
        latest = await conn.fetchrow(
            "SELECT * FROM raw_oy_option_ingredient_observation "
            "WHERE option_id='G-SYNTHETIC-001' "
            "ORDER BY collected_at DESC LIMIT 1"
        )
        assert latest["source_version"] == newer["source_version"] != old["source_version"]
        assert latest["raw_text"] == "Water,Salicylic Acid"
        original = await conn.fetchval(
            "SELECT entries FROM raw_oy_option_ingredient_observation WHERE source_version=$1",
            old["source_version"],
        )
        assert len(json.loads(original)) == 3
        assert (
            json.loads(original)[1]["ingredient_norm"] == json.loads(original)[2]["ingredient_norm"]
        )
        assert (
            await conn.fetchval(
                "SELECT count(*) FROM raw_oy_ingredient WHERE ingredient_norm='SALICYLICACID'"
            )
            == 1
        )
        with pytest.raises(asyncpg.RaiseError, match="immutable"):
            async with conn.transaction():
                await conn.execute(
                    "UPDATE raw_oy_option_ingredient_observation SET raw_text='wrong' "
                    "WHERE option_id='G-SYNTHETIC-001'"
                )
        # An interrupted transaction leaves no partial observation. Repeating it is safe.
        partial = record("Water,Ceramide NP(1.215ppm)", "2026-11-04 10:00:00")
        with pytest.raises(RuntimeError):
            async with conn.transaction():
                await ingest(partial)
                raise RuntimeError("synthetic interrupted collection")
        assert not await conn.fetchval(
            "SELECT EXISTS(SELECT 1 FROM raw_oy_option_ingredient_observation "
            "WHERE source_version=$1)",
            partial["source_version"],
        )
        await ingest(partial)
        assert (
            await conn.fetchval(
                "SELECT count(*) FROM raw_oy_option_ingredient_observation "
                "WHERE option_id='G-SYNTHETIC-001'"
            )
            == 3
        )
        assert await conn.fetchval("SELECT count(*) FROM aihub_claim_publication") == 0
    finally:
        await transaction.rollback()
        await conn.close()


def test_legacy_fingerprint_cannot_approve_a_new_observation():
    from datetime import datetime

    from app.repositories.ingredient_repository import (
        _observation_gate,
        _prepare_evidence,
        fingerprint,
    )
    from app.schemas.ingredient import IngredientMapping, IngredientReadResult

    raw = (
        "option",
        "goods",
        None,
        None,
        None,
        None,
        None,
        "url",
        "Water",
        datetime(2026, 11, 2),
        None,
    )
    rows = [(1, "Water", 1)]
    obs = observation_fixture(raw, rows)
    legacy = fingerprint([list(raw), [list(r) for r in rows]])
    version = _source_version(raw, rows, obs)
    assert legacy != version
    mapping = IngredientMapping(
        product_id="p",
        mapping_status="directly_reviewed",
        mapping_method="direct_review",
        source_version=legacy,
        review_status="verified",
    )
    result = IngredientReadResult(product_id="p", reason="fixture")
    _prepare_evidence(result, mapping, raw, rows, version)
    assert result.evidence is None and result.reason == "source_version_mismatch"
    assert mapping.review_status == "verified" and mapping.source_version == legacy
    assert not _observation_gate(result, None, raw)
    assert result.reason == "option_original_unavailable"


@pytest.mark.anyio
@pytest.mark.skipif(not os.getenv("G_TEST_DSN"), reason="requires isolated real catalog restore")
async def test_real_options_reconstruct_only_stored_original_without_approval(tmp_path):
    from sqlalchemy import text
    from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

    dsn = os.environ["G_TEST_DSN"]
    assert "127.0.0.1:15439/" in dsn
    engine = create_async_engine(dsn.replace("postgresql://", "postgresql+asyncpg://"))
    ids = [
        "A000000231632-001",
        "A000000185429-002",
        "A000000258296-001",
        "A000000199714-002",
        "A000000244812-001",
    ]
    async with engine.connect() as connection:
        transaction = await connection.begin()
        await connection.execute(text("SELECT 1"))  # Start the driver's transaction before COPY.
        conn = (await connection.get_raw_connection()).driver_connection
        try:
            captured = {}
            for oid in ids:
                raw = await conn.fetchrow(
                    """
                    SELECT o.*,n.ingredients_raw,n.volume,p.product_url
                    FROM raw_oy_product_option o JOIN raw_oy_product p USING(goods_no)
                    JOIN raw_oy_product_notice n USING(goods_no) WHERE o.option_id=$1
                """,
                    oid,
                )
                assert raw is not None
                siblings = await conn.fetch(
                    "SELECT option_no,option_name FROM raw_oy_product_option WHERE goods_no=$1",
                    raw["goods_no"],
                )
                options = [
                    dict(goodsNumber=raw["goods_no"], optionNumber=s[0], optionName=s[1] or "")
                    for s in siblings
                ]
                option = next(o for o in options if o["optionNumber"] == raw["option_no"])
                observation = collector.ingredient_observation(
                    raw["ingredients_raw"],
                    options,
                    option,
                    raw["collected_at"],
                    raw["product_url"],
                    raw["volume"],
                )
                loader.validate_observation(observation)
                await conn.execute("DROP TABLE IF EXISTS pg_temp.stg_option_ingredient_observation")
                batch = files(tmp_path, observation)
                await loader._stage(conn, batch)
                await loader._apply_observations(conn, batch)
                await loader._apply_observations(conn, batch)
                captured[oid] = observation
            session = AsyncSession(bind=connection)
            repository = IngredientRepository(session, mappings=[])
            result = await repository.lookup_options(
                {oid: "oy-" + oid.split("-")[0].lower() for oid in ids}
            )
            for oid, info in result.items():
                original = captured[oid]
                assert info.review.evidence is None and info.review.verdict == "UNKNOWN"
                assert info.observed.observation_version == original["source_version"]
                assert [e.name for e in info.observed.displayed_ingredients] == [
                    e["name"] for e in json.loads(original["entries"])
                ]
                assert all(
                    original["raw_text"][e.source_start : e.source_end] == e.name
                    for e in info.observed.displayed_ingredients
                )
                if oid == "A000000231632-001":
                    assert info.observed.ownership_status == "unknown"
                    assert "세라마이드엔피(1.215ppm)" not in [
                        e.name for e in info.observed.displayed_ingredients
                    ]
                print(
                    f"REAL restored {oid}: {info.observed.parsed_row_count} occurrences; "
                    f"ownership={info.observed.ownership_status}; verdict=UNKNOWN; "
                    f"sourceVersion={info.observed.source_version}"
                )
            assert await conn.fetchval("SELECT count(*) FROM aihub_claim_publication") == 0
        finally:
            await transaction.rollback()
    await engine.dispose()


@pytest.mark.anyio
@pytest.mark.skipif(not os.getenv("G_TEST_DSN"), reason="requires isolated G restore")
async def test_complete_loader_accepts_legacy_then_idempotent_new_snapshot(tmp_path):
    dsn = os.environ["G_TEST_DSN"]
    assert "127.0.0.1:15439/" in dsn
    conn = await asyncpg.connect(dsn)
    outer = conn.transaction()
    await outer.start()
    try:
        observation = record()
        manifest = dict(
            kind="skincare",
            mode="incremental",
            listing_complete=True,
            complete=True,
            jobs=[["fixture", "G-SYNTHETIC"]],
            collected_count=1,
            run_id=8800000000001,
        )
        for modern in (False, True, True):
            manifest["run_id"] = 8800000000002 if modern else 8800000000001
            if modern:
                manifest["observation_version"] = collector.OBSERVATION_VERSION
            for table, columns in skincare.SCHEMA.items():
                with (tmp_path / f"{table}.csv").open("w", encoding="utf-8", newline="") as stream:
                    writer = csv.DictWriter(stream, fieldnames=columns)
                    writer.writeheader()
                    rows = {
                        "crawl_run": [dict(run_id=manifest["run_id"], status="done")],
                        "product": [
                            dict(
                                goods_no="G-SYNTHETIC",
                                product_url=observation["source_url"],
                                first_collected_at=observation["collected_at"],
                                last_collected_at=observation["collected_at"],
                            )
                        ],
                        "product_option": [
                            dict(
                                option_id="G-SYNTHETIC-001",
                                goods_no="G-SYNTHETIC",
                                option_no="001",
                                option_name="Cream",
                                collected_at=observation["collected_at"],
                            )
                        ],
                        "product_notice": [
                            dict(
                                goods_no="G-SYNTHETIC",
                                ingredients_raw=observation["raw_text"],
                                collected_at=observation["collected_at"],
                            )
                        ],
                        "option_ingredient_observation": [observation] if modern else [],
                    }.get(table, [])
                    writer.writerows(rows)
            (tmp_path / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
            batch = loader._files(tmp_path, "skincare")
            for table in [*batch, "writable", "seen_goods"]:
                await conn.execute(f"DROP TABLE IF EXISTS pg_temp.stg_{table}")
            await loader._stage(conn, batch)
            await loader._validate_stage(conn, batch)
            await loader._apply(conn, batch, "skincare", manifest["run_id"], "incremental", {})
            count = await conn.fetchval("""
                SELECT count(*) FROM raw_oy_option_ingredient_observation
                WHERE option_id='G-SYNTHETIC-001'
            """)
            assert count == int(modern)
        # No partial/missing observation file may turn into a completed new-format import.
        path, columns, _ = batch["option_ingredient_observation"]
        path.write_text(",".join(columns) + "\n", encoding="utf-8")
        with pytest.raises(ValueError, match="Exactly one observation"):
            loader._files(tmp_path, "skincare")
    finally:
        await outer.rollback()
        await conn.close()

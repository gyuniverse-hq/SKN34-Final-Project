"""Offline tests for the isolated I-3 seed; no database or Docker calls."""

import asyncio
import importlib.util
from pathlib import Path

import pytest

SCRIPT = Path(__file__).with_name("i3_execution_seed.py")
SPEC = importlib.util.spec_from_file_location("i3_execution_seed", SCRIPT)
seed = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(seed)

TOKEN = "a" * 32
URL = "postgresql+asyncpg://i3_eval:i3_eval@127.0.0.1:15499/i3_eval"


def test_valid_target_requires_exact_isolation_identity_and_output_path():
    assert seed.validate_target(URL, TOKEN, seed.ALLOWED_MAPPING).database == "i3_eval"


@pytest.mark.parametrize(
    "url,token,path",
    [
        ("postgresql+asyncpg://i3_eval:i3_eval@remote:15499/i3_eval", TOKEN, seed.ALLOWED_MAPPING),
        (
            "postgresql+asyncpg://i3_eval:i3_eval@127.0.0.1:15499/postgres",
            TOKEN,
            seed.ALLOWED_MAPPING,
        ),
        ("postgresql+asyncpg://other:i3_eval@127.0.0.1:15499/i3_eval", TOKEN, seed.ALLOWED_MAPPING),
        (
            "postgresql+asyncpg://i3_eval:i3_eval@127.0.0.1:15499/i3_eval?x=y",
            TOKEN,
            seed.ALLOWED_MAPPING,
        ),
        (URL, "not-a-run-id", seed.ALLOWED_MAPPING),
        (URL, TOKEN, Path("not-approved.json")),
    ],
)
def test_invalid_targets_rejected_before_connect_or_write(url, token, path, monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("Must not attempt a connection")

    monkeypatch.setattr(seed, "create_async_engine", forbidden)
    with pytest.raises(ValueError):
        asyncio.run(seed.seed_database(url, token, path, "Q01"))


def test_synthetic_fixture_contract_and_cross_option_ownership():
    fixture, spec, options, fixture_hash = seed.load_scenario(seed.FIXTURE, "O06")
    assert fixture["synthetic"] is True and fixture["productionEvidence"] is False
    assert len(fixture_hash) == 64 and spec["publication"] == "none"
    assert [(o["productId"], o["optionId"], o["ingredientIds"]) for o in options] == [
        ("syn-a", "syn-a-01", ["SYN-G", "SYN-F"]),
        ("syn-a", "syn-b-01", ["SYN-G"]),
    ]
    assert fixture["dictionary"]["sourceHash"] != seed.SOURCE_HASH


def test_page_boundary_is_generated_from_fixture_not_expected_assertions():
    _, _, options, _ = seed.load_scenario(seed.FIXTURE, "O09")
    assert len(options) == 160 and len({o["optionId"] for o in options}) == 160
    assert all(o["collectedSalePriceKRW"] == 90000 for o in options)


def test_unreviewed_and_stock_limitations_remain_explicit():
    _, _, options, _ = seed.load_scenario(seed.FIXTURE, "O05")
    assert options[0]["verification"] == "unknown"
    _, spec, options, _ = seed.load_scenario(seed.FIXTURE, "M02")
    assert spec["overrides"]["syn-a-01.currentStockStatus"] == "in_stock"
    assert options[0]["currentStockStatus"] == "in_stock"
    # load_scenario preserves the request; the real Catalog seed does not invent current stock.


def test_invalid_scenario_does_not_connect_or_write(monkeypatch):
    monkeypatch.setattr(
        seed,
        "create_async_engine",
        lambda *a, **kw: (_ for _ in ()).throw(AssertionError("connected")),
    )
    with pytest.raises(ValueError, match="Unknown scenario"):
        asyncio.run(seed.seed_database(URL, TOKEN, seed.ALLOWED_MAPPING, "Q99"))


class RowResult:
    def __init__(self, row):
        self.row = row

    def one(self):
        return self.row


class Connection:
    def __init__(self, row):
        self.row = row

    async def execute(self, statement):
        return RowResult(self.row)


def test_server_marker_and_identity_must_match():
    asyncio.run(seed.verify_server(Connection(("i3_eval", "i3_eval", TOKEN)), TOKEN))
    for row in [
        ("production", "i3_eval", TOKEN),
        ("i3_eval", "admin", TOKEN),
        ("i3_eval", "i3_eval", None),
        ("i3_eval", "i3_eval", "b" * 32),
    ]:
        with pytest.raises(ValueError, match="identity/run marker"):
            asyncio.run(seed.verify_server(Connection(row), TOKEN))


class OccupiedSession:
    async def scalar(self, statement):
        return 1


def test_occupied_database_is_never_reset():
    with pytest.raises(ValueError, match="not an empty"):
        asyncio.run(seed.assert_empty(OccupiedSession()))

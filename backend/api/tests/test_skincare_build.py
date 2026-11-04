"""Exercise the DB export boundary without accessing or publishing to a shared DB."""

import asyncio
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.schemas.skincare import SkincareSnapshot
from app.services.skincare_service import recommend
from tests.test_skincare import mapping, option, request

SCRIPT = Path(__file__).resolve().parents[3] / "scripts/data/oliveyoung/build_skincare.py"
spec = importlib.util.spec_from_file_location("build_skincare", SCRIPT)
builder = importlib.util.module_from_spec(spec)
spec.loader.exec_module(builder)


@pytest.mark.parametrize("enabled", [False, True])
def test_export_reads_db_components_links_and_option_matches(tmp_path, monkeypatch, enabled):
    m = mapping(runtime_enabled=enabled).model_dump(by_alias=False)
    m["evidence_id"] = "e"
    # Deliberately different raw text: normalized components must win.
    m["ingredient_codes"] = "OLD_SOURCE_CODE"
    queries = []

    async def fetch(sql):
        queries.append(sql)
        if "FROM rec_mapping ORDER" in sql:
            return [m]
        if "FROM rec_evidence" in sql:
            return [{"evidence_id": "e", "title": "Study", "study_limit": "Limited", "pmid": None}]
        if "FROM rec_mapping_ingredient" in sql:
            return [{"mapping_id": "m", "ingredient_code": "A"}]
        if "FROM rec_ingredient_link" in sql:
            return [
                dict(
                    ingredient_code="A",
                    oy_ingredient_id=999,
                    link_method="exact_name",
                    reviewed_by=None,
                    reviewed_at=None,
                )
            ]
        if "FROM rec_concern_match" in sql:
            return [{"mapping_id": "m", "option_id": "a1"}]
        if "FROM products c" in sql:
            assert "raw.is_in_catalog" in sql
            return [
                dict(
                    goods_no="P",
                    std_category_code="cream",
                    catalog_product=option("oy-p").product.model_dump_json(),
                    delisted_at=None,
                    sale_status="SALE",
                )
            ]
        if "FROM raw_oy_product_option" in sql:
            return [
                dict(
                    goods_no="P",
                    option_id=i,
                    option_name=i,
                    delisted_at=None,
                    is_sold_out=False,
                    sale_price=100,
                )
                for i in ("a1", "a2")
            ]
        if "FROM raw_oy_option_ingredient" in sql:
            return [dict(option_id=i, ingredient_code="A") for i in ("a1", "a2")]
        if "FROM raw_oy_review_summary" in sql or "FROM raw_oy_image" in sql:
            return []
        raise AssertionError(sql)

    conn = SimpleNamespace(fetch=fetch, execute=AsyncMock(), close=AsyncMock())
    monkeypatch.setattr(builder.asyncpg, "connect", AsyncMock(return_value=conn))
    monkeypatch.setenv("DATABASE_URL", "postgresql://fixture")
    manifest = tmp_path / "manifest.json"
    manifest.write_text(
        json.dumps(
            dict(
                version="db-test",
                reviewedBy="reviewer",
                categories={"cream": "cream"},
                availableSaleStatuses=["SALE"],
            )
        )
    )
    output = tmp_path / "bundle.json"
    asyncio.run(builder.build(SimpleNamespace(manifest=manifest, output=output)))
    snapshot = SkincareSnapshot.model_validate_json(output.read_text(encoding="utf-8"))
    assert snapshot.mappings[0].ingredient_codes == ["A"]
    assert snapshot.mappings[0].runtime_enabled is enabled
    assert snapshot.evidence["e"]["study_limit"] == "Limited"
    assert snapshot.options[0].product == option("oy-p").product
    assert snapshot.options[1].matched_mapping_ids == []
    assert snapshot.ingredient_provenance["A"]["reviewedBy"] == "db:exact_name"
    expected = ["a1"] if enabled else []
    assert [m.option_id for m in recommend(snapshot, request()).matches] == expected
    conn.execute.assert_awaited_once_with("BEGIN ISOLATION LEVEL REPEATABLE READ READ ONLY")
    conn.close.assert_awaited_once()
    assert all("oy_mfds_ingredient_map" not in sql for sql in queries)

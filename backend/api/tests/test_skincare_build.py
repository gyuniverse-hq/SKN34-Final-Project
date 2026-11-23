"""Exercise the DB export boundary without accessing or publishing to a shared DB."""

import asyncio
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

from app.schemas.skincare import SkincareProfileRequest, SkincareSnapshot
from app.services.skincare_service import recommend_hybrid
from tests.test_skincare import option

SCRIPT = Path(__file__).resolve().parents[3] / "scripts/data/oliveyoung/build_skincare.py"
spec = importlib.util.spec_from_file_location("build_skincare", SCRIPT)
builder = importlib.util.module_from_spec(spec)
spec.loader.exec_module(builder)


def test_export_reads_db_components_links_and_option_matches(tmp_path, monkeypatch):
    queries = []

    async def fetch(sql, *params):
        queries.append(sql)
        if "JOIN oy_mfds_ingredient_map" in sql:
            assert params == (["SALE"], ["cream"])
            return [
                {
                    "option_id": "a2",
                    "mfds_ingredient_id": 42,
                    "oy_ingredient_id": 999,
                    "oy_match_method": "exact_name",
                    "rule_version": "test-rule",
                    "reviewed_by": None,
                    "cosing_match_method": "normalized",
                    "query_name": "VITIS VINIFERA ROOT EXTRACT",
                    "substance_id": "123",
                    "name_en": "Vitis Vinifera (Grape) Root Extract",
                    "target_concern": "pores",
                    "function_names": ["ANTI-SEBUM", "ASTRINGENT"],
                },
                {
                    "option_id": "a1",
                    "mfds_ingredient_id": 43,
                    "oy_ingredient_id": 998,
                    "oy_match_method": "exact_name",
                    "rule_version": "test-rule",
                    "reviewed_by": None,
                    "cosing_match_method": "exact",
                    "query_name": "OLD NAME",
                    "substance_id": "124",
                    "name_en": "Changed Name",
                    "target_concern": "pores",
                    "function_names": ["ASTRINGENT"],
                },
            ]
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
        if "FROM raw_oy_review_survey" in sql:
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
    assert len(snapshot.mappings) == 1
    assert snapshot.evidence == {}
    assert snapshot.options[0].product == option("oy-p").product
    assert snapshot.options[0].matched_mapping_ids == []
    assert snapshot.options[1].matched_mapping_ids == ["cosing:42:pores"]
    cosing = snapshot.mappings[0]
    assert cosing.function_names == ["ANTI-SEBUM", "ASTRINGENT"]
    assert cosing.match_method == "normalized"
    assert "cosing:mfds:42" in snapshot.options[1].ingredient_codes
    assert "cosing:43:pores" not in {m.mapping_id for m in snapshot.mappings}
    assert "A" not in snapshot.ingredient_provenance
    profile = SkincareProfileRequest(detectedConcerns=[{"goal": "pores", "sources": ["analysis"]}])
    assert [m.option_id for m in recommend_hybrid(snapshot, profile).overall_top10] == ["a2"]
    assert not recommend_hybrid(snapshot, SkincareProfileRequest(skinType="dry")).overall_top10
    assert all(
        call.args == ("BEGIN ISOLATION LEVEL REPEATABLE READ READ ONLY",)
        for call in conn.execute.await_args_list
    )
    assert conn.close.await_count == conn.execute.await_count
    assert any("JOIN oy_mfds_ingredient_map" in sql for sql in queries)
    assert not any(
        "FROM rec_mapping" in sql or "FROM rec_ingredient_link" in sql for sql in queries
    )

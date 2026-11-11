"""Validate the CosIng import before it touches persistent data."""

import csv
import importlib.util
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[3] / "scripts/data/recommendation/load_cosing.py"
spec = importlib.util.spec_from_file_location("load_cosing", SCRIPT)
loader = importlib.util.module_from_spec(spec)
spec.loader.exec_module(loader)


def write_csv(path, fields, rows):
    with path.open("w", encoding="utf-8-sig", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def inputs(directory):
    tags = directory / "cosing_function_tags.csv"
    fields = ["functionName", "ingredient_count", *loader.CONCERNS]
    tag = {field: "0" for field in fields}
    tag.update(functionName="ANTI-SEBUM", ingredient_count="1", 유분="1")
    tag["트러블 케어"] = "1"
    tag["모공 케어"] = "1"
    write_csv(tags, fields, [tag])
    fields = [
        "ingredient_id",
        "name_ko",
        "input_inci",
        "mfds_cas",
        "status",
        "method",
        "query_name",
        "http_status",
        "response_count",
        "returned_inci",
        "cosing_cas",
        "substance_id",
        "function_names",
        "detail",
        "updated_at",
    ]
    row = dict.fromkeys(fields, "")
    row.update(
        ingredient_id="1",
        name_ko="성분",
        input_inci="Example",
        status="accepted",
        method="exact",
        query_name="EXAMPLE",
        http_status="200",
        response_count="1",
        returned_inci='["EXAMPLE"]',
        cosing_cas="[]",
        substance_id="42",
        function_names='["ANTI-SEBUM"]',
        updated_at="2026-11-07T00:00:00+00:00",
    )
    write_csv(directory / "cosing_ingredients.csv", fields, [row])
    return row, fields


def test_multi_concern_and_function_are_preserved(tmp_path):
    inputs(tmp_path)
    names, concerns, lookup, links, snapshot = loader.read_inputs(tmp_path)
    assert names == ["ANTI-SEBUM"]
    assert set(concerns) == {
        ("ANTI-SEBUM", "oiliness"),
        ("ANTI-SEBUM", "blemish"),
        ("ANTI-SEBUM", "pores"),
    }
    assert links == [(1, "ANTI-SEBUM")]
    assert lookup[0][1:3] == ("accepted", "exact")
    assert snapshot[0][:2] == (1, "성분")


def test_rejects_duplicate_or_unaccepted_function_rows(tmp_path):
    row, fields = inputs(tmp_path)
    write_csv(tmp_path / "cosing_ingredients.csv", fields, [row, row])
    with pytest.raises(ValueError, match="Duplicate ingredient ID"):
        loader.read_inputs(tmp_path)
    row["status"] = "no_results"
    write_csv(tmp_path / "cosing_ingredients.csv", fields, [row])
    with pytest.raises(ValueError, match="Status and function list disagree"):
        loader.read_inputs(tmp_path)

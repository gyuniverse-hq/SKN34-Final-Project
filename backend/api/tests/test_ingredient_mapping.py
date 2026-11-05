"""Synthetic CSV replay, using the existing production generator without editing it."""

import csv
import importlib.util
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
spec = importlib.util.spec_from_file_location(
    "mapping_audit", ROOT / "scripts/data/oliveyoung/audit_ingredient_mapping.py"
)
audit = importlib.util.module_from_spec(spec)
spec.loader.exec_module(audit)


@pytest.fixture
def snapshot(tmp_path):
    tables = {
        "product": (
            ["goods_no", "goods_name", "brand_code", "category_no", "product_url"],
            [["FIXTURE", "Synthetic Lip", "b", "c", "fixture://only"]],
        ),
        "category": (
            ["category_no", "category_name", "category_path"],
            [["c", "립스틱", "메이크업/립"]],
        ),
        "brand": (["brand_code", "brand_name_ko"], [["b", "Fixture Brand"]]),
        "product_option": (
            ["option_id", "goods_no", "shade_code", "shade_name"],
            [["FIXTURE-A", "FIXTURE", "01", "First"], ["FIXTURE-B", "FIXTURE", "01", "Second"]],
        ),
        "option_color": (
            ["option_id", "hex_code", "collected_at"],
            [["FIXTURE-A", "#112233", "2026-01-01"], ["FIXTURE-B", "#445566", "2026-01-01"]],
        ),
        "price_snapshot": (
            ["option_id", "sale_price", "list_price", "is_latest", "collected_at"],
            [
                ["FIXTURE-A", "10000", "12000", "True", "2026-01-01"],
                ["FIXTURE-B", "11000", "12000", "True", "2026-01-01"],
            ],
        ),
        "image": (["goods_no", "option_id", "image_type", "sort_seq", "image_url"], []),
        "product_texture": (
            ["goods_no", "texture_code", "collected_at"],
            [["FIXTURE", "matte", "2026-01-01"]],
        ),
        "product_notice": (
            ["goods_no", "volume", "collected_at"],
            [["FIXTURE", "1g", "2026-01-01"]],
        ),
    }
    for name, (header, rows) in tables.items():
        with (tmp_path / (name + ".csv")).open("w", encoding="utf-8", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(header)
            writer.writerows(rows)
    inputs = audit._products_from_dir(tmp_path)
    generated = audit.oy_catalog.build_oy_catalog(inputs)
    seed = audit.CatalogBundle(products=generated.products).model_dump(mode="json", by_alias=True)
    client = json.loads(json.dumps(seed))
    client["products"][0]["sourceUrl"] = "fixture://only"
    for s in client["products"][0]["shades"]:
        s["measureMethod"] = "estimated"
    return tmp_path, seed, client


def test_replay_tracks_collision_suffix_and_input_order(snapshot):
    folder, seed, client = snapshot
    replay = audit.replay_snapshot(folder, seed, client)
    assert replay["matches"]
    assert [(r["optionId"], r["shadeId"]) for r in replay["trace"]] == [
        ("FIXTURE-A", "01"),
        ("FIXTURE-B", "01-2"),
    ]
    unanchored = audit.finalize_report({"inputRows": []}, seed, client, folder)
    assert unanchored["summary"] == {"candidate": 2}
    assert not unanchored["exactSnapshotAvailable"]
    assert all(r["mappingMethod"] == "unanchored_replay" for r in unanchored["records"])
    manifest = {
        "inputHashes": replay["inputHashes"],
        "generatorVersion": audit.generator_version(),
        "catalogFingerprint": audit.fingerprint(seed),
        "clientFingerprint": audit.fingerprint(client),
        "generationRecordId": "SYNTHETIC:original-run",
        "command": "SYNTHETIC:build-command",
    }
    report = audit.finalize_report({"inputRows": []}, seed, client, folder, manifest)
    assert report["summary"] == {"reproduced": 2}
    assert report["ingredientReviewApproved"] == 0
    assert all(r["reviewStatus"] == "unreviewed" for r in report["records"])
    options = folder / "product_option.csv"
    lines = options.read_text(encoding="utf-8").splitlines()
    options.write_text("\n".join([lines[0], *reversed(lines[1:])]) + "\n", encoding="utf-8")
    mismatch = audit.finalize_report({"inputRows": []}, seed, client, folder, manifest)
    assert mismatch["summary"] == {"mismatch": 2}
    assert mismatch["replay"]["sourceFingerprint"] != replay["sourceFingerprint"]


def test_current_raw_candidates_never_become_reproduced(snapshot):
    _, seed, client = snapshot
    report = audit.finalize_report(
        {"rawOptions": [["FIXTURE-A", "FIXTURE", "01"], ["FIXTURE-B", "FIXTURE", "01"]]},
        seed,
        client,
    )
    assert report["summary"] == {"ambiguous": 2}
    assert report["exactSnapshotAvailable"] is False
    report = audit.finalize_report({"rawOptions": [["FIXTURE-A", "FIXTURE", "01"]]}, seed, client)
    assert report["summary"] == {"candidate": 1, "unmapped": 1}
    assert all(r["mappingStatus"] != "reproduced" for r in report["records"])

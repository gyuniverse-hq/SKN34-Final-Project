from app.services.look_product_link_service import (
    SOURCE_TYPE,
    plan_links,
    row_id,
    shade_base,
    shade_lookup,
)


def mention(look: str, product: str, **extra) -> dict:
    return {
        "look_id": look,
        "mention_number": 1,
        "video_url": "https://www.youtube.com/watch?v=v1",
        "video_use_evidence": "설명란에 사용 제품으로 기재",
        "product_id": product,
        "path": "oy_confirmed",
        "oy_goods_no": None,
        "oy_option_id": None,
        "similarity": 0.9,
        "makeup_zone": "lip",
        **extra,
    }


def test_shade_base_matches_the_catalog_build() -> None:
    assert shade_base("No.03 Rose Mood", "A1-003") == "no-03-rose-mood"
    assert shade_base(None, "A000000123-003") == "a000000123-003"
    assert shade_base("", "!!") == "shade"


def test_shade_lookup_skips_ids_two_options_could_share() -> None:
    options = [
        {"option_id": "G1-001", "goods_no": "G1", "shade_code": "01"},
        {"option_id": "G1-002", "goods_no": "G1", "shade_code": "02"},
        {"option_id": "G1-003", "goods_no": "G1", "shade_code": "02"},
        {"option_id": "G1-004", "goods_no": "G1", "shade_code": "04"},
    ]
    shades = [("oy-g1", "01"), ("oy-g1", "02"), ("oy-g1", "02-2")]
    assert shade_lookup(options, shades) == {"G1-001": "01"}


def test_plan_keeps_one_row_per_look_product_and_shade() -> None:
    plan = plan_links(
        [
            mention("LOOK-004", "oy-g1", oy_option_id="G1-001"),
            mention("LOOK-004", "oy-g1", oy_option_id="G1-001", mention_number=2),
            mention("LOOK-004", "oy-g1", oy_option_id="G1-009"),
            mention("LOOK-005", "oy-g1", oy_option_id="G1-001"),
        ],
        {"G1-001": "01"},
    )
    assert [(r["look_id"], r["shade_id"]) for r in plan.rows] == [
        ("LOOK-004", "01"),
        ("LOOK-004", None),
        ("LOOK-005", "01"),
    ]
    assert plan.merged == 1
    row = plan.rows[0]
    assert row["id"] == row_id("LOOK-004", "oy-g1", "01")
    assert row["status"] == "unverified" and row["verified"] is False
    assert row["source_type"] == SOURCE_TYPE


def test_products_outside_the_makeup_zones_are_skipped() -> None:
    plan = plan_links(
        [
            mention("LOOK-004", "oy-care", makeup_zone=None),
            mention("LOOK-004", "oy-primer", makeup_zone="primer"),
            mention(
                "LOOK-004", "yt-brow", makeup_zone="brow", path="catalog_link", similarity=None
            ),
        ],
        {},
    )
    assert [r["product_id"] for r in plan.rows] == ["yt-brow"]
    assert plan.skipped_zone == {"(none)": 1, "primer": 1}


def test_row_id_is_stable_and_fits_the_column() -> None:
    first = row_id("LOOK-108", "oy-" + "a" * 61, "shade")
    assert first == row_id("LOOK-108", "oy-" + "a" * 61, "shade")
    assert len(first) <= 64

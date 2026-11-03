from app.schemas.oy_catalog import (
    OyProductInput,
    OyShadeInput,
    catalog_category,
    derive_care_tags,
)
from app.services.oy_catalog import build_oy_catalog


def shade(**kwargs: object) -> OyShadeInput:
    base = {
        "option_id": "A1-001",
        "shade_name": "01 코랄",
        "hex_code": "#C04050",
        "sale_price": 18000,
    }
    base.update(kwargs)
    return OyShadeInput(**base)  # type: ignore[arg-type]


def test_maps_confirmed_hex_and_skips_missing_color_or_price() -> None:
    built = build_oy_catalog(
        [
            OyProductInput(
                goods_no="A000000000001",
                brand_name="퓌",
                goods_name="립틴트",
                category_name="립틴트",
                product_url="https://www.oliveyoung.co.kr/store/goods/getGoodsDetail.do?goodsNo=A000000000001",
                shades=(
                    shade(),
                    shade(option_id="A1-002", shade_name="02", hex_code=None, sale_price=18000),
                ),
            ),
            OyProductInput(
                goods_no="A000000000002",
                brand_name="브랜드",
                goods_name="색 없는 쿠션",
                category_name="쿠션",
                shades=(shade(option_id="B-1", shade_name="기본", hex_code="", sale_price=32000),),
            ),
            OyProductInput(
                goods_no="A000000000003",
                brand_name="브랜드",
                goods_name="가격 없는 블러셔",
                category_name="블러셔",
                shades=(
                    shade(option_id="C-1", hex_code="#AA6688", sale_price=None, list_price=None),
                ),
            ),
            OyProductInput(
                goods_no="A000000000004",
                brand_name="브랜드",
                goods_name="스킨",
                category_name="토너",
                shades=(),
            ),
            OyProductInput(
                goods_no="A000000000005",
                brand_name="브랜드",
                goods_name="수분 크림",
                category_name="스킨케어",
                care_tags=("hydrating",),
                shades=(shade(option_id="S-1", hex_code=None, sale_price=22000),),
            ),
        ]
    )
    assert built.ar_products == 1
    assert built.ar_shades == 1
    assert built.listed_without_color == 2
    assert built.skipped_without_price == 1
    assert built.skipped_unknown_category == 1
    lip = built.products[0]
    assert lip.id == "oy-a000000000001"
    assert lip.makeup_zone == "lip"
    assert lip.shades[0].hex == "#C04050"
    assert lip.price_krw == 18000
    cushion = next(p for p in built.products if p.category == "base")
    assert cushion.makeup_zone is None
    assert cushion.shades == []
    cream = next(p for p in built.products if p.id == "oy-a000000000005")
    assert cream.makeup_zone is None
    assert "hydrating" in cream.tags


def test_leaf_category_is_grouped_from_the_collected_path() -> None:
    # Collected names are leaves; the group comes from the path.
    assert catalog_category("크림", "뷰티 > 스킨케어 > 크림 > 크림") == "스킨케어"
    assert catalog_category("선크림", "뷰티 > 선케어 > 선크림 > 선크림") == "선케어"
    assert catalog_category("시트 마스크", "뷰티 > 마스크팩 > 시트팩 > 시트 마스크") == "스킨케어"
    assert (
        catalog_category("클렌징폼/젤", "뷰티 > 클렌징 > 클렌징폼/젤 > 클렌징폼/젤") == "스킨케어"
    )
    # A leaf that is already a serving key keeps its own name.
    assert catalog_category("립케어", "뷰티 > 메이크업 > 립메이크업 > 립케어") == "립케어"
    # Makeup leaves with no serving key stay out.
    assert catalog_category("컨실러", "뷰티 > 메이크업 > 베이스메이크업 > 컨실러") is None


def test_care_tags_come_from_the_name_and_only_for_care_groups() -> None:
    assert derive_care_tags("수분 진정 크림", "스킨케어") == ("hydrating", "soothing")
    assert derive_care_tags("톤업 선크림", "선케어") == ("brightening",)
    # A makeup group never gets care tags, whatever the name says.
    assert derive_care_tags("수분 립틴트", "립틴트") == ()
    # No keyword means no tag; nothing is guessed.
    assert derive_care_tags("믹순 병풀 클렌징 폼 150ml", "스킨케어") == ()


def test_care_products_keep_an_unknown_texture_and_makeup_does_not() -> None:
    built = build_oy_catalog(
        [
            OyProductInput(
                goods_no="A000000000010",
                brand_name="브랜드",
                goods_name="수분 토너",
                category_name="스킨케어",
                care_tags=("hydrating",),
                shades=(shade(option_id="T-1", hex_code=None, sale_price=15000),),
            ),
            OyProductInput(
                goods_no="A000000000011",
                brand_name="브랜드",
                goods_name="제형 없는 쿠션",
                category_name="쿠션",
                shades=(shade(option_id="U-1", hex_code=None, sale_price=30000),),
            ),
        ]
    )
    toner = next(p for p in built.products if p.id == "oy-a000000000010")
    cushion = next(p for p in built.products if p.id == "oy-a000000000011")
    assert toner.texture is None
    assert cushion.texture == "satin"
    assert built.care_products == 1
    assert built.care_products_tagged == 1

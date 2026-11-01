from app.schemas.oy_catalog import OyProductInput, OyShadeInput
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

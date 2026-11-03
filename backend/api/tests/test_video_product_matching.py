from app.schemas.catalog import Product
from app.services.video_product_matching import (
    candidates,
    classify,
    find_shade,
    normalize,
)


def product(**overrides):
    data = {
        "id": "p1",
        "brand": "브랜드",
        "name": "립 워터 틴트",
        "nameKo": "브랜드 립 워터 틴트",
        "category": "lip",
        "makeupZone": "lip",
        "texture": "glossy",
        "priceKRW": 1000,
        "volume": "4g",
        "shades": [
            {"id": "s1", "name": "04호 핑크", "hex": "#112233"},
            {"id": "s2", "name": "05호 레드", "hex": "#223344"},
        ],
        "description": "",
        "keyIngredients": [],
        "tags": [],
        "imageUrl": "",
        "searchKeyword": "",
    }
    return Product.model_validate(data | overrides)


def test_normalization_and_brand_gate():
    assert normalize("[한정/1+1] 립 틴트 (기획/단품) 4ml") == "립틴트"
    p = product()
    row = {"brand": "다른브랜드", "name": "립 워터 틴트", "option": "04호", "zone": "립"}
    assert candidates(row, [p], {}) == []
    assert candidates(row, [p], {normalize("다른브랜드"): "브랜드"})[0].product.id == "p1"


def test_no_shade_fallback_and_unique_code():
    p = product()
    assert find_shade("원문에 명시 정보 없음", p.shades) is None
    assert find_shade("06호", p.shades) is None
    assert find_shade("04호", p.shades).id == "s1"
    assert find_shade("원문에 명시 정보 없음", p.shades[:1]).id == "s1"


def test_classification_and_conflicts():
    p = product()
    row = {"brand": "브랜드", "name": "립 워터 틴트", "option": "04호", "zone": "립"}
    assert classify(row, candidates(row, [p], {}))[0] == "EXACT_MATCH"
    assert (
        classify(row | {"option": "06호"}, candidates(row | {"option": "06호"}, [p], {}))[0]
        == "VARIANT_MATCH"
    )
    assert classify(row | {"zone": "눈"}, candidates(row, [p], {}))[0] == "REVIEW_REQUIRED"
    assert classify(row, candidates(row, [p, product(id="p2")], {}))[0] == "CANDIDATE_MATCH"
    assert classify(row, [])[0] == "NO_MATCH"

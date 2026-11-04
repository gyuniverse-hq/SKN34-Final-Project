from app.core.oliveyoung_image import public_oliveyoung_image_url
from app.schemas.catalog import Product
from tests.conftest import make_product

GLUED = "https://image.oliveyoung.co.kr/cfimages/cf-goods/uploads/images/thumbnails10/0000/0016/A00000016209254ko.jpg"
FIXED = "https://image.oliveyoung.co.kr/cfimages/cf-goods/uploads/images/thumbnails/10/0000/0016/A00000016209254ko.jpg"


def test_glued_thumbnail_path_gets_a_slash():
    assert public_oliveyoung_image_url(GLUED) == FIXED
    assert public_oliveyoung_image_url(FIXED) == FIXED
    assert public_oliveyoung_image_url("") == ""
    assert public_oliveyoung_image_url("https://shopping-phinf.pstatic.net/a.jpg") == (
        "https://shopping-phinf.pstatic.net/a.jpg"
    )


def test_product_schema_rewrites_oliveyoung_thumbs():
    p = make_product("lip-1", "lip", [("r1", "Rose", "#c0485a")], imageUrl=GLUED)
    assert p.image_url == FIXED
    assert Product.model_validate(p.model_dump(by_alias=True)).image_url == FIXED

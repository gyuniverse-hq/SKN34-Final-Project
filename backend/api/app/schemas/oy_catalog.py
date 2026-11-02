"""Rows the Olive Young raw tables provide to the serving catalog. Not an HTTP schema."""

from pydantic import BaseModel, ConfigDict

# Leaf category name -> (catalog category, AR zone). None zone is listed without live try-on.
ZONE_BY_CATEGORY: dict[str, tuple[str, str | None]] = {
    "립스틱": ("lip", "lip"),
    "립틴트": ("lip", "lip"),
    "립글로스": ("lip", "lip"),
    "립케어": ("lip", "lip"),
    "블러셔": ("cheek", "blush"),
    "아이섀도우": ("eye", "eyeshadow"),
    "아이라이너": ("eye", "eyeliner"),
    "아이브로우": ("eye", "brow"),
    "파운데이션": ("base", "foundation"),
    "쿠션": ("base", "foundation"),
    "립라이너": ("lip", None),
    "마스카라": ("eye", None),
    "스킨케어": ("skincare", None),
    "선케어": ("suncare", None),
}


class OyShadeInput(BaseModel):
    model_config = ConfigDict(frozen=True)

    option_id: str
    shade_name: str
    shade_code: str | None = None
    hex_code: str | None = None
    sale_price: int | None = None
    list_price: int | None = None


class OyProductInput(BaseModel):
    model_config = ConfigDict(frozen=True)

    goods_no: str
    brand_name: str
    goods_name: str
    category_name: str
    product_url: str | None = None
    image_url: str | None = None
    texture_code: str | None = None
    volume: str | None = None
    shades: tuple[OyShadeInput, ...] = ()
    care_tags: tuple[str, ...] = ()

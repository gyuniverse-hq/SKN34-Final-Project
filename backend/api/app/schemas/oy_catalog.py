"""Rows the Olive Young raw tables provide to the serving catalog. Not an HTTP schema.

The leaf-to-group mapping and the care tags live here because both the CSV job and the
raw-table repository need them, and a repository may not import a service.
"""

from pydantic import BaseModel, ConfigDict

# Leaf category name -> (catalog category, AR zone). None zone is listed without live try-on.
ZONE_BY_CATEGORY: dict[str, tuple[str, str | None]] = {
    "립스틱": ("lip", "lip"),
    "립틴트": ("lip", "lip"),
    "립글로스": ("lip", "lip"),
    "립케어": ("lip", "lip"),
    "블러셔": ("cheek", "blush"),
    "하이라이터": ("cheek", "highlighter"),
    "쉐이딩": ("cheek", "contour"),
    "아이섀도우": ("eye", "eyeshadow"),
    "아이라이너": ("eye", "eyeliner"),
    "아이브로우": ("eye", "brow"),
    "파운데이션": ("base", "foundation"),
    "쿠션": ("base", "foundation"),
    "립라이너": ("lip", None),
    "마스카라": ("eye", "mascara"),
    "스킨케어": ("skincare", None),
    "선케어": ("suncare", None),
}

# Collected category names are leaves ("크림", "스킨/토너"). The group is read from the
# path ("뷰티 > 스킨케어 > 크림 > 크림"). Order matters: 선케어 is checked before 스킨케어.
CARE_PATH_TOKENS: tuple[tuple[str, str], ...] = (
    ("선케어", "선케어"),
    ("스킨케어", "스킨케어"),
    ("마스크팩", "스킨케어"),
    ("클렌징", "스킨케어"),
)

# Cosmetic care tags from product names (docs/DATA.md). Not medical claims.
CARE_KEYWORDS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("hydrating", ("수분", "보습", "히알루론", "하이드라", "moist")),
    ("soothing", ("진정", "시카", "센텔라", "카밍", "cica", "sooth")),
    ("oil-control", ("피지", "오일컨트롤", "지성", "oil control", "세범")),
    ("blemish-care", ("트러블", "여드름", "아크네", "acne", "스팟")),
    ("pore-care", ("모공", "pore")),
    ("brightening", ("미백", "브라이트", "톤업", "잡티", "비타민c", "비타민 c", "bright")),
    ("firming", ("주름", "탄력", "레티놀", "콜라겐", "firm", "retinol")),
)


def catalog_category(category_name: str, category_path: str) -> str | None:
    """Group a collected leaf category into a ``ZONE_BY_CATEGORY`` key, or None to skip."""
    if category_name in ZONE_BY_CATEGORY:
        return category_name
    for token, mapped in CARE_PATH_TOKENS:
        if token in category_path:
            return mapped
    return None


def derive_care_tags(name: str, category_name: str) -> tuple[str, ...]:
    """Care tags read from a product name. Only for the two care groups."""
    if category_name not in {"스킨케어", "선케어"}:
        return ()
    blob = name.lower()
    return tuple(tag for tag, words in CARE_KEYWORDS if any(word.lower() in blob for word in words))


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

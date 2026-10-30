from typing import Any, Literal, get_args

from pydantic import Field, SerializerFunctionWrapHandler, model_serializer

from app.schemas.base import ApiModel, OmitNoneModel

ProductCategory = Literal["lip", "cheek", "eye", "base", "skincare", "suncare"]
MakeupZone = Literal[
    "lip",
    "blush",
    "eyeshadow",
    "eyeliner",
    "mascara",
    "highlighter",
    "contour",
    "brow",
    "foundation",
]
Texture = Literal["matte", "velvet", "glossy", "satin", "sheer", "cream", "shimmer"]
ShadowFinish = Literal["matte", "shimmer", "glitter", "glossy"]
LookStep = Literal["prep", "base", "eyes", "cheeks", "lips"]
SkinConcern = Literal[
    "dryness", "oiliness", "sensitivity", "blemish", "pores", "pigmentation", "wrinkles"
]

CATEGORIES: tuple[str, ...] = get_args(ProductCategory)
CONCERNS: tuple[str, ...] = get_args(SkinConcern)


class Shade(OmitNoneModel):
    id: str
    name: str
    hex: str = Field(pattern=r"^#[0-9A-Fa-f]{6}$")
    measure_method: Literal["measured", "user_verified", "estimated", "placeholder"] | None = None
    color_source: (
        Literal[
            "measured",
            "option_chip",
            "color_compare",
            "product_photo",
            "official_hex",
            "placeholder",
        ]
        | None
    ) = None
    color_confidence: float | None = Field(default=None, ge=0, le=1)


class Product(ApiModel):
    id: str
    brand: str
    name: str
    name_ko: str
    category: ProductCategory
    makeup_zone: MakeupZone | None
    texture: Texture | None
    price_krw: int = Field(alias="priceKRW", ge=0)
    volume: str
    shades: list[Shade]
    description: str
    key_ingredients: list[str]
    tags: list[str]
    image_url: str
    search_keyword: str


class LookItem(OmitNoneModel):
    product_id: str
    shade_id: str | None = None
    step: LookStep


HighlightArea = Literal["forehead", "nose_bridge", "under_eye", "chin"]
BlushPlacement = Literal["apple", "under_eye", "side"]
LinerStyle = Literal["classic_winged", "puppy", "tightline"]


class InnerPoint(ApiModel):
    """Pearl accent at the inner eye corner; radius is a share of the eye width."""

    hex: str
    a1: float = Field(ge=0, le=1)
    radius: float = Field(gt=0, le=0.5)


class ZoneGeometry(OmitNoneModel):
    """Shape of a zone; omitted fields use the app's defaults (see `types/index.ts`)."""

    length: float | None = None
    angle: float | None = None
    thickness: float | None = None
    liner_style: LinerStyle | None = None
    liner_softness: float | None = Field(default=None, ge=0, le=1)
    liner_lower: bool | None = None
    liner_lower_thickness: float | None = Field(default=None, ge=0.002, le=0.08)
    upper_line: bool | None = None
    underline: bool | None = None
    underline_thickness: float | None = Field(default=None, ge=0, le=0.05)
    underline_alpha: float | None = Field(default=None, ge=0, le=1)
    underline_start: float | None = Field(default=None, ge=0, le=1)
    underline_length: float | None = Field(default=None, ge=0, le=1)
    underline_join: bool | None = None
    lower: bool | None = None
    overlip: float | None = Field(default=None, ge=0, le=0.06)
    peak_overdraw: float | None = Field(default=None, ge=0, le=0.05)
    center_highlight: float | None = Field(default=None, ge=0, le=0.3)
    inner_point: InnerPoint | None = None
    areas: list[HighlightArea] | None = None
    pearl: float | None = Field(default=None, ge=0, le=0.5)
    sparkle: float | None = Field(default=None, ge=0, le=1)
    glitter: bool | None = None
    shadow_finish: ShadowFinish | None = None
    blush_placement: BlushPlacement | None = None
    blush_size: float | None = Field(default=None, gt=0, le=2.5)
    blush_softness: float | None = Field(default=None, ge=0, le=1)
    intensity: float | None = Field(default=None, ge=0, le=1)


class ZoneSetting(OmitNoneModel):
    hex: str = Field(pattern=r"^#[0-9A-Fa-f]{6}$")
    hex_to: str | None = None
    intensity: float = Field(ge=0, le=1)
    texture: Texture
    geometry: ZoneGeometry | None = None


class MakeupState(ApiModel):
    lip: ZoneSetting | None
    blush: ZoneSetting | None
    eyeshadow: ZoneSetting | None
    # Added later: optional, so looks stored with only the first three zones still validate.
    eyeliner: ZoneSetting | None = None
    mascara: ZoneSetting | None = None
    highlighter: ZoneSetting | None = None
    contour: ZoneSetting | None = None
    brow: ZoneSetting | None = None
    foundation: ZoneSetting | None = None

    @model_serializer(mode="wrap")
    def _omit_empty_added_zones(self, handler: SerializerFunctionWrapHandler) -> dict[str, Any]:
        """The three original zones are always sent; zones added later are left out when empty."""
        data = handler(self)
        for key in ("eyeliner", "mascara", "highlighter", "contour", "brow", "foundation"):
            if data.get(key) is None:
                data.pop(key, None)
        return data


class ColorLink(ApiModel):
    """Zones that share one color; a product change in one is followed by the others."""

    zones: list[MakeupZone]
    hex: str = Field(pattern=r"^#[0-9A-Fa-f]{6}$")
    follow_on_change: bool


class CelebLook(OmitNoneModel):
    id: str
    title: str
    inspiration: str
    description: str
    thumbnail_url: str
    tutorial_query: str
    items: list[LookItem]
    makeup: MakeupState
    color_links: list[ColorLink] | None = None
    hero_zones: list[MakeupZone] | None = None
    step_order: list[MakeupZone] | None = None
    tags: list[str]


class Store(OmitNoneModel):
    id: str
    name: str
    address: str
    district: str
    lat: float
    lng: float
    hours: str
    phone: str | None = None
    pickup_available: bool


class CatalogBundle(ApiModel):
    """Seed file format: the same shapes as `data/catalog/*.ts`."""

    products: list[Product] = []
    looks: list[CelebLook] = []
    stores: list[Store] = []


class ProductsResponse(ApiModel):
    products: list[Product]


class ProductResponse(ApiModel):
    product: Product


class LooksResponse(ApiModel):
    looks: list[CelebLook]


class LookDetailResponse(ApiModel):
    look: CelebLook
    products: list[Product]


class StoresResponse(ApiModel):
    stores: list[Store]

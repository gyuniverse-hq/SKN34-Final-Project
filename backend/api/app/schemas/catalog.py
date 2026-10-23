from typing import Literal, get_args

from pydantic import Field

from app.schemas.base import ApiModel, OmitNoneModel

ProductCategory = Literal["lip", "cheek", "eye", "base", "skincare", "suncare"]
MakeupZone = Literal["lip", "blush", "eyeshadow"]
Texture = Literal["matte", "velvet", "glossy", "satin", "sheer", "cream", "shimmer"]
LookStep = Literal["prep", "base", "eyes", "cheeks", "lips"]

CATEGORIES: tuple[str, ...] = get_args(ProductCategory)


class Shade(ApiModel):
    id: str
    name: str
    hex: str = Field(pattern=r"^#[0-9A-Fa-f]{6}$")


class Product(ApiModel):
    id: str
    brand: str
    name: str
    name_ko: str
    category: ProductCategory
    makeup_zone: MakeupZone | None
    texture: Texture
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


class ZoneSetting(ApiModel):
    hex: str
    intensity: float = Field(ge=0, le=1)
    texture: Texture


class MakeupState(ApiModel):
    lip: ZoneSetting | None
    blush: ZoneSetting | None
    eyeshadow: ZoneSetting | None


class CelebLook(ApiModel):
    id: str
    title: str
    inspiration: str
    description: str
    thumbnail_url: str
    tutorial_query: str
    items: list[LookItem]
    makeup: MakeupState
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

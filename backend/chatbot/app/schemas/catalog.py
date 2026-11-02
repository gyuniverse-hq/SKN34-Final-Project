"""Subset of the api service's catalog contract that the graph needs. Unknown fields are ignored."""

from pydantic import BaseModel, ConfigDict, Field
from pydantic.alias_generators import to_camel


class _CatalogModel(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True, extra="ignore")


class CatalogShade(_CatalogModel):
    id: str
    name: str
    hex: str


class CatalogProduct(_CatalogModel):
    """keyIngredients is partial information, never a verified full ingredient list."""

    id: str
    brand: str
    name: str
    name_ko: str
    category: str
    makeup_zone: str | None = None
    texture: str | None
    price_krw: int = Field(alias="priceKRW")
    description: str
    key_ingredients: list[str]
    tags: list[str]
    shades: list[CatalogShade]


class CatalogLookItem(_CatalogModel):
    product_id: str
    shade_id: str | None = None
    step: str


class CatalogLook(_CatalogModel):
    id: str
    title: str
    tags: list[str]
    items: list[CatalogLookItem]

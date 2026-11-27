"""Server-only, conversation-scoped user declarations; never durable inventory memory."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field
from pydantic.alias_generators import to_camel

from app.schemas.catalog import OptionSearchResponse, PriceBasis, SearchIngredient
from app.schemas.style_recipe import LookKind, Zone


class OwnershipDeclaration(BaseModel):
    source: Literal["user"] = "user"
    status: Literal["missing", "present"]
    quote: str = Field(min_length=1, max_length=500)


class OwnedLookFilters(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True, extra="forbid")

    source: Literal["user"] = "user"
    max_price_krw: int | None = Field(default=None, alias="maxPriceKRW", ge=0, le=100_000_000)
    ingredient_conditions: list[SearchIngredient] = Field(default_factory=list, max_length=6)
    fragrance_free: bool = False
    price_basis: PriceBasis = "collected_snapshot"
    unsupported: list[str] = Field(default_factory=list, max_length=8)


class OwnedLookContext(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True, extra="forbid")

    kind: LookKind
    look_id: str
    recipe_version: str
    version: int = Field(default=1, ge=1)
    # Closed Zone enum naturally bounds this map to nine areas.
    declarations: dict[Zone, OwnershipDeclaration] = Field(default_factory=dict)
    filters: OwnedLookFilters = Field(default_factory=OwnedLookFilters)


class OwnedLookOptionRef(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True, extra="forbid")

    product_id: str
    shade_id: str | None = None
    option_id: str
    product_name: str
    brand: str
    shade_name: str


class OwnedLookOptionDisplay(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True, extra="forbid")

    selections: list[OwnedLookOptionRef] = Field(default_factory=list)
    batches: list[OptionSearchResponse] = Field(default_factory=list)
    failed_product_ids: list[str] = Field(default_factory=list)

"""Sale identity and recorded price; independent of AR capability."""

from typing import Literal

from pydantic import Field

from app.schemas.base import ApiModel


class ProductOptionImage(ApiModel):
    url: str
    kind: Literal["option", "color_chip", "color_compare"]


class ProductOption(ApiModel):
    product_id: str
    option_id: str
    name: str
    price_krw: int | None = Field(default=None, alias="priceKRW")
    price_basis: Literal["collected_snapshot"] = "collected_snapshot"
    observed_at: str | None = None
    source_url: str | None = None
    image: ProductOptionImage | None = None
    ar_shade_id: str | None = None

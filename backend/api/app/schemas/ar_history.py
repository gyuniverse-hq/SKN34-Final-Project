from typing import Annotated, Literal
from uuid import UUID

from pydantic import AwareDatetime, Field, model_validator

from app.schemas.catalog import MakeupZone
from app.schemas.skincare import StrictModel

CatalogId = Annotated[str, Field(min_length=1, max_length=64)]


class ShadeRef(StrictModel):
    product_id: CatalogId
    shade_id: CatalogId


class Candidate(ShadeRef):
    candidate_id: UUID


class RankPalette(StrictModel):
    request_id: UUID
    session_id: UUID
    makeup_zone: Literal["lip", "blush"]
    shades: list[ShadeRef] = Field(max_length=10000)

    @model_validator(mode="after")
    def unique_shades(self):
        if len({(row.product_id, row.shade_id) for row in self.shades}) != len(self.shades):
            raise ValueError("duplicate shade")
        return self


class RankedPalette(StrictModel):
    request_id: UUID
    candidates: list[Candidate]


class PaletteRequest(StrictModel):
    request_id: UUID
    session_id: UUID
    makeup_zone: Literal["lip", "blush"]
    direction: Literal["similar", "lighter", "darker", "muted", "vivid", "rating", "personalized"]
    candidates: list[Candidate] = Field(max_length=1000)

    @model_validator(mode="after")
    def unique_candidates(self):
        if self.direction in ("rating", "personalized") and len(self.candidates) > 3:
            raise ValueError("at most three suggested chips")
        keys = {(c.product_id, c.shade_id) for c in self.candidates}
        if len(keys) != len(self.candidates) or len(
            {c.candidate_id for c in self.candidates}
        ) != len(keys):
            raise ValueError("duplicate candidate")
        return self


class PaletteZone(StrictModel):
    makeup_zone: Literal["lip", "blush"]


class ProductRating(StrictModel):
    product_id: str
    rating: float
    reviews: int


class ShadePreference(StrictModel):
    product_id: str
    shade_id: str
    weight: float


class PaletteInputs(StrictModel):
    ratings: list[ProductRating]
    preferences: list[ShadePreference]


class Impression(StrictModel):
    impression_id: UUID
    candidate_id: UUID
    view_instance_id: UUID
    displayed_position: int = Field(ge=1, le=1000, strict=True)
    occurred_at: AwareDatetime
    visibility_policy_version: Literal["arc-inner-500ms-v1", "direct-interaction-v1"]


class Activity(StrictModel):
    event_id: UUID
    session_id: UUID
    product_id: CatalogId
    shade_id: CatalogId
    makeup_zone: MakeupZone
    event_type: Literal["try_on", "cart_add"]
    impression_id: UUID | None = None
    occurred_at: AwareDatetime

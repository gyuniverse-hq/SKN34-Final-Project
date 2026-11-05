from typing import Literal

from pydantic import ConfigDict, Field, field_validator

from app.schemas.base import ApiModel
from app.schemas.catalog import CONCERNS, Product, SkinConcern


class SkinRecommendationRequest(ApiModel):
    """Only user-confirmed concern codes; no photos, model grades or survey answers."""

    model_config = ConfigDict(extra="forbid")

    concerns: list[SkinConcern] = Field(max_length=7)
    limit: int = Field(default=8, ge=1, le=20, strict=True)

    @field_validator("concerns")
    @classmethod
    def canonical_concerns(cls, value: list[SkinConcern]) -> list[SkinConcern]:
        return [concern for concern in CONCERNS if concern in value]


class SkinRecommendationMatch(ApiModel):
    product: Product
    matched_concerns: list[SkinConcern]
    # Count of matching concerns, not a probability or a clinical efficacy score.
    score: int = Field(ge=1, le=7)


class SkinRecommendationResponse(ApiModel):
    strategy_version: Literal["skin-concern-v1"] = "skin-concern-v1"
    concerns: list[SkinConcern]
    status: Literal["ok", "no_concerns", "empty_catalog", "no_matches"]
    matches: list[SkinRecommendationMatch]

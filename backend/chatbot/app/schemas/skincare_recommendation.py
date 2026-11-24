"""Contract for the independent, non-recording skincare recommendation tool."""

from typing import Annotated, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator
from pydantic.alias_generators import to_camel

from app.schemas.catalog import CatalogProduct

SkinGoal = Literal[
    "dryness", "sensitivity", "pigmentation", "wrinkles", "pores", "oiliness", "blemish"
]
SkinType = Literal["dry", "balanced", "oily", "unknown"]
ReasonSource = Literal[
    "analysis", "survey", "skinType", "skinProfile", "concern", "analysisSupport", "conversation"
]


class SkincareToolInput(BaseModel):
    """Only explicitly supplied conversation goals and skin characteristics are accepted."""

    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True, extra="forbid")

    goals: list[SkinGoal] = Field(min_length=1, max_length=7)
    skin_type: SkinType | None = None
    irritation_signal: Literal["caution", "none", "unknown"] | None = None

    @model_validator(mode="after")
    def unique_goals(self) -> Self:
        if len(set(self.goals)) != len(self.goals):
            raise ValueError("Duplicate skincare goals")
        return self


class _ResponseModel(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True, extra="ignore")


class SkincareProduct(CatalogProduct):
    id: str = Field(min_length=1, max_length=128, pattern=r"\S")
    category: Literal["skincare"]
    volume: str
    image_url: str
    search_keyword: str


class SkincareReason(_ResponseModel):
    goal: SkinGoal
    sources: list[ReasonSource] = Field(min_length=1)
    ingredient_codes: list[Annotated[str, Field(min_length=1, pattern=r"\S")]] = Field(min_length=1)
    evidence_level: Literal["ingredient_presence"]
    evidence_sources: list[Literal["cosing_function"]] = Field(min_length=1)


class SkincareMatch(_ResponseModel):
    product: SkincareProduct
    option_id: str = Field(min_length=1, max_length=128, pattern=r"\S")
    option_name: str
    price_krw: int = Field(alias="priceKRW", strict=True, ge=0)
    reasons: list[SkincareReason] = Field(min_length=1)


class SkincareCoverage(_ResponseModel):
    goal: SkinGoal
    status: Literal["ok", "mapping_unavailable", "no_matches"]


class SkincareRecommendation(_ResponseModel):
    strategy_version: Literal["skincare-v4"]
    data_version: Annotated[str, Field(min_length=1, pattern=r"\S")] | None
    coverage: list[SkincareCoverage]
    overall_top5: list[SkincareMatch] = Field(max_length=5)
    overall_top10: list[SkincareMatch] = Field(max_length=10)
    by_concern: dict[SkinGoal, list[SkincareMatch]]
    balance_matches: list[SkincareMatch] | None = None

    @model_validator(mode="after")
    def check_ranking(self) -> Self:
        if self.overall_top5 != self.overall_top10[:5]:
            raise ValueError("Inconsistent skincare recommendation ranking")
        product_ids = [match.product.id for match in self.overall_top10]
        if len(set(product_ids)) != len(product_ids):
            raise ValueError("Duplicate skincare recommendation product")
        goals = [item.goal for item in self.coverage]
        if len(set(goals)) != len(goals):
            raise ValueError("Duplicate skincare coverage")
        if self.data_version is None and (
            self.overall_top10 or any(self.by_concern.values()) or self.balance_matches
        ):
            raise ValueError("Recommendations lack a data version")
        return self

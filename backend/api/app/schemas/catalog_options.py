from typing import Literal, Self

from pydantic import AwareDatetime, ConfigDict, Field, model_validator

from app.schemas.base import ApiModel
from app.schemas.ingredient import IngredientReadResult

Verdict = Literal["MATCH", "NOT_MATCH", "UNKNOWN", "ERROR"]
PriceBasis = Literal["current_sale", "collected_sale"]
StockStatus = Literal["in_stock", "sold_out", "unknown"]


class IngredientFilter(ApiModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    ingredient_name: str = Field(min_length=1, max_length=500)
    operator: Literal["includes", "excludes"]


class OptionSearchRequest(ApiModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    category_id: str = Field(min_length=1, max_length=64)
    product_id: str | None = Field(default=None, min_length=1, max_length=128)
    option_id: str | None = Field(default=None, min_length=1, max_length=128)
    max_price_krw: int | None = Field(default=None, gt=0, strict=True, alias="maxPriceKRW")
    price_basis: PriceBasis = "current_sale"
    ingredient_conditions: list[IngredientFilter] = Field(default_factory=list, max_length=6)
    ingredient_evidence_since: AwareDatetime | None = None
    offset: int = Field(default=0, ge=0, strict=True)
    limit: int = Field(default=12, ge=1, le=32, strict=True)

    @model_validator(mode="after")
    def check_selection(self) -> Self:
        if self.option_id is not None and self.product_id is None:
            raise ValueError("optionId requires productId")
        return self


class OptionCategory(ApiModel):
    category_id: str
    parent_id: str | None
    name: str | None
    path: str | None
    depth: int | None


class OptionCategoriesResponse(ApiModel):
    categories: list[OptionCategory]


class CollectedOptionPrice(ApiModel):
    evidence_id: str
    source: Literal["oliveyoung_price_snapshot"] = "oliveyoung_price_snapshot"
    source_url: str | None
    sale_price_krw: int | None = Field(alias="salePriceKRW")
    list_price_krw: int | None = Field(alias="listPriceKRW")
    collected_at_raw: str | None
    stock_status: StockStatus


class OptionPrice(ApiModel):
    reference_price_krw: int | None = Field(alias="referencePriceKRW")
    reference_source: Literal["catalog_reference"] = "catalog_reference"
    collected: CollectedOptionPrice | None
    current_sale_price_krw: int | None = Field(default=None, alias="currentSalePriceKRW")
    current_stock_status: StockStatus = "unknown"


class DisplayedIngredient(ApiModel):
    name: str
    sequence: int | None


class ObservedOptionLabel(ApiModel):
    source: Literal["oliveyoung_product_notice"] = "oliveyoung_product_notice"
    source_url: str | None
    collected_at_raw: str | None
    source_version: str
    has_product_notice: bool
    parsed_row_count: int
    displayed_ingredients: list[DisplayedIngredient]


class OptionIngredientInformation(ApiModel):
    observed: ObservedOptionLabel | None = None
    review: IngredientReadResult
    error_code: str | None = None


class OptionCandidate(ApiModel):
    product_id: str
    product_name: str
    catalog_category: str
    category: OptionCategory
    option_id: str
    option_name: str | None
    price: OptionPrice


class BudgetDecision(ApiModel):
    condition: Literal["budget"] = "budget"
    price_basis: PriceBasis
    max_price_krw: int = Field(alias="maxPriceKRW")
    verdict: Verdict
    reason: str
    evidence_id: str | None = None


class EvaluatedOption(OptionCandidate):
    ingredients: OptionIngredientInformation
    budget_condition: BudgetDecision | None = None
    required_verdict: Verdict


class OptionSearchScope(ApiModel):
    request: OptionSearchRequest
    category: OptionCategory
    candidate_count: int
    evaluated_count: int
    next_offset: int | None
    exhaustive: bool
    options_with_lookup_errors: int


class OptionSearchResponse(ApiModel):
    status: Literal["matches", "no_matches", "unconfirmed", "search_incomplete", "partial_failure"]
    scope: OptionSearchScope
    matches: list[EvaluatedOption]
    excluded: list[EvaluatedOption]
    unconfirmed: list[EvaluatedOption]

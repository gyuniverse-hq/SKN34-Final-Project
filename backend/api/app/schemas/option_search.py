"""Bounded option search; facts and predicate verdicts are separate from language."""

from typing import Annotated, Literal, Self

from pydantic import AwareDatetime, Field, NaiveDatetime, model_validator

from app.schemas.catalog import Product
from app.schemas.ingredient import IngredientModel, IngredientSelection

Verdict = Literal["MATCH", "NOT_MATCH", "UNKNOWN", "ERROR"]
PriceBasis = Literal["current_offer", "catalog_reference", "collected_snapshot"]


class SearchIngredient(IngredientModel):
    ingredient_name: str = Field(min_length=1, max_length=500)
    operator: Literal["includes", "excludes"]


BaseProductType = Literal["foundation", "cushion"]


class OptionSearchRequest(IngredientModel):
    product_type: BaseProductType | None = Field(default=None, exclude_if=lambda v: v is None)
    query: str = Field(default="", max_length=80)
    category: Literal["lip", "cheek", "eye", "base", "skincare", "suncare"] | None = None
    product_ids: list[str] | None = Field(default=None, max_length=6)
    option_scope: list[IngredientSelection] | None = Field(default=None, max_length=42)
    texture: Literal["matte"] | None = None
    max_price_krw: int | None = Field(
        default=None, alias="maxPriceKRW", strict=True, ge=0, le=100_000_000
    )
    price_basis: PriceBasis = "collected_snapshot"
    ingredient_conditions: list[SearchIngredient] = Field(default_factory=list, max_length=6)
    fragrance_free: bool = Field(default=False, strict=True)
    moisturizing: bool = Field(default=False, strict=True)
    unsupported_conditions: list[Annotated[str, Field(min_length=1, max_length=500)]] = Field(
        default_factory=list, max_length=8
    )

    @model_validator(mode="after")
    def bounded_scope(self) -> Self:
        if self.product_type and self.category != "base":
            raise ValueError("A base category is required for a base product type")
        if not self.category and not self.query.strip() and self.product_ids is None:
            raise ValueError("A category, query or explicit previous scope is required")
        if self.option_scope is not None and (
            self.product_ids is None
            or any(
                r.product_id not in self.product_ids or not r.option_id for r in self.option_scope
            )
        ):
            raise ValueError("Option scope must belong to explicit products")
        return self


class OptionCheck(IngredientModel):
    condition: str
    verdict: Verdict
    reason: str
    ingredient_name: str | None = None
    operator: Literal["includes", "excludes"] | None = None
    evidence_id: str | None = None
    source_version: str | None = None
    source_ref: str | None = None
    review_ref: str | None = None
    observed_at: AwareDatetime | None = None
    reviewed_at: AwareDatetime | None = None
    ingredient_coverage: Literal["full", "partial", "unknown"] | None = None
    normalization_status: Literal["verified", "unverified"] | None = None
    review_status: Literal["verified", "unreviewed", "rejected"] | None = None
    limitations: list[str] = Field(default_factory=list)
    texture_basis: (
        Literal[
            "product_name", "review_survey", "review_ai", "catalog_metadata", "official_reviewed"
        ]
        | None
    ) = None
    texture_code: str | None = None


class OptionPrice(IngredientModel):
    requested_basis: PriceBasis
    observed_basis: Literal["catalog_reference", "collected_snapshot"]
    amount_krw: int = Field(alias="amountKRW", ge=0)
    observed_at: AwareDatetime | None = None
    observed_at_raw: NaiveDatetime | None = None
    limitations: list[str] = Field(default_factory=list)
    checked_at: AwareDatetime
    source_ref: str
    source_version: str


class OptionCandidate(IngredientSelection):
    option_name: str | None = Field(default=None, exclude_if=lambda v: v is None)
    product_type: BaseProductType | None = Field(default=None, exclude_if=lambda v: v is None)
    option_id: str = Field(min_length=1, max_length=128)
    source_version: str
    group: Literal["ELIGIBLE", "REFERENCE_ONLY", "EXCLUDED"]
    checks: list[OptionCheck] = Field(min_length=1)
    price: OptionPrice | None = None
    synthetic: bool = False
    ingredient_entry_count: int | None = Field(default=None, ge=0)
    ingredient_identity_count: int | None = Field(default=None, ge=0)

    @model_validator(mode="after")
    def group_matches_checks(self) -> Self:
        if (self.ingredient_entry_count is None) != (self.ingredient_identity_count is None):
            raise ValueError("Incomplete ingredient counts")
        if (
            self.ingredient_entry_count is not None
            and self.ingredient_identity_count > self.ingredient_entry_count
        ):
            raise ValueError("Invalid ingredient counts")
        verdicts = {c.verdict for c in self.checks}
        expected = (
            "EXCLUDED"
            if "NOT_MATCH" in verdicts
            else "ELIGIBLE"
            if verdicts == {"MATCH"}
            else "REFERENCE_ONLY"
        )
        if self.group != expected:
            raise ValueError("Candidate group contradicts conditions")
        return self


class CheckedScope(IngredientModel):
    candidate_products: int = Field(ge=0)
    candidate_options: int = Field(ge=0)
    checked_options: int = Field(ge=0)
    unidentified_options: int = Field(ge=0)
    exhaustive: bool
    stopped_reason: Literal[
        "COMPLETE", "PRODUCT_LIMIT", "WORK_LIMIT", "TIMEOUT", "INGREDIENT_CONFIRMATION"
    ]
    errors: int = Field(ge=0)


class OptionIngredientResolution(IngredientModel):
    ingredient_name: str = Field(min_length=1, max_length=500)
    operator: Literal["includes", "excludes"]
    status: Literal[
        "resolved",
        "literal",
        "unresolved",
        "ambiguous",
        "unverified_alias",
        "unsupported_group",
        "conflict",
    ]
    canonical_name: str | None = None
    suggestions: list[str] = Field(default_factory=list, max_length=3)


class OptionSearchResponse(IngredientModel):
    ingredient_resolutions: list[OptionIngredientResolution] = Field(
        default_factory=list, max_length=6, exclude_if=lambda value: not value
    )
    schema_version: Literal[1] = 1
    limitations: list[str] = Field(default_factory=list)
    # Optional only to read pre-audit stored responses; new HTTP results require both.
    effective_request: OptionSearchRequest | None = None
    checked_at: AwareDatetime | None = None
    status: Literal["SUCCESS", "PARTIAL", "ERROR"]
    items: list[OptionCandidate] = Field(default_factory=list, max_length=42)
    products: list[Product] = Field(default_factory=list, max_length=6)
    checked_scope: CheckedScope
    excluded_count: int = Field(ge=0)
    omitted_count: int = Field(ge=0)

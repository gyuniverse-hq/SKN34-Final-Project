"""Subset of the api service's catalog contract that the graph needs. Unknown fields are ignored."""

from typing import Literal, Self
from uuid import UUID

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, HttpUrl, model_validator
from pydantic.alias_generators import to_camel

from app.core.config import get_settings
from app.schemas.style_recipe import ReviewedRecipe


class _CatalogModel(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True, extra="ignore")


class CatalogShade(_CatalogModel):
    id: str
    name: str
    hex: str
    measure_method: str | None = None
    color_source: str | None = None


class CatalogProduct(_CatalogModel):
    """keyIngredients is partial information, never a verified full ingredient list."""

    id: str
    brand: str
    name: str
    name_ko: str
    category: str
    makeup_zone: str | None = None
    texture: str | None
    price_krw: int = Field(alias="priceKRW", strict=True)
    price_evidence: str | None = None
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
    description: str = ""
    makeup: dict = Field(default_factory=dict)
    step_order: list[str] = Field(default_factory=list)
    recipe: ReviewedRecipe | None = None


class CatalogStyleProduct(_CatalogModel):
    number: int
    brand: str
    name: str
    option: str
    category: str
    zone: str
    review_status: str
    mapping_verified: bool = Field(default=False, strict=True)
    catalog_product_id: str | None = None
    catalog_shade_id: str | None = None


class CatalogStyleLook(_CatalogModel):
    id: str
    title: str
    group: str
    tag: str
    video_url: str
    products: list[CatalogStyleProduct]
    recipe: ReviewedRecipe | None = None


class IngredientIdentity(_CatalogModel):
    model_config = ConfigDict(str_strip_whitespace=True)
    mfds_ingredient_id: int = Field(strict=True, gt=0)
    name_ko: str = Field(min_length=1)
    source_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    match_method: Literal[
        "standard_name",
        "english_name",
        "official_synonym",
        "exact_name",
        "amount_suffix_exact",
        "amount_suffix_synonym",
        "manual",
    ]
    rule_version: str | None = None
    reviewed_by: str | None = None
    reviewed_at: AwareDatetime | None = None

    @model_validator(mode="after")
    def require_provenance(self) -> Self:
        if self.match_method == "manual":
            if not self.reviewed_by or not self.reviewed_at:
                raise ValueError("Manual identity requires a reviewer and timestamp")
        elif not self.rule_version:
            raise ValueError("Identity requires a rule version")
        return self


class IngredientEntry(_CatalogModel):
    name: str = Field(min_length=1)
    sequence: int | None = Field(default=None, strict=True, ge=1)
    identity: IngredientIdentity | None = None


class IngredientDecision(_CatalogModel):
    product_id: str
    shade_id: str | None
    option_id: str | None
    condition: Literal["ingredient"]
    ingredient_name: str
    operator: Literal["includes", "excludes"]
    verdict: Literal["MATCH", "NOT_MATCH", "UNKNOWN", "ERROR"]
    reason: str
    evidence_id: str | None = None
    synthetic: bool = False
    query_identity: IngredientIdentity | None = None


class CatalogIngredients(_CatalogModel):
    """HTTP evidence contract; 200 and reproduced mapping alone prove no ingredient fact."""

    product_id: str
    shade_id: str | None
    option_id: str | None = None
    status: Literal["ok", "unknown", "error"]
    verdict: Literal["MATCH", "NOT_MATCH", "UNKNOWN", "ERROR"]
    mapping_status: Literal[
        "reproduced", "directly_reviewed", "candidate", "ambiguous", "unmapped", "mismatch"
    ]
    ingredient_coverage: Literal["full", "partial", "unknown"]
    review_status: Literal["verified", "unreviewed", "rejected"]
    normalization_status: Literal["verified", "unverified"]
    ingredients: list[IngredientEntry]
    source: str | None = None
    collected_at: AwareDatetime | None = None
    reviewed_at: AwareDatetime | None = None
    review_ref: str | None = None
    collected_at_raw: str | None = None
    source_version: str | None = None
    source_fingerprint: str | None = None
    generator_version: str | None = None
    evidence_id: str | None = None
    reason: str
    issues: list[str] = Field(default_factory=list)
    conditions: list[IngredientDecision] = Field(default_factory=list)
    synthetic: bool = False

    @model_validator(mode="after")
    def block_synthetic_public_evidence(self) -> Self:
        if self.synthetic and get_settings().is_production:
            self.status, self.verdict = "unknown", "UNKNOWN"
            self.review_status = "unreviewed"
            self.reason = "synthetic_test_only"
            self.ingredients = []
            self.evidence_id = None
            for condition in self.conditions:
                condition.verdict, condition.reason = "UNKNOWN", "synthetic_test_only"
                condition.evidence_id = None
        return self

    @property
    def verified(self) -> bool:
        direct = self.mapping_status == "directly_reviewed"
        if direct:
            provenance = self.reviewed_at and self.review_ref and self.review_ref.strip()
            blocking_issues = set(self.issues) - {"source_timezone_unknown"}
        else:
            provenance = (
                self.mapping_status == "reproduced"
                and self.collected_at
                and self.source_fingerprint
                and self.generator_version
            )
            blocking_issues = set(self.issues)
        return bool(
            self.status == "ok"
            and not (self.synthetic and get_settings().is_production)
            and provenance
            and self.review_status == "verified"
            and self.ingredient_coverage != "unknown"
            and self.option_id
            and self.source
            and self.evidence_id
            and self.source_version
            and self.ingredients
            and not blocking_issues
        )

    @property
    def complete(self) -> bool:
        names = [i.name.casefold().strip() for i in self.ingredients]
        return bool(
            self.verified
            and self.ingredient_coverage == "full"
            and self.normalization_status == "verified"
            and [i.sequence for i in self.ingredients] == list(range(1, len(names) + 1))
            and len(set(names)) == len(names)
        )


Verdict = Literal["MATCH", "NOT_MATCH", "UNKNOWN", "ERROR"]
PriceBasis = Literal["current_sale", "collected_sale"]
ClaimUse = Literal["explain", "rank", "avoid"]


class ClaimContext(_CatalogModel):
    concern: str | None = Field(default=None, min_length=1, max_length=80)
    target: str | None = Field(default=None, min_length=1, max_length=80)
    formulation: str | None = Field(default=None, min_length=1, max_length=80)
    concentration_pct: float | None = Field(default=None, ge=0, le=100)


class ClaimIngredientKey(_CatalogModel):
    mfds_ingredient_id: int = Field(gt=0, strict=True)
    source_hash: str = Field(pattern=r"^[0-9a-f]{64}$")


class ClaimCitation(_CatalogModel):
    publication_id: UUID
    revision: int
    ingredient: ClaimIngredientKey
    ingredient_name: str
    summary: str = Field(min_length=1, max_length=1200)
    use: ClaimUse
    scope: dict
    source_title: str
    source_url: HttpUrl
    source_version: str
    study_type: str


class ClaimLookup(_CatalogModel):
    use: ClaimUse
    context: ClaimContext
    ingredient_names: list[str] = Field(default_factory=list)
    ingredients: list[ClaimIngredientKey] = Field(default_factory=list)
    publication_ids: list[UUID] = Field(default_factory=list)


class ClaimSearchResult(_CatalogModel):
    claims: list[ClaimCitation] = Field(max_length=24)


class OptionCategory(_CatalogModel):
    category_id: str
    parent_id: str | None = None
    name: str | None
    path: str | None


class OptionCategories(_CatalogModel):
    categories: list[OptionCategory]


class OptionFilter(_CatalogModel):
    ingredient_name: str
    operator: Literal["includes", "excludes"]


class OptionLookup(_CatalogModel):
    category_id: str
    product_id: str | None = None
    option_id: str | None = None
    max_price_krw: int | None = Field(default=None, alias="maxPriceKRW")
    price_basis: PriceBasis = "current_sale"
    ingredient_conditions: list[OptionFilter] = Field(default_factory=list)
    offset: int = Field(default=0, ge=0)
    limit: int = Field(default=32, ge=1, le=32)


class CollectedOptionPrice(_CatalogModel):
    evidence_id: str
    source: Literal["oliveyoung_price_snapshot"]
    source_url: str | None
    sale_price_krw: int | None = Field(alias="salePriceKRW")
    collected_at_raw: str | None
    stock_status: Literal["in_stock", "sold_out", "unknown"]


class CatalogOptionPrice(_CatalogModel):
    reference_price_krw: int | None = Field(alias="referencePriceKRW")
    collected: CollectedOptionPrice | None
    current_sale_price_krw: int | None = Field(alias="currentSalePriceKRW")
    current_stock_status: Literal["in_stock", "sold_out", "unknown"]


class BudgetDecision(_CatalogModel):
    price_basis: PriceBasis
    max_price_krw: int = Field(alias="maxPriceKRW")
    verdict: Verdict
    reason: str
    evidence_id: str | None = None


class OptionIngredientReview(_CatalogModel):
    review: CatalogIngredients
    error_code: str | None = None


class CatalogOption(_CatalogModel):
    product_id: str
    product_name: str
    catalog_category: str
    category: OptionCategory
    option_id: str
    option_name: str | None
    price: CatalogOptionPrice
    ingredients: OptionIngredientReview
    budget_condition: BudgetDecision | None
    required_verdict: Verdict


class OptionPageScope(_CatalogModel):
    request: OptionLookup
    category: OptionCategory
    candidate_count: int = Field(ge=0)
    evaluated_count: int = Field(ge=0, le=32)
    next_offset: int | None = Field(ge=0)
    options_with_lookup_errors: int = Field(ge=0, le=32)


class OptionPage(_CatalogModel):
    scope: OptionPageScope
    matches: list[CatalogOption] = Field(max_length=32)
    excluded: list[CatalogOption] = Field(max_length=32)
    unconfirmed: list[CatalogOption] = Field(max_length=32)

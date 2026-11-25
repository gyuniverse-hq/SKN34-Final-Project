"""Subset of the api service's catalog contract that the graph needs. Unknown fields are ignored."""

from typing import Annotated, Literal, Self

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, NaiveDatetime, model_validator
from pydantic.alias_generators import to_camel

from app.core.config import get_settings
from app.schemas.style_recipe import ReviewedRecipe


class _CatalogModel(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True, extra="ignore")


ColorFamily = Literal["red", "coral", "pink", "berry", "nude", "brown"]


class CatalogShade(_CatalogModel):
    id: str
    name: str
    hex: str
    product_id: str | None = Field(default=None, exclude=True)
    measure_method: str | None = None
    color_source: str | None = None
    color_family: ColorFamily | None = None


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


class IngredientModel(_CatalogModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class IngredientSelection(IngredientModel):
    product_id: str = Field(min_length=1, max_length=128)
    shade_id: str | None = Field(default=None, min_length=1, max_length=128)
    option_id: str | None = Field(default=None, min_length=1, max_length=128)


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
    products: list[CatalogProduct] = Field(default_factory=list, max_length=6)
    checked_scope: CheckedScope
    excluded_count: int = Field(ge=0)
    omitted_count: int = Field(ge=0)

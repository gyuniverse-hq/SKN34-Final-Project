"""Subset of the api service's catalog contract that the graph needs. Unknown fields are ignored."""

from typing import Literal, Self

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, model_validator
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
    mapping_status: Literal["reproduced", "candidate", "ambiguous", "unmapped", "mismatch"]
    ingredient_coverage: Literal["full", "partial", "unknown"]
    review_status: Literal["verified", "unreviewed", "rejected"]
    normalization_status: Literal["verified", "unverified"]
    ingredients: list[IngredientEntry]
    source: str | None = None
    collected_at: AwareDatetime | None = None
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
        return bool(
            self.status == "ok"
            and not (self.synthetic and get_settings().is_production)
            and self.mapping_status == "reproduced"
            and self.review_status == "verified"
            and self.ingredient_coverage != "unknown"
            and self.option_id
            and self.source
            and self.collected_at
            and self.evidence_id
            and self.source_version
            and self.source_fingerprint
            and self.generator_version
            and self.ingredients
            and not self.issues
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

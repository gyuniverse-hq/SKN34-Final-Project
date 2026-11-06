"""Validated skincare recommendation and serving data contracts."""

from typing import Any, Literal

from pydantic import ConfigDict, Field, model_validator

from app.schemas.base import ApiModel
from app.schemas.catalog import Product

Goal = Literal["dryness", "sensitivity", "pigmentation", "wrinkles", "pores", "blemish", "oiliness"]
SkinType = Literal["dry", "balanced", "oily", "unknown"]
GOALS = ("dryness", "sensitivity", "pigmentation", "wrinkles", "pores", "blemish", "oiliness")
LINK_METHODS = {"standard_id", "exact_name", "verified_alias", "verified_group_member"}


class StrictModel(ApiModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


class SkincareRequest(StrictModel):
    primary_goal: Goal
    secondary_goals: list[Goal] = Field(default_factory=list, max_length=7)
    skin_type: SkinType = "unknown"
    irritation_signal: Literal["caution", "none", "unknown"] = "unknown"
    goal_policy_version: Literal["care-goals-v2"]
    limit: int = Field(default=8, ge=1, le=20, strict=True)
    include_trace: bool = False

    @model_validator(mode="after")
    def canonicalize(self):
        self.secondary_goals = [
            g for g in GOALS if g in self.secondary_goals and g != self.primary_goal
        ]
        return self


class MappingEvidence(StrictModel):
    evidence_id: str
    supported_endpoint: str = Field(min_length=1)
    study_conditions: dict[str, Any] = Field(default_factory=dict)
    applicability_note: str | None = None


class EvidenceMetadata(StrictModel):
    evidence_id: str
    pmid: str | None = None
    title: str = Field(min_length=1)
    source_url: str = Field(min_length=1)
    study_limit: str | None = None
    study_type: Literal[
        "human_intervention",
        "human_observational",
        "in_vitro",
        "animal",
        "method_validation",
        "review",
        "other",
    ]
    publication_year: int | None = Field(default=None, ge=1800, le=2200)


class IngredientMapping(StrictModel):
    mapping_id: str
    target_concern: Goal
    mapping_type: Literal["single", "combination"]
    applicability_scope: Literal["ingredient_level", "formula_specific"]
    ingredient_codes: list[str] = Field(min_length=1)
    evidence: list[MappingEvidence] = Field(min_length=1)
    runtime_enabled: bool

    def composition_valid(self) -> bool:
        codes = set(self.ingredient_codes)
        return len(codes) == len(self.ingredient_codes) and (
            (self.mapping_type == "single" and len(codes) == 1)
            or (self.mapping_type == "combination" and len(codes) >= 2)
        )

    def eligible(self) -> bool:
        return (
            self.runtime_enabled
            and self.applicability_scope == "ingredient_level"
            and self.composition_valid()
            and bool(self.evidence)
        )


class SkincareOption(StrictModel):
    product: Product
    option_id: str
    option_name: str
    price_krw: int = Field(alias="priceKRW", gt=0, strict=True)
    subcategory: Literal["toner", "essence", "serum", "ampoule", "lotion", "cream"]
    available: bool
    ingredient_codes: list[str]
    identity_verified: bool
    skin_types: list[SkinType] = Field(default_factory=list)
    sensitive_label: bool = False
    label_source: str | None = None
    review_count: int | None = Field(default=None, ge=0, strict=True)
    rating_avg: float | None = Field(default=None, ge=1, le=5)
    source_option_id: str


class SkincareSnapshot(StrictModel):
    data_version: str = Field(min_length=1)
    source_manifest: dict[str, str]
    mappings: list[IngredientMapping]
    options: list[SkincareOption]
    evidence: dict[str, EvidenceMetadata]
    # Each code carries deterministic link provenance, not a per-row approval state.
    ingredient_provenance: dict[str, list[dict[str, str]]]

    @model_validator(mode="after")
    def references(self):
        if not self.source_manifest:
            raise ValueError("Source manifest required")
        if len({m.mapping_id for m in self.mappings}) != len(self.mappings):
            raise ValueError("Duplicate mapping ID")
        if len({o.option_id for o in self.options}) != len(self.options):
            raise ValueError("Duplicate option ID")
        for code, provenance_rows in self.ingredient_provenance.items():
            if (
                not code
                or not provenance_rows
                or any(row.get("linkMethod") not in LINK_METHODS for row in provenance_rows)
            ):
                raise ValueError("A reproducible ingredient-link method is required")
        products = {}
        for option in self.options:
            signature = (
                option.product.model_dump(exclude={"price_krw"}),
                option.review_count,
                option.rating_avg,
            )
            if option.product.id in products and products[option.product.id] != signature:
                raise ValueError("Conflicting product metadata or reviews across options")
            products[option.product.id] = signature
        for mapping in self.mappings:
            if not mapping.composition_valid():
                raise ValueError("Mapping type must match its distinct ingredient count")
            for link in mapping.evidence:
                if link.evidence_id not in self.evidence:
                    raise ValueError("Missing mapping evidence metadata")
            if mapping.eligible() and any(
                code not in self.ingredient_provenance for code in mapping.ingredient_codes
            ):
                raise ValueError("Enabled mapping has an unlinked ingredient code")
        for option in self.options:
            if option.product.category != "skincare" or option.source_option_id != option.option_id:
                raise ValueError("Invalid product/option lineage")
            if option.identity_verified and any(
                code not in self.ingredient_provenance for code in option.ingredient_codes
            ):
                raise ValueError("Option contains an unlinked ingredient code")
        return self


class GoalCoverage(ApiModel):
    goal: Goal
    status: Literal["ok", "mapping_unavailable", "no_matches"]


class SkincareMatch(ApiModel):
    product: Product
    option_id: str
    option_name: str
    price_krw: int = Field(alias="priceKRW")
    matched_goals: list[Goal]
    target_concern: Goal
    reason_code: Literal["primary", "secondary"]


class SkincareResponse(ApiModel):
    strategy_version: Literal["skincare-ingredient-v2"] = "skincare-ingredient-v2"
    data_version: str | None = None
    coverage: list[GoalCoverage]
    matches: list[SkincareMatch]
    trace: dict | None = None

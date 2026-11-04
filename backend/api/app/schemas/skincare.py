"""Versioned serving contract. Initial ranking rules are unvalidated heuristics."""

from typing import Literal

from pydantic import ConfigDict, Field, model_validator

from app.schemas.base import ApiModel
from app.schemas.catalog import Product

Goal = Literal["dryness", "sensitivity", "pigmentation", "wrinkles", "pores"]
SkinType = Literal["dry", "balanced", "oily", "unknown"]
GOALS = ("dryness", "sensitivity", "pigmentation", "wrinkles", "pores")


class StrictModel(ApiModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


class SkincareRequest(StrictModel):
    primary_goal: Goal
    secondary_goals: list[Goal] = Field(default_factory=list, max_length=5)
    skin_type: SkinType = "unknown"
    irritation_signal: Literal["caution", "none", "unknown"] = "unknown"
    goal_policy_version: Literal["care-goals-v1"]
    limit: int = Field(default=8, ge=1, le=20, strict=True)
    include_trace: bool = False

    @model_validator(mode="after")
    def canonicalize(self):
        self.secondary_goals = [
            g for g in GOALS if g in self.secondary_goals and g != self.primary_goal
        ]
        return self


class IngredientMapping(StrictModel):
    mapping_id: str
    target_concern: Goal | Literal["blemish"]
    mapping_type: Literal["single", "combination"]
    ingredient_codes: list[str] = Field(min_length=1)
    evidence_ids: list[str]
    mapping_status: str
    human_mapping_review: str
    ai_paper_review: str
    re_review_required: bool
    runtime_enabled: bool
    identity_verified: bool

    def eligible(self) -> bool:
        return (
            self.mapping_type == "single"
            and len(set(self.ingredient_codes)) == 1
            and self.target_concern in GOALS
            and self.runtime_enabled
            and self.identity_verified
            and bool(self.evidence_ids)
            and self.mapping_status == "candidate_after_match"
            and self.human_mapping_review == "승인"
            and self.ai_paper_review == "승인"
            and not self.re_review_required
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
    # DB-computed matches; None preserves previously published snapshots.
    matched_mapping_ids: list[str] | None = None


class SkincareSnapshot(StrictModel):
    data_version: str = Field(min_length=1)
    source_manifest: dict[str, str]
    mappings: list[IngredientMapping]
    options: list[SkincareOption]
    evidence: dict[str, dict[str, str]]
    # Each code has reviewed provenance, not an unchecked integer source ID.
    ingredient_provenance: dict[str, dict[str, str]]

    @model_validator(mode="after")
    def references(self):
        if not self.source_manifest:
            raise ValueError("Source manifest required")
        if len({m.mapping_id for m in self.mappings}) != len(self.mappings):
            raise ValueError("Duplicate mapping ID")
        if len({o.option_id for o in self.options}) != len(self.options):
            raise ValueError("Duplicate option ID")
        for code, provenance in self.ingredient_provenance.items():
            if not code or not provenance.get("source") or not provenance.get("reviewedBy"):
                raise ValueError("Reviewed ingredient provenance required")
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
        for m in self.mappings:
            if any(e not in self.evidence for e in m.evidence_ids):
                raise ValueError("Missing evidence")
            if m.identity_verified and any(
                c not in self.ingredient_provenance for c in m.ingredient_codes
            ):
                raise ValueError("Missing ingredient provenance")
        for o in self.options:
            if o.matched_mapping_ids is not None and not set(o.matched_mapping_ids).issubset(
                {m.mapping_id for m in self.mappings}
            ):
                raise ValueError("Unknown matched mapping ID")
            if o.product.category != "skincare" or o.source_option_id != o.option_id:
                raise ValueError("Invalid product/option lineage")
            if o.identity_verified and any(
                c not in self.ingredient_provenance for c in o.ingredient_codes
            ):
                raise ValueError("Unverified ingredient")
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
    strategy_version: Literal["skincare-ingredient-v1"] = "skincare-ingredient-v1"
    data_version: str | None = None
    coverage: list[GoalCoverage]
    matches: list[SkincareMatch]
    trace: dict | None = None

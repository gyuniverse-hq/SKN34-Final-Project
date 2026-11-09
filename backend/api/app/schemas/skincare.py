"""Versioned serving contract. Initial ranking rules are unvalidated heuristics."""

from typing import Annotated, Literal

from pydantic import ConfigDict, Field, StringConstraints, model_validator

from app.schemas.base import ApiModel
from app.schemas.catalog import Product

Goal = Literal["dryness", "sensitivity", "pigmentation", "wrinkles", "pores", "oiliness", "blemish"]
SkinType = Literal["dry", "balanced", "oily", "unknown"]
GOALS = ("dryness", "sensitivity", "pigmentation", "wrinkles", "pores", "oiliness", "blemish")


class StrictModel(ApiModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


class SkincareRequest(StrictModel):
    primary_goal: Goal
    secondary_goals: list[Goal] = Field(default_factory=list, max_length=6)
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


NonBlank = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]


class MappingReview(StrictModel):
    decision: Literal["approve", "revoke", "re_review"]
    reviewer: NonBlank
    source: NonBlank
    fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    condition: Literal["none", "option_proof", "unreviewed"] = "unreviewed"
    requirement: NonBlank | None = None
    # Each reference documents satisfaction of all required conditions on this option.
    option_proofs: dict[NonBlank, NonBlank] = Field(default_factory=dict)

    @model_validator(mode="after")
    def check_conditions(self):
        if self.decision == "approve" and self.condition == "unreviewed":
            raise ValueError("Review product conditions before approval")
        if self.condition == "option_proof" and not self.requirement:
            raise ValueError("Describe the required product conditions")
        if self.option_proofs and self.condition != "option_proof":
            raise ValueError("Option proofs require option_proof conditions")
        return self


class IngredientMapping(StrictModel):
    mapping_id: str
    target_concern: str = Field(min_length=1)
    mapping_type: Literal["single", "combination"]
    ingredient_codes: list[str] = Field(min_length=1)
    evidence_ids: list[str]
    mapping_status: str
    human_mapping_review: str
    ai_paper_review: str
    re_review_required: bool
    runtime_enabled: bool
    identity_verified: bool

    evidence_verified: bool = False
    review: MappingReview | None = None
    review_fingerprint: str | None = None

    def blockers(self, *, require_review=True) -> list[str]:
        checks = {
            "unsupported_goal": self.target_concern in GOALS,
            "single_ingredient_required": self.mapping_type == "single"
            and len(set(self.ingredient_codes)) == 1,
            "unverified_identity": self.identity_verified,
            "missing_evidence": bool(self.evidence_ids),
            "mapping_status": self.mapping_status == "candidate_after_match",
            "human_review": self.human_mapping_review == "승인",
            "paper_review": self.ai_paper_review == "승인",
            "re_review_required": not self.re_review_required,
        }
        if require_review:
            review = self.review
            checks["paper_reference_unverified"] = self.evidence_verified
            checks["operational_approval"] = bool(review and review.decision == "approve")
            checks["product_conditions_unreviewed"] = bool(
                review and review.condition != "unreviewed"
            )
            if review:
                checks["review_source_changed"] = review.fingerprint == self.review_fingerprint
                if review.decision == "re_review":
                    checks["re_review_required"] = False
        return [reason for reason, passed in checks.items() if not passed]

    def eligible(self) -> bool:
        # Backward compatibility for v1 readers of pre-migration snapshots.
        return self.runtime_enabled and not self.blockers(
            require_review=self.review_fingerprint is not None
        )

    def allows_option(self, option_id: str) -> bool:
        return bool(
            self.review
            and (self.review.condition == "none" or option_id in self.review.option_proofs)
        )


class StudySupport(StrictModel):
    evidence_id: str
    supported_endpoint: NonBlank
    study_conditions: dict
    applicability_note: NonBlank


class KnowledgeMapping(StrictModel):
    mapping_id: str
    target_concern: Goal
    mapping_type: Literal["single", "combination"]
    applicability_scope: Literal["ingredient_level", "formula_specific"]
    ingredient_codes: list[str] = Field(min_length=1)
    studies: list[StudySupport] = Field(min_length=1)
    runtime_enabled: bool
    identity_verified: bool

    @model_validator(mode="after")
    def check_components(self):
        count = len(set(self.ingredient_codes))
        if count != len(self.ingredient_codes) or (count == 1) != (self.mapping_type == "single"):
            raise ValueError("Mapping type and component count disagree")
        return self

    @property
    def evidence_ids(self):
        return [study.evidence_id for study in self.studies]

    def blockers(self):
        checks = {
            "runtime_disabled": self.runtime_enabled,
            "formula_specific": self.applicability_scope == "ingredient_level",
            "unverified_identity": self.identity_verified,
        }
        return [reason for reason, passed in checks.items() if not passed]

    def eligible(self):
        return not self.blockers()

    def allows_option(self, option_id: str):
        return self.eligible()


class CosingMapping(StrictModel):
    """User-classified CosIng functions, separate from research-backed mappings."""

    mapping_id: str
    target_concern: Goal
    mapping_type: Literal["single"] = "single"
    applicability_scope: Literal["ingredient_level"] = "ingredient_level"
    ingredient_codes: list[str] = Field(min_length=1, max_length=1)
    function_names: list[NonBlank] = Field(min_length=1)
    substance_id: NonBlank
    match_method: Literal["exact", "normalized"]
    runtime_enabled: bool = True
    identity_verified: bool = True

    @property
    def evidence_ids(self):
        return []

    def blockers(self):
        return [reason for reason, valid in {
            "runtime_disabled": self.runtime_enabled,
            "unverified_identity": self.identity_verified,
        }.items() if not valid]

    def eligible(self):
        return not self.blockers()

    def allows_option(self, option_id: str):
        return self.eligible()


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
    survey_ratios: dict[
        Literal[
            "dry",
            "oily",
            "combination",
            "gentle",
            "irritating",
            "hydrating",
            "brighteningFirming",
            "soothing",
        ],
        Annotated[float, Field(ge=0, le=1)],
    ] = Field(default_factory=dict)


class SkincareSnapshot(StrictModel):
    data_version: str = Field(min_length=1)
    source_manifest: dict[str, str]
    mappings: list[KnowledgeMapping | IngredientMapping | CosingMapping]
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
            if (
                not code
                or not provenance.get("source")
                or not (provenance.get("ruleVersion") or provenance.get("reviewedBy"))
            ):
                raise ValueError("Reviewed ingredient provenance required")
        products = {}
        for option in self.options:
            signature = (
                option.product.model_dump(exclude={"price_krw"}),
                option.review_count,
                option.rating_avg,
                option.survey_ratios,
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
    strategy_version: Literal["skincare-ingredient-cosing-v1"] = "skincare-ingredient-cosing-v1"
    data_version: str | None = None
    coverage: list[GoalCoverage]
    matches: list[SkincareMatch]
    trace: dict | None = None


DetectionSource = Literal["analysis", "survey", "skinType"]
MatchSource = Literal[
    "primary", "secondary", "analysis", "survey", "skinType", "skinProfile", "concern",
    "analysisSupport",
]


class DetectedConcern(StrictModel):
    goal: Goal
    sources: list[DetectionSource] = Field(min_length=1, max_length=3)


class SkincareProfileRequest(StrictModel):
    detected_concerns: list[DetectedConcern] = Field(default_factory=list, max_length=7)
    # Only the three mobile-v4 binary models share a verified 0.5 decision threshold.
    analysis_scores: dict[
        Literal["pores", "pigmentation", "wrinkles"],
        Annotated[float, Field(ge=0, le=1, strict=True, allow_inf_nan=False)],
    ] = Field(default_factory=dict)
    skin_type: SkinType = "unknown"
    irritation_signal: Literal["caution", "none", "unknown"] = "unknown"


class HybridRequest(SkincareProfileRequest):
    primary_goal: Goal
    secondary_goals: list[Goal] = Field(default_factory=list, max_length=6)
    balance_goal: Literal["primary", "secondary"] | None = None

    @model_validator(mode="after")
    def validate_balance_goal(self):
        balance = {"dryness", "oiliness"}
        if self.balance_goal == "primary" and self.primary_goal not in balance:
            raise ValueError("Primary balance requires a moisture or oil goal")
        if self.balance_goal == "secondary" and (
            self.primary_goal in balance or not balance.issubset(self.secondary_goals)
        ):
            raise ValueError("Secondary balance requires both moisture and oil goals")
        return self


class ConcernReason(ApiModel):
    goal: Goal
    sources: list[MatchSource]
    ingredient_codes: list[str] = Field(default_factory=list)
    evidence_level: Literal["ingredient_presence"] = "ingredient_presence"
    evidence_sources: list[Literal["research_mapping", "cosing_function"]] = Field(
        default_factory=list
    )


class HybridMatch(ApiModel):
    product: Product
    option_id: str
    option_name: str
    price_krw: int = Field(alias="priceKRW")
    reasons: list[ConcernReason]


class HybridResponse(ApiModel):
    strategy_version: Literal[
        "skincare-hybrid-v2-cosing-only-v1", "skincare-v4"
    ] = "skincare-hybrid-v2-cosing-only-v1"
    data_version: str | None
    coverage: list[GoalCoverage]
    overall_top5: list[HybridMatch]
    by_concern: dict[Goal, list[HybridMatch]]
    balance_matches: list[HybridMatch] | None = Field(
        default=None, exclude_if=lambda value: value is None
    )

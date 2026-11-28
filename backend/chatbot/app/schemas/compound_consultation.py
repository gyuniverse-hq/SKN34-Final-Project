"""Typed jobs, exact option evidence and resumable *completed-turn* references for G8."""

from typing import Annotated, Literal, Self
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator
from pydantic.alias_generators import to_camel

from app.schemas.catalog import (
    CheckedScope,
    OptionCandidate,
    OptionIngredientResolution,
    OptionSearchRequest,
)
from app.schemas.consultation_answer import KnowledgeCoverage
from app.schemas.knowledge import KnowledgeReply
from app.schemas.skincare_recommendation import SkincareReason, SkinGoal

Text = Annotated[str, Field(min_length=1, max_length=500)]
TaskKind = Literal["knowledge", "recommend", "verify"]


class CompoundModel(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True, extra="forbid")


class CompoundGoal(CompoundModel):
    goals: list[SkinGoal] = Field(min_length=1, max_length=7)
    max_price_krw: int | None = Field(
        default=None, alias="maxPriceKRW", strict=True, ge=0, le=100_000_000
    )
    excluded_ingredients: list[Text] = Field(default_factory=list, max_length=6)
    wants_knowledge: bool = True
    wants_products: bool = True
    fragrance_free: bool = False
    unsupported_conditions: list[Text] = Field(default_factory=list, max_length=8)

    @model_validator(mode="after")
    def unique_goals(self) -> Self:
        if len(self.goals) != len(set(self.goals)):
            raise ValueError("Duplicate care goal")
        return self


class RankedOption(CompoundModel):
    rank: int = Field(ge=1, le=10)
    product_id: Text
    option_id: Text
    option_name: str
    product_name: str
    brand: str
    has_shades: bool
    data_version: str | None = None
    ingredient_codes: list[str] = Field(default_factory=list)
    reasons: list[SkincareReason] = Field(default_factory=list)


class VerifiedOption(CompoundModel):
    candidate: RankedOption
    outcome: Literal["eligible", "excluded", "unknown", "failed"]
    verification: OptionCandidate | None = None
    reason: str | None = None

    @model_validator(mode="after")
    def match_option(self) -> Self:
        if self.verification:
            v = self.verification
            if (v.product_id, v.option_id) != (self.candidate.product_id, self.candidate.option_id):
                raise ValueError("Mismatched option evidence")
            expected = {"ELIGIBLE": "eligible", "EXCLUDED": "excluded", "REFERENCE_ONLY": "unknown"}
            if self.outcome != expected[v.group] and not (
                self.outcome == "failed" and v.group == "REFERENCE_ONLY"
            ):
                raise ValueError("Verdict contradicts catalog evidence")
        elif self.outcome in {"eligible", "excluded"}:
            raise ValueError("Decisive verdict requires option evidence")
        return self


class BatchCoverage(CompoundModel):
    deferred_knowledge_conditions: list[str] = Field(default_factory=list)
    attempt: Literal["primary", "without_unresolved_knowledge"] = "primary"
    product_ids: list[str] = Field(max_length=6)
    scope: CheckedScope | None = None
    reason: str | None = None
    request: OptionSearchRequest | None = None
    status: str | None = None
    omitted_count: int = 0
    excluded_count: int = 0
    limitations: list[str] = Field(default_factory=list)
    ingredient_resolutions: list[OptionIngredientResolution] = Field(default_factory=list)


class KnowledgeSearchCondition(CompoundModel):
    ingredient_name: Text
    operator: Literal["includes", "excludes"]
    claim_index: int = Field(ge=0)
    evidence_id: Text
    quote: Text


class KnowledgeSearchPlan(CompoundModel):
    conditions: list[KnowledgeSearchCondition] = Field(default_factory=list, max_length=6)


class KnowledgeSearchState(CompoundModel):
    coverage: KnowledgeCoverage | None = None
    deferred_ingredients: list[Text] = Field(default_factory=list)
    source: Literal["knowledge"] = "knowledge"
    goals: list[SkinGoal]
    conditions: list[KnowledgeSearchCondition] = Field(default_factory=list, max_length=6)
    knowledge: KnowledgeReply | None = None
    removed_ingredients: list[Text] = Field(default_factory=list)
    cleared: bool = False


class CompoundContext(CompoundModel):
    plan_version: int = Field(ge=1)
    goal: CompoundGoal
    candidates: list[RankedOption] = Field(default_factory=list, max_length=10)
    candidate_goals: list[SkinGoal] | None = None
    knowledge_search: KnowledgeSearchState | None = None


class CompoundDisplay(CompoundModel):
    plan_version: int = Field(ge=1)
    goal: CompoundGoal
    options: list[VerifiedOption] = Field(default_factory=list, max_length=10)
    batches: list[BatchCoverage] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)


class InputBinding(CompoundModel):
    source_task: str
    source_field: Literal["candidates", "search_conditions"] = "candidates"
    target_input: Literal["option_scope", "ingredient_conditions"] = "option_scope"


class TaskRequest(CompoundModel):
    task_id: str
    plan_id: UUID
    plan_version: int = Field(ge=1)
    agent: TaskKind
    goal: CompoundGoal
    depends_on: list[str] = Field(default_factory=list)
    input_bindings: list[InputBinding] = Field(default_factory=list)


class TaskResult(CompoundModel):
    knowledge_coverage: KnowledgeCoverage | None = None
    task_id: str
    plan_id: UUID
    plan_version: int
    input_fingerprint: str
    status: Literal["complete", "partial", "failed", "skipped"]
    candidates: list[RankedOption] = Field(default_factory=list)
    options: list[VerifiedOption] = Field(default_factory=list)
    batches: list[BatchCoverage] = Field(default_factory=list)
    knowledge: KnowledgeReply | None = None
    search_conditions: list[KnowledgeSearchCondition] = Field(default_factory=list)
    knowledge_search: KnowledgeSearchState | None = None
    limitations: list[str] = Field(default_factory=list)

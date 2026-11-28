"""Server-only facts for answer rendering; no new public API or inventory decisions."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.knowledge import KnowledgeReply
from app.schemas.owned_look_context import OwnedLookContext, OwnedLookOptionRef, OwnedLookOutcome


class RequirementCoverage(BaseModel):
    requirement_id: str
    description: str
    fulfilled: bool


class KnowledgeCoverage(BaseModel):
    scope: Literal["question", "explanation"] = "question"
    requirements: list[RequirementCoverage] = Field(default_factory=list)


class KnowledgeResearch(BaseModel):
    reply: KnowledgeReply
    coverage: KnowledgeCoverage | None = None


class IndependentAnswer(BaseModel):
    """Display facts only; never an internal objective or executable request."""

    model_config = ConfigDict(extra="forbid")
    label: str
    card_ids: list[str]
    preserved: bool = False
    kind_cleared: bool = False
    kind_changed: bool = False
    budget: int | None = None
    budget_changed: bool = False
    moisturizing: bool = False
    preference_changed: bool = False
    status: str
    outcome: str
    cards_visible: bool = True


class AnswerTarget(BaseModel):
    need_id: str
    status: Literal["fulfilled", "confirmed_missing", "ownership_unknown", "evidence_missing"]
    product_id: str | None = None
    option_id: str | None = None
    shade_id: str | None = None
    label: str
    alternative_product_ids: list[str] = Field(default_factory=list)


class ConsultationAnswer(BaseModel):
    model_config = ConfigDict(extra="forbid")

    coverage: list[AnswerTarget]
    outcome: OwnedLookOutcome
    current: OwnedLookContext
    previous: OwnedLookContext | None = None
    previous_question_id: str | None = None
    card_ids: list[str]
    options: list[OwnedLookOptionRef] = Field(default_factory=list)
    guidance: list[str] = Field(default_factory=list)
    general_guidance: bool = False
    alternatives: list[str] = Field(default_factory=list)
    unverified_roles: bool = False
    incomplete_search: bool = False
    notices: list[str] = Field(default_factory=list)
    explanation: str | None = None

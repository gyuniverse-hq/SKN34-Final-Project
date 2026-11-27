"""Server-owned coordination metadata, never an execution capability or product evidence."""

from typing import Literal
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, model_validator
from pydantic.alias_generators import to_camel

from app.schemas.style_recipe import StyleContext, Zone

GoalKind = Literal["skin", "owned_look", "knowledge", "style"]
GoalStatus = Literal["pending", "completed", "partial", "waiting_user", "failed", "superseded"]


class ParentModel(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True, extra="forbid")


class ParentTask(ParentModel):
    goal: GoalKind
    objective: str = ""
    status: GoalStatus = "pending"
    version: int = Field(ge=1)
    depends_on: list[GoalKind] = Field(default_factory=list)
    input_refs: list[str] = Field(default_factory=list)
    reference_digest: str | None = None
    result_refs: list[str] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)


class ParentQuestion(ParentModel):
    goal: GoalKind
    version: int = Field(ge=1)
    text: str
    input_key: Literal["ownership", "situation", "selection", "consent"]
    zone: Zone | None = None
    need_id: str | None = None
    recipe_version: str | None = None


class ConsultationParent(ParentModel):
    schema_version: Literal[1] = 1
    plan_id: UUID = Field(default_factory=uuid4)
    version: int = Field(default=1, ge=1)
    # Closed capabilities: at most one task of each kind per conversational revision.
    tasks: list[ParentTask] = Field(default_factory=list, max_length=4)
    question: ParentQuestion | None = None
    look: StyleContext | None = None

    @model_validator(mode="after")
    def coherent(self):
        if len({t.goal for t in self.tasks}) != len(self.tasks):
            raise ValueError("Duplicate parent goal")
        if any(t.version > self.version for t in self.tasks):
            raise ValueError("Future task revision")
        if self.question and self.question.version != self.version:
            raise ValueError("Stale question revision")
        return self

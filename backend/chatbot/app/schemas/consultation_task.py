"""Request-local coordination envelope; domain payloads keep their original contracts."""

from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, JsonValue, SerializeAsAny

from app.schemas.style_recipe import Zone

ProductKind = Literal[
    "toner",
    "cream",
    "lotion",
    "serum",
    "cleanser",
    "sunscreen",
    "mask",
    "cleansing_cream",
    "tone_up_cream",
    "eye_cream",
]


class ProductRequirement(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kind: ProductKind | None = None
    name_term: str | None = Field(default=None, min_length=1, exclude_if=lambda v: v is None)


class OwnershipQuestionAnswer(BaseModel):
    """Meaning of one answer; its exact target and scope are owned by the server."""

    model_config = ConfigDict(extra="forbid")
    action: Literal["answer", "defer", "clarify"]
    status: Literal["present", "missing"] | None = None
    question: str = ""


class ProductRequirementChange(BaseModel):
    model_config = ConfigDict(extra="forbid")
    operation: Literal["keep", "set", "clear", "unknown"]
    kind: ProductKind | None = None
    name_term: str | None = Field(default=None, min_length=1, exclude_if=lambda v: v is None)
    quote: str | None = ""


class ProductAssessment(BaseModel):
    model_config = ConfigDict(extra="forbid")
    status: Literal["completed", "partial", "waiting_user", "failed"]
    outcome: Literal["matched", "no_match", "unknown", "unsupported"]
    requirement: ProductRequirement
    inspected: int = 0
    matched: int = 0
    unknown: int = 0
    evidence: list[dict[str, JsonValue]] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)


class TaskBinding(BaseModel):
    source_task: str
    source_field: str
    target_input: str
    value_fingerprint: str


class TaskInputNeed(BaseModel):
    model_config = ConfigDict(extra="forbid")
    key: Literal["selection", "situation", "ownership", "consent"] = "selection"
    question: str = Field(min_length=1)
    zone: Zone | None = None
    need_id: str | None = None
    recipe_version: str | None = None
    ownership_scope: Literal["product", "option"] | None = None
    comparison_price_basis: (
        Literal["current_offer", "catalog_reference", "collected_snapshot"] | None
    ) = None
    comparison_base_id: str | None = None
    comparison_choices: list[dict[str, str]] = Field(default_factory=list)


class TaskContinuation(BaseModel):
    """A read suggestion; the parent must authorize its target and source binding."""

    model_config = ConfigDict(extra="forbid")
    capability: Literal["knowledge"] = "knowledge"
    objective: str = Field(min_length=1)
    source_field: Literal["style_recipe"] = "style_recipe"
    target_input: Literal["referenceContext"] = "referenceContext"
    source_fingerprint: str


class ConsultationTaskRequest(BaseModel):
    """Server-created request; no model-selected tools or executable payload."""

    model_config = ConfigDict(extra="forbid")
    task_id: str
    capability: str
    inputs: dict[str, JsonValue]
    depends_on: list[str] = Field(default_factory=list)
    requires_success: bool = True


class ConsultationTaskResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    plan_id: UUID
    plan_version: int = Field(ge=1)
    task_id: str
    family: Literal["compound", "owned_look", "independent"]
    capability: str
    status: Literal["completed", "partial", "waiting_user", "failed", "skipped"]
    attempt: int = Field(ge=0)
    depends_on: list[str] = Field(default_factory=list)
    bindings: list[TaskBinding] = Field(default_factory=list)
    inputs: dict[str, JsonValue]
    input_fingerprint: str
    source_fingerprint: str | None = None
    payload: SerializeAsAny[BaseModel] | None = None
    limitations: list[str] = Field(default_factory=list)
    reason: str | None = None
    missing_inputs: list[TaskInputNeed] = Field(default_factory=list)
    proposed_next_tasks: list[TaskContinuation] = Field(default_factory=list)
    reused: bool = False
    product_assessment: ProductAssessment | None = None

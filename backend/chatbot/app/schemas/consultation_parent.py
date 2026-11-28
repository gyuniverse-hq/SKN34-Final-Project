"""Server-owned coordination metadata, never an execution capability or product evidence."""

from typing import Literal
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, JsonValue, model_validator
from pydantic.alias_generators import to_camel

from app.schemas.compound_consultation import CompoundContext
from app.schemas.consultation_task import ProductAssessment, ProductRequirement, TaskInputNeed
from app.schemas.style_recipe import StyleContext, Zone

GoalKind = Literal["skin", "owned_look", "knowledge", "style", "product"]
ProductOperation = Literal["search", "detail", "compare"]
GoalStatus = Literal[
    "pending", "completed", "partial", "waiting_user", "failed", "superseded", "cancelled"
]


class ParentModel(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True, extra="forbid")


class ResultChoice(ParentModel):
    task_id: str
    label: str


class ResultSelection(ParentModel):
    version: int = Field(ge=1)
    task_ids: list[str]
    selected_task_id: str | None = None


class ConsultationSummary(ParentModel):
    status: Literal["completed", "partial", "waiting_user", "failed", "cancelled", "pending"]
    has_pending_input: bool
    display_selection_required: bool = False
    display_choices: list[ResultChoice] = Field(default_factory=list)
    selected_task_id: str | None = Field(default=None, exclude_if=lambda v: v is None)


class ParentTask(ParentModel):
    compound_context: CompoundContext | None = None
    product_operation: ProductOperation | None = None
    product_requirement: ProductRequirement | None = None
    product_assessment: ProductAssessment | None = None
    product_context: dict[str, JsonValue] | None = None
    task_id: str = ""
    attempts: int = Field(default=0, ge=0)
    reason: str | None = None
    tool_trace_ids: list[str] = Field(default_factory=list)
    goal: GoalKind
    objective: str = ""
    explanation_quote: str = ""
    status: GoalStatus = "pending"
    version: int = Field(ge=1)
    depends_on: list[str] = Field(default_factory=list)
    input_refs: list[str] = Field(default_factory=list)
    reference_digest: str | None = None
    result_refs: list[str] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)
    display_result: dict[str, JsonValue] | None = None
    scope_digest: str | None = None
    scope_snapshot: dict[str, JsonValue] | None = Field(
        default=None, exclude_if=lambda v: v is None
    )
    input_needs: list[TaskInputNeed] = Field(default_factory=list)

    @model_validator(mode="after")
    def legacy_identity(self):
        if not self.task_id:
            self.task_id = self.goal
        return self


class ComparisonChoice(ParentModel):
    product_id: str
    label: str


class ParentQuestion(ParentModel):
    comparison_price_basis: (
        Literal["current_offer", "catalog_reference", "collected_snapshot"] | None
    ) = None
    comparison_base_id: str | None = None
    comparison_choices: list[ComparisonChoice] = Field(default_factory=list, max_length=6)
    task_id: str | None = None
    goal: GoalKind
    version: int = Field(ge=1)
    text: str
    input_key: Literal["ownership", "situation", "selection", "consent"]
    zone: Zone | None = None
    need_id: str | None = None
    recipe_version: str | None = None
    ownership_scope: Literal["product", "option"] | None = None


class ConsultationParent(ParentModel):
    schema_version: Literal[1] = 1
    plan_id: UUID = Field(default_factory=uuid4)
    version: int = Field(default=1, ge=1)
    # Existing five-task bound is retained; roles may repeat with distinct task IDs.
    tasks: list[ParentTask] = Field(default_factory=list, max_length=5)
    question: ParentQuestion | None = None
    pending_questions: list[ParentQuestion] = Field(default_factory=list)
    result_selection: ResultSelection | None = None
    look: StyleContext | None = None
    execution_state: Literal["active", "cancelled"] = "active"

    @model_validator(mode="after")
    def coherent(self):
        if len({t.task_id for t in self.tasks}) != len(self.tasks):
            raise ValueError("Duplicate parent task ID")
        if any(t.version > self.version for t in self.tasks):
            raise ValueError("Future task revision")
        if self.question and self.question.version != self.version:
            raise ValueError("Stale question revision")
        if self.question and self.question.task_id is None:
            owners = [
                task
                for task in self.tasks
                if task.goal == self.question.goal and task.status == "waiting_user"
            ]
            if len(owners) == 1:
                self.question = self.question.model_copy(update={"task_id": owners[0].task_id})
        if self.question and self.question.task_id and not self.pending_questions:
            self.pending_questions = [self.question.model_copy(deep=True)]
        if any(
            q.version != self.version or q.task_id not in {t.task_id for t in self.tasks}
            for q in self.pending_questions
        ):
            raise ValueError("Stale or unowned pending question")
        selection = self.result_selection
        if selection and (
            selection.version != self.version
            or len(set(selection.task_ids)) != len(selection.task_ids)
            or set(selection.task_ids) - {t.task_id for t in self.tasks}
            or (
                selection.selected_task_id is not None
                and selection.selected_task_id not in selection.task_ids
            )
        ):
            raise ValueError("Invalid display selection")
        return self


class ConsultationChange(ParentModel):
    """An utterance-grounded change to an existing task, not a tool instruction."""

    task_id: str
    operation: Literal["update", "withdraw", "preserve"]
    quote: str = Field(min_length=1)
    product_operation: ProductOperation | None = None


class ConsultationAddition(ParentModel):
    """Independent read goal, grounded entirely in the current user utterance."""

    capability: Literal["knowledge", "product", "style", "skin", "owned_look"] = Field(
        description=(
            "product: catalog search/detail/compare, including ingredient/budget-filtered skincare "
            "searches. skin: explicit skin explanation/management AND suitable product "
            "recommendations in one workflow; its specialist owns situation clarification."
        )
    )
    quote: str = Field(min_length=1)
    explanation_quote: str = ""
    shared_quotes: list[str] = Field(default_factory=list)
    product_operation: ProductOperation | None = None


class QuestionChange(ParentModel):
    """Reference an outstanding server question, not an inventory declaration."""

    task_id: str
    input_key: Literal["ownership", "situation", "selection", "consent"]
    need_id: str | None = Field(
        default=None, description="Exact needId of ONE listed pending question"
    )
    operation: Literal["answer", "preserve"] = Field(
        description=(
            "answer: supplies any substantive response, including negative ownership. "
            "preserve: explicitly defers answering THIS question; no answer is supplied."
        )
    )
    quote: str = Field(min_length=1)


class ConsultationIntent(ParentModel):
    """A proposal about read-only consultation work, never an execution permission."""

    plan_id: UUID
    version: int = Field(ge=1)
    action: Literal[
        "continue", "retry", "cancel", "resume", "withdraw", "clarify", "delegate", "show"
    ]
    targets: list[str] = Field(default_factory=list)
    result_position: int | None = Field(
        default=None,
        ge=1,
        description=(
            "One-based position in resultChoices for an explicit request to display a result. "
            "Use action=show; the server resolves the task ID. Not a product number or quantity."
        ),
    )
    quote: str = ""
    question: str = ""
    clarification_scope: Literal["task", "product_input"] | None = None
    changes: list[ConsultationChange] = Field(default_factory=list)
    question_changes: list[QuestionChange] = Field(
        default_factory=list,
        description=(
            "Only listed pending questions, once per question. Answer one and preserve a named "
            "sibling "
            "without preserving the whole owner task. Completed result preservation uses changes."
        ),
    )
    additions: list[ConsultationAddition] = Field(default_factory=list)

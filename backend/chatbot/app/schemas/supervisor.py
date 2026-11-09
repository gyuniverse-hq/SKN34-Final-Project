"""Internal Supervisor contracts; never authorize writes or claim app execution."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field
from pydantic.alias_generators import to_camel

from app.schemas.style_recipe import StyleContext

ToolName = Literal["beauty", "graph_chat", "ar_command", "style", "knowledge"]


class SupervisorModel(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True, extra="forbid")


class ScreenContext(SupervisorModel):
    screen_id: str | None = Field(default=None, max_length=64)
    product_id: str | None = Field(default=None, max_length=128)
    shade_id: str | None = Field(default=None, max_length=128)
    look_id: str | None = Field(default=None, max_length=128)
    style_id: str | None = Field(default=None, max_length=128)


class ResolvedContext(SupervisorModel):
    style: StyleContext | None = None
    message: str
    request_type: str
    screen: ScreenContext | None = None
    candidate_ids: list[str] = Field(default_factory=list)
    selected_product_id: str | None = None
    selected_shade_id: str | None = None
    ar_state_version: int | None = None
    has_beauty_context: bool = False
    has_ar_context: bool = False
    # Caller IDs are references, not catalog facts or server-owned sessions.
    trusted: Literal[False] = False
    session_version: int | None = None
    result_set_id: str | None = None
    state_source: Literal["client_hint", "server_session"] = "client_hint"


class IngredientPlanCondition(SupervisorModel):
    ingredient_name: str = Field(min_length=1, max_length=500)
    operator: Literal["includes", "excludes"]


class SearchPlan(SupervisorModel):
    intent: Literal["search", "refine", "detail", "price", "general"]
    scope: Literal["catalog", "previous"] = "catalog"
    selection: Literal["lowest_price"] | None = None
    category: Literal["lip", "cheek", "eye", "base", "skincare", "suncare"] | None = None
    max_price_krw: int | None = Field(
        default=None, alias="maxPriceKRW", strict=True, ge=0, le=100_000_000
    )
    fragrance_free: bool | None = None
    moisturizing: bool | None = None
    query: str | None = Field(default=None, max_length=80)
    ordinal: int | None = Field(default=None, ge=1, le=6)
    ingredient_name: str | None = Field(default=None, min_length=1, max_length=500)
    ingredient_operator: Literal["includes", "excludes"] = "includes"
    ingredient_lookup: bool = False
    ingredient_conditions: list[IngredientPlanCondition] = Field(default_factory=list, max_length=6)
    shade_name: str | None = Field(default=None, min_length=1, max_length=128)
    compare_ordinals: list[int] = Field(default_factory=list, max_length=2)
    clear_filters: list[
        Literal[
            "category",
            "maxPriceKRW",
            "fragranceFree",
            "moisturizing",
            "query",
            "ingredientConditions",
        ]
    ] = Field(default_factory=list, max_length=6)


class IntentDecision(SupervisorModel):
    intent: Literal["product", "ingredient", "general", "style", "ar", "compound"]
    request_type_hint: str
    slots: SearchPlan | None = None


class Sufficiency(SupervisorModel):
    ready: bool
    missing: list[str] = Field(default_factory=list)


class TaskPlan(SupervisorModel):
    tasks: list[ToolName] = Field(default_factory=list, max_length=2)
    stop_reason: str | None = None
    stop_on_error: Literal[True] = True


class ConditionCheck(SupervisorModel):
    condition: str
    verdict: Literal["MATCH", "NOT_MATCH", "UNKNOWN", "ERROR"]
    product_id: str | None = None
    reason: str | None = None
    shade_id: str | None = None
    evidence_id: str | None = None


class EvidenceRef(SupervisorModel):
    product_id: str
    shade_id: str | None = None
    source: Literal["catalog_api", "neo4j"]
    verification: Literal["verified", "partial", "unknown"]
    reason: str | None = None
    evidence_id: str | None = None


class ToolResult(SupervisorModel):
    tool: ToolName
    status: Literal["success", "partial", "unsupported", "clarification", "error"]
    product_ids: list[str] = Field(default_factory=list)
    evidence: list[EvidenceRef] = Field(default_factory=list)
    conditions: list[ConditionCheck] = Field(default_factory=list)
    reason: str | None = None
    action_proposed: bool = False
    # Only the app can establish actual application; receiving a proposal is not ACK.
    application: Literal["not_requested", "awaiting_app_ack"] = "not_requested"


class SupervisorResult(SupervisorModel):
    intent: IntentDecision
    plan: TaskPlan
    result: ToolResult
    unavailable_tools: list[ToolName] = Field(default_factory=lambda: ["knowledge"])

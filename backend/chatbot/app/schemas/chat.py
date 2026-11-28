from typing import Annotated, Literal, Self
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, PrivateAttr, StringConstraints, model_validator
from pydantic.alias_generators import to_camel

from app.core.config import get_settings
from app.schemas.ar_geometry import STYLE_IDS
from app.schemas.catalog import (
    BaseProductType,
    CatalogIngredients,
    IngredientSelection,
    OptionSearchResponse,
)
from app.schemas.compound_consultation import CompoundContext, CompoundDisplay
from app.schemas.consultation_answer import ConsultationAnswer
from app.schemas.consultation_parent import (
    ComparisonChoice,
    ConsultationIntent,
    ConsultationParent,
    ConsultationSummary,
    ParentQuestion,
)
from app.schemas.consultation_task import (
    ConsultationTaskResult,
    ProductAssessment,
    ProductRequirement,
    TaskContinuation,
)
from app.schemas.conversation import ConversationMetadata
from app.schemas.knowledge import KnowledgeReply
from app.schemas.memory import (
    AppliedColorMemory,
    AppliedMemory,
    AppliedOwnedProductMemory,
    AppliedSkinTypeMemory,
    ConsultationMemory,
    MemoryProposal,
)
from app.schemas.owned_look_context import (
    OwnedLookContext,
    OwnedLookOptionDisplay,
    OwnedLookOutcome,
)
from app.schemas.product_style_consultation import ProductStyleContext
from app.schemas.style_recipe import (
    StyleCandidate,
    StyleCandidateRef,
    StyleCondition,
    StyleContext,
    StyleRecipe,
)
from app.schemas.supervisor import IngredientComparison, ScreenContext, SupervisorResult, ToolResult

Locale = Literal["en", "ko", "ja", "zh"]


class ApiModel(BaseModel):
    model_config = ConfigDict(
        alias_generator=to_camel, populate_by_name=True, serialize_by_alias=True
    )


class SkinHint(ApiModel):
    """On-device estimate only; face images never leave the device."""

    mst: int | None = Field(default=None, ge=1, le=10)
    undertone: Literal["cool", "neutral", "warm"] | None = None


ArIntensity = Annotated[float, Field(strict=True, ge=0, le=1, allow_inf_nan=False)]
ArVersion = Annotated[int, Field(strict=True, ge=0, le=2**53 - 1)]
ArIdentifier = Annotated[str, StringConstraints(min_length=1, max_length=128, pattern=r"\S")]


class ArModel(ApiModel):
    model_config = ConfigDict(extra="forbid")


class ArLipSelection(ArModel):
    product_id: ArIdentifier
    shade_id: ArIdentifier
    intensity: ArIntensity


class ArContext(ArModel):
    """Caller-supplied snapshot, not proof of catalog validity or current app state."""

    screen_id: Literal["A-01"]
    state_version: ArVersion
    active_zone: (
        Literal[
            "lip",
            "blush",
            "eyeshadow",
            "eyeliner",
            "highlighter",
            "contour",
            "brow",
            "foundation",
            "mascara",
        ]
        | None
    )
    supported_actions: list[Annotated[str, StringConstraints(min_length=1, max_length=64)]] = Field(
        max_length=16
    )
    lip: ArLipSelection | None
    highlighter: ArLipSelection | None = None
    contour: ArLipSelection | None = None
    blush: ArLipSelection | None = None
    eyeshadow: ArLipSelection | None = None
    eyeliner: ArLipSelection | None = None
    mascara: ArLipSelection | None = None


class IngredientFilter(ArModel):
    ingredient_name: str = Field(min_length=1, max_length=500)
    operator: Literal["includes", "excludes"]


class BeautyFilters(ArModel):
    product_type: BaseProductType | None = Field(default=None, exclude_if=lambda v: v is None)
    unsupported_conditions: list[str] = Field(
        default_factory=list, max_length=8, exclude_if=lambda v: not v
    )
    option_search: bool = Field(default=False, exclude_if=lambda v: not v)
    price_basis: Literal["current_offer", "catalog_reference", "collected_snapshot"] | None = Field(
        default=None, exclude_if=lambda v: v is None
    )
    texture: Literal["matte"] | None = Field(default=None, exclude_if=lambda v: v is None)
    category: Literal["lip", "cheek", "eye", "base", "skincare", "suncare"] | None = None
    max_price_krw: Annotated[int, Field(strict=True, ge=0, le=100_000_000)] | None = Field(
        default=None, alias="maxPriceKRW"
    )
    fragrance_free: bool = False
    moisturizing: bool = False
    query: str = Field(default="", max_length=80)
    ingredient_conditions: list[IngredientFilter] = Field(default_factory=list, max_length=6)


class ChatSessionRef(ArModel):
    session_id: UUID
    session_token: str = Field(min_length=32, max_length=128, repr=False)
    result_set_id: UUID
    state_version: Annotated[int, Field(strict=True, ge=1, le=2**53 - 1)]
    expires_at: Annotated[int, Field(strict=True, ge=0)]


class BeautyContext(ArModel):
    """Client-carried search context; IDs and facts are always rechecked with Catalog."""

    compound: CompoundContext | None = Field(default=None, exclude_if=lambda v: v is None)
    option_scope: list[IngredientSelection] | None = Field(
        default=None, max_length=42, exclude_if=lambda v: v is None
    )
    version: Literal[1] = 1
    issued_at: Annotated[int, Field(strict=True, ge=0)]
    filters: BeautyFilters
    candidate_ids: list[ArIdentifier] = Field(default_factory=list, max_length=6)
    scope_ids: list[ArIdentifier] = Field(default_factory=list, max_length=6)
    selected_product_id: ArIdentifier | None = None
    selected_option_id: str | None = Field(default=None, max_length=128)
    shade_selections: dict[ArIdentifier, ArIdentifier] = Field(
        default_factory=dict, max_length=6, exclude_if=lambda v: not v
    )
    session: ChatSessionRef | None = Field(default=None, exclude_if=lambda v: v is None)


class ProductEvidence(ArModel):
    product_id: str
    source: Literal["catalog_api"] = "catalog_api"
    ingredient_coverage: Literal["key_only", "unknown"]
    fragrance_status: Literal["unknown"] = "unknown"


class RecentChatMessage(ArModel):
    id: ArIdentifier
    role: Literal["user", "assistant"]
    text: str = Field(min_length=1, max_length=2000)

    @model_validator(mode="after")
    def limit_user_text(self) -> Self:
        if self.role == "user" and len(self.text) > 1000:
            raise ValueError("User history exceeds 1000 characters")
        return self


class PendingClarification(ArModel):
    id: UUID
    missing_slot: Literal["product", "shade"]
    product_id: ArIdentifier | None = None
    result_set_id: UUID
    created_request_id: UUID
    created_state_version: int = Field(ge=1)
    expires_at: int = Field(ge=0)
    ingredient_conditions: list[IngredientFilter] = Field(default_factory=list, max_length=6)


class ChatRequest(ApiModel):
    _comparison_question: ParentQuestion | None = PrivateAttr(default=None)
    _comparison_followup: bool = PrivateAttr(default=False)
    _product_requirement: ProductRequirement | None = PrivateAttr(default=None)
    _product_operation: str | None = PrivateAttr(default=None)
    _product_contract_required: bool = PrivateAttr(default=False)
    _parent_intent: ConsultationIntent | None = PrivateAttr(default=None)
    _parent_intent_audit: dict | None = PrivateAttr(default=None)
    _parent_deadline: float | None = PrivateAttr(default=None)
    _parent_replan: dict | None = PrivateAttr(default=None)
    _requested_explanation: str = PrivateAttr(default="")
    _requested_explanation: str = PrivateAttr(default="")
    _parent_sources: dict = PrivateAttr(default_factory=dict)
    _consultation_parent: ConsultationParent | None = PrivateAttr(default=None)
    _product_style_context: ProductStyleContext | None = PrivateAttr(default=None)
    structured_memory: bool = Field(default=False, strict=True, exclude_if=lambda value: not value)
    _server_history: bool = PrivateAttr(default=False)
    _historical_product_ids: tuple[str, ...] = PrivateAttr(default=())
    _compound_context: CompoundContext | None = PrivateAttr(default=None)
    _owned_look_context: OwnedLookContext | None = PrivateAttr(default=None)
    _owned_look_goal_followup: bool = PrivateAttr(default=False)
    _owned_look_llm: object | None = PrivateAttr(default=None)
    _owned_look_reference: bool = PrivateAttr(default=False)
    _owned_look_answer: tuple[str, str, str, str] | None = PrivateAttr(default=None)
    _question_answers: list[tuple[ParentQuestion, str]] = PrivateAttr(default_factory=list)
    _g7_execution: object | None = PrivateAttr(default=None)
    _consented_memories: list[str] = PrivateAttr(default_factory=list)
    _consultation_memories: tuple[ConsultationMemory, ...] | None = PrivateAttr(default=None)
    _memory_epoch: int | None = PrivateAttr(default=None)
    _memory_generation: str | None = PrivateAttr(default=None)
    style_search: bool = Field(default=False, strict=True, exclude_if=lambda v: not v)
    excluded_style: StyleCandidateRef | None = None
    previous_style_candidates: list[StyleCandidateRef] = Field(
        default_factory=list, max_length=6, exclude_if=lambda v: not v
    )
    previous_style_selection: StyleCandidateRef | None = None
    style_conditions: list[StyleCondition] | None = Field(default=None, max_length=7)
    style_compare: bool = False
    recent_messages: list[RecentChatMessage] = Field(
        default_factory=list, max_length=8, exclude_if=lambda v: not v
    )
    clarification_id: UUID | None = Field(default=None, exclude_if=lambda v: v is None)

    @model_validator(mode="after")
    def validate_recent_messages(self) -> Self:
        ids = [m.id for m in self.recent_messages]
        if len(ids) != len(set(ids)) or sum(len(m.text) for m in self.recent_messages) > 8000:
            raise ValueError("Invalid recent conversation")
        looks = [(item.kind, item.look_id) for item in self.previous_style_candidates]
        if len(looks) != len(set(looks)):
            raise ValueError("Duplicate previous looks")
        slots = [item.slot for item in self.style_conditions or []]
        if len(slots) != len(set(slots)):
            raise ValueError("Duplicate style conditions")
        return self

    general_makeup: bool = Field(default=False, strict=True, exclude_if=lambda v: not v)
    message: str = Field(min_length=1, max_length=1000)
    locale: Locale = "en"
    skin: SkinHint | None = None
    request_type: Literal[
        "chat", "ar_command", "beauty_consultation", "style_consultation", "knowledge_consultation"
    ] = "chat"
    chat_context: BeautyContext | None = None
    request_id: UUID | None = None
    conversation_id: UUID | None = None
    expected_conversation_version: Annotated[int, Field(strict=True, ge=0, le=2**53 - 1)] | None = (
        None
    )
    ar_context: ArContext | None = None
    screen_context: ScreenContext | None = None
    style_context: StyleContext | None = None

    @model_validator(mode="before")
    @classmethod
    def ignore_ar_fields_for_chat(cls, data):
        # Older chat clients could send unrecognized fields; keep them inert.
        if not isinstance(data, dict):
            return data
        request_type = data.get("requestType", data.get("request_type", "chat"))
        g2_enabled = data.get("locale", "en") == "ko" and get_settings().g1_supervisor_enabled
        style_search = data.get("styleSearch", data.get("style_search")) is True
        if (
            not g2_enabled or request_type not in {"chat", "beauty_consultation"}
        ) and not style_search:
            ignored = {"clarificationId", "clarification_id"}
            if not (
                g2_enabled
                and get_settings().g5_enabled
                and request_type == "knowledge_consultation"
            ):
                ignored.update({"recentMessages", "recent_messages"})
            data = {k: v for k, v in data.items() if k not in ignored}
        if data.get("generalMakeup", data.get("general_makeup")) is True and not g2_enabled:
            # The app used to omit context for these requests; preserve that OFF contract.
            data = {k: v for k, v in data.items() if k not in {"chatContext", "chat_context"}}
        session_chat = request_type in {"chat", "knowledge_consultation"} and g2_enabled
        if request_type != "beauty_consultation" and not session_chat:
            data = {k: v for k, v in data.items() if k not in {"chatContext", "chat_context"}}
        if isinstance(data, dict) and request_type in {"chat", "knowledge_consultation"}:
            ar_fields = {"requestId", "request_id", "arContext", "ar_context"}
            if session_chat or data.get("conversationId", data.get("conversation_id")) is not None:
                ar_fields = {"arContext", "ar_context"}
            data = {k: v for k, v in data.items() if k not in ar_fields}
        return data

    @model_validator(mode="after")
    def validate_ar_request(self) -> Self:
        if self.conversation_id is not None:
            if self.request_type == "ar_command":
                raise ValueError("AR commands do not support persistent conversations")
            if self.request_id is None or self.expected_conversation_version is None:
                raise ValueError("Persistent chat requires a request ID and expected version")
        if self.style_search and self.request_type not in {"chat", "style_consultation"}:
            raise ValueError("Style search is only available in chat")
        if self.excluded_style and (not self.style_search or self.previous_style_candidates):
            raise ValueError("Look exclusion requires a new style search")
        if (
            self.previous_style_candidates or self.previous_style_selection
        ) and not self.style_search:
            raise ValueError("Previous look references require style search")
        if self.style_compare and (not self.style_search or not self.previous_style_candidates):
            raise ValueError("Style comparison requires previous candidates")
        if self.request_type == "ar_command" and (
            self.request_id is None or self.ar_context is None or not self.message.strip()
        ):
            raise ValueError("AR commands require a request ID, context, and non-blank message")
        return self


class ArIntensityAction(ArModel):
    action: Literal["set_intensity"]
    zone: Literal["lip"]
    value: ArIntensity


class ArGeometryAction(ArModel):
    action: Literal["set_geometry"]
    zone: Literal[
        "highlighter",
        "contour",
        "eyeliner",
        "blush",
        "eyeshadow",
        "lip",
        "mascara",
    ]
    style: Annotated[str, StringConstraints(min_length=1, max_length=64)]

    @model_validator(mode="after")
    def style_belongs_to_zone(self) -> Self:
        if self.style not in STYLE_IDS.get(self.zone, ()):
            raise ValueError("style is not allowed for zone")
        return self


ArAction = Annotated[ArIntensityAction | ArGeometryAction, Field(discriminator="action")]


class ArActionDecision(ArModel):
    status: Literal["proposed"]
    action: ArAction


class ArClarificationDecision(ArModel):
    status: Literal["clarification"]
    reason: Literal["target_required", "value_required", "ambiguous_value"]


class ArUnsupportedDecision(ArModel):
    status: Literal["unsupported"]
    reason: Literal["unsupported_zone", "unsupported_action", "compound_request"]


class ArNoopDecision(ArModel):
    status: Literal["noop"]


ArDecision = Annotated[
    ArActionDecision | ArClarificationDecision | ArUnsupportedDecision | ArNoopDecision,
    Field(discriminator="status"),
]


class ArIntensityProposal(ArIntensityAction):
    command_id: UUID
    expected_state_version: ArVersion
    product_id: ArIdentifier
    shade_id: ArIdentifier


class ArGeometryProposal(ArGeometryAction):
    command_id: UUID
    expected_state_version: ArVersion
    product_id: ArIdentifier
    shade_id: ArIdentifier
    geometry: dict[str, object]


ArActionProposal = Annotated[
    ArIntensityProposal | ArGeometryProposal, Field(discriminator="action")
]


class ArResult(ArModel):
    request_id: UUID
    status: Literal["proposed", "clarification", "unsupported", "noop"]
    action_proposal: ArActionProposal | None = Field(default=None, exclude_if=lambda v: v is None)
    reason: (
        Literal[
            "lip_not_selected",
            "target_required",
            "value_required",
            "ambiguous_value",
            "absolute_command_required",
            "unsupported_zone",
            "unsupported_action",
            "compound_request",
            "client_capability_missing",
            "invalid_intensity",
            "zone_not_selected",
        ]
        | None
    ) = Field(default=None, exclude_if=lambda v: v is None)

    @model_validator(mode="after")
    def validate_result(self) -> Self:
        if (self.status == "proposed") != (self.action_proposal is not None):
            raise ValueError("Only proposed results carry an action")
        if (self.status in {"clarification", "unsupported"}) != (self.reason is not None):
            raise ValueError("Only clarification and unsupported results carry a reason")
        return self


class ArAckRequest(ArModel):
    request_id: UUID
    command_id: UUID
    session_id: UUID
    status: Literal["APPLIED", "NO_CHANGE", "REJECTED", "FAILED", "UNKNOWN"]
    actual_state_version: ArVersion | None = None


class ArAckResponse(ApiModel):
    received: bool


class ProductRef(ApiModel):
    id: str
    brand: str
    name: str
    category: str


class FragranceSearchSummary(ApiModel):
    checked: int = Field(ge=0)
    total: int = Field(ge=0)
    verified_product_ids: list[ArIdentifier] = Field(default_factory=list)


class ChatIngredientResult(CatalogIngredients):
    shade_name: str | None = Field(default=None, exclude_if=lambda value: value is None)


class ChatResponse(ApiModel):
    consultation: ConsultationSummary | None = Field(default=None, exclude_if=lambda v: v is None)
    _comparison_choices: list[ComparisonChoice] = PrivateAttr(default_factory=list)
    _comparison_price_basis: (
        Literal["current_offer", "catalog_reference", "collected_snapshot"] | None
    ) = PrivateAttr(default=None)
    _comparison_base_id: str | None = PrivateAttr(default=None)
    _product_assessment: ProductAssessment | None = PrivateAttr(default=None)
    _consultation_answer: ConsultationAnswer | None = PrivateAttr(default=None)
    _product_style_context: ProductStyleContext | None = PrivateAttr(default=None)
    _consultation_parent: ConsultationParent | None = PrivateAttr(default=None)
    _parent_trace: list[dict] = PrivateAttr(default_factory=list)
    _proposed_next_tasks: list[TaskContinuation] = PrivateAttr(default_factory=list)
    _proposed_next_tasks: list[TaskContinuation] = PrivateAttr(default_factory=list)
    _task_results: list[ConsultationTaskResult] = PrivateAttr(default_factory=list)
    _preserve_parent_context: bool = PrivateAttr(default=False)
    owned_look_options: OwnedLookOptionDisplay | None = Field(
        default=None, exclude_if=lambda v: v is None
    )
    _owned_look_context: OwnedLookContext | None = PrivateAttr(default=None)
    _owned_look_outcome: OwnedLookOutcome | None = PrivateAttr(default=None)
    _owned_look_interpretation: dict | None = PrivateAttr(default=None)

    compound: CompoundDisplay | None = Field(default=None, exclude_if=lambda v: v is None)
    conversation: ConversationMetadata | None = Field(default=None, exclude_if=lambda v: v is None)
    memory_proposal: MemoryProposal | None = Field(default=None, exclude_if=lambda v: v is None)
    applied_memories: list[
        AppliedMemory | AppliedSkinTypeMemory | AppliedColorMemory | AppliedOwnedProductMemory
    ] = Field(default_factory=list, exclude_if=lambda v: not v)
    style_candidates: list[StyleCandidate] | None = Field(
        default=None, exclude_if=lambda v: v is None
    )
    style_conditions: list[StyleCondition] | None = Field(
        default=None, exclude_if=lambda v: v is None
    )
    knowledge: KnowledgeReply | None = Field(default=None, exclude_if=lambda v: v is None)
    option_search: OptionSearchResponse | None = Field(default=None, exclude_if=lambda v: v is None)
    pending_clarification: PendingClarification | None = Field(
        default=None, exclude_if=lambda v: v is None
    )
    style_status: Literal["ready", "clarification", "not_found", "error", "unsupported"] | None = (
        Field(default=None, exclude_if=lambda v: v is None)
    )
    style_recipe: StyleRecipe | None = Field(default=None, exclude_if=lambda v: v is None)
    style_context: StyleContext | None = Field(default=None, exclude_if=lambda v: v is None)
    # Internal compatibility adapter: existing app JSON and fingerprints stay unchanged.
    supervisor: SupervisorResult | None = Field(default=None, exclude=True)
    tool_result: ToolResult | None = Field(default=None, exclude=True)
    answer: str
    products: list[ProductRef]
    ar_result: ArResult | None = Field(default=None, exclude_if=lambda v: v is None)
    chat_context: BeautyContext | None = Field(default=None, exclude_if=lambda v: v is None)
    result_type: Literal["recommendations", "product_detail", "clarification", "empty"] | None = (
        Field(default=None, exclude_if=lambda v: v is None)
    )
    evidence: list[ProductEvidence] | None = Field(default=None, exclude_if=lambda v: v is None)
    ingredient_results: list[ChatIngredientResult] | None = Field(
        default=None, exclude_if=lambda v: v is None
    )
    ingredient_comparison: IngredientComparison | None = Field(
        default=None, exclude_if=lambda value: value is None
    )
    fragrance_search_summary: FragranceSearchSummary | None = Field(
        default=None, exclude_if=lambda v: v is None
    )
    session_status: Literal["stored", "unchanged", "unavailable"] | None = Field(
        default=None, exclude_if=lambda v: v is None
    )

    @model_validator(mode="after")
    def verify_ingredient_references(self) -> Self:
        ids = [p.id for p in self.products]
        for result in self.ingredient_results or []:
            if result.product_id not in ids:
                raise ValueError("Ingredient evidence outside response products")
            if result.shade_id and (
                not self.chat_context
                or self.chat_context.shade_selections.get(result.product_id) != result.shade_id
            ):
                raise ValueError("Ingredient shade outside selected context")
        return self


class ChatSessionState(ArModel):
    """Redis-only snapshot and one TTL-bound retry response, never a transcript archive."""

    conversation_id: UUID | None = Field(default=None, exclude_if=lambda v: v is None)
    pending_clarification: PendingClarification | None = Field(
        default=None, exclude_if=lambda v: v is None
    )
    memory_epoch: int | None = Field(default=None, exclude_if=lambda v: v is None, ge=0)
    memory_generation: str | None = Field(
        default=None, exclude_if=lambda v: v is None, max_length=64
    )
    session_id: UUID
    owner: str
    owner_kind: Literal["user", "guest"]
    token_hash: str = Field(repr=False, pattern=r"^[0-9a-f]{64}$")
    result_set_id: UUID
    state_version: Annotated[int, Field(strict=True, ge=1, le=2**53 - 1)]
    context: BeautyContext
    evidence_refs: list[dict[str, str | None]] = Field(default_factory=list, max_length=6)
    created_at: int
    result_created_at: int
    expires_at: int
    last_request_id: UUID
    last_fingerprint: str
    last_response: dict
    last_supervisor: SupervisorResult | None = None
    last_tool_result: ToolResult | None = None


class GraphProduct(ApiModel):
    """Product context retrieved from the graph for one question."""

    id: str
    brand: str
    name: str
    category: str
    texture: str | None = None
    price_krw: int | None = Field(default=None, alias="priceKRW")
    ingredients: list[str] = []
    tags: list[str] = []
    looks: list[str] = []

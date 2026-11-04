from typing import Annotated, Literal, Self
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator
from pydantic.alias_generators import to_camel

from app.schemas.catalog import CatalogIngredients
from app.schemas.style_recipe import StyleContext, StyleRecipe
from app.schemas.supervisor import ScreenContext, SupervisorResult, ToolResult

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


ArZone = Literal[
    "lip", "blush", "eyeshadow", "eyeliner", "brow", "foundation", "contour", "highlighter"
]


class ArSelection(ArModel):
    product_id: ArIdentifier
    shade_id: ArIdentifier
    intensity: ArIntensity


class ArUndo(ArModel):
    zone: ArZone
    value: ArIntensity


class ArContext(ArModel):
    """Caller-supplied snapshot, not proof of catalog validity or current app state."""

    screen_id: Literal["A-01"]
    state_version: ArVersion
    active_zone: ArZone | None
    supported_actions: list[Annotated[str, StringConstraints(min_length=1, max_length=64)]] = Field(
        max_length=16
    )
    lip: ArSelection | None
    selections: dict[ArZone, ArSelection] | None = None
    undo: ArUndo | None = None

    def selection(self, zone: ArZone) -> ArSelection | None:
        if self.selections is not None:
            return self.selections.get(zone)
        return self.lip if zone == "lip" else None


class IngredientFilter(ArModel):
    ingredient_name: str = Field(min_length=1, max_length=500)
    operator: Literal["includes", "excludes"]


class BeautyFilters(ArModel):
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

    version: Literal[1] = 1
    issued_at: Annotated[int, Field(strict=True, ge=0)]
    filters: BeautyFilters
    candidate_ids: list[ArIdentifier] = Field(default_factory=list, max_length=6)
    scope_ids: list[ArIdentifier] = Field(default_factory=list, max_length=6)
    selected_product_id: ArIdentifier | None = None
    shade_selections: dict[ArIdentifier, ArIdentifier] = Field(
        default_factory=dict, max_length=6, exclude_if=lambda v: not v
    )
    session: ChatSessionRef | None = Field(default=None, exclude_if=lambda v: v is None)


class ProductEvidence(ArModel):
    product_id: str
    source: Literal["catalog_api"] = "catalog_api"
    ingredient_coverage: Literal["key_only", "unknown"]
    fragrance_status: Literal["unknown"] = "unknown"


class ChatRequest(ApiModel):
    message: str = Field(min_length=1, max_length=1000)
    locale: Locale = "en"
    skin: SkinHint | None = None
    request_type: Literal["chat", "ar_command", "beauty_consultation", "style_consultation"] = (
        "chat"
    )
    chat_context: BeautyContext | None = None
    request_id: UUID | None = None
    ar_context: ArContext | None = None
    screen_context: ScreenContext | None = None
    style_context: StyleContext | None = None

    @model_validator(mode="before")
    @classmethod
    def ignore_ar_fields_for_chat(cls, data):
        # Older chat clients could send unrecognized fields; keep them inert.
        if (
            isinstance(data, dict)
            and data.get("requestType", data.get("request_type", "chat")) != "beauty_consultation"
        ):
            data = {k: v for k, v in data.items() if k not in {"chatContext", "chat_context"}}
        if (
            isinstance(data, dict)
            and data.get("requestType", data.get("request_type", "chat")) == "chat"
        ):
            ar_fields = {"requestId", "request_id", "arContext", "ar_context"}
            data = {k: v for k, v in data.items() if k not in ar_fields}
        return data

    @model_validator(mode="after")
    def validate_ar_request(self) -> Self:
        if self.request_type == "ar_command" and (
            self.request_id is None or self.ar_context is None or not self.message.strip()
        ):
            raise ValueError("AR commands require a request ID, context, and non-blank message")
        return self


class ArAction(ArModel):
    action: Literal["set_intensity"]
    zone: Literal["lip"]
    value: ArIntensity


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


class ArActionProposal(ArModel):
    action: Literal["set_intensity", "undo"]
    zone: ArZone
    value: ArIntensity
    command_id: UUID
    expected_state_version: ArVersion
    product_id: ArIdentifier
    shade_id: ArIdentifier


class ArResult(ArModel):
    request_id: UUID
    status: Literal["proposed", "clarification", "unsupported", "noop"]
    action_proposal: ArActionProposal | None = Field(default=None, exclude_if=lambda v: v is None)
    reason: (
        Literal[
            "lip_not_selected",
            "product_not_selected",
            "undo_unavailable",
            "target_required",
            "value_required",
            "ambiguous_value",
            "absolute_command_required",
            "unsupported_zone",
            "unsupported_action",
            "compound_request",
            "client_capability_missing",
            "invalid_intensity",
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


class ChatResponse(ApiModel):
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
    ingredient_results: list[CatalogIngredients] | None = Field(
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

    session_id: UUID
    owner: str
    owner_kind: Literal["user", "guest"]
    token_hash: str = Field(repr=False, pattern=r"^[0-9a-f]{64}$")
    result_set_id: UUID
    state_version: Annotated[int, Field(strict=True, ge=1, le=2**53 - 1)]
    context: BeautyContext
    evidence_refs: list[dict[str, str]] = Field(default_factory=list, max_length=6)
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

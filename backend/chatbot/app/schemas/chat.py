from typing import Annotated, Literal, Self
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator
from pydantic.alias_generators import to_camel

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
    active_zone: Literal["lip", "blush", "eyeshadow", "eyeliner", "brow", "foundation"] | None
    supported_actions: list[Annotated[str, StringConstraints(min_length=1, max_length=64)]] = Field(
        max_length=16
    )
    lip: ArLipSelection | None


class ChatRequest(ApiModel):
    message: str = Field(min_length=1, max_length=1000)
    locale: Locale = "en"
    skin: SkinHint | None = None
    request_type: Literal["chat", "ar_command"] = "chat"
    request_id: UUID | None = None
    ar_context: ArContext | None = None

    @model_validator(mode="before")
    @classmethod
    def ignore_ar_fields_for_chat(cls, data):
        # Older chat clients could send unrecognized fields; keep them inert.
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


class ArActionProposal(ArAction):
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
    answer: str
    products: list[ProductRef]
    ar_result: ArResult | None = Field(default=None, exclude_if=lambda v: v is None)



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

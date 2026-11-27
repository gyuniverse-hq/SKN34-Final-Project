from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator
from pydantic.alias_generators import to_camel

from app.schemas.compound_consultation import CompoundContext
from app.schemas.consultation_parent import ConsultationParent
from app.schemas.owned_look_context import OwnedLookContext
from app.schemas.style_recipe import StyleCandidateRef, StyleCondition, StyleContext


class ConversationModel(BaseModel):
    model_config = ConfigDict(
        alias_generator=to_camel, populate_by_name=True, serialize_by_alias=True, extra="forbid"
    )


ConversationVersion = Annotated[int, Field(strict=True, ge=0, le=2**53 - 1)]


class GeneralEntry(ConversationModel):
    type: Literal["general"]


class ProductEntry(ConversationModel):
    option_id: str | None = Field(default=None, min_length=1, max_length=128)
    type: Literal["product"]
    product_id: str = Field(min_length=1, max_length=128)
    shade_id: str | None = Field(default=None, min_length=1, max_length=128)


class LookEntry(StyleCandidateRef):
    type: Literal["look"]


ConversationEntry = Annotated[GeneralEntry | ProductEntry | LookEntry, Field(discriminator="type")]


class CreateConversationRequest(ConversationModel):
    request_id: UUID
    entry: ConversationEntry


class CreateConversationResponse(ConversationModel):
    conversation_id: UUID
    conversation_version: ConversationVersion
    subject: ConversationEntry
    created_at: datetime


class SelectProductPayload(ConversationModel):
    option_id: str | None = Field(default=None, min_length=1, max_length=128)
    product_id: str = Field(min_length=1, max_length=64, pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]*$")


class SelectShadePayload(SelectProductPayload):
    shade_id: str = Field(min_length=1, max_length=128, pattern=r"\S")


class SelectLookPayload(StyleCandidateRef):
    pass


class SetRecipeStepPayload(StyleCandidateRef):
    recipe_version: str = Field(min_length=1, max_length=128)
    current_step: int = Field(strict=True, ge=0, le=100)


class ClearSelectionPayload(ConversationModel):
    pass


class UpdateConversationStateRequest(ConversationModel):
    request_id: UUID
    expected_conversation_version: ConversationVersion
    operation: Literal[
        "select_product", "select_shade", "select_look", "set_recipe_step", "clear_selection"
    ]
    payload: dict[str, object]

    @model_validator(mode="after")
    def validate_payload(self):
        models = {
            "select_product": SelectProductPayload,
            "select_shade": SelectShadePayload,
            "select_look": SelectLookPayload,
            "set_recipe_step": SetRecipeStepPayload,
            "clear_selection": ClearSelectionPayload,
        }
        self.payload = (
            models[self.operation]
            .model_validate(self.payload)
            .model_dump(mode="json", by_alias=True, exclude_none=True)
        )
        return self


class ConversationMetadata(ConversationModel):
    id: UUID
    version: ConversationVersion
    turn_id: UUID
    persistence_status: Literal["stored"]


class StoredGoal(ConversationModel):
    domain: Literal["general", "product", "ingredient", "style", "knowledge"]
    status: Literal["active", "complete", "pending"] = "active"


class StoredProductContext(ConversationModel):
    selected_option_id: str | None = Field(default=None, max_length=128)
    selected_product_id: str | None = Field(default=None, max_length=128)
    selected_shade_id: str | None = Field(default=None, max_length=128)
    filters: dict[str, object] = Field(default_factory=dict)
    historical_candidate_refs: list[str] = Field(default_factory=list, max_length=6)
    source_version: str | None = Field(default=None, max_length=128)


class StoredStyleContext(StyleContext):
    conditions: list[StyleCondition] = Field(default_factory=list, max_length=7)
    historical_candidate_refs: list[StyleCandidateRef] = Field(default_factory=list, max_length=6)


class StoredMemoryRef(ConversationModel):
    memory_id: UUID
    version: ConversationVersion


class StoredConversationContext(ConversationModel):
    consultation_parent: ConsultationParent | None = Field(
        default=None, exclude_if=lambda v: v is None
    )
    schema_version: Literal[1] = 1
    owned_look: OwnedLookContext | None = Field(default=None, exclude_if=lambda v: v is None)
    current_goal: StoredGoal | None = None
    compound: CompoundContext | None = Field(default=None, exclude_if=lambda v: v is None)
    product: StoredProductContext | None = None
    style: StoredStyleContext | None = None
    style_candidates: list[StyleCandidateRef] = Field(default_factory=list, max_length=6)
    style_conditions: list[StyleCondition] = Field(default_factory=list, max_length=7)
    # Pending execution capabilities are not restorable in G7-3.
    pending_goal: None = None
    memory_revocation_epoch: ConversationVersion = 0
    memory_refs: list[StoredMemoryRef] = Field(default_factory=list, max_length=100)

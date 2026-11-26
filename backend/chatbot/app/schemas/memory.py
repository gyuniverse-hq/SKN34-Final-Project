from dataclasses import dataclass
from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import Field, model_validator

from app.schemas.conversation import ConversationModel, ConversationVersion


class CreateMemoryRequest(ConversationModel):
    request_id: UUID
    proposal_id: str = Field(min_length=1, max_length=128)
    expected_proposal_version: ConversationVersion
    confirmed: Literal[True]


class UpdateMemoryRequest(ConversationModel):
    request_id: UUID
    expected_version: ConversationVersion
    confirmed: Literal[True]
    value: object


class MemoryProposal(ConversationModel):
    proposal_id: UUID
    version: ConversationVersion
    kind: Literal["preference", "profile", "owned_product"]
    value: str = Field(min_length=1, max_length=500)
    consent_scope: Literal["future_consultations"] = "future_consultations"
    expires_at: datetime


class MemoryItem(ConversationModel):
    id: UUID
    kind: Literal["preference", "profile", "owned_product"]
    value: str = Field(min_length=1, max_length=500)
    version: ConversationVersion
    consent_scope: Literal["future_consultations"]


MemoryKey = Literal["skin.type", "makeup.color", "makeup.finish", "inventory.product"]
MemoryLocale = Literal["ko", "en", "ja", "zh"]


class AccountMemorySettings(ConversationModel):
    enabled: bool
    version: ConversationVersion
    notice_acknowledged: bool
    memory_set_revision: str


class UpdateAccountMemorySettings(ConversationModel):
    request_id: UUID
    expected_version: ConversationVersion
    enabled: bool | None = Field(default=None, strict=True)
    acknowledge_notice: Literal[True] | None = None

    @model_validator(mode="after")
    def check_change(self):
        if self.enabled is None and self.acknowledge_notice is None:
            raise ValueError("A settings decision is required")
        return self


class DeleteAllMemories(ConversationModel):
    request_id: UUID
    expected_version: ConversationVersion
    expected_memory_set_revision: str = Field(pattern=r"^[0-9a-f]{64}$")
    confirmed: Literal[True]


class UpdateStructuredMemory(ConversationModel):
    request_id: UUID
    expected_version: ConversationVersion
    confirmed: Literal[True]
    value: str = Field(min_length=1, max_length=500)
    locale: MemoryLocale = "en"


class StructuredMemoryValue(ConversationModel):
    key: MemoryKey
    kind: Literal["preference", "profile", "owned_product"]
    value: dict[str, str]
    display_value: str = Field(min_length=1)
    context: Literal["work"] | None = None


@dataclass(frozen=True, slots=True)
class ConsultationMemory:
    id: UUID
    version: int
    text: str | None = None
    structured: StructuredMemoryValue | None = None


class AppliedMemory(ConversationModel):
    memory_id: UUID
    version: ConversationVersion
    key: Literal["makeup.finish"] = "makeup.finish"
    tool: Literal["catalog.search_products"] = "catalog.search_products"
    field: Literal["texture"] = "texture"
    application_kind: Literal["ranking"] = "ranking"


class AppliedSkinTypeMemory(ConversationModel):
    memory_id: UUID
    version: ConversationVersion
    key: Literal["skin.type"] = "skin.type"
    tool: Literal["skincare.recommend"] = "skincare.recommend"
    field: Literal["skinType"] = "skinType"
    application_kind: Literal["candidate_selection"] = "candidate_selection"


class ColorShadeMatch(ConversationModel):
    product_id: str = Field(min_length=1, max_length=128)
    shade_id: str = Field(min_length=1, max_length=128)
    basis: Literal["measured", "user_verified", "estimated", "catalog_name"]


class AppliedColorMemory(ConversationModel):
    memory_id: UUID
    version: ConversationVersion
    key: Literal["makeup.color"] = "makeup.color"
    tool: Literal["catalog.search_products"] = "catalog.search_products"
    field: Literal["shadeColorFamily"] = "shadeColorFamily"
    application_kind: Literal["ranking"] = "ranking"
    matches: list[ColorShadeMatch] = Field(min_length=1, max_length=6)


class AppliedOwnedProductMemory(ConversationModel):
    memory_id: UUID
    version: ConversationVersion
    key: Literal["inventory.product"] = "inventory.product"
    tool: Literal["catalog.search_products"] = "catalog.search_products"
    field: Literal["productId"] = "productId"
    application_kind: Literal["candidate_filter"] = "candidate_filter"
    action: Literal["include", "exclude"]
    product_id: str = Field(min_length=1, max_length=128)
    shade_id: str | None = Field(
        default=None, max_length=128, exclude_if=lambda value: value is None
    )


class StructuredProposalItem(StructuredMemoryValue):
    item_id: UUID
    version: ConversationVersion
    status: Literal["pending", "deferred"]
    previous_display_value: str | None = None
    editable_value: str
    choices: list[tuple[str, str]]


class StructuredProposalGroup(ConversationModel):
    group_id: UUID
    conversation_id: UUID
    expires_at: datetime
    items: list[StructuredProposalItem]


class EditStructuredProposal(ConversationModel):
    request_id: UUID
    expected_version: ConversationVersion
    value: str = Field(min_length=1, max_length=500)


class DecideStructuredItem(ConversationModel):
    item_id: UUID
    expected_version: ConversationVersion
    action: Literal["approve", "defer", "reject"]
    confirmed: Literal[True] | None = None

    @model_validator(mode="after")
    def check_confirmation(self):
        if (self.action == "approve") != (self.confirmed is True):
            raise ValueError("An approval requires explicit confirmation")
        return self


class DecideStructuredProposals(ConversationModel):
    request_id: UUID
    decisions: list[DecideStructuredItem] = Field(min_length=1)

    @model_validator(mode="after")
    def check_unique_items(self):
        if len({item.item_id for item in self.decisions}) != len(self.decisions):
            raise ValueError("Each item can be decided once per request")
        return self

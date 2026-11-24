from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import Field

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

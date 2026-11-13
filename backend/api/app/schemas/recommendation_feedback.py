"""Authenticated V2 history contract. No arbitrary client snapshots or purchase claims."""

from typing import Literal
from uuid import UUID

from pydantic import AwareDatetime, Field

from app.schemas.recommendation_comparison import ComparisonInput
from app.schemas.skincare import StrictModel


class RecordedComparisonInput(StrictModel):
    session_id: UUID
    input: ComparisonInput


class RecommendationImpressionInput(StrictModel):
    impression_id: UUID
    candidate_id: UUID
    view_instance_id: UUID
    displayed_position: int = Field(ge=1, le=5, strict=True)
    occurred_at: AwareDatetime
    surface: Literal["v2_comparison"] = "v2_comparison"
    visibility_policy_version: Literal["half-visible-500ms-v1", "direct-interaction-v1"]


class RecommendationEventInput(StrictModel):
    event_id: UUID
    impression_id: UUID
    session_id: UUID
    product_id: str = Field(min_length=1, max_length=200)
    option_id: str | None = Field(min_length=1, max_length=200)
    event_type: Literal["product_view", "cart_add", "outbound_click"]
    occurred_at: AwareDatetime
    surface: Literal["product_detail"] = "product_detail"

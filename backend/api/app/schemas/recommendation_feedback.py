"""Authenticated skin recommendation history contracts."""

from typing import Literal
from uuid import UUID

from pydantic import AwareDatetime, Field

from app.schemas.skincare import SkincareProfileRequest, StrictModel

# Keep the stored identifier so existing impressions, carts, and reports still join.
SKINCARE_HISTORY_CONTRACT = "skincare-v1-serving-history-v1"


class RecordedSkincareInput(StrictModel):
    session_id: UUID
    input: SkincareProfileRequest


class SkincareImpressionInput(StrictModel):
    impression_id: UUID
    candidate_id: UUID
    view_instance_id: UUID
    displayed_position: int = Field(ge=1, le=10, strict=True)
    occurred_at: AwareDatetime
    surface: Literal["skin_recommendations"]
    visibility_policy_version: Literal["half-visible-500ms-v1", "direct-interaction-v1"]


class SkincareEventInput(StrictModel):
    event_id: UUID
    impression_id: UUID
    session_id: UUID
    product_id: str = Field(min_length=1, max_length=200)
    option_id: str | None = Field(min_length=1, max_length=200)
    event_type: Literal["product_view", "cart_add"]
    occurred_at: AwareDatetime
    surface: Literal["product_detail"] = "product_detail"

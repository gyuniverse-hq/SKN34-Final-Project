"""Validated proposals for conversation-scoped ownership changes, never capabilities."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field
from pydantic.alias_generators import to_camel

from app.schemas.style_recipe import Zone


class ReferenceModel(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True, extra="forbid")


class LookReferenceTarget(ReferenceModel):
    target_id: str
    product_id: str
    option_id: str | None = None
    shade_id: str | None = None
    label: str
    zone: Zone


class LookReferenceSnapshot(ReferenceModel):
    recipe_version: str
    version: str
    targets: list[LookReferenceTarget] = Field(default_factory=list)
    # Preserve actual display positions, including unresolved entries.
    look_products: list[str | None] = Field(default_factory=list)
    recommendations: list[str | None] = Field(default_factory=list)


class LookReferenceOperation(ReferenceModel):
    action: Literal["declare", "exempt"]
    target_id: str
    scope: Literal["product", "option"]
    status: Literal["present", "missing"] | None = None


class OwnedLookIntent(ReferenceModel):
    snapshot_version: str
    action: Literal["update", "clarify"]
    operations: list[LookReferenceOperation] = Field(default_factory=list)
    question: str = ""

"""Internal N02 contracts; no new public response fields or execution authority."""

from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field
from pydantic.alias_generators import to_camel

from app.schemas.catalog import OptionSearchResponse
from app.schemas.chat import ProductRef
from app.schemas.style_recipe import StyleRecipe, Zone


class OwnedLookModel(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True, extra="forbid")


class OwnedLookProduct(OwnedLookModel):
    memory_id: UUID
    memory_version: int
    product_id: str
    shade_id: str | None = None
    zone: str | None = None


class OwnedLookCoverage(OwnedLookModel):
    zone: Zone
    status: Literal["fulfilled", "confirmed_missing", "ownership_unknown", "evidence_missing"]
    product_ids: list[str] = Field(default_factory=list)
    reason: str
    user_quote: str | None = None
    substitution_status: Literal["exact_match", "unverified", "not_assessed"] = "not_assessed"
    alternative_product_ids: list[str] = Field(default_factory=list)
    substitution_evidence: str | None = None


class OwnedLookBinding(OwnedLookModel):
    source_task: str
    source_field: Literal["owned_products", "recipe", "coverage", "products", "option_searches"]
    target_input: Literal["owned_products", "recipe", "coverage", "products", "option_searches"]


class OwnedLookTask(OwnedLookModel):
    task_id: str
    plan_id: UUID
    plan_version: int = 1
    agent: Literal["owned", "style", "needs", "products", "options", "review"]
    depends_on: list[str] = Field(default_factory=list)
    input_bindings: list[OwnedLookBinding] = Field(default_factory=list)


class OwnedLookResult(OwnedLookModel):
    task_id: str
    plan_id: UUID
    plan_version: int = 1
    input_fingerprint: str
    status: Literal["complete", "partial", "waiting_user", "failed", "skipped"]
    owned_products: list[OwnedLookProduct] = Field(default_factory=list)
    recipe: StyleRecipe | None = None
    coverage: list[OwnedLookCoverage] = Field(default_factory=list)
    products: list[ProductRef] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)
    option_searches: list[OptionSearchResponse] = Field(default_factory=list)

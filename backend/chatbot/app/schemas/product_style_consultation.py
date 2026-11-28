"""Server-owned completed results, never client execution capabilities."""

from pydantic import BaseModel, ConfigDict, Field
from pydantic.alias_generators import to_camel


class ProductStyleContext(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True, extra="forbid")

    objective: str
    scope_digest: str
    product_result: dict | None = None
    style_result: dict | None = None
    failed: list[str] = Field(default_factory=list)

"""Reviewed consultation instructions, separate from AR geometry recipes."""

from typing import Literal

from pydantic import ConfigDict, Field, model_validator

from app.schemas.base import ApiModel

RecipeZone = Literal[
    "foundation",
    "brow",
    "eyeshadow",
    "eyeliner",
    "mascara",
    "blush",
    "contour",
    "highlighter",
    "lip",
]


class ConsultationStep(ApiModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    order: int = Field(strict=True, ge=1, le=100)
    zone: RecipeZone
    title: str = Field(min_length=1, max_length=200)
    description: str = Field(min_length=1, max_length=2000)
    guide_key: RecipeZone | None = None


class ReviewedProductUsage(ApiModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    step_order: int = Field(strict=True, ge=1, le=100)
    product_id: str = Field(min_length=1, max_length=128, pattern=r"\S")
    shade_id: str = Field(min_length=1, max_length=128, pattern=r"\S")
    evidence_id: str = Field(min_length=1, pattern=r"\S")
    source: str = Field(min_length=1, pattern=r"\S")


class ConsultationRecipe(ApiModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    look_id: str = Field(pattern=r"^[A-Za-z0-9_-]{1,64}$")
    kind: Literal["video"] = "video"
    version: str = Field(min_length=1, max_length=128)
    review_status: Literal["verified"]
    reviewer_id: str = Field(min_length=1)
    source: str = Field(min_length=1)
    evidence_id: str = Field(min_length=1)
    synthetic: bool = Field(default=False, strict=True)
    features: list[str] = Field(default_factory=list, max_length=20)
    steps: list[ConsultationStep] = Field(min_length=1, max_length=100)
    product_usages: list[ReviewedProductUsage] = Field(
        default_factory=list, max_length=100, exclude_if=lambda v: not v
    )

    @model_validator(mode="after")
    def ordered_steps(self):
        if [step.order for step in self.steps] != list(range(1, len(self.steps) + 1)):
            raise ValueError("Recipe steps must be complete and sequential")
        keys = [(u.step_order, u.product_id, u.shade_id) for u in self.product_usages]
        if any(u.step_order > len(self.steps) for u in self.product_usages) or len(keys) != len(
            set(keys)
        ):
            raise ValueError("Invalid or duplicate product usage step")
        return self

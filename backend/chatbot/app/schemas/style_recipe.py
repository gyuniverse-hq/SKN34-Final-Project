"""Public Style contracts. Client progress is a hint, never content or AR authority."""

import re
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator
from pydantic.alias_generators import to_camel

LookKind = Literal["video", "catalog"]
Zone = Literal[
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


class StyleModel(BaseModel):
    model_config = ConfigDict(
        alias_generator=to_camel, populate_by_name=True, serialize_by_alias=True, extra="forbid"
    )


class StyleContext(StyleModel):
    kind: LookKind
    look_id: str = Field(min_length=1, max_length=64, pattern=r"^[A-Za-z0-9_-][A-Za-z0-9._-]*$")
    recipe_id: str | None = Field(default=None, max_length=128)
    recipe_version: str | None = Field(default=None, max_length=128)
    current_step: int = Field(default=0, strict=True, ge=0, le=100)

    @model_validator(mode="after")
    def validate_namespace(self):
        pattern = (
            r"[A-Za-z0-9_-]{1,64}" if self.kind == "video" else r"[A-Za-z0-9][A-Za-z0-9._-]{0,63}"
        )
        if not re.fullmatch(pattern, self.look_id):
            raise ValueError("Invalid look ID for namespace")
        return self


class RecipeStep(StyleModel):
    order: int = Field(strict=True, ge=1, le=100)
    zone: Zone
    title: str = Field(min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=2000)
    guide_key: (
        Literal[
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
        | None
    ) = None


class ReviewedRecipe(StyleModel):
    look_id: str
    kind: LookKind
    version: str = Field(min_length=1, max_length=128)
    review_status: Literal["verified", "unreviewed"]
    source: str = Field(min_length=1)
    evidence_id: str = Field(min_length=1)
    reviewer_id: str | None = None
    features: list[str] = Field(default_factory=list, max_length=20)
    steps: list[RecipeStep] = Field(min_length=1, max_length=100)
    synthetic: bool = False

    @model_validator(mode="after")
    def validate_steps(self):
        if [s.order for s in self.steps] != list(range(1, len(self.steps) + 1)):
            raise ValueError("Recipe order must be complete and sequential")
        if self.review_status == "verified" and (
            not self.reviewer_id or any(not s.description for s in self.steps)
        ):
            raise ValueError("Reviewed steps require reviewer and instructions")
        return self


class RecipeProduct(StyleModel):
    label: str
    zone: str
    product_id: str | None = None
    shade_id: str | None = None
    mapping_status: Literal["verified", "unknown", "invalid"] = "unknown"
    catalog_valid: bool = False
    ar_eligible: bool = False


class StyleRecipe(StyleModel):
    look_id: str
    source_look_id: str
    kind: LookKind
    recipe_id: str
    recipe_version: str
    title: str
    basis: Literal["reviewed_recipe", "catalog_settings", "video_metadata"]
    review_status: Literal["verified", "unreviewed", "not_applicable"]
    video_analyzed: Literal[False] = False
    synthetic: bool = False
    source: str
    evidence_id: str | None = None
    features: list[str]
    steps: list[RecipeStep]
    current_step: int = Field(strict=True, ge=0)
    products: list[RecipeProduct]
    ar_eligible: bool
    reason: Literal[
        "reviewed_recipe", "catalog_settings", "video_not_analyzed", "no_steps", "recipe_changed"
    ]
    makeup: dict | None = None

    @model_validator(mode="after")
    def valid_references(self):
        if [s.order for s in self.steps] != list(range(1, len(self.steps) + 1)):
            raise ValueError("Recipe step order is inconsistent")
        if self.basis == "reviewed_recipe" and (
            self.review_status != "verified" or not self.evidence_id
        ):
            raise ValueError("Reviewed recipe requires review evidence")
        if self.current_step >= max(1, len(self.steps)):
            raise ValueError("Step outside recipe")
        if self.ar_eligible != any(p.ar_eligible for p in self.products):
            raise ValueError("Invalid AR eligibility")
        if any(
            p.ar_eligible
            and (
                not p.catalog_valid
                or p.mapping_status != "verified"
                or not p.product_id
                or not p.shade_id
            )
            for p in self.products
        ):
            raise ValueError("AR requires verified catalog selection")
        return self

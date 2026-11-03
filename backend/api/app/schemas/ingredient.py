"""Ingredient evidence contract, independent of Catalog keyIngredients and live DB access."""

from typing import Literal, Self

from pydantic import AwareDatetime, ConfigDict, Field, model_validator

from app.schemas.base import ApiModel


class IngredientModel(ApiModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class IngredientSelection(IngredientModel):
    product_id: str = Field(min_length=1, max_length=128)
    shade_id: str | None = Field(default=None, min_length=1, max_length=128)
    option_id: str | None = Field(default=None, min_length=1, max_length=128)


class IngredientEntry(IngredientModel):
    name: str = Field(min_length=1, max_length=500)
    sequence: int | None = Field(default=None, strict=True, ge=1)


class IngredientEvidence(IngredientSelection):
    evidence_id: str = Field(min_length=1, max_length=256)
    ingredients: list[IngredientEntry] = Field(default_factory=list)
    ingredient_coverage: Literal["full", "partial", "unknown"] = "unknown"
    source: Literal["product_notice", "option_ingredients", "mfds_dictionary", "key_ingredients"]
    source_ref: str | None = Field(default=None, max_length=2048)
    collected_at: AwareDatetime | None = None
    review_status: Literal["verified", "unreviewed", "rejected"] = "unreviewed"
    mapping_status: Literal["verified", "unverified", "ambiguous"] = "unverified"
    normalization_status: Literal["verified", "unverified"] = "unverified"
    # Test fixtures may satisfy the algorithm without establishing any real product fact.
    synthetic: bool = False


class IngredientLookupResult(IngredientModel):
    status: Literal["ok", "not_found", "error"]
    evidence: IngredientEvidence | None = None
    error_code: str | None = Field(default=None, min_length=1, max_length=128)

    @model_validator(mode="after")
    def check_status(self) -> Self:
        if (self.status == "ok") != (self.evidence is not None):
            raise ValueError("Only successful lookups carry evidence")
        if (self.status == "error") != (self.error_code is not None):
            raise ValueError("Only failed lookups carry an error code")
        return self


class IngredientCondition(IngredientSelection):
    ingredient_name: str = Field(min_length=1, max_length=500)
    operator: Literal["includes", "excludes"]


class IngredientDecision(IngredientSelection):
    condition: Literal["ingredient"] = "ingredient"
    ingredient_name: str
    operator: Literal["includes", "excludes"]
    verdict: Literal["MATCH", "NOT_MATCH", "UNKNOWN", "ERROR"]
    reason: str
    evidence_id: str | None = None
    synthetic: bool = False


class IngredientMapping(IngredientSelection):
    goods_no: str | None = None
    mapping_status: Literal["reproduced", "candidate", "ambiguous", "unmapped", "mismatch"]
    mapping_method: str
    generation_record_id: str | None = None
    source_fingerprint: str | None = None
    generator_version: str | None = None
    catalog_fingerprint: str | None = None
    source_version: str | None = None
    candidate_option_ids: list[str] = Field(default_factory=list)
    review_status: Literal["verified", "unreviewed", "rejected"] = "unreviewed"
    ingredient_coverage: Literal["full", "partial", "unknown"] = "unknown"
    normalization_status: Literal["verified", "unverified"] = "unverified"
    synthetic: bool = False


class IngredientReadResult(IngredientSelection):
    status: Literal["ok", "unknown"] = "unknown"
    verdict: Literal["MATCH", "NOT_MATCH", "UNKNOWN", "ERROR"] = "UNKNOWN"
    mapping_status: Literal["reproduced", "candidate", "ambiguous", "unmapped", "mismatch"] = (
        "unmapped"
    )
    ingredient_coverage: Literal["full", "partial", "unknown"] = "unknown"
    review_status: Literal["verified", "unreviewed", "rejected"] = "unreviewed"
    normalization_status: Literal["verified", "unverified"] = "unverified"
    ingredients: list[IngredientEntry] = Field(default_factory=list)
    source: str | None = None
    collected_at: AwareDatetime | None = None
    collected_at_raw: str | None = None
    source_version: str | None = None
    source_fingerprint: str | None = None
    generator_version: str | None = None
    evidence_id: str | None = None
    reason: str
    issues: list[str] = Field(default_factory=list)
    conditions: list[IngredientDecision] = Field(default_factory=list)
    synthetic: bool = False
    # Repository-only evidence; unreviewed raw rows are never emitted as verified facts.
    evidence: IngredientEvidence | None = Field(default=None, exclude=True)

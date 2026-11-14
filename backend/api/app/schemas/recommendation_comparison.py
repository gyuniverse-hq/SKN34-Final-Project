"""Development comparison contract: numeric analysis only; no images or identifiers."""

from typing import Annotated, Literal

from pydantic import Field

from app.schemas.skincare import StrictModel


class AnalysisScores(StrictModel):
    pores: float = Field(ge=0, le=1)
    pigmentation: float = Field(ge=0, le=1)
    wrinkles: float = Field(ge=0, le=1)


class ComparisonInput(StrictModel):
    age_group: Literal["10대", "20대", "30대", "40대", "50대", "60대"]
    gender: Literal["남성", "여성"]
    skin_type: Literal["건성", "중성", "지성", "복합성"]
    analysis_version: Literal["skin-analysis-v4"]
    score_kind: Literal["binary_caution_probability"]
    aggregation: Literal["mean-cheeks-pore-tone-eyes-wrinkle-v1"]
    scores: AnalysisScores
    irritation_signal: Literal["caution", "none", "unknown"] = "unknown"


class ReviewEvidence(StrictModel):
    """Review inputs; review count equals survey respondents as confirmed by the user."""

    survey_ratios: dict[str, Annotated[float, Field(ge=0, le=1)]] = Field(default_factory=dict)
    review_count: int | None = Field(default=None, ge=0, strict=True)
    rating_avg: float | None = Field(default=None, ge=1, le=5)
    rating_percentages: (
        tuple[float | None, float | None, float | None, float | None, float | None] | None
    ) = None
    rating_distribution_status: str = "missing"


class CandidateOption(StrictModel):
    product_id: str
    product_name: str
    option_id: str
    ingredient_ids: list[int]
    review: ReviewEvidence
    subcategory: str | None = None
    skin_types: list[str] = Field(default_factory=list)
    label_source: str | None = None


class ComparisonCatalog(StrictModel):
    version: str
    digest: str
    options: list[CandidateOption]
    names: dict[int, str]
    source_manifest: dict[str, str]
    functions_by_id: dict[int, list[str]] = Field(default_factory=dict)
    functions_by_concern: dict[str, list[str]] = Field(default_factory=dict)

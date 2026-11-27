import re
from datetime import datetime
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator
from pydantic.alias_generators import to_camel

Role = Literal["admin", "viewer"]
Status = Literal["pending", "paid", "preparing", "shipped", "delivered", "canceled"]
Label = Annotated[str, StringConstraints(pattern=r"^[a-zA-Z0-9가-힣 _()−+-]{1,64}$")]
Version = Annotated[str, StringConstraints(pattern=r"^[a-zA-Z0-9][a-zA-Z0-9_.-]{0,63}$")]
Number = Annotated[float, Field(allow_inf_nan=False, strict=True)]


class Contract(BaseModel):
    model_config = ConfigDict(
        extra="forbid", alias_generator=to_camel, populate_by_name=True, allow_inf_nan=False
    )


class StatusChange(Contract):
    status: Status
    reason: str = Field(default="", max_length=200)


class AdminStatePatch(Contract):
    is_visible: bool | None = None
    stock: int | None = Field(default=None, ge=0, le=2_000_000_000, strict=True)

    @model_validator(mode="after")
    def validate_patch(self):
        if not self.model_fields_set or (
            "is_visible" in self.model_fields_set and self.is_visible is None
        ):
            raise ValueError("empty patch or null visibility")
        return self


class Estimate(Contract):
    estimate: Number | None = None
    low: Number | None = None
    high: Number | None = None
    n: int = Field(ge=0, strict=True)

    @model_validator(mode="after")
    def interval(self):
        if self.estimate is not None and self.n < 1:
            raise ValueError("measured estimates need a sample")
        if (self.low is None) != (self.high is None):
            raise ValueError("both confidence bounds are required")
        if self.low is not None and (
            self.estimate is None or not self.low <= self.estimate <= self.high
        ):
            raise ValueError("invalid confidence interval")
        return self


class Factors(Contract):
    total: Estimate
    texture: Estimate
    shading: Estimate
    gloss: Estimate
    boundary: Estimate
    adhesion: Estimate

    @model_validator(mode="after")
    def score_ranges(self):
        for field in ("total", "texture", "shading", "gloss", "boundary", "adhesion"):
            value = getattr(self, field)
            maximum = 5 if field == "total" else 1
            if any(
                number is not None and not 0 <= number <= maximum
                for number in (value.estimate, value.low, value.high)
            ):
                raise ValueError("score is outside the rubric range")
        return self


class Reliability(Contract):
    rater_count: int = Field(ge=0, strict=True)
    icc21: Number | None = Field(default=None, le=1)
    icc2k: Number | None = Field(default=None, le=1)
    normalized_icc: Number | None = Field(default=None, le=1)
    alpha: Number | None = Field(default=None, le=1)


class GroupEstimate(Contract):
    label: Literal[
        "glossy",
        "satin",
        "matte",
        "velvet",
        "sheer",
        "cream",
        "shimmer",
        "open",
        "closed",
        "q1",
        "q2",
        "q3",
        "q4",
        "unknown",
    ]
    total: Estimate


class Correlation(Contract):
    metric: Literal[
        "edge_width", "flat_ratio", "hf_corr_bare", "hf_std", "highlight_area", "lum_spread"
    ]
    spearman: Number | None = Field(default=None, ge=-1, le=1)


class CodeMetric(Contract):
    metric: Version
    value: Estimate


class PairedComparison(Contract):
    previous_renderer_commit: str = Field(pattern=r"^[0-9a-f]{7,40}$")
    method: Literal["face-paired-bootstrap"]
    total_delta: Estimate


class EvalSummary(Contract):
    factors: Factors
    reliability: Reliability
    mdc95: Number | None = Field(default=None, ge=0)
    finishes: list[GroupEstimate] = Field(default_factory=list, max_length=20)
    mouths: list[GroupEstimate] = Field(default_factory=list, max_length=10)
    ita_bins: list[GroupEstimate] = Field(default_factory=list, max_length=20)
    correlations: list[Correlation] = Field(default_factory=list, max_length=30)
    code_metrics: list[CodeMetric] = Field(default_factory=list, max_length=30)
    paired_comparison: PairedComparison | None = None
    vlm_verdict: Literal["대체 가능", "보조만", "쓰지 않음", "판정 불가"] = "판정 불가"
    unmeasured: list[Literal["색 재현", "피팅 안정성", "VLM 판정", "짝 비교", "사람 평가"]] = Field(
        default_factory=list, max_length=5
    )


class EvalCreate(Contract):
    kind: Literal["human", "bench", "judge"]
    renderer_commit: str = Field(pattern=r"^[0-9a-f]{7,40}$")
    renderer_dirty: bool
    rubric_version: Version
    metric_version: Version
    # Hash of the benchmark manifest, never an individual image hash.
    benchmark_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    summary_json: EvalSummary

    @model_validator(mode="before")
    @classmethod
    def reject_sensitive_strings(cls, data):
        def walk(value, key=""):
            if isinstance(value, dict):
                for name, child in value.items():
                    walk(child, name)
            elif isinstance(value, list):
                for child in value:
                    walk(child, key)
            elif isinstance(value, str) and (
                len(value.encode("utf8")) > 1024
                or re.search(
                    r"https?:|www\.|[/\\]|\.(?:png|jpg|jpeg|webp)|image[_ -]?id", value, re.I
                )
            ):
                raise ValueError("paths, URLs and image references are forbidden")

        walk(data)
        return data


class StaffResponse(Contract):
    user_id: str
    email: str | None
    role: Role


class OrderLineResponse(Contract):
    id: int
    product_id: str
    product_name: str
    shade_id: str | None
    quantity: int
    unit_price_krw: int = Field(alias="unitPriceKRW")


class OrderResponse(Contract):
    id: str
    user_id: str
    amount_krw: int = Field(alias="amountKRW")
    order_name: str
    status: Status
    created_at: datetime | None
    paid_at: datetime | None
    payment_key: str | None
    next_statuses: list[Status]
    lines: list[OrderLineResponse] | None = None


class ShadeResponse(Contract):
    id: str
    name: str
    hex: str
    measure_method: str | None
    color_source: str | None
    color_confidence: float | None


class ProductResponse(Contract):
    id: str
    name: str
    brand: str
    category: str
    price_krw: int = Field(alias="priceKRW")
    is_visible: bool
    stock: int | None
    shade_count: int
    measurement_methods: list[str]
    shades: list[ShadeResponse] | None = None


class AuditResponse(Contract):
    id: str
    actor_user_id: str | None
    action: str
    target_type: str
    target_id: str
    before_json: dict[str, Any] | None
    after_json: dict[str, Any] | None
    request_id: str
    created_at: datetime


class EvalResponse(EvalCreate):
    id: str
    created_at: datetime


class Page[T](Contract):
    items: list[T]
    next_cursor: str | None = None


class EvalList(Contract):
    items: list[EvalResponse]


class TechnicalMetricItem(Contract):
    value: Number | None = None
    bare_value: Number | None = None
    beats_bare: bool | None = None
    pass_line: Number | None = None
    verdict: Literal["pass", "fail", "report_only"]
    method: str | None = None


class TechnicalTrack(Contract):
    criteria_version: Version
    overall: Literal["pass", "fail", "report_only"]
    items: dict[str, TechnicalMetricItem]


class NaturalnessTrack(Contract):
    criteria_version: Version
    scores: dict[str, int]
    mean: Number
    brief_reason: str = ""
    model: str | None = None


class LipTriadEvalResponse(Contract):
    id: str
    technical: TechnicalTrack
    naturalness: NaturalnessTrack
    retained_images: bool = False


class NaturalnessCriteriaScale(Contract):
    min: int = Field(ge=1, le=5, strict=True)
    max: int = Field(ge=1, le=5, strict=True)
    note: str = ""


class NaturalnessCriteriaItem(Contract):
    id: str
    label: str
    text: str
    likert: dict[str, str]


class NaturalnessCriteriaResponse(Contract):
    version: Version
    title: str
    scale: NaturalnessCriteriaScale
    items: list[NaturalnessCriteriaItem]


class LipEvalRater(Contract):
    id: int
    label: str


class LipEvalImageUrls(Contract):
    bare: str | None = None
    real: str | None = None
    ar: str | None = None


class LipEvalSlot(Contract):
    rater_id: int
    label: str
    has_bare: bool
    has_real: bool
    has_ar: bool
    ready_for_ar: bool
    scored: bool
    technical: dict | None = None
    naturalness: dict | None = None
    scored_at: str | None = None
    image_urls: LipEvalImageUrls


class LipEvalAggregate(Contract):
    scored_count: int
    finalized: bool
    naturalness_mean: Number | None = None
    technical_overall_pass_rate: Number | None = None
    metric_means: dict[str, Number] | None = None


class LipEvalProduct(Contract):
    id: str
    brand: str
    name: str
    shade: str
    sort_order: int
    aggregate: LipEvalAggregate
    slots: list[LipEvalSlot]
    raters: list[LipEvalRater] | None = None
    last_score: dict | None = None


class LipEvalProductList(Contract):
    items: list[LipEvalProduct]
    raters: list[LipEvalRater]


class OpsRecommendationCounts(Contract):
    recommendation_impressions: int
    skincare_events: int
    cart_recommendation_visits: int


class OpsRecommendations(Contract):
    ar_palette_mode: str
    ar_palette_experiment: str | None = None
    cart_recommendation_experiment: str | None = None
    counts: OpsRecommendationCounts


class OpsProbe(Contract):
    ok: bool
    status: int | None = None
    body: dict | None = None


class OpsChatbot(Contract):
    configured: bool
    base_url: str | None = None
    healthz: OpsProbe | None = None
    readyz: OpsProbe | None = None
    error: str | None = None


class OpsSystem(Contract):
    env: str
    admin_enabled: bool
    alembic_head: str | None = None
    lip_eval_dir: str
    lip_eval_dir_exists: bool
    llm_configured: bool
    chatbot_base_url: str | None = None
    cors_origin_count: int

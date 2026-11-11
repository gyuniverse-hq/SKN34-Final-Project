"""The public contract exposes reviewed summaries and citations only."""

from typing import Annotated, Literal, Self
from uuid import UUID

from pydantic import ConfigDict, Field, HttpUrl, StringConstraints, model_validator

from app.schemas.base import ApiModel

ClaimUse = Literal["explain", "rank", "avoid"]
ScopeLabel = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=80)]
MfdsHash = Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{64}$")]


class ClaimModel(ApiModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class ClaimContext(ClaimModel):
    concern: ScopeLabel | None = None
    target: ScopeLabel | None = None
    formulation: ScopeLabel | None = None
    concentration_pct: float | None = Field(default=None, ge=0, le=100)


class ClaimScope(ClaimModel):
    concerns: list[ScopeLabel] = Field(default_factory=list, max_length=16)
    targets: list[ScopeLabel] = Field(default_factory=list, max_length=16)
    formulations: list[ScopeLabel] = Field(default_factory=list, max_length=16)
    concentration_min_pct: float | None = Field(default=None, ge=0, le=100)
    concentration_max_pct: float | None = Field(default=None, ge=0, le=100)

    @model_validator(mode="after")
    def valid_range(self) -> Self:
        if (
            self.concentration_min_pct is not None
            and self.concentration_max_pct is not None
            and self.concentration_min_pct > self.concentration_max_pct
        ):
            raise ValueError("Invalid concentration range")
        return self

    def applies(self, context: ClaimContext) -> bool:
        for choices, value in (
            (self.concerns, context.concern),
            (self.targets, context.target),
            (self.formulations, context.formulation),
        ):
            if choices and (
                value is None or value.casefold() not in {label.casefold() for label in choices}
            ):
                return False
        minimum, maximum = self.concentration_min_pct, self.concentration_max_pct
        if minimum is None and maximum is None:
            return True
        value = context.concentration_pct
        return (
            value is not None
            and (minimum is None or value >= minimum)
            and (maximum is None or value <= maximum)
        )


class ClaimIngredientKey(ClaimModel):
    mfds_ingredient_id: int = Field(gt=0, strict=True)
    source_hash: MfdsHash


class ReviewedApplicability(ClaimScope):
    ingredient: ClaimIngredientKey

    @property
    def scope(self) -> ClaimScope:
        return ClaimScope(**self.model_dump(exclude={"ingredient"}, by_alias=False))


class ClaimSearchRequest(ClaimModel):
    use: ClaimUse
    context: ClaimContext = Field(default_factory=ClaimContext)
    ingredient_names: list[ScopeLabel] = Field(default_factory=list, max_length=6)
    ingredients: list[ClaimIngredientKey] = Field(default_factory=list, max_length=64)
    publication_ids: list[UUID] = Field(default_factory=list, max_length=24)

    @model_validator(mode="after")
    def bounded_selector(self) -> Self:
        if sum(map(bool, (self.ingredient_names, self.ingredients, self.publication_ids))) != 1:
            raise ValueError("Specify one ingredient or publication selector")
        return self


class PublishClaim(ClaimModel):
    claim_version_id: int = Field(gt=0, strict=True)
    source_review_id: int = Field(gt=0, strict=True)
    release_id: int = Field(gt=0, strict=True)
    ingredient: ClaimIngredientKey
    source_title: str = Field(min_length=1, max_length=300)
    source_url: HttpUrl
    publisher: str = Field(min_length=1, max_length=120)

    @model_validator(mode="after")
    def public_citation_url(self) -> Self:
        if self.source_url.username or self.source_url.password:
            raise ValueError("Source URLs cannot carry credentials")
        return self


class PublishedClaim(ClaimModel):
    publication_id: UUID
    revision: int
    ingredient: ClaimIngredientKey
    ingredient_name: str
    summary: str
    use: ClaimUse
    scope: ClaimScope
    source_title: str
    source_url: HttpUrl
    source_version: str
    study_type: str


class ClaimSearchResponse(ClaimModel):
    claims: list[PublishedClaim]

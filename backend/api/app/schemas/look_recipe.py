"""Makeup recipe read from a public video (plan step 3).

Intent, not coordinates: the app lays it on the user face. The zone names match
backend/chatbot/app/schemas/style_recipe.py. No person names, faces or images are stored.
"""

from typing import Literal, get_args

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.schemas.catalog import BlushPlacement, ContourStyle, HighlighterStyle, ShadowFinish

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
HIGHLIGHTER_STYLES: tuple[str, ...] = get_args(HighlighterStyle)
CONTOUR_STYLES: tuple[str, ...] = get_args(ContourStyle)
BLUSH_STYLES: tuple[str, ...] = get_args(BlushPlacement)
SHADOW_STYLES: tuple[str, ...] = get_args(ShadowFinish)
# Chip ids from lib/linerLooks.ts (numbers must stay in lockstep).
LINER_LOOKS: dict[str, dict] = {
    "natural": {
        "linerStyle": "classic_winged",
        "thickness": 0.063,
        "length": 0,
        "angle": 0,
        "linerSoftness": 0.2,
        "linerLower": False,
    },
    "cat_wing": {
        "linerStyle": "classic_winged",
        "thickness": 0.108,
        "length": 0.3,
        "angle": 15,
        "linerSoftness": 0.15,
        "linerLower": False,
    },
    "puppy": {
        "linerStyle": "puppy",
        "thickness": 0.09,
        "length": 0.12,
        "angle": -10,
        "linerSoftness": 0.2,
        "linerLower": False,
    },
    "smoky": {
        "linerStyle": "classic_winged",
        "thickness": 0.144,
        "length": 0.08,
        "angle": 0,
        "linerSoftness": 0.8,
        "linerLower": True,
    },
    "gyaru": {
        "linerStyle": "classic_winged",
        "thickness": 0.144,
        "length": 0.35,
        "angle": 12,
        "linerSoftness": 0.15,
        "linerLower": True,
    },
    "under_point": {
        "linerStyle": "classic_winged",
        "thickness": 0.054,
        "length": 0,
        "angle": 0,
        "linerSoftness": 0.4,
        "linerLower": True,
    },
}
LIP_LOOKS: dict[str, dict] = {
    "full": {"overlip": 0.0},
    "overlip": {"overlip": 0.03, "peakOverdraw": 0.02},
    "center_glow": {"centerHighlight": 0.15},
}
# Multipliers on the AR mascara default (lib/mascaraLooks.ts).
MASCARA_LOOKS: dict[str, dict] = {
    "slim": {"length": 1.28, "thickness": 0.78, "lower": True},
    "long_curl": {"length": 1.48, "thickness": 1.12, "lower": True},
    "volume_skinny": {"length": 1.4, "thickness": 1.3, "lower": True},
    "long": {"length": 1.45, "thickness": 1.28, "lower": True},
    "fine": {"length": 1.12, "thickness": 0.72, "lower": False},
}
# Plan step 5: video wording → geometry the app already knows how to lay on a face.
STYLE_IDS: dict[str, tuple[str, ...]] = {
    "highlighter": HIGHLIGHTER_STYLES,
    "contour": CONTOUR_STYLES,
    "eyeliner": tuple(LINER_LOOKS),
    "blush": BLUSH_STYLES,
    "eyeshadow": SHADOW_STYLES,
    "lip": tuple(LIP_LOOKS),
    "mascara": tuple(MASCARA_LOOKS),
}
STYLE_ENUM: tuple[str, ...] = tuple(sorted({sid for ids in STYLE_IDS.values() for sid in ids}))


def geometry_for_style(zone: str, style: str | None, intensity: float | None = None) -> dict:
    """App geometry for one recipe step. Unknown styles are already dropped on the draft."""
    geometry: dict = {}
    if style and zone == "highlighter":
        geometry["hlStyle"] = style
    elif style and zone == "contour":
        geometry["contourStyle"] = style
    elif style and zone == "eyeliner":
        geometry.update(LINER_LOOKS[style])
    elif style and zone == "blush":
        geometry["blushPlacement"] = style
    elif style and zone == "eyeshadow":
        geometry["shadowFinish"] = style
    elif style and zone == "lip":
        geometry.update(LIP_LOOKS[style])
    elif style and zone == "mascara":
        geometry.update(MASCARA_LOOKS[style])
    if intensity is not None and zone == "highlighter":
        geometry["intensity"] = intensity
    return geometry


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class RecipeStepDraft(_Strict):
    """One step as the model reported it (a single run)."""

    zone: RecipeZone
    start_seconds: int | None = Field(default=None, ge=0, le=36000)
    style: str | None = Field(default=None, max_length=40)
    intensity: float | None = Field(default=None, ge=0, le=1)
    product_family: str | None = Field(default=None, max_length=80)

    @model_validator(mode="after")
    def style_belongs_to_zone(self):
        if self.style is not None and self.style not in STYLE_IDS.get(self.zone, ()):
            # An unknown style is dropped, never guessed into a different one.
            self.style = None
        return self


class RecipeDraft(_Strict):
    steps: list[RecipeStepDraft] = Field(max_length=30)


class VotedStep(_Strict):
    order: int = Field(ge=1)
    zone: RecipeZone
    start_seconds: int | None = None
    style: str | None = None
    intensity: float | None = Field(default=None, ge=0, le=1)
    product_family: str | None = None
    votes: int = Field(ge=1)
    runs: int = Field(ge=1)


class ExtractedRecipe(_Strict):
    video_id: str
    model: str
    runs: int
    steps: list[VotedStep]
    review_status: Literal["unreviewed"] = "unreviewed"


class ReviewEntry(_Strict):
    """One line of the review file. Only an entry a person set to approved is ever applied."""

    video_id: str
    look_id: str | None = None
    recipe: ExtractedRecipe
    approved: bool = False
    reviewer: str | None = None

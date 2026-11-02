from typing import Literal

from pydantic import BaseModel, Field

Band = Literal['<=2', '2-4', '4-6', '6-10', '>10']
Amount = Literal['none', 'slight(<=10%)', 'moderate(10-25%)', 'severe(>25%)']
Choice = Literal['X', 'Y', 'tie']


class Color(BaseModel):
    color_band: Band
    reason: str


class Placement(BaseModel):
    overflow: Amount
    missing: Amount
    edge: Literal['natural_soft', 'slightly_sharp', 'sticker_sharp', 'blurry_bleed']
    corner_fade: Literal['natural', 'too_strong', 'too_weak']
    placement_score: int = Field(ge=1, le=5)
    reason: str


class Texture(BaseModel):
    contrast_closer: Choice
    highlight_closer: Choice
    texture_closer: Choice
    x_finish_look: Literal['matte', 'satin', 'gloss']
    y_finish_look: Literal['matte', 'satin', 'gloss']
    x_plastic_look: bool
    y_plastic_look: bool
    reason: str


class NaturalSingle(BaseModel):
    guess: Literal['real_makeup', 'ar_virtual']
    confidence: int = Field(ge=1, le=5)
    naturalness: int = Field(ge=1, le=5)
    awkward_regions: list[Literal['lips', 'skin', 'eyes', 'brows', 'cheeks', 'none']]
    awkward_reasons: list[Literal['texture', 'gloss', 'edge', 'sharpness_mismatch', 'color', 'position', 'none']]
    reason: str


class NaturalPair(BaseModel):
    choice: Literal['X', 'Y']
    reason: str


SCHEMAS = {'color': Color, 'placement': Placement, 'texture': Texture,
           'natural_single': NaturalSingle, 'natural_pair': NaturalPair}

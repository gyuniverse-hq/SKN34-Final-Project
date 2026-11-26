"""Conservative serving-shade fallback for already confirmed raw Olive Young options."""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Iterable
from dataclasses import dataclass

_HEX = re.compile(r"^#[0-9a-fA-F]{6}$")
_RAW_COLOR_METHODS = frozenset({"color_chip", "swatch", "pencil_tip"})


@dataclass(frozen=True)
class RawShadeOption:
    option_id: str
    goods_no: str
    shade_code: str | None
    shade_name: str | None


@dataclass(frozen=True)
class RawShadeColor:
    hex_code: str | None
    color_method: str | None


@dataclass(frozen=True)
class ServingShade:
    product_id: str
    id: str
    name: str
    hex: str
    measure_method: str | None
    color_source: str | None


def legacy_shade_base(option: RawShadeOption) -> str:
    """Match the ID generation used by app.services.oy_catalog."""
    raw = (option.shade_code or option.option_id).lower()
    return (re.sub(r"[^a-z0-9]+", "-", raw).strip("-") or "shade")[:60]


def _name(value: str | None) -> str:
    return "".join(c for c in unicodedata.normalize("NFKC", value or "").casefold() if c.isalnum())


def resolve_confirmed_shade_fallback(
    *,
    product_id: str,
    raw_option_id: str,
    options: Iterable[RawShadeOption],
    shades: Iterable[ServingShade],
    color: RawShadeColor | None,
) -> str | None:
    """Resolve a missing exact-ID match without guessing color or another product.

    Only a uniquely owned legacy code or case-only ID can qualify. The candidate
    must also match the source shade name and the independently collected HEX.
    Ambiguity, missing evidence and explicit placeholder colors remain unresolved.
    Exact IDs are handled by the existing repository join before this fallback.
    """
    goods = [option for option in options if f"oy-{option.goods_no.lower()}" == product_id]
    original = [option for option in goods if option.option_id == raw_option_id]
    if len(original) != 1:
        return None
    option = original[0]
    base = legacy_shade_base(option)
    if sum(legacy_shade_base(other) == base for other in goods) != 1:
        return None
    if (
        color is None
        or color.color_method not in _RAW_COLOR_METHODS
        or not _HEX.fullmatch(color.hex_code or "")
        or not _name(option.shade_name)
    ):
        return None

    candidates = [
        shade
        for shade in shades
        if shade.product_id == product_id
        and (shade.id.casefold() == raw_option_id.casefold() or shade.id == base)
    ]
    if len(candidates) != 1:
        return None
    candidate = candidates[0]
    if (
        candidate.measure_method == "placeholder"
        or candidate.color_source == "placeholder"
        or _name(candidate.name) != _name(option.shade_name)
        or not _HEX.fullmatch(candidate.hex)
        or candidate.hex.upper() != color.hex_code.upper()
    ):
        return None
    return candidate.id

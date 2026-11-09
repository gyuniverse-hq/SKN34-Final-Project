"""Closed-set AR placement styles. LLM may name a style; it must not invent numbers or hex."""

from __future__ import annotations

import re

GeometryZone = (
    "highlighter",
    "contour",
    "eyeliner",
    "blush",
    "eyeshadow",
    "lip",
    "mascara",
)

# Chip ids stay in lockstep with backend/api look_recipe.py and lib/zoneRecipe.ts.
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
MASCARA_LOOKS: dict[str, dict] = {
    "slim": {"length": 1.28, "thickness": 0.78, "lower": True},
    "long_curl": {"length": 1.48, "thickness": 1.12, "lower": True},
    "volume_skinny": {"length": 1.4, "thickness": 1.3, "lower": True},
    "long": {"length": 1.45, "thickness": 1.28, "lower": True},
    "fine": {"length": 1.12, "thickness": 0.72, "lower": False},
}
STYLE_IDS: dict[str, tuple[str, ...]] = {
    "highlighter": (
        "natural_cheek",
        "glass_c_zone",
        "nose_tip",
        "under_eye_smile",
        "cupid_bow",
        "forehead_center",
    ),
    "contour": ("jawline", "nose"),
    "eyeliner": tuple(LINER_LOOKS),
    "blush": ("apple", "under_eye", "side"),
    "eyeshadow": ("matte", "shimmer", "glitter", "glossy"),
    "lip": tuple(LIP_LOOKS),
    "mascara": tuple(MASCARA_LOOKS),
}

ZONE_WORDS: dict[str, tuple[str, ...]] = {
    "highlighter": ("하이라이터", "highlighter", "ハイライト", "高光"),
    "contour": ("쉐딩", "셰이딩", "컨투어", "contour", "シェーディング", "修容"),
    "eyeliner": ("아이라인", "아이라이너", "eyeliner", "アイライン", "眼线"),
    "blush": ("블러셔", "블러시", "치크", "blush", "チーク", "腮红"),
    "eyeshadow": ("아이섀도", "아이섀도우", "섀도", "eyeshadow", "アイシャドウ", "眼影"),
    "lip": ("립", "입술", "lips", "lip", "lipstick", "リップ", "唇", "口红"),
    "brow": ("눈썹", "아이브로우", "brow", "eyebrow"),
    "foundation": ("파운데이션", "foundation"),
    "mascara": ("마스카라", "mascara"),
}

STYLE_WORDS: dict[str, tuple[tuple[str, tuple[str, ...]], ...]] = {
    "highlighter": (
        ("glass_c_zone", ("c존", "씨존", "c-zone", "c zone", "cゾーン", "c区")),
        ("under_eye_smile", ("애교살", "under-eye", "under eye", "卧蚕", "卧蠶", "目の下")),
        ("cupid_bow", ("큐피드", "인중", "cupid", "人中")),
        ("forehead_center", ("이마", "forehead", "額", "额头")),
        ("nose_tip", ("콧대", "코끝", "nose tip", "nose", "鼻")),
        ("natural_cheek", ("내추럴 광대", "natural cheek", "광대", "cheek", "チーク", "颧骨")),
    ),
    "contour": (
        ("jawline", ("턱선", "v라인", "브이라인", "jawline", "jaw", "下颌", "顎")),
        ("nose", ("콧대", "코 쉐딩", "nose", "鼻")),
    ),
    "eyeliner": (
        ("cat_wing", ("캣윙", "캣 윙", "고양이", "cat wing", "cat", "猫")),
        ("puppy", ("강아지", "퍼피", "puppy", "垂れ")),
        ("smoky", ("스모키", "smoky", "烟熏")),
        ("gyaru", ("갸루", "gyaru", "ギャル")),
        ("under_point", ("언더 포인트", "아래라인", "under")),
        ("natural", ("내추럴", "natural", "自然")),
    ),
    "blush": (
        ("under_eye", ("눈밑", "눈 밑", "under-eye", "under eye", "目の下")),
        ("side", ("귀쪽", "사이드", "side", "耳")),
        ("apple", ("광대", "애플", "apple", "颧骨")),
    ),
    "eyeshadow": (
        ("glitter", ("글리터", "glitter", "亮片")),
        ("shimmer", ("쉬머", "펄", "shimmer", "パール")),
        ("glossy", ("글로시", "물광", "glossy")),
        ("matte", ("매트", "matte", "雾面")),
    ),
    "lip": (
        ("overlip", ("오버립", "오버라인", "overlip", "overline")),
        ("center_glow", ("입술 중앙", "중앙 하이라이트", "center")),
        ("full", ("풀립", "full")),
    ),
    "mascara": (
        ("volume_skinny", ("볼륨 업 스키니", "스키니", "volume skinny")),
        ("long_curl", ("컬픽스", "컬 픽스", "롱컬", "컬링", "curl")),
        ("fine", ("파인", "fine")),
        ("slim", ("슬림", "메탈", "slim")),
        ("long", ("킬래쉬", "킬 래쉬", "롱", "long")),
    ),
}

_VALUE = r"[+\-]?\d+(?:\.\d+)?\s*(?:%|퍼센트|프로|percent\b)"
_ZONE_ALT = "|".join(re.escape(word) for zone in GeometryZone for word in ZONE_WORDS[zone])
_STYLE_ALT = "|".join(
    sorted(
        {re.escape(word) for pairs in STYLE_WORDS.values() for _, words in pairs for word in words},
        key=len,
        reverse=True,
    )
)
_GEOMETRY_ABSOLUTE = tuple(
    re.compile(pattern, re.IGNORECASE)
    for pattern in (
        rf"(?:{_ZONE_ALT})\s*[을를]?\s*(?:{_STYLE_ALT})\s*(?:으로|로)\s*"
        r"(?:설정(?:해\s*(?:줘(?:요)?|주세요)|하세요)?"
        r"|(?:변경|조절)해\s*(?:줘(?:요)?|주세요)"
        r"|(?:해|맞춰|바꿔)\s*(?:줘(?:요)?|주세요))[.!。]?",
        rf"(?:please\s+)?set\s+(?:the\s+)?(?:{_ZONE_ALT})\s+to\s+(?:{_STYLE_ALT})"
        r"(?:\s+please)?[.!]?",
        rf"(?:{_ZONE_ALT})を\s*(?:{_STYLE_ALT})\s*に(?:設定|変更)して(?:ください)?[。.!]?",
        rf"(?:请)?(?:把|将)?(?:{_ZONE_ALT})\s*(?:设为|设置为|调到|调至)\s*(?:{_STYLE_ALT})[。.!]?",
    )
)


def geometry_for_style(zone: str, style: str) -> dict:
    if zone == "highlighter":
        return {"hlStyle": style}
    if zone == "contour":
        return {"contourStyle": style}
    if zone == "eyeliner":
        return dict(LINER_LOOKS[style])
    if zone == "blush":
        return {"blushPlacement": style}
    if zone == "eyeshadow":
        return {"shadowFinish": style}
    if zone == "lip":
        return dict(LIP_LOOKS[style])
    if zone == "mascara":
        return dict(MASCARA_LOOKS[style])
    return {}


def mentioned_zones(message: str) -> set[str]:
    found: set[str] = set()
    lowered = message.lower()
    for zone, words in ZONE_WORDS.items():
        if any(word.lower() in lowered for word in words):
            found.add(zone)
    return found


def _first_style(zone: str, message: str) -> str | None:
    lowered = message.lower()
    hits = [
        style
        for style, words in STYLE_WORDS.get(zone, ())
        if any(word.lower() in lowered for word in words)
    ]
    return hits[0] if len(hits) == 1 else None


def _first_zone(message: str) -> str | None:
    hits = [zone for zone in GeometryZone if zone in mentioned_zones(message)]
    return hits[0] if len(hits) == 1 else None


def absolute_geometry(message: str) -> tuple[str, str] | None:
    text = message.strip()
    if not any(pattern.fullmatch(text) for pattern in _GEOMETRY_ABSOLUTE):
        return None
    zone = _first_zone(text)
    if zone is None:
        return None
    style = _first_style(zone, text)
    if style is None:
        return None
    return zone, style

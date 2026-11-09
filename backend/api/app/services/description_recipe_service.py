"""Draft a recipe from a video description (chapters), without watching the video.

Plan step 3, route A. Chapters like "1:51 쉐딩" give the zone, its order and its start. They
almost never give a style, so a style is read only when the same chapter line names one;
otherwise it stays empty for the team to fill in. Nothing is guessed: a video with fewer than
MIN_CHAPTERS timestamp lines gets no recipe.
"""

import re

from app.clients.youtube_client import YoutubeClient
from app.schemas.look_recipe import ExtractedRecipe, VotedStep

MODEL = "description-rules"
MIN_CHAPTERS = 3

CHAPTER = re.compile(r"^\s*[\(\[]?(\d{1,2}):(\d{2})(?::(\d{2}))?[\)\]]?\s*[-–:]?\s*(.+?)\s*$", re.M)

# Keyword -> zone. A chapter can name several zones ("베이스, 쉐딩"); each keeps the same start.
ZONE_WORDS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("foundation", ("파운데이션", "쿠션", "베이스")),
    ("brow", ("눈썹", "브로우", "아이브로우")),
    ("eyeshadow", ("아이섀도", "아이섀도우", "섀도우", "아이 메이크업", "아이메이크업")),
    ("eyeliner", ("아이라인", "아이라이너")),
    ("mascara", ("속눈썹", "마스카라")),
    ("blush", ("블러셔", "치크")),
    ("contour", ("쉐딩", "셰이딩", "섀딩", "컨투어", "음영")),
    ("highlighter", ("하이라이터", "하이라이트")),
    ("lip", ("립", "틴트")),
)
# Style words, read only from the same chapter line (plan step 5). First match wins.
STYLE_WORDS: dict[str, tuple[tuple[str, tuple[str, ...]], ...]] = {
    "contour": (
        ("jawline", ("턱선", "v라인", "브이라인")),
        ("nose", ("콧대", "코 쉐딩", "노즈")),
    ),
    "highlighter": (
        ("glass_c_zone", ("c존", "씨존")),
        ("nose_tip", ("코끝", "콧대")),
        ("under_eye_smile", ("애교살",)),
        ("cupid_bow", ("큐피드", "인중")),
        ("forehead_center", ("이마",)),
        ("natural_cheek", ("광대",)),
    ),
    "eyeliner": (
        ("cat_wing", ("캣윙", "캣 윙", "고양이", "날개")),
        ("puppy", ("강아지", "퍼피")),
        ("smoky", ("스모키",)),
        ("gyaru", ("갸루",)),
        ("under_point", ("언더", "아래라인")),
        ("natural", ("내추럴",)),
    ),
    "blush": (
        ("under_eye", ("눈밑", "눈 밑", "언더아이")),
        ("side", ("귀쪽", "사이드")),
        ("apple", ("광대", "애플")),
    ),
    "eyeshadow": (
        ("glitter", ("글리터",)),
        ("shimmer", ("쉬머", "펄")),
        ("glossy", ("글로시", "물광")),
        ("matte", ("매트",)),
    ),
    "lip": (
        ("overlip", ("오버립", "오버라인")),
        ("center_glow", ("중앙 하이라이트", "입술 중앙")),
        ("full", ("풀립",)),
    ),
    "mascara": (
        ("volume_skinny", ("볼륨 업 스키니", "볼륨업 스키니", "스키니")),
        ("long_curl", ("컬픽스", "컬 픽스", "롱컬", "컬링")),
        ("fine", ("파인",)),
        ("slim", ("슬림", "메탈")),
        ("long", ("킬래쉬", "킬 래쉬", "롱")),
    ),
}


def _seconds(h_or_m: str, m_or_s: str, s: str | None) -> int:
    if s is None:
        return int(h_or_m) * 60 + int(m_or_s)
    return int(h_or_m) * 3600 + int(m_or_s) * 60 + int(s)


def _first_word_match(text: str, table: tuple[tuple[str, tuple[str, ...]], ...]) -> str | None:
    lowered = text.lower()
    for key, words in table:
        if any(word in lowered for word in words):
            return key
    return None


def recipe_from_description(video_id: str, description: str) -> ExtractedRecipe | None:
    """Steps from the chapter lines of ``description``; None with too few chapters to trust."""
    chapters = [
        (_seconds(m.group(1), m.group(2), m.group(3)), m.group(4))
        for m in CHAPTER.finditer(description)
    ]
    if len(chapters) < MIN_CHAPTERS:
        return None
    seen: dict[str, tuple[int, str | None]] = {}
    for start, title in chapters:
        lowered = title.lower()
        for zone, words in ZONE_WORDS:
            probe = (
                lowered.replace("속눈썹", "") if zone == "brow" else lowered
            )  # lashes are not brows
            if zone in seen or not any(word in probe for word in words):
                continue
            style = _first_word_match(title, STYLE_WORDS[zone]) if zone in STYLE_WORDS else None
            seen[zone] = (start, style)
    steps = [
        VotedStep(order=i, zone=zone, start_seconds=start, style=style, votes=1, runs=1)  # type: ignore[arg-type]
        for i, (zone, (start, style)) in enumerate(sorted(seen.items(), key=lambda kv: kv[1][0]), 1)
    ]
    if not steps:
        return None
    return ExtractedRecipe(video_id=video_id, model=MODEL, runs=1, steps=steps)


class DescriptionRecipeService:
    def __init__(self, youtube: YoutubeClient) -> None:
        self._youtube = youtube

    @property
    def configured(self) -> bool:
        return self._youtube.configured

    async def extract(self, video_id: str) -> ExtractedRecipe | None:
        """Read the official description through the YouTube Data API (no scraping, no video)."""
        metadata = await self._youtube.get_video_metadata(video_id)
        if metadata is None:
            return None
        return recipe_from_description(video_id, metadata.description)


def description_recipe_service_for_batch() -> DescriptionRecipeService | None:
    """The description route, or None when YOUTUBE_API_KEY is not set (jobs use only this)."""
    from app.clients.youtube_client import get_youtube_client

    client = get_youtube_client()
    return DescriptionRecipeService(client) if client.configured else None

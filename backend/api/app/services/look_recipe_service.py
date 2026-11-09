import json
import statistics
from collections import Counter
from typing import Protocol

from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from app.clients.gemini_client import GeminiClient, get_gemini_client
from app.core.errors import UpstreamError
from app.repositories.idol_look_repository import IdolLookRepository
from app.schemas.look_recipe import (
    STYLE_ENUM,
    ExtractedRecipe,
    RecipeDraft,
    RecipeStepDraft,
    ReviewEntry,
    VotedStep,
    geometry_for_style,
)

RUNS = 3
ZONES: tuple[str, ...] = (
    "foundation",
    "brow",
    "eyeshadow",
    "eyeliner",
    "mascara",
    "blush",
    "contour",
    "highlighter",
    "lip",
)

PROMPT = (
    "This is a makeup tutorial video. List the makeup steps in the order they are applied. "
    "For each step give: zone (one of the allowed values), start_seconds (when that step "
    "begins in the video), style (only an allowed id for that zone; leave it out if none "
    "fits), intensity (0 very light to 1 heavy, how strongly it is applied), product_family "
    "(the kind of product in a few words, e.g. cream stick). "
    "Highlighter styles: natural_cheek, glass_c_zone, nose_tip, under_eye_smile, cupid_bow, "
    "forehead_center. Contour: jawline, nose. Eyeliner: natural, cat_wing, puppy, "
    "smoky, gyaru, under_point. Blush: apple, under_eye, side. Eyeshadow: matte, shimmer, "
    "glitter, glossy. Lip: full, overlip, center_glow. "
    "Mascara: slim, long_curl, volume_skinny, long, fine. "
    "Describe only what is applied. Do not name people, and do not describe faces or "
    "personal features. "
    "If a zone is not applied, leave it out. Never guess a style you cannot see."
)

SCHEMA = {
    "type": "OBJECT",
    "properties": {
        "steps": {
            "type": "ARRAY",
            "items": {
                "type": "OBJECT",
                "properties": {
                    "zone": {"type": "STRING", "enum": list(ZONES)},
                    "start_seconds": {"type": "INTEGER"},
                    "style": {"type": "STRING", "enum": list(STYLE_ENUM)},
                    "intensity": {"type": "NUMBER"},
                    "product_family": {"type": "STRING"},
                },
                "required": ["zone"],
            },
        }
    },
    "required": ["steps"],
}


def vote_recipes(runs: list[RecipeDraft]) -> list[VotedStep]:
    """Keep what most runs agree on: a zone needs a majority of runs, a style a majority too."""
    need = len(runs) // 2 + 1
    per_zone: dict[str, list[RecipeStepDraft]] = {}
    for run in runs:
        seen: set[str] = set()
        for step in run.steps:
            if step.zone in seen:  # one step per zone per run
                continue
            seen.add(step.zone)
            per_zone.setdefault(step.zone, []).append(step)
    voted: list[tuple[float, VotedStep]] = []
    for zone, steps in per_zone.items():
        if len(steps) < need:
            continue
        styles = Counter(s.style for s in steps if s.style)
        style, count = styles.most_common(1)[0] if styles else (None, 0)
        if count < need:
            style = None
        starts = [s.start_seconds for s in steps if s.start_seconds is not None]
        intensities = [s.intensity for s in steps if s.intensity is not None]
        families = Counter(s.product_family for s in steps if s.product_family)
        start = round(statistics.median(starts)) if starts else None
        step = VotedStep(
            order=1,
            zone=zone,  # type: ignore[arg-type]
            start_seconds=start,
            style=style,
            intensity=round(statistics.median(intensities), 2) if intensities else None,
            product_family=families.most_common(1)[0][0] if families else None,
            votes=len(steps),
            runs=len(runs),
        )
        voted.append((start if start is not None else 10**9, step))
    voted.sort(key=lambda item: item[0])
    return [step.model_copy(update={"order": i}) for i, (_, step) in enumerate(voted, 1)]


class GeometryStore(Protocol):
    async def merge_geometry(self, look_id: str, zone: str, geometry: dict) -> bool: ...


class LookRecipeService:
    def __init__(self, client: GeminiClient | None) -> None:
        self._client = client

    async def extract(self, video_id: str, runs: int = RUNS) -> ExtractedRecipe:
        """Read the same public video several times and vote. Nothing but the public URL is sent."""
        url = f"https://www.youtube.com/watch?v={video_id}"
        drafts: list[RecipeDraft] = []
        for _ in range(runs):
            text = await self._client.generate_json(url, PROMPT, SCHEMA)  # type: ignore[union-attr]
            try:
                drafts.append(RecipeDraft.model_validate(json.loads(text)))
            except (ValueError, ValidationError) as exc:
                raise UpstreamError("Gemini answered outside the recipe schema") from exc
        return ExtractedRecipe(
            video_id=video_id,
            model=self._client.model if self._client else "",
            runs=runs,
            steps=vote_recipes(drafts),
        )

    @staticmethod
    def geometry_for(step: VotedStep) -> dict:
        """What the app can lay on a face today (plan step 5 translators)."""
        return geometry_for_style(step.zone, step.style, step.intensity)

    async def apply_to_database(
        self, entries: list[ReviewEntry], session: AsyncSession
    ) -> dict[str, list[str]]:
        return await self.apply(entries, IdolLookRepository(session))

    async def apply(self, entries: list[ReviewEntry], store: GeometryStore) -> dict[str, list[str]]:
        """Write approved, look-linked entries into zone settings. Never creates a color."""
        applied: list[str] = []
        skipped: list[str] = []
        for entry in entries:
            if not entry.approved or not entry.look_id or not entry.reviewer:
                skipped.append(f"{entry.video_id}: not approved by a named reviewer, or no look")
                continue
            for step in entry.recipe.steps:
                geometry = self.geometry_for(step)
                if not geometry:
                    continue
                if await store.merge_geometry(entry.look_id, step.zone, geometry):
                    applied.append(f"{entry.look_id}:{step.zone}")
                else:
                    skipped.append(
                        f"{entry.look_id}:{step.zone}: the look has no setting for this zone"
                    )
        return {"applied": applied, "skipped": skipped}


def look_recipe_service_for_batch() -> LookRecipeService | None:
    """The extraction service, or None when GEMINI_API_KEY is not set (jobs use only this)."""
    client = get_gemini_client()
    return LookRecipeService(client) if client.configured else None
